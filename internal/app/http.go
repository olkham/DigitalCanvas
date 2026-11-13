package app

import (
	"encoding/json"
	"errors"
	"io"
	"log"
	"mime"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/olkham/DigitalCanvas/internal/hub"
	"github.com/olkham/DigitalCanvas/internal/media"
)

func (a *App) routes() http.Handler {
	mux := http.NewServeMux()

	// Pages and static assets.
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) { a.web.serve(w, r, "index.html") })
	mux.HandleFunc("POST /{$}", func(w http.ResponseWriter, r *http.Request) { a.web.serve(w, r, "index.html") })
	mux.HandleFunc("GET /display", func(w http.ResponseWriter, r *http.Request) { a.web.serve(w, r, "display.html") })
	mux.HandleFunc("GET /assets/{file...}", func(w http.ResponseWriter, r *http.Request) {
		a.web.serve(w, r, r.PathValue("file"))
	})
	mux.HandleFunc("GET /favicon.ico", func(w http.ResponseWriter, r *http.Request) { a.web.serve(w, r, "favicon.ico") })

	// JSON API used by the web UI and display.
	mux.HandleFunc("GET /api/state", a.apiState)
	mux.HandleFunc("GET /api/info", a.apiInfo)
	mux.HandleFunc("GET /api/events", a.apiEvents)
	mux.HandleFunc("GET /api/media", a.apiMedia)
	mux.HandleFunc("POST /api/media", a.apiUpload)
	mux.HandleFunc("POST /api/media/url", a.apiUploadURL)
	mux.HandleFunc("POST /api/media/delete", a.apiDeleteMany)
	mux.HandleFunc("DELETE /api/media/{name}", a.apiDelete)
	mux.HandleFunc("POST /api/media/{name}/show", a.apiShow)
	mux.HandleFunc("POST /api/command", a.apiCommand)
	mux.HandleFunc("PATCH /api/config", a.apiConfig)
	mux.HandleFunc("POST /api/config", a.apiConfig)
	mux.HandleFunc("POST /api/monitor", a.apiMonitor)
	mux.HandleFunc("POST /api/system", a.apiSystem)
	mux.HandleFunc("POST /api/display/report", a.apiDisplayReport)

	// Media files.
	mux.HandleFunc("GET /media/{name}", a.serveOriginal)
	mux.HandleFunc("GET /media/{name}/display", a.serveDisplayFile)
	mux.HandleFunc("GET /media/{name}/bg", a.serveBackground)
	mux.HandleFunc("GET /thumbnails/{name}", a.serveThumb)
	mux.HandleFunc("GET /transient/{id}", a.serveTransient)
	mux.HandleFunc("GET /transient/{id}/bg", a.serveTransient)
	mux.HandleFunc("GET /canvas", a.serveCanvas)

	a.legacyRoutes(mux)
	return a.middleware(mux)
}

// middleware rejects cross-site browser requests that change state (a
// malicious web page cannot drive the canvas), while non-browser clients
// such as Plex, Home Assistant or curl, which send no Origin, are unaffected.
func (a *App) middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("http: panic serving %s %s: %v", r.Method, r.URL.Path, rec)
				http.Error(w, "internal error", http.StatusInternalServerError)
			}
		}()
		if r.Method != http.MethodGet && r.Method != http.MethodHead && r.Method != http.MethodOptions {
			if o := r.Header.Get("Origin"); o != "" && o != "null" {
				if u, err := url.Parse(o); err != nil || !sameHost(u.Host, r.Host) {
					http.Error(w, "cross-origin request rejected", http.StatusForbidden)
					return
				}
			}
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		next.ServeHTTP(w, r)
	})
}

func sameHost(a, b string) bool {
	ha, pa, err1 := net.SplitHostPort(a)
	hb, pb, err2 := net.SplitHostPort(b)
	if err1 != nil {
		ha, pa = a, ""
	}
	if err2 != nil {
		hb, pb = b, ""
	}
	return strings.EqualFold(ha, hb) && (pa == pb || pa == "" || pb == "")
}

// ---- helpers ----

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, status int, err error) {
	writeJSON(w, status, map[string]any{"success": false, "error": err.Error()})
}

func readJSON(r *http.Request, v any) error {
	defer r.Body.Close()
	dec := json.NewDecoder(io.LimitReader(r.Body, 1<<20))
	dec.UseNumber()
	return dec.Decode(v)
}

// wantsJSON distinguishes the new UI (fetch) from classic form posts.
func wantsJSON(r *http.Request) bool {
	return strings.Contains(r.Header.Get("Accept"), "application/json") || r.Header.Get("X-Requested-With") != ""
}

func (a *App) serveFile(w http.ResponseWriter, r *http.Request, p, ctype string, immutable bool) {
	f, err := os.Open(p)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil || st.IsDir() {
		http.NotFound(w, r)
		return
	}
	if ctype == "" {
		ctype = mime.TypeByExtension(strings.ToLower(filepath.Ext(p)))
	}
	if ctype != "" {
		w.Header().Set("Content-Type", ctype)
	}
	if immutable && r.URL.Query().Get("v") != "" {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	} else {
		w.Header().Set("Cache-Control", "no-cache")
	}
	http.ServeContent(w, r, "", st.ModTime(), f) // handles Range for video seeking
}

func videoType(name string) string {
	switch strings.ToLower(filepath.Ext(name)) {
	case ".mp4", ".m4v", ".mov":
		return "video/mp4" // QuickTime is ISO-BMFF; browsers accept it as MP4
	case ".webm", ".mkv":
		return "video/webm"
	}
	return ""
}

func (a *App) mediaName(w http.ResponseWriter, r *http.Request) (media.Item, bool) {
	name, ok := media.SafeName(r.PathValue("name"))
	if !ok {
		http.Error(w, "bad name", http.StatusBadRequest)
		return media.Item{}, false
	}
	it, ok := a.lib.Get(name)
	if !ok {
		http.NotFound(w, r)
		return media.Item{}, false
	}
	return it, true
}

func (a *App) serveOriginal(w http.ResponseWriter, r *http.Request) {
	it, ok := a.mediaName(w, r)
	if !ok {
		return
	}
	ct := ""
	if it.Kind == media.KindVideo {
		ct = videoType(it.Name)
	}
	a.serveFile(w, r, a.lib.OriginalPath(it.Name), ct, false)
}

func (a *App) serveDisplayFile(w http.ResponseWriter, r *http.Request) {
	it, ok := a.mediaName(w, r)
	if !ok {
		return
	}
	p, err := a.lib.DisplayPath(it.Name)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	ct := ""
	if it.Kind == media.KindVideo {
		ct = videoType(p)
	}
	a.serveFile(w, r, p, ct, true)
}

func (a *App) serveBackground(w http.ResponseWriter, r *http.Request) {
	it, ok := a.mediaName(w, r)
	if !ok {
		return
	}
	p, err := a.lib.BackgroundPath(it.Name)
	if err != nil {
		// Fall back to a neutral dark backdrop rather than a broken image.
		w.Header().Set("Cache-Control", "no-cache")
		a.web.serve(w, r, "blank.svg")
		return
	}
	a.serveFile(w, r, p, "image/jpeg", true)
}

// serveThumb serves /thumbnails/<media name>. Thumbnails are always JPEG and
// named after the media stem, so the original URL scheme keeps working.
func (a *App) serveThumb(w http.ResponseWriter, r *http.Request) {
	name, ok := media.SafeName(r.PathValue("name"))
	if !ok {
		http.Error(w, "bad name", http.StatusBadRequest)
		return
	}
	if _, found := a.lib.Get(name); !found {
		// Accept "<stem>.jpg" for media whose extension differs.
		stem := strings.TrimSuffix(name, filepath.Ext(name))
		for _, it := range a.lib.Items() {
			if it.Stem() == stem {
				name = it.Name
				break
			}
		}
	}
	p, err := a.lib.ThumbPath(name)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	a.serveFile(w, r, p, "image/jpeg", true)
}

func (a *App) serveTransient(w http.ResponseWriter, r *http.Request) {
	t, ok := a.trans.Get(r.PathValue("id"))
	if !ok {
		http.NotFound(w, r)
		return
	}
	data := t.Data
	if strings.HasSuffix(r.URL.Path, "/bg") {
		data = t.Bg
	}
	w.Header().Set("Content-Type", "image/jpeg")
	w.Header().Set("Cache-Control", "public, max-age=86400, immutable")
	http.ServeContent(w, r, "", t.Created, strings.NewReader(string(data)))
}

func (a *App) serveCanvas(w http.ResponseWriter, r *http.Request) {
	b, err := a.CanvasJPEG()
	if err != nil {
		http.Error(w, "Viewer not ready: "+err.Error(), http.StatusServiceUnavailable)
		return
	}
	w.Header().Set("Content-Type", "image/jpeg")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = w.Write(b)
}

// ---- events ----

func (a *App) apiEvents(w http.ResponseWriter, r *http.Request) {
	role := r.URL.Query().Get("role")
	if role != hub.RoleDisplay {
		role = hub.RoleUI
	}
	kiosk := role == hub.RoleDisplay && a.kiosk != nil && r.URL.Query().Get("kiosk") == a.kiosk.Token()
	a.hub.Serve(w, r, role, kiosk, a.state(role == hub.RoleUI))
}

func (a *App) apiState(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, a.state(true))
}

func (a *App) apiInfo(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, a.info())
}

func (a *App) apiMedia(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, a.lib.Items())
}

// ---- uploads ----

type uploadResult struct {
	Added  []media.Item `json:"added"`
	Errors []string     `json:"errors,omitempty"`
}

// handleUploadForm streams a multipart upload (files and/or image_url) to
// disk without buffering it in memory.
func (a *App) handleUploadForm(r *http.Request) (uploadResult, error) {
	res := uploadResult{Added: []media.Item{}}
	mr, err := r.MultipartReader()
	if err != nil {
		// application/x-www-form-urlencoded: only image_url is possible.
		if perr := r.ParseForm(); perr == nil {
			if u := r.PostFormValue("image_url"); u != "" {
				it, err := a.ImportURL(r.Context(), u)
				if err != nil {
					res.Errors = append(res.Errors, err.Error())
				} else {
					res.Added = append(res.Added, it)
				}
				return res, nil
			}
		}
		return res, errors.New("expected a multipart upload")
	}
	for {
		part, err := mr.NextPart()
		if err == io.EOF {
			break
		}
		if err != nil {
			return res, err
		}
		switch part.FormName() {
		case "file", "files", "file[]":
			if part.FileName() == "" {
				continue
			}
			f, err := a.tempFile()
			if err != nil {
				return res, err
			}
			_, cerr := io.Copy(f, part)
			f.Close()
			if cerr != nil {
				os.Remove(f.Name())
				return res, cerr
			}
			it, err := a.lib.Import(f.Name(), media.ImportOptions{OriginalName: part.FileName(), ContentType: part.Header.Get("Content-Type")})
			if err != nil {
				res.Errors = append(res.Errors, part.FileName()+": "+err.Error())
				continue
			}
			res.Added = append(res.Added, it)
		case "image_url", "url":
			b, _ := io.ReadAll(io.LimitReader(part, 8<<10))
			if u := strings.TrimSpace(string(b)); u != "" {
				it, err := a.ImportURL(r.Context(), u)
				if err != nil {
					res.Errors = append(res.Errors, u+": "+err.Error())
					continue
				}
				res.Added = append(res.Added, it)
			}
		}
	}
	return res, nil
}

func (a *App) apiUpload(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 16<<30)
	res, err := a.handleUploadForm(r)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	status := http.StatusOK
	if len(res.Added) == 0 && len(res.Errors) > 0 {
		status = http.StatusUnprocessableEntity
	}
	writeJSON(w, status, res)
}

func (a *App) apiUploadURL(w http.ResponseWriter, r *http.Request) {
	var body struct {
		URL string `json:"url"`
	}
	if err := readJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	it, err := a.ImportURL(r.Context(), body.URL)
	if err != nil {
		writeErr(w, http.StatusUnprocessableEntity, err)
		return
	}
	writeJSON(w, http.StatusOK, uploadResult{Added: []media.Item{it}})
}

func (a *App) apiDelete(w http.ResponseWriter, r *http.Request) {
	n, err := a.DeleteMedia(r.PathValue("name"))
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err)
		return
	}
	if n == 0 {
		writeErr(w, http.StatusNotFound, errors.New("not found"))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "deleted": n})
}

func (a *App) apiDeleteMany(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Names []string `json:"names"`
	}
	if err := readJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	n, err := a.DeleteMedia(body.Names...)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "deleted": n})
}

func (a *App) apiShow(w http.ResponseWriter, r *http.Request) {
	it, ok := a.mediaName(w, r)
	if !ok {
		return
	}
	a.player.Select(it.Name)
	writeJSON(w, http.StatusOK, map[string]any{"success": true})
}

// ---- commands and settings ----

func (a *App) apiCommand(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Action string `json:"action"`
		Value  string `json:"value"`
	}
	if err := readJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	switch body.Action {
	case "quit":
		// Only the supervised kiosk display may quit the application.
		if a.kiosk == nil || r.Header.Get("X-Kiosk-Token") != a.kiosk.Token() {
			writeJSON(w, http.StatusOK, map[string]any{"success": false, "handled": false})
			return
		}
	case "toggle_fullscreen":
		if a.kiosk == nil || r.Header.Get("X-Kiosk-Token") != a.kiosk.Token() {
			// Not our kiosk: the page toggles fullscreen itself.
			writeJSON(w, http.StatusOK, map[string]any{"success": false, "handled": false})
			return
		}
	}
	if err := a.Command(body.Action, body.Value); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "handled": true, "playback": a.player.Status()})
}

func (a *App) apiConfig(w http.ResponseWriter, r *http.Request) {
	var body map[string]any
	if err := readJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	changed, errs := a.UpdateConfig(body)
	status := http.StatusOK
	if len(errs) > 0 {
		status = http.StatusUnprocessableEntity
	}
	restart := []string{}
	for _, k := range changed {
		if isRestartKey(k) {
			restart = append(restart, k)
		}
	}
	writeJSON(w, status, map[string]any{"success": len(errs) == 0, "changed": changed, "errors": errs, "restart_required": restart, "config": a.cfg.Map(true)})
}

func (a *App) apiMonitor(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Power      *bool `json:"power"`
		Brightness *int  `json:"brightness"`
		Auto       *bool `json:"auto"`
	}
	if err := readJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	var err error
	if body.Auto != nil {
		err = a.cfg.Set("auto_brightness", *body.Auto)
	}
	if body.Brightness != nil {
		err = a.SetBrightness(*body.Brightness)
	}
	if body.Power != nil {
		err = a.SetPower(*body.Power)
	}
	if err != nil {
		writeErr(w, http.StatusBadGateway, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true, "status": a.status()})
}

func (a *App) apiSystem(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Action string `json:"action"`
	}
	if err := readJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	if err := a.systemAction(body.Action); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"success": true})
}

func (a *App) apiDisplayReport(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Type   string `json:"type"`
		Seq    int64  `json:"seq"`
		Width  int    `json:"width"`
		Height int    `json:"height"`
		Kiosk  string `json:"kiosk"`
		Error  string `json:"error"`
	}
	if err := readJSON(r, &body); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	switch body.Type {
	case "hello":
		// The kiosk's screen is authoritative; other displays only count
		// when no kiosk is running.
		isKiosk := a.kiosk != nil && body.Kiosk == a.kiosk.Token()
		if isKiosk || a.kiosk == nil {
			a.setScreen(body.Width, body.Height)
		}
	case "ended":
		a.player.Ended(body.Seq)
	case "ready":
		a.player.Ready(body.Seq)
	case "error":
		if body.Error != "" {
			log.Printf("display: %s", body.Error)
		}
		a.player.Failed(body.Seq)
	}
	w.WriteHeader(http.StatusNoContent)
}

func isRestartKey(k string) bool {
	switch k {
	case "image_folder", "thumbnail_folder", "web_interface_port", "i2c_bus", "display_browser":
		return true
	}
	return false
}

var _ = time.Second
