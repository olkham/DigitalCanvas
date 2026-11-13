package player

import (
	"sort"
	"sync"
	"testing"
	"time"

	"github.com/olkham/DigitalCanvas/internal/media"
)

type fakeLib struct {
	mu    sync.Mutex
	items []media.Item
}

func (f *fakeLib) Items() []media.Item {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := append([]media.Item(nil), f.items...)
	sort.Slice(out, func(i, j int) bool { return out[i].Added < out[j].Added })
	return out
}

func (f *fakeLib) Get(name string) (media.Item, bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, it := range f.items {
		if it.Name == name {
			return it, true
		}
	}
	return media.Item{}, false
}

func (f *fakeLib) Prefetch(string) {}

func (f *fakeLib) remove(name string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	for i, it := range f.items {
		if it.Name == name {
			f.items = append(f.items[:i], f.items[i+1:]...)
			return
		}
	}
}

func lib(names ...string) *fakeLib {
	f := &fakeLib{}
	for i, n := range names {
		o := "landscape"
		if n[0] == 'p' {
			o = "portrait"
		}
		f.items = append(f.items, media.Item{Name: n, Kind: media.KindImage, Orientation: o, Playable: true, Added: int64(i)})
	}
	return f
}

type harness struct {
	t      *testing.T
	p      *Player
	lib    *fakeLib
	s      Settings
	mu     sync.Mutex
	slides []Slide
}

func newHarness(t *testing.T, l *fakeLib) *harness {
	h := &harness{t: t, lib: l, s: Settings{FrameInterval: 3600, Transition: 0, Filter: "both", Order: "sequential"}}
	h.p = New(l, func() Settings { h.mu.Lock(); defer h.mu.Unlock(); return h.s }, func(name string, data any) {
		if s, ok := data.(Slide); ok && name == "slide" {
			h.mu.Lock()
			h.slides = append(h.slides, s)
			h.mu.Unlock()
		}
	}, func() Slide { return Slide{Name: "idle"} })
	return h
}

func (h *harness) cur() string {
	s, _ := h.p.Current()
	return s.Name
}

func (h *harness) expect(want string) {
	h.t.Helper()
	if got := h.cur(); got != want {
		h.t.Fatalf("current = %q, want %q", got, want)
	}
}

func TestSequentialNavigation(t *testing.T) {
	h := newHarness(t, lib("a", "b", "c"))
	h.p.Start()
	h.expect("a")
	h.p.Next()
	h.expect("b")
	h.p.Next()
	h.p.Next() // wraps
	h.expect("a")
	h.p.Previous() // wraps backwards
	h.expect("c")
	if !h.p.Select("b") {
		t.Fatal("select failed")
	}
	h.p.Next()
	h.expect("c")
	if st := h.p.Status(); st.Position != 3 || st.Count != 3 {
		t.Fatalf("status %+v", st)
	}
}

func TestTimerAdvances(t *testing.T) {
	h := newHarness(t, lib("a", "b"))
	h.s.FrameInterval = 0.05
	h.p.Start()
	time.Sleep(180 * time.Millisecond)
	h.mu.Lock()
	n := len(h.slides)
	h.mu.Unlock()
	if n < 3 {
		t.Fatalf("expected the timer to advance, got %d slides", n)
	}
	h.p.Pause(ByUser)
	h.mu.Lock()
	n = len(h.slides)
	h.mu.Unlock()
	time.Sleep(150 * time.Millisecond)
	h.mu.Lock()
	defer h.mu.Unlock()
	if len(h.slides) != n {
		t.Fatal("advanced while paused")
	}
}

func TestOrientationFilter(t *testing.T) {
	h := newHarness(t, lib("l1", "p1", "l2", "p2"))
	h.s.Filter = "portrait"
	h.p.Start()
	h.expect("p1")
	h.p.Next()
	h.expect("p2")
	h.p.Next()
	h.expect("p1")
}

func TestRandomNeverRepeatsBackToBack(t *testing.T) {
	h := newHarness(t, lib("a", "b", "c", "d"))
	h.s.Order = "random"
	h.p.Start()
	prev := h.cur()
	seen := map[string]bool{prev: true}
	for i := 0; i < 200; i++ {
		h.p.Next()
		if c := h.cur(); c == prev {
			t.Fatalf("repeated %q", c)
		} else {
			prev = c
			seen[c] = true
		}
	}
	if len(seen) != 4 {
		t.Fatalf("not all items shown: %v", seen)
	}
}

func TestPauseReasons(t *testing.T) {
	h := newHarness(t, lib("a", "b"))
	h.p.Start()
	// Plex pauses, Plex resumes.
	h.p.Pause(ByPlex)
	h.p.Resume(ByPlex)
	if !h.p.Active() {
		t.Fatal("plex should resume its own pause")
	}
	// A user pause is not undone by Plex stopping or the schedule.
	h.p.Pause(ByUser)
	h.p.Resume(ByPlex)
	h.p.Resume(BySchedule)
	if h.p.Active() {
		t.Fatal("automatic resume overrode a user pause")
	}
	h.p.Resume(ByUser)
	// Schedule off then on restores playback.
	h.p.Pause(BySchedule)
	h.p.Resume(BySchedule)
	if !h.p.Active() {
		t.Fatal("schedule should resume")
	}
}

func TestTransientThenContinue(t *testing.T) {
	h := newHarness(t, lib("a", "b", "c"))
	h.p.Start()
	h.p.Next() // b
	h.p.ShowTransient(&media.Transient{ID: "t1", Title: "Plex"})
	if s, _ := h.p.Current(); !s.Transient || s.Title != "Plex" {
		t.Fatalf("transient not shown: %+v", s)
	}
	h.p.Previous() // back to the interrupted item
	h.expect("b")
	h.p.ShowTransient(&media.Transient{ID: "t2"})
	h.p.Next()
	h.expect("c")
}

func TestVideoEndAdvancesOnlyWhenActive(t *testing.T) {
	l := lib("a", "b")
	l.items[0].Kind = media.KindVideo
	l.items[0].Duration = 100
	h := newHarness(t, l)
	h.p.Start()
	s, _ := h.p.Current()
	h.p.Ended(s.Seq + 1) // stale/unknown sequence number
	h.expect("a")
	h.p.Pause(ByUser)
	h.p.Ended(s.Seq) // paused: the display loops the video
	h.expect("a")
	h.p.Resume(ByUser)
	h.p.Ended(s.Seq)
	h.expect("b")
}

func TestDeletingCurrentAdvancesAndEmptyGoesIdle(t *testing.T) {
	l := lib("a", "b")
	h := newHarness(t, l)
	h.p.Start()
	l.remove("a")
	h.p.Rebuild(false)
	h.expect("b")
	l.remove("b")
	h.p.Rebuild(false)
	if s, _ := h.p.Current(); s.Kind != "idle" {
		t.Fatalf("expected idle, got %+v", s)
	}
	l.mu.Lock()
	l.items = append(l.items, media.Item{Name: "new", Kind: media.KindImage, Orientation: "landscape", Playable: true})
	l.mu.Unlock()
	h.p.Rebuild(false)
	h.expect("new") // the first upload is shown straight away
}

func TestDeletedMiddleKeepsPosition(t *testing.T) {
	l := lib("a", "b", "c", "d")
	h := newHarness(t, l)
	h.p.Start()
	h.p.Next() // b
	l.remove("c")
	h.p.Rebuild(false)
	h.p.Next()
	h.expect("d")
}

func TestFailedSkips(t *testing.T) {
	h := newHarness(t, lib("a", "b"))
	h.p.Start()
	s, _ := h.p.Current()
	h.p.Failed(s.Seq)
	time.Sleep(1700 * time.Millisecond)
	h.expect("b")
}
