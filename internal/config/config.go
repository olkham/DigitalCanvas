// Package config loads, validates and persists config.json.
//
// The file format is a superset of the original Python implementation's
// config.json: every original key keeps its name and meaning, unknown keys are
// preserved, and new keys are appended with sensible defaults.
package config

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Settings mirrors config.json. Field order is the on-disk key order.
type Settings struct {
	ImageFolder            string  `json:"image_folder"`
	ThumbnailFolder        string  `json:"thumbnail_folder"`
	FrameInterval          float64 `json:"frame_interval"`
	TransitionDuration     float64 `json:"transition_duration"`
	MediaOrientationFilter string  `json:"media_orientation_filter"`
	DisplayMode            string  `json:"display_mode"`
	WebInterfacePort       int     `json:"web_interface_port"`
	MQTTBroker             string  `json:"mqtt_broker"`
	MQTTPort               int     `json:"mqtt_port"`
	MQTTTopic              string  `json:"mqtt_topic"`
	DeviceName             string  `json:"device_name"`
	Theme                  string  `json:"theme"`
	Rotation               int     `json:"rotation"`
	ScaleMode              string  `json:"scale_mode"`
	PlexPort               int     `json:"plex_port"`
	AllowPlex              bool    `json:"allow_plex"`
	PauseWhenPlexPlaying   bool    `json:"pause_when_plex_playing"`
	AutoBrightness         bool    `json:"auto_brightness"`
	AutoRotation           bool    `json:"auto_rotation"`
	LightSensorMaxReading  float64 `json:"light_sensor_max_reading"`
	LightSensorMinReading  float64 `json:"light_sensor_min_reading"`
	PlaybackMode           string  `json:"playback_mode"`
	TimeOn                 string  `json:"time_on"`
	TimeOff                string  `json:"time_off"`

	// Added in the Go rewrite.
	ScheduleEnabled  bool   `json:"schedule_enabled"`
	MQTTUsername     string `json:"mqtt_username"`
	MQTTPassword     string `json:"mqtt_password"`
	DisplayBrowser   string `json:"display_browser"`
	ScreenOnCommand  string `json:"screen_on_command"`
	ScreenOffCommand string `json:"screen_off_command"`
	TranscodeVideos  bool   `json:"transcode_videos"`
	I2CBus           int    `json:"i2c_bus"`
}

// Enumerations shared with the UI.
var (
	Orientations  = []string{"portrait", "landscape", "both"}
	ScaleModes    = []string{"fit", "fill"}
	DisplayModes  = []string{"windowed", "fullscreen"}
	PlaybackModes = []string{"sequential", "random"}
	Rotations     = []int{0, 90, 180, 270}
	Themes        = []string{
		"dark-theme", "light-theme", "darcula-theme", "warm-sunset-theme",
		"ocean-breeze-theme", "autumn-leaves-theme", "winter-wonderland-theme",
		"spring-blossom-theme",
	}
)

// RestartKeys are settings that only take effect after a restart.
var RestartKeys = map[string]bool{
	"image_folder": true, "thumbnail_folder": true, "web_interface_port": true, "i2c_bus": true,
}

// SecretKeys are never echoed back verbatim to clients.
var SecretKeys = map[string]bool{"mqtt_password": true}

// Defaults returns the default settings. deviceID is used to make the default
// device name and MQTT topic unique, as the original implementation did.
func Defaults(deviceID string) Settings {
	if deviceID == "" {
		deviceID = "0000"
	}
	return Settings{
		ImageFolder:            "images",
		ThumbnailFolder:        "thumbnails",
		FrameInterval:          10,
		TransitionDuration:     5,
		MediaOrientationFilter: "both",
		DisplayMode:            "fullscreen",
		WebInterfacePort:       7000,
		MQTTBroker:             "localhost",
		MQTTPort:               1883,
		MQTTTopic:              "digital-canvas-" + deviceID,
		DeviceName:             "digital-canvas-" + deviceID,
		Theme:                  "dark-theme",
		Rotation:               0,
		ScaleMode:              "fit",
		PlexPort:               32400,
		AllowPlex:              true,
		PauseWhenPlexPlaying:   true,
		AutoBrightness:         true,
		AutoRotation:           true,
		LightSensorMaxReading:  1000,
		LightSensorMinReading:  0,
		PlaybackMode:           "sequential",
		TimeOn:                 "06:00",
		TimeOff:                "22:00",
		ScheduleEnabled:        true,
		DisplayBrowser:         "auto",
		TranscodeVideos:        true,
		I2CBus:                 1,
	}
}

type fieldInfo struct {
	index int
	kind  reflect.Kind
}

var (
	fields    = map[string]fieldInfo{}
	fieldKeys []string // in struct order
)

func init() {
	t := reflect.TypeOf(Settings{})
	for i := 0; i < t.NumField(); i++ {
		f := t.Field(i)
		key := strings.Split(f.Tag.Get("json"), ",")[0]
		fields[key] = fieldInfo{index: i, kind: f.Type.Kind()}
		fieldKeys = append(fieldKeys, key)
	}
}

// Keys returns all known setting keys in file order.
func Keys() []string { return append([]string(nil), fieldKeys...) }

// IsKnown reports whether key is a known setting.
func IsKnown(key string) bool { _, ok := fields[key]; return ok }

// Store is a concurrency-safe, persisted configuration.
type Store struct {
	mu        sync.RWMutex
	path      string
	s         Settings
	extra     map[string]json.RawMessage // unknown keys, preserved verbatim
	subs      []func(changed []string)
	saveTimer *time.Timer
	wmu       sync.Mutex // serialises file writes and reloads
	defaults  Settings
	lastMod   time.Time // mtime of the file as we last wrote/read it
}

// Open loads path, creating it with defaults when missing.
func Open(path, deviceID string) (*Store, error) {
	st := &Store{path: path, defaults: Defaults(deviceID), extra: map[string]json.RawMessage{}}
	st.s = st.defaults
	if err := st.load(); err != nil {
		if !os.IsNotExist(err) {
			return nil, err
		}
		log.Printf("config: %s not found, writing defaults", path)
		if err := st.writeFile(); err != nil {
			return nil, err
		}
	}
	if err := st.Flush(); err != nil { // persist keys added by this version
		return nil, err
	}
	return st, nil
}

// Path returns the config file path.
func (st *Store) Path() string { return st.path }

func (st *Store) load() error {
	data, err := os.ReadFile(st.path)
	if err != nil {
		return err
	}
	var raw map[string]json.RawMessage
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	if err := dec.Decode(&raw); err != nil {
		return fmt.Errorf("config: %s is not valid JSON: %w", st.path, err)
	}
	s := st.defaults
	extra := map[string]json.RawMessage{}
	missing := false
	for _, k := range fieldKeys {
		if _, ok := raw[k]; !ok {
			missing = true
		}
	}
	for k, v := range raw {
		if !IsKnown(k) {
			extra[k] = v
			continue
		}
		var val any
		d := json.NewDecoder(bytes.NewReader(v))
		d.UseNumber()
		if err := d.Decode(&val); err != nil {
			continue
		}
		if err := setField(&s, k, val); err != nil {
			log.Printf("config: ignoring invalid %s=%s (%v), using default", k, string(v), err)
		}
	}
	st.mu.Lock()
	st.s = s
	st.extra = extra
	if fi, err := os.Stat(st.path); err == nil {
		st.lastMod = fi.ModTime()
	}
	st.mu.Unlock()
	if missing {
		// Same as the original add_missing_defaults(): persist new keys.
		st.scheduleSave()
	}
	return nil
}

// Reload re-reads the file if it was edited outside the app, and notifies
// subscribers of changes. Pending (debounced) writes are flushed first so
// they are never lost.
func (st *Store) Reload() error {
	if err := st.Flush(); err != nil {
		return err
	}
	st.wmu.Lock() // wait for any in-flight write
	defer st.wmu.Unlock()
	if fi, err := os.Stat(st.path); err == nil {
		st.mu.RLock()
		same := fi.ModTime().Equal(st.lastMod)
		st.mu.RUnlock()
		if same {
			return nil
		}
	}
	before := st.Get()
	if err := st.load(); err != nil {
		return err
	}
	after := st.Get()
	if changed := diff(before, after); len(changed) > 0 {
		st.notify(changed)
	}
	return nil
}

// Get returns a copy of the current settings.
func (st *Store) Get() Settings {
	st.mu.RLock()
	defer st.mu.RUnlock()
	return st.s
}

// Defaults returns the defaults used for this store.
func (st *Store) Defaults() Settings { return st.defaults }

// Subscribe registers fn to be called (synchronously, outside the lock)
// after settings change.
func (st *Store) Subscribe(fn func(changed []string)) {
	st.mu.Lock()
	st.subs = append(st.subs, fn)
	st.mu.Unlock()
}

// Set updates one key. See Update.
func (st *Store) Set(key string, value any) error {
	_, errs := st.Update(map[string]any{key: value})
	if e, ok := errs[key]; ok {
		return fmt.Errorf("%s", e)
	}
	return nil
}

// Update validates and applies values. Valid keys are applied even when
// others fail. It returns the keys whose value actually changed and a map of
// per-key validation errors.
func (st *Store) Update(values map[string]any) (changed []string, errs map[string]string) {
	errs = map[string]string{}
	st.mu.Lock()
	next := st.s
	for k, v := range values {
		if !IsKnown(k) {
			errs[k] = "unknown setting"
			continue
		}
		if SecretKeys[k] {
			if s, ok := v.(string); ok && s == RedactedSecret {
				continue // client echoed the placeholder back; keep the stored secret
			}
		}
		if err := setField(&next, k, v); err != nil {
			errs[k] = err.Error()
		}
	}
	changed = diff(st.s, next)
	st.s = next
	st.mu.Unlock()
	if len(changed) > 0 {
		st.scheduleSave()
		st.notify(changed)
	}
	return changed, errs
}

func (st *Store) notify(changed []string) {
	st.mu.RLock()
	subs := append([]func([]string){}, st.subs...)
	st.mu.RUnlock()
	for _, fn := range subs {
		fn(changed)
	}
}

// RedactedSecret replaces secrets in Map(true).
const RedactedSecret = "********"

// Map returns settings as a generic map (including preserved unknown keys).
func (st *Store) Map(redact bool) map[string]any {
	st.mu.RLock()
	s := st.s
	extra := st.extra
	st.mu.RUnlock()
	out := map[string]any{}
	v := reflect.ValueOf(s)
	for _, k := range fieldKeys {
		out[k] = v.Field(fields[k].index).Interface()
		if redact && SecretKeys[k] && out[k] != "" {
			out[k] = RedactedSecret
		}
	}
	for k, raw := range extra {
		var x any
		if json.Unmarshal(raw, &x) == nil {
			out[k] = x
		}
	}
	return out
}

func (st *Store) scheduleSave() {
	st.mu.Lock()
	defer st.mu.Unlock()
	if st.saveTimer != nil {
		st.saveTimer.Stop()
	}
	// Coalesce bursts of updates (sliders, sensors) into a single write.
	st.saveTimer = time.AfterFunc(400*time.Millisecond, func() {
		if err := st.writeFile(); err != nil {
			log.Printf("config: save failed: %v", err)
		}
	})
}

// Flush writes pending changes immediately.
func (st *Store) Flush() error {
	st.mu.Lock()
	pending := st.saveTimer != nil && st.saveTimer.Stop()
	st.saveTimer = nil
	st.mu.Unlock()
	if pending {
		return st.writeFile()
	}
	return nil
}

func (st *Store) writeFile() error {
	st.wmu.Lock()
	defer st.wmu.Unlock()
	st.mu.RLock()
	s := st.s
	extraKeys := make([]string, 0, len(st.extra))
	for k := range st.extra {
		extraKeys = append(extraKeys, k)
	}
	sort.Strings(extraKeys)
	extra := st.extra
	st.mu.RUnlock()

	var buf bytes.Buffer
	buf.WriteString("{\n")
	v := reflect.ValueOf(s)
	n := 0
	write := func(k string, raw []byte) {
		if n > 0 {
			buf.WriteString(",\n")
		}
		kb, _ := json.Marshal(k)
		buf.WriteString("    ")
		buf.Write(kb)
		buf.WriteString(": ")
		buf.Write(raw)
		n++
	}
	for _, k := range fieldKeys {
		raw, err := marshalValue(v.Field(fields[k].index).Interface())
		if err != nil {
			return err
		}
		write(k, raw)
	}
	for _, k := range extraKeys {
		write(k, extra[k])
	}
	buf.WriteString("\n}\n")
	if err := WriteFileAtomic(st.path, buf.Bytes(), 0o644); err != nil {
		return err
	}
	if fi, err := os.Stat(st.path); err == nil {
		st.mu.Lock()
		st.lastMod = fi.ModTime()
		st.mu.Unlock()
	}
	return nil
}

func marshalValue(v any) ([]byte, error) {
	if f, ok := v.(float64); ok && f == math.Trunc(f) && math.Abs(f) < 1e15 {
		return []byte(strconv.FormatInt(int64(f), 10)), nil // keep ints as ints
	}
	return json.Marshal(v)
}

// WriteFileAtomic writes data to a temp file and renames it into place so a
// power cut never leaves a truncated file behind.
func WriteFileAtomic(path string, data []byte, perm os.FileMode) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	_, werr := tmp.Write(data)
	serr := tmp.Sync()
	cerr := tmp.Close()
	if werr != nil || serr != nil || cerr != nil {
		os.Remove(name)
		if werr != nil {
			return werr
		}
		if serr != nil {
			return serr
		}
		return cerr
	}
	_ = os.Chmod(name, perm)
	if err := os.Rename(name, path); err != nil {
		os.Remove(name)
		return err
	}
	return nil
}

func diff(a, b Settings) []string {
	va, vb := reflect.ValueOf(a), reflect.ValueOf(b)
	var out []string
	for _, k := range fieldKeys {
		i := fields[k].index
		if va.Field(i).Interface() != vb.Field(i).Interface() {
			out = append(out, k)
		}
	}
	return out
}

// ---- coercion and validation ----

var (
	timeRe     = regexp.MustCompile(`^([01]\d|2[0-3]):[0-5]\d$`)
	hostnameRe = regexp.MustCompile(`^(?i)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*\.?$`)
)

func setField(s *Settings, key string, raw any) error {
	fi := fields[key]
	fv := reflect.ValueOf(s).Elem().Field(fi.index)
	switch fi.kind {
	case reflect.String:
		str, err := toString(raw)
		if err != nil {
			return err
		}
		str, err = validateString(key, str)
		if err != nil {
			return err
		}
		fv.SetString(str)
	case reflect.Int:
		n, err := toFloat(raw)
		if err != nil {
			return err
		}
		if n != math.Trunc(n) {
			return fmt.Errorf("must be a whole number")
		}
		i, err := validateInt(key, int(n))
		if err != nil {
			return err
		}
		fv.SetInt(int64(i))
	case reflect.Float64:
		n, err := toFloat(raw)
		if err != nil {
			return err
		}
		if err := validateFloat(key, n); err != nil {
			return err
		}
		fv.SetFloat(n)
	case reflect.Bool:
		b, err := ToBool(raw)
		if err != nil {
			return err
		}
		fv.SetBool(b)
	}
	return nil
}

func toString(v any) (string, error) {
	switch x := v.(type) {
	case string:
		return x, nil
	case json.Number:
		return x.String(), nil
	case float64, int, int64:
		return fmt.Sprint(x), nil
	case nil:
		return "", fmt.Errorf("value required")
	}
	return "", fmt.Errorf("must be a string")
}

func toFloat(v any) (float64, error) {
	switch x := v.(type) {
	case float64:
		return x, nil
	case float32:
		return float64(x), nil
	case int:
		return float64(x), nil
	case int64:
		return float64(x), nil
	case json.Number:
		return x.Float64()
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(x), 64)
		if err != nil {
			return 0, fmt.Errorf("must be a number")
		}
		return f, nil
	}
	return 0, fmt.Errorf("must be a number")
}

// ToBool converts booleans, numbers and the strtobool() vocabulary used by
// the original implementation ("y", "yes", "t", "true", "on", "1", ...).
func ToBool(v any) (bool, error) {
	switch x := v.(type) {
	case bool:
		return x, nil
	case float64:
		return x != 0, nil
	case int:
		return x != 0, nil
	case json.Number:
		f, err := x.Float64()
		return f != 0, err
	case string:
		switch strings.ToLower(strings.TrimSpace(x)) {
		case "y", "yes", "t", "true", "on", "1":
			return true, nil
		case "n", "no", "f", "false", "off", "0":
			return false, nil
		}
	}
	return false, fmt.Errorf("must be true or false")
}

func oneOf(v string, allowed []string) error {
	for _, a := range allowed {
		if v == a {
			return nil
		}
	}
	return fmt.Errorf("must be one of %s", strings.Join(allowed, ", "))
}

func validateString(key, v string) (string, error) {
	v = strings.TrimSpace(v)
	switch key {
	case "media_orientation_filter":
		v = strings.ToLower(v)
		if v == "all" {
			v = "both"
		}
		return v, oneOf(v, Orientations)
	case "display_mode":
		v = strings.ToLower(v)
		return v, oneOf(v, DisplayModes)
	case "scale_mode":
		v = strings.ToLower(v)
		return v, oneOf(v, ScaleModes)
	case "playback_mode":
		v = strings.ToLower(v)
		if v == "shuffle" {
			v = "random"
		}
		return v, oneOf(v, PlaybackModes)
	case "theme":
		v = strings.ToLower(v)
		if !strings.HasSuffix(v, "-theme") {
			v += "-theme"
		}
		return v, oneOf(v, Themes)
	case "time_on", "time_off":
		if len(v) == 4 && v[1] == ':' { // "8:00" -> "08:00"
			v = "0" + v
		}
		if !timeRe.MatchString(v) {
			return v, fmt.Errorf("must be HH:MM")
		}
	case "device_name":
		if v == "" {
			return v, fmt.Errorf("must not be empty")
		}
		if len(v) > 64 {
			return v, fmt.Errorf("must be at most 64 characters")
		}
	case "mqtt_topic":
		v = strings.Trim(v, "/")
		if v == "" {
			return v, fmt.Errorf("must not be empty")
		}
		if strings.ContainsAny(v, "+#") {
			return v, fmt.Errorf("must not contain MQTT wildcards")
		}
	case "mqtt_broker":
		for _, p := range []string{"mqtt://", "tcp://"} {
			v = strings.TrimPrefix(v, p)
		}
		if v == "" {
			return v, fmt.Errorf("must not be empty")
		}
		if net.ParseIP(strings.Trim(v, "[]")) == nil && !hostnameRe.MatchString(v) {
			return v, fmt.Errorf("must be an IP address or hostname")
		}
	case "image_folder", "thumbnail_folder":
		if v == "" {
			return v, fmt.Errorf("must not be empty")
		}
	case "display_browser":
		if v == "" {
			v = "none"
		}
	}
	return v, nil
}

func validateInt(key string, v int) (int, error) {
	switch key {
	case "web_interface_port", "mqtt_port", "plex_port":
		if v < 1 || v > 65535 {
			return v, fmt.Errorf("must be a port between 1 and 65535")
		}
	case "rotation":
		v = ((v % 360) + 360) % 360
		if v%90 != 0 {
			return v, fmt.Errorf("must be 0, 90, 180 or 270")
		}
	case "i2c_bus":
		if v < 0 || v > 255 {
			return v, fmt.Errorf("must be between 0 and 255")
		}
	}
	return v, nil
}

func validateFloat(key string, v float64) error {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return fmt.Errorf("must be a finite number")
	}
	switch key {
	case "frame_interval":
		if v < 1 || v > 86400 {
			return fmt.Errorf("must be between 1 and 86400 seconds")
		}
	case "transition_duration":
		if v < 0 || v > 3600 {
			return fmt.Errorf("must be between 0 and 3600 seconds")
		}
	}
	return nil
}

// ParseClock parses "HH:MM" into minutes after midnight.
func ParseClock(s string) (int, bool) {
	if !timeRe.MatchString(s) {
		return 0, false
	}
	h, _ := strconv.Atoi(s[:2])
	m, _ := strconv.Atoi(s[3:])
	return h*60 + m, true
}

// ScheduleActive reports whether the on/off schedule is in effect.
func (s Settings) ScheduleActive() bool {
	return s.ScheduleEnabled && s.TimeOn != s.TimeOff
}

// InOnWindow reports whether t falls in the [time_on, time_off) window.
// Windows that cross midnight (e.g. 18:00-02:00) are supported.
func (s Settings) InOnWindow(t time.Time) bool {
	on, ok1 := ParseClock(s.TimeOn)
	off, ok2 := ParseClock(s.TimeOff)
	if !ok1 || !ok2 || on == off {
		return true
	}
	now := t.Hour()*60 + t.Minute()
	if on < off {
		return now >= on && now < off
	}
	return now >= on || now < off
}
