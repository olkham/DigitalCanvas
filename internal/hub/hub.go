// Package hub fans server events out to browsers over Server-Sent Events.
// SSE is plain HTTP, reconnects automatically and needs no dependencies.
package hub

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"sync/atomic"
	"time"
)

// Roles a client can subscribe with.
const (
	RoleUI      = "ui"
	RoleDisplay = "display"
)

// Events displays care about; everything else only goes to UIs.
var displayEvents = map[string]bool{
	"hello": true, "slide": true, "playback": true, "config": true,
	"power": true, "preload": true, "reload": true, "osd": true,
}

// Client is one connected browser.
type Client struct {
	ID     uint64
	Role   string
	Kiosk  bool
	ch     chan []byte
	closed atomic.Bool
}

// Hub broadcasts events to clients.
type Hub struct {
	mu      sync.RWMutex
	clients map[*Client]struct{}
	nextID  atomic.Uint64
	done    chan struct{}
	once    sync.Once
	// OnChange is called when the set of display clients changes.
	OnChange func()
}

// New creates a hub.
func New() *Hub { return &Hub{clients: map[*Client]struct{}{}, done: make(chan struct{})} }

// Close ends all streams (used on server shutdown).
func (h *Hub) Close() { h.once.Do(func() { close(h.done) }) }

// Encode formats one SSE frame.
func Encode(event string, data any) []byte {
	b, err := json.Marshal(data)
	if err != nil {
		log.Printf("hub: encoding %s: %v", event, err)
		b = []byte("null")
	}
	return []byte(fmt.Sprintf("event: %s\ndata: %s\n\n", event, b))
}

// Broadcast sends an event to every interested client without blocking;
// clients that fall too far behind are disconnected (they will reconnect and
// receive a fresh snapshot).
func (h *Hub) Broadcast(event string, data any) {
	frame := Encode(event, data)
	// Exclusive lock: sends and closes must never race each other.
	h.mu.Lock()
	defer h.mu.Unlock()
	for c := range h.clients {
		if c.closed.Load() || (c.Role == RoleDisplay && !displayEvents[event]) {
			continue
		}
		select {
		case c.ch <- frame:
		default:
			if c.closed.CompareAndSwap(false, true) {
				close(c.ch)
			}
		}
	}
}

// Displays returns the number of connected display clients.
func (h *Hub) Displays() (total int, kiosk int) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for c := range h.clients {
		if c.Role == RoleDisplay {
			total++
			if c.Kiosk {
				kiosk++
			}
		}
	}
	return
}

// Serve streams events to one client until it disconnects. hello is sent
// first so a (re)connecting client always starts from a consistent snapshot.
func (h *Hub) Serve(w http.ResponseWriter, r *http.Request, role string, kiosk bool, hello any) {
	fl, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	c := &Client{ID: h.nextID.Add(1), Role: role, Kiosk: kiosk, ch: make(chan []byte, 64)}
	hdr := w.Header()
	hdr.Set("Content-Type", "text/event-stream")
	hdr.Set("Cache-Control", "no-cache")
	hdr.Set("Connection", "keep-alive")
	hdr.Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	rc := http.NewResponseController(w)

	write := func(b []byte) bool {
		_ = rc.SetWriteDeadline(time.Now().Add(15 * time.Second))
		if _, err := w.Write(b); err != nil {
			return false
		}
		fl.Flush()
		return true
	}
	if !write([]byte("retry: 2000\n\n")) || !write(Encode("hello", hello)) {
		return
	}

	h.mu.Lock()
	h.clients[c] = struct{}{}
	h.mu.Unlock()
	if role == RoleDisplay && h.OnChange != nil {
		h.OnChange()
	}
	defer func() {
		h.mu.Lock()
		delete(h.clients, c)
		h.mu.Unlock()
		if c.closed.CompareAndSwap(false, true) {
			close(c.ch)
		}
		if role == RoleDisplay && h.OnChange != nil {
			h.OnChange()
		}
	}()

	ping := time.NewTicker(25 * time.Second)
	defer ping.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case <-h.done:
			return
		case frame, ok := <-c.ch:
			if !ok || !write(frame) {
				return
			}
		case <-ping.C:
			if !write([]byte(": ping\n\n")) {
				return
			}
		}
	}
}
