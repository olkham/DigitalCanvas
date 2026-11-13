// Package mqttc bridges the canvas to an MQTT broker.
//
// Topic layout (compatible with the original implementation):
//
//	<topic>/<command>           commands in (display_mode, rotation, slideshow, ...)
//	<topic>/<command>/set       accepted as an alias (Home Assistant style)
//	<topic>/current_image       published on change
//	<topic>/config              published on connect and on change (JSON)
//	<topic>/available_images    published retained (JSON list)
//	<topic>/light_sensor        lux, while auto brightness is active
//	<topic>/screen_brightness   0-100, while auto brightness is active
//	<topic>/status              "online"/"offline" (retained, last will)
package mqttc

import (
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	paho "github.com/eclipse/paho.mqtt.golang"
)

// Config is what the bridge needs from the settings.
type Config struct {
	Broker, Topic, Username, Password, ClientID string
	Port                                        int
}

// Handler receives commands: cmd is the sub-topic, payload the message.
type Handler func(cmd, payload string)

// published sub-topics are ignored when they come back via <topic>/#.
var ownTopics = map[string]bool{
	"current_image": true, "config": true, "available_images": true,
	"light_sensor": true, "screen_brightness": true, "status": true, "state": true,
}

// Bridge maintains one client.
type Bridge struct {
	handler   Handler
	onConnect func()
	onStatus  func()

	mu        sync.Mutex
	client    paho.Client
	cfg       Config
	connected atomic.Bool
	lastErr   atomic.Value // string
	failures  atomic.Int64
}

// New creates a bridge. onConnect publishes the initial state; onStatus is
// told about connection changes.
func New(h Handler, onConnect, onStatus func()) *Bridge {
	b := &Bridge{handler: h, onConnect: onConnect, onStatus: onStatus}
	b.lastErr.Store("")
	return b
}

// Connected reports the live connection state.
func (b *Bridge) Connected() bool { return b.connected.Load() }

// LastError is the most recent connection error ("" when fine).
func (b *Bridge) LastError() string { return b.lastErr.Load().(string) }

// Topic returns the configured base topic.
func (b *Bridge) Topic() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.cfg.Topic
}

// Configure (re)connects with new settings. It returns immediately; the
// client keeps retrying in the background if the broker is unreachable.
func (b *Bridge) Configure(cfg Config) {
	b.mu.Lock()
	if b.client != nil && b.cfg == cfg {
		b.mu.Unlock()
		return
	}
	old := b.client
	b.cfg = cfg
	b.client = nil
	b.mu.Unlock()
	if old != nil {
		b.publishOn(old, cfg.Topic+"/status", "offline", true)
		old.Disconnect(250)
	}
	b.setConnected(false)
	b.failures.Store(0)
	if cfg.Broker == "" {
		return
	}

	opts := paho.NewClientOptions()
	opts.AddBroker(fmt.Sprintf("tcp://%s:%d", hostPort(cfg.Broker), cfg.Port))
	opts.SetClientID(cfg.ClientID)
	if cfg.Username != "" {
		opts.SetUsername(cfg.Username)
		opts.SetPassword(cfg.Password)
	}
	opts.SetKeepAlive(60 * time.Second)
	opts.SetPingTimeout(10 * time.Second)
	opts.SetConnectTimeout(10 * time.Second)
	opts.SetAutoReconnect(true)
	opts.SetConnectRetry(true)
	opts.SetConnectRetryInterval(10 * time.Second)
	opts.SetMaxReconnectInterval(2 * time.Minute)
	opts.SetCleanSession(true)
	opts.SetOrderMatters(false) // handlers run in their own goroutines
	opts.SetWill(cfg.Topic+"/status", "offline", 1, true)
	opts.SetOnConnectHandler(func(c paho.Client) {
		b.failures.Store(0)
		b.lastErr.Store("")
		log.Printf("mqtt: connected to %s:%d", cfg.Broker, cfg.Port)
		if t := c.Subscribe(cfg.Topic+"/#", 0, b.onMessage(cfg.Topic)); t.WaitTimeout(10*time.Second) && t.Error() != nil {
			log.Printf("mqtt: subscribe failed: %v", t.Error())
		}
		b.setConnected(true)
		b.publishOn(c, cfg.Topic+"/status", "online", true)
		if b.onConnect != nil {
			b.onConnect()
		}
	})
	opts.SetConnectionLostHandler(func(c paho.Client, err error) {
		log.Printf("mqtt: connection lost: %v", err)
		b.lastErr.Store(err.Error())
		b.setConnected(false)
	})
	opts.SetReconnectingHandler(func(c paho.Client, o *paho.ClientOptions) {
		if n := b.failures.Add(1); n == 1 || n%30 == 0 {
			log.Printf("mqtt: reconnecting to %s:%d (attempt %d)", cfg.Broker, cfg.Port, n)
		}
	})

	client := paho.NewClient(opts)
	b.mu.Lock()
	b.client = client
	b.mu.Unlock()
	go func() {
		t := client.Connect()
		t.Wait()
		if err := t.Error(); err != nil {
			b.lastErr.Store(err.Error())
			log.Printf("mqtt: %v", err)
		}
	}()
}

func (b *Bridge) setConnected(v bool) {
	if b.connected.Swap(v) != v && b.onStatus != nil {
		b.onStatus()
	}
}

// ParseTopic extracts the command from a topic below base. Commands are
// matched exactly on the last path segment ("<base>/rotation"), optionally
// followed by "/set". Our own state topics are ignored.
func ParseTopic(base, topic string) (string, bool) {
	if !strings.HasPrefix(topic, base+"/") {
		return "", false
	}
	rel := strings.Trim(topic[len(base):], "/")
	if rel == "" {
		return "", false
	}
	parts := strings.Split(rel, "/")
	cmd := parts[len(parts)-1]
	if cmd == "set" && len(parts) > 1 {
		return parts[len(parts)-2], true
	}
	if ownTopics[cmd] {
		return "", false
	}
	return cmd, true
}

func (b *Bridge) onMessage(base string) paho.MessageHandler {
	return func(_ paho.Client, m paho.Message) {
		cmd, ok := ParseTopic(base, m.Topic())
		if !ok {
			return
		}
		payload := strings.TrimSpace(string(m.Payload()))
		defer func() {
			if r := recover(); r != nil {
				log.Printf("mqtt: handler panic for %s: %v", m.Topic(), r)
			}
		}()
		b.handler(cmd, payload)
	}
}

// Publish sends a message on <topic>/<sub>. Values that are not strings or
// byte slices are JSON encoded.
func (b *Bridge) Publish(sub string, value any, retain bool) {
	b.mu.Lock()
	c, base := b.client, b.cfg.Topic
	b.mu.Unlock()
	if c == nil || !b.connected.Load() {
		return
	}
	b.publishOn(c, base+"/"+sub, value, retain)
}

func (b *Bridge) publishOn(c paho.Client, topic string, value any, retain bool) {
	var payload []byte
	switch v := value.(type) {
	case string:
		payload = []byte(v)
	case []byte:
		payload = v
	default:
		var err error
		if payload, err = json.Marshal(v); err != nil {
			return
		}
	}
	if !c.IsConnectionOpen() {
		return
	}
	c.Publish(topic, 0, retain, payload)
}

// Close publishes offline and disconnects.
func (b *Bridge) Close() {
	b.mu.Lock()
	c, base := b.client, b.cfg.Topic
	b.client = nil
	b.mu.Unlock()
	if c != nil {
		if c.IsConnectionOpen() {
			c.Publish(base+"/status", 1, true, "offline").WaitTimeout(time.Second)
		}
		c.Disconnect(500)
	}
}

func hostPort(h string) string {
	if strings.Contains(h, ":") && !strings.HasPrefix(h, "[") {
		return "[" + h + "]" // IPv6 literal
	}
	return h
}
