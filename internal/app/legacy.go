package app

import (
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/olkham/DigitalCanvas/internal/config"
	"github.com/olkham/DigitalCanvas/internal/media"
	"github.com/olkham/DigitalCanvas/internal/player"
	"github.com/olkham/DigitalCanvas/internal/sysinfo"
)

// legacyRoutes keeps every endpoint of the original Flask app working with
// the same parameters and response codes, so existing automations (Home
// Assistant rest_commands, Plex webhooks, scripts) need no changes.
func (a *App) legacyRoutes(mux *http.ServeMux) {
	back := func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, "/", http.StatusFound) }
	ok := func(w http.ResponseWriter) { writeJSON(w, http.StatusOK, map[string]bool{"success": true}) }

	mux.HandleFunc("POST /display_now", a.legacyDisplayNow)

	mux.HandleFunc("POST /upload", func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, 16<<30)
		res, err := a.handleUploadForm(r)
		if wantsJSON(r) {
			if err != nil {
				writeErr(w, http.StatusBadRequest, err)
				return
			}
			writeJSON(w, http.StatusOK, res)
			return
		}
		back(w, r)
	})
	mux.HandleFunc("GET /uploads/{name}", a.serveOriginal)

	mux.HandleFunc("POST /update_device_name", func(w http.ResponseWriter, r *http.Request) {
		if err := a.cfg.Set("device_name", formValue(r, "deviceName")); err != nil {
			writeErr(w, http.StatusBadRequest, err)
			return
		}
		ok(w)
	})

	mux.HandleFunc("POST /delete", func(w http.ResponseWriter, r *http.Request) {
		name := formValue(r, "filename")
		if name == "" {
			http.Error(w, "Filename is required", http.StatusBadRequest)
			return
		}
		_, _ = a.DeleteMedia(name)
		back(w, r)
	})

	mux.HandleFunc("POST /select", func(w http.ResponseWriter, r *http.Request) {
		name := formValue(r, "filename")
		if name == "" {
			http.Error(w, "Filename is required", http.StatusBadRequest)
			return
		}
		a.player.Select(name)
		w.WriteHeader(http.StatusNoContent)
	})

	mux.HandleFunc("GET /current_image_name", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		if s, ok := a.player.Current(); ok && s.Kind != "idle" {
			if s.Transient {
				io.WriteString(w, s.Title)
			} else {
				io.WriteString(w, s.Name)
			}
		}
	})

	mux.HandleFunc("POST /configure/mqtt", func(w http.ResponseWriter, r *http.Request) {
		a.UpdateConfig(present(r, "mqtt_broker", "mqtt_port", "mqtt_topic", "mqtt_username", "mqtt_password"))
		back(w, r)
	})

	mux.HandleFunc("POST /configure/app", func(w http.ResponseWriter, r *http.Request) {
		if err := a.cfg.Set("theme", formValue(r, "theme")); err != nil {
			writeErr(w, http.StatusBadRequest, err)
			return
		}
		ok(w)
	})

	mux.HandleFunc("GET /configure/display", func(w http.ResponseWriter, r *http.Request) {
		s := a.cfg.Get()
		power := "off"
		if a.status().Monitor.Power {
			power = "on"
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"display_mode": s.DisplayMode, "media_orientation_filter": s.MediaOrientationFilter,
			"scale_mode": s.ScaleMode, "rotation": s.Rotation,
			"brightness": a.mon.Brightness(), "power": power,
		})
	})
	mux.HandleFunc("POST /configure/display", func(w http.ResponseWriter, r *http.Request) {
		if v := formValue(r, "brightness"); v != "" {
			if n, err := strconv.Atoi(v); err == nil && n >= -1 && n <= 100 {
				_ = a.SetBrightness(n)
			}
		}
		values := present(r, "display_mode", "media_orientation_filter", "scale_mode", "time_on", "time_off")
		if v := formValue(r, "rotation"); v != "" {
			if n, err := strconv.Atoi(v); err == nil {
				if n < 0 {
					values["auto_rotation"] = true
				} else {
					values["auto_rotation"] = false
					values["rotation"] = n
				}
			}
		}
		if len(values) > 0 {
			a.UpdateConfig(values)
		}
		switch formValue(r, "power") {
		case "on":
			_ = a.SetPower(true)
			ok(w)
			return
		case "off":
			_ = a.SetPower(false)
			ok(w)
			return
		}
		if _, has := values["media_orientation_filter"]; has {
			back(w, r) // the original reloaded the gallery here
			return
		}
		w.WriteHeader(http.StatusNoContent)
	})

	mux.HandleFunc("POST /configure/slideshow", func(w http.ResponseWriter, r *http.Request) {
		a.UpdateConfig(present(r, "transition_duration", "frame_interval"))
		if v := formValue(r, "slideshow_active"); v != "" {
			if on, err := config.ToBool(v); err == nil {
				if on {
					a.player.Resume(player.ByUser)
				} else {
					a.player.Pause(player.ByUser)
				}
			}
		}
		if wantsJSON(r) {
			ok(w)
			return
		}
		back(w, r)
	})

	mux.HandleFunc("POST /slideshow/next", func(w http.ResponseWriter, r *http.Request) {
		a.player.Next()
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("POST /slideshow/previous", func(w http.ResponseWriter, r *http.Request) {
		a.player.Previous()
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("POST /slideshow/delete", func(w http.ResponseWriter, r *http.Request) {
		_ = a.DeleteCurrent()
		back(w, r)
	})
	mux.HandleFunc("POST /slideshow/quit", func(w http.ResponseWriter, r *http.Request) {
		a.player.Pause(player.ByUser) // stops playback (the original stopped video)
		back(w, r)
	})

	mux.HandleFunc("POST /configure/plex", func(w http.ResponseWriter, r *http.Request) {
		a.UpdateConfig(present(r, "plex_port", "allow_plex", "pause_when_plex_playing"))
		if wantsJSON(r) {
			ok(w)
			return
		}
		back(w, r)
	})

	mux.HandleFunc("GET /configure", func(w http.ResponseWriter, r *http.Request) {
		_ = a.cfg.Reload() // pick up manual edits, as the original did
		writeJSON(w, http.StatusOK, a.cfg.Map(true))
	})
	mux.HandleFunc("POST /configure", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		if err := readJSON(r, &body); err != nil {
			writeErr(w, http.StatusBadRequest, err)
			return
		}
		a.UpdateConfig(body)
		writeJSON(w, http.StatusOK, a.cfg.Map(true))
	})

	mux.HandleFunc("POST /plex_hook", a.plexHook)

	mux.HandleFunc("POST /power_control", func(w http.ResponseWriter, r *http.Request) {
		_ = a.systemAction(formValue(r, "action"))
		w.WriteHeader(http.StatusNoContent)
	})
}

func (a *App) systemAction(action string) error {
	switch action {
	case "restart":
		a.Restart()
		return nil
	case "reboot", "shutdown":
	default:
		return errors.New("unknown action")
	}
	if a.opts.Simulate {
		return errors.New("disabled in simulation mode")
	}
	if action == "reboot" {
		return sysinfo.Reboot()
	}
	return sysinfo.Shutdown()
}

// formValue reads a form field from urlencoded or multipart bodies.
func formValue(r *http.Request, key string) string {
	if r.Form == nil {
		_ = r.ParseMultipartForm(32 << 20)
	}
	return strings.TrimSpace(r.FormValue(key))
}

// present collects the given keys that were actually submitted.
func present(r *http.Request, keys ...string) map[string]any {
	out := map[string]any{}
	if r.Form == nil {
		_ = r.ParseMultipartForm(32 << 20)
	}
	for _, k := range keys {
		if vs, ok := r.Form[k]; ok && len(vs) > 0 && strings.TrimSpace(vs[0]) != "" {
			out[k] = strings.TrimSpace(vs[0])
		}
	}
	return out
}

// legacyDisplayNow accepts a multipart "file", a form field "image" holding
// base64, or a raw body that is either base64 text or image bytes.
func (a *App) legacyDisplayNow(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 64<<20)
	var raw []byte
	var err error
	ct := r.Header.Get("Content-Type")
	switch {
	case strings.HasPrefix(ct, "multipart/form-data"):
		if err = r.ParseMultipartForm(64 << 20); err == nil {
			if f, _, ferr := r.FormFile("file"); ferr == nil {
				raw, err = io.ReadAll(f)
				f.Close()
			} else if s := r.FormValue("image"); s != "" {
				raw, err = decodeBase64Image(s)
			}
		}
	case strings.HasPrefix(ct, "application/x-www-form-urlencoded"):
		if s := formValue(r, "image"); s != "" {
			raw, err = decodeBase64Image(s)
		}
	default:
		var body []byte
		if body, err = io.ReadAll(r.Body); err == nil && len(body) > 0 {
			if sniff := http.DetectContentType(body); strings.HasPrefix(sniff, "image/") {
				raw = body
			} else {
				raw, err = decodeBase64Image(string(body))
			}
		}
	}
	if err == nil && len(raw) == 0 {
		http.Error(w, "No image data provided", http.StatusBadRequest)
		return
	}
	if err == nil {
		err = a.ShowBytes(raw, "remote_image", "display_now")
	}
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

var _ = media.KindImage
