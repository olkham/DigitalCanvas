package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// The config.json shipped with the original Python app.
const original = `{
    "image_folder": "images",
    "thumbnail_folder": "thumbnails",
    "frame_interval": 10,
    "transition_duration": 5,
    "media_orientation_filter": "both",
    "display_mode": "fullscreen",
    "web_interface_port": 7000,
    "mqtt_broker": "192.168.1.241",
    "mqtt_port": 1883,
    "mqtt_topic": "1/office/canvas-nuc",
    "device_name": "office-canvas",
    "theme": "dark-theme",
    "rotation": 0,
    "scale_mode": "fit",
    "plex_port": 32400,
    "allow_plex": true,
    "pause_when_plex_playing": true,
    "auto_brightness": false,
    "auto_rotation": false,
    "light_sensor_max_reading": 10000,
    "light_sensor_min_reading": 0,
    "playback_mode": "sequential",
    "time_on": "08:00",
    "time_off": "22:00",
    "some_future_key": {"x": 1}
}`

func openTemp(t *testing.T, content string) *Store {
	t.Helper()
	p := filepath.Join(t.TempDir(), "config.json")
	if content != "" {
		if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	st, err := Open(p, "abcd")
	if err != nil {
		t.Fatal(err)
	}
	return st
}

func TestLoadOriginalConfig(t *testing.T) {
	st := openTemp(t, original)
	s := st.Get()
	if s.MQTTTopic != "1/office/canvas-nuc" || s.FrameInterval != 10 || s.LightSensorMaxReading != 10000 || s.AutoBrightness {
		t.Fatalf("unexpected settings: %+v", s)
	}
	if !s.ScheduleEnabled || s.DisplayBrowser != "auto" {
		t.Fatalf("new keys should get defaults: %+v", s)
	}
	// New keys are written back, unknown keys and integer formatting kept.
	b, _ := os.ReadFile(st.Path())
	text := string(b)
	for _, want := range []string{`"some_future_key": {"x": 1}`, `"frame_interval": 10,`, `"schedule_enabled": true`} {
		if !strings.Contains(text, want) {
			t.Errorf("saved config missing %s:\n%s", want, text)
		}
	}
	if strings.Index(text, `"image_folder"`) > strings.Index(text, `"time_off"`) {
		t.Error("original key order not preserved")
	}
}

func TestDefaultsWhenMissing(t *testing.T) {
	st := openTemp(t, "")
	s := st.Get()
	if s.DeviceName != "digital-canvas-abcd" || s.MQTTTopic != "digital-canvas-abcd" {
		t.Fatalf("device defaults: %+v", s)
	}
	if _, err := os.Stat(st.Path()); err != nil {
		t.Fatal("defaults not written")
	}
}

func TestUpdateCoercionAndValidation(t *testing.T) {
	st := openTemp(t, original)
	var notified []string
	st.Subscribe(func(c []string) { notified = append(notified, c...) })
	// Values as they arrive from HTML forms and MQTT payloads.
	changed, errs := st.Update(map[string]any{
		"rotation": "90", "auto_rotation": "on", "frame_interval": "30",
		"transition_duration": 1.5, "theme": "ocean-breeze", "time_on": "7:30",
		"mqtt_broker": "homeassistant.local", "media_orientation_filter": "all",
	})
	if len(errs) != 0 {
		t.Fatalf("unexpected errors: %v", errs)
	}
	s := st.Get()
	if s.Rotation != 90 || !s.AutoRotation || s.FrameInterval != 30 || s.TransitionDuration != 1.5 ||
		s.Theme != "ocean-breeze-theme" || s.TimeOn != "07:30" || s.MQTTBroker != "homeassistant.local" ||
		s.MediaOrientationFilter != "both" {
		t.Fatalf("coercion failed: %+v", s)
	}
	if len(changed) != 7 || len(notified) != 7 { // filter was already "both"
		t.Fatalf("changed=%v notified=%v", changed, notified)
	}
	_, errs = st.Update(map[string]any{
		"rotation": 45, "scale_mode": "stretch", "frame_interval": 0, "time_off": "25:00",
		"mqtt_port": 70000, "mqtt_topic": "a/#", "device_name": "  ", "nope": 1, "auto_brightness": "maybe",
	})
	if len(errs) != 9 {
		t.Fatalf("expected 9 errors, got %v", errs)
	}
	if st.Get().Rotation != 90 {
		t.Fatal("invalid value must not be applied")
	}
	if err := st.Flush(); err != nil {
		t.Fatal(err)
	}
	var onDisk map[string]any
	b, _ := os.ReadFile(st.Path())
	if err := json.Unmarshal(b, &onDisk); err != nil {
		t.Fatal(err)
	}
	if onDisk["rotation"].(float64) != 90 {
		t.Fatalf("not persisted: %v", onDisk["rotation"])
	}
}

func TestSecretsRedacted(t *testing.T) {
	st := openTemp(t, original)
	st.Set("mqtt_password", "hunter2")
	if st.Map(true)["mqtt_password"] != RedactedSecret {
		t.Fatal("password leaked")
	}
	// Echoing the placeholder back keeps the stored secret.
	st.Update(map[string]any{"mqtt_password": RedactedSecret})
	if st.Get().MQTTPassword != "hunter2" {
		t.Fatal("placeholder overwrote the secret")
	}
}

func TestSchedule(t *testing.T) {
	at := func(h, m int) time.Time { return time.Date(2026, 1, 1, h, m, 0, 0, time.Local) }
	day := Settings{ScheduleEnabled: true, TimeOn: "08:00", TimeOff: "22:00"}
	night := Settings{ScheduleEnabled: true, TimeOn: "18:00", TimeOff: "02:00"}
	cases := []struct {
		s    Settings
		t    time.Time
		want bool
	}{
		{day, at(7, 59), false}, {day, at(8, 0), true}, {day, at(21, 59), true}, {day, at(22, 0), false},
		// Windows crossing midnight were impossible in the original.
		{night, at(17, 0), false}, {night, at(19, 0), true}, {night, at(1, 30), true}, {night, at(2, 0), false},
	}
	for _, c := range cases {
		if got := c.s.InOnWindow(c.t); got != c.want {
			t.Errorf("%s-%s at %s: got %v", c.s.TimeOn, c.s.TimeOff, c.t.Format("15:04"), got)
		}
	}
	if (Settings{ScheduleEnabled: true, TimeOn: "08:00", TimeOff: "08:00"}).ScheduleActive() {
		t.Error("equal times disable the schedule")
	}
}

func TestReloadKeepsPendingAndPicksUpManualEdits(t *testing.T) {
	st := openTemp(t, original)
	st.Set("rotation", 90) // debounced, not on disk yet
	if err := st.Reload(); err != nil {
		t.Fatal(err)
	}
	if st.Get().Rotation != 90 {
		t.Fatal("reload discarded a pending change")
	}
	// A manual edit made outside the app is picked up.
	time.Sleep(20 * time.Millisecond)
	b, _ := os.ReadFile(st.Path())
	os.WriteFile(st.Path(), []byte(strings.Replace(string(b), `"rotation": 90`, `"rotation": 180`, 1)), 0o644)
	future := time.Now().Add(2 * time.Second)
	os.Chtimes(st.Path(), future, future)
	if err := st.Reload(); err != nil {
		t.Fatal(err)
	}
	if st.Get().Rotation != 180 {
		t.Fatalf("manual edit not picked up: %d", st.Get().Rotation)
	}
}
