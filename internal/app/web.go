package app

import (
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"io/fs"
	"mime"
	"net/http"
	"path"
	"strings"

	"github.com/olkham/DigitalCanvas/web"
)

type asset struct {
	data  []byte
	gz    []byte
	ctype string
	etag  string
}

// webAssets serves the embedded UI: precompressed, ETagged and versioned so
// phones revalidate cheaply and the Pi never compresses on the fly.
type webAssets struct {
	files   map[string]*asset
	version string
}

func loadWebAssets() (*webAssets, error) {
	w := &webAssets{files: map[string]*asset{}}
	all := sha256.New()
	err := fs.WalkDir(web.Static, "static", func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		b, err := web.Static.ReadFile(p)
		if err != nil {
			return err
		}
		all.Write(b)
		name := strings.TrimPrefix(p, "static/")
		w.files[name] = &asset{data: b}
		return nil
	})
	if err != nil {
		return nil, err
	}
	w.version = hex.EncodeToString(all.Sum(nil))[:10]
	for name, a := range w.files {
		if strings.HasSuffix(name, ".html") {
			a.data = bytes.ReplaceAll(a.data, []byte("{{V}}"), []byte(w.version))
		}
		a.ctype = mime.TypeByExtension(path.Ext(name))
		if a.ctype == "" {
			a.ctype = http.DetectContentType(a.data)
		}
		sum := sha256.Sum256(a.data)
		a.etag = `"` + hex.EncodeToString(sum[:8]) + `"`
		if isCompressible(a.ctype) && len(a.data) > 512 {
			var buf bytes.Buffer
			zw, _ := gzip.NewWriterLevel(&buf, gzip.BestCompression)
			zw.Write(a.data)
			zw.Close()
			if buf.Len() < len(a.data) {
				a.gz = buf.Bytes()
			}
		}
	}
	return w, nil
}

func isCompressible(ct string) bool {
	return strings.HasPrefix(ct, "text/") || strings.Contains(ct, "javascript") || strings.Contains(ct, "json") || strings.Contains(ct, "svg")
}

func (w *webAssets) raw(name string) []byte {
	if a, ok := w.files[name]; ok {
		return a.data
	}
	return nil
}

func (w *webAssets) serve(rw http.ResponseWriter, r *http.Request, name string) {
	a, ok := w.files[name]
	if !ok {
		http.NotFound(rw, r)
		return
	}
	h := rw.Header()
	h.Set("Content-Type", a.ctype)
	h.Set("ETag", a.etag)
	h.Set("Vary", "Accept-Encoding")
	if r.URL.Query().Get("v") != "" {
		h.Set("Cache-Control", "public, max-age=31536000, immutable")
	} else {
		h.Set("Cache-Control", "no-cache")
	}
	if match := r.Header.Get("If-None-Match"); match != "" && strings.Contains(match, a.etag) {
		rw.WriteHeader(http.StatusNotModified)
		return
	}
	body := a.data
	if a.gz != nil && strings.Contains(r.Header.Get("Accept-Encoding"), "gzip") {
		h.Set("Content-Encoding", "gzip")
		body = a.gz
	}
	if r.Method == http.MethodHead {
		return
	}
	_, _ = rw.Write(body)
}
