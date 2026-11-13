package media

import (
	"sync"
	"time"

	"github.com/olkham/DigitalCanvas/internal/imaging"
)

// Transient is an image shown once without being added to the library
// (display_now requests and Plex artwork). It lives in memory only.
type Transient struct {
	ID      string
	Title   string
	Source  string // display_now | plex
	Width   int
	Height  int
	Data    []byte // screen sized JPEG
	Bg      []byte // blurred backdrop JPEG
	Created time.Time
}

// TransientStore keeps the last few transient images.
type TransientStore struct {
	mu    sync.Mutex
	items []*Transient
	keep  int
}

// NewTransientStore keeps at most keep items.
func NewTransientStore(keep int) *TransientStore { return &TransientStore{keep: keep} }

// Add decodes raw image bytes, scales them for the screen and stores them.
func (s *TransientStore) Add(raw []byte, title, source string, limit int) (*Transient, error) {
	d, err := imaging.Decode(raw)
	if err != nil {
		return nil, err
	}
	w, h := d.Size()
	nw, nh := imaging.MinSideSize(w, h, limit, 4096)
	img := imaging.Flatten(d.ScaleTo(nw, nh))
	data, err := imaging.EncodeJPEG(img, 88)
	if err != nil {
		return nil, err
	}
	tw, th := imaging.FitSize(nw, nh, 512, 512)
	bg, err := imaging.EncodeJPEG(imaging.Background(imaging.Resize(img, tw, th), bgLongSide), 90)
	if err != nil {
		return nil, err
	}
	t := &Transient{ID: NewUUID(), Title: title, Source: source, Width: nw, Height: nh, Data: data, Bg: bg, Created: time.Now()}
	s.mu.Lock()
	s.items = append(s.items, t)
	if len(s.items) > s.keep {
		s.items = s.items[len(s.items)-s.keep:]
	}
	s.mu.Unlock()
	return t, nil
}

// Get returns a stored transient by ID.
func (s *TransientStore) Get(id string) (*Transient, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, t := range s.items {
		if t.ID == id {
			return t, true
		}
	}
	return nil, false
}
