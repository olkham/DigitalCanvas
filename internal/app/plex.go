package app

import (
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"strconv"
	"strings"

	"github.com/olkham/DigitalCanvas/internal/player"
)

type plexPayload struct {
	Event    string `json:"event"`
	Metadata struct {
		LibrarySectionType string `json:"librarySectionType"`
		Title              string `json:"title"`
		ParentTitle        string `json:"parentTitle"`
		GrandparentTitle   string `json:"grandparentTitle"`
		Thumb              string `json:"thumb"`
		ParentThumb        string `json:"parentThumb"`
		GrandparentThumb   string `json:"grandparentThumb"`
	} `json:"Metadata"`
}

// art mirrors the original get_thumbnail()/get_title(): movie poster, show
// poster for episodes, album art for music.
func (p plexPayload) art() (thumb, title string) {
	m := p.Metadata
	switch m.LibrarySectionType {
	case "movie":
		thumb, title = m.Thumb, m.Title
	case "show":
		thumb, title = m.GrandparentThumb, m.GrandparentTitle
	default:
		thumb, title = m.ParentThumb, m.ParentTitle
	}
	if thumb == "null" {
		thumb = ""
	}
	return
}

// plexHook handles Plex Media Server webhooks: show artwork on play/resume
// (optionally pausing the slideshow) and resume on stop/pause.
func (a *App) plexHook(w http.ResponseWriter, r *http.Request) {
	s := a.cfg.Get()
	if !s.AllowPlex {
		writeJSON(w, http.StatusForbidden, map[string]bool{"success": false})
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 32<<20)
	payloadStr, thumb, err := readPlexRequest(r)
	if err != nil || payloadStr == "" {
		writeErr(w, http.StatusBadRequest, errors.New("missing payload"))
		return
	}
	var p plexPayload
	if err := json.Unmarshal([]byte(payloadStr), &p); err != nil {
		writeErr(w, http.StatusBadRequest, err)
		return
	}
	switch p.Event {
	case "media.play", "media.resume":
		thumbURL, title := p.art()
		var art []byte
		if thumbURL != "" {
			u := "http://" + net.JoinHostPort(clientIP(r), strconv.Itoa(s.PlexPort)) + thumbURL + ".jpg"
			if art, err = a.fetchBytes(r.Context(), u, 32<<20); err != nil {
				log.Printf("plex: failed to fetch artwork from %s: %v", u, err)
			}
		}
		if len(art) == 0 {
			art = thumb // the webhook's own attachment, if any
		}
		if len(art) == 0 {
			writeJSON(w, http.StatusInternalServerError, map[string]bool{"success": false})
			return
		}
		if s.PauseWhenPlexPlaying {
			a.player.Pause(player.ByPlex)
		}
		if err := a.ShowBytes(art, title, "plex"); err != nil {
			log.Printf("plex: artwork is not a usable image: %v", err)
			writeJSON(w, http.StatusInternalServerError, map[string]bool{"success": false})
			return
		}
		log.Printf("plex: now playing %q", title)
	case "media.stop", "media.pause":
		a.player.Resume(player.ByPlex)
	}
	writeJSON(w, http.StatusOK, map[string]bool{"success": true})
}

func readPlexRequest(r *http.Request) (payload string, thumb []byte, err error) {
	ct := r.Header.Get("Content-Type")
	switch {
	case strings.HasPrefix(ct, "multipart/form-data"):
		mr, err := r.MultipartReader()
		if err != nil {
			return "", nil, err
		}
		for {
			part, err := mr.NextPart()
			if err == io.EOF {
				break
			}
			if err != nil {
				return payload, thumb, err
			}
			switch part.FormName() {
			case "payload":
				b, _ := io.ReadAll(io.LimitReader(part, 1<<20))
				payload = string(b)
			case "thumb":
				thumb, _ = io.ReadAll(io.LimitReader(part, 16<<20))
			}
		}
		return payload, thumb, nil
	case strings.HasPrefix(ct, "application/x-www-form-urlencoded"):
		return r.PostFormValue("payload"), nil, nil
	default:
		b, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		if err != nil {
			return "", nil, err
		}
		// {"payload": "<json string>"} as accepted by the original, or the
		// event JSON itself.
		var wrap struct {
			Payload json.RawMessage `json:"payload"`
		}
		if json.Unmarshal(b, &wrap) == nil && len(wrap.Payload) > 0 {
			var s string
			if json.Unmarshal(wrap.Payload, &s) == nil {
				return s, nil, nil
			}
			return string(wrap.Payload), nil, nil
		}
		return string(b), nil, nil
	}
}

// clientIP returns the caller's address (first X-Forwarded-For hop if set),
// i.e. the Plex server that sent the webhook.
func clientIP(r *http.Request) string {
	if xf := r.Header.Get("X-Forwarded-For"); xf != "" {
		return strings.TrimSpace(strings.Split(xf, ",")[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
