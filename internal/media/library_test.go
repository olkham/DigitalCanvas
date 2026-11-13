package media

import (
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func writeJPEG(t *testing.T, path string, w, h int) {
	t.Helper()
	m := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := 0; y < h; y += 7 {
		for x := 0; x < w; x += 7 {
			m.Set(x, y, color.RGBA{uint8(x), uint8(y), 128, 255})
		}
	}
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if err := jpeg.Encode(f, m, &jpeg.Options{Quality: 80}); err != nil {
		t.Fatal(err)
	}
}

func openLib(t *testing.T, root string) *Library {
	t.Helper()
	l, err := Open(Options{
		MediaDir: filepath.Join(root, "images"), ThumbDir: filepath.Join(root, "thumbnails"),
		CacheDir: filepath.Join(root, "cache"),
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(l.Close)
	return l
}

func waitFor(t *testing.T, what string, cond func() bool) {
	t.Helper()
	for deadline := time.Now().Add(5 * time.Second); time.Now().Before(deadline); time.Sleep(20 * time.Millisecond) {
		if cond() {
			return
		}
	}
	t.Fatalf("timed out waiting for %s", what)
}

func TestScanRenamesAndPrepares(t *testing.T) {
	root := t.TempDir()
	os.MkdirAll(filepath.Join(root, "images"), 0o755)
	os.MkdirAll(filepath.Join(root, "thumbnails"), 0o755)
	writeJPEG(t, filepath.Join(root, "images", "My Holiday.jpg"), 900, 1200)
	os.WriteFile(filepath.Join(root, "images", "notes.txt"), []byte("ignore me"), 0o644)
	os.WriteFile(filepath.Join(root, "thumbnails", "orphan.jpg"), []byte("x"), 0o644)

	l := openLib(t, root)
	if err := l.Scan(); err != nil {
		t.Fatal(err)
	}
	items := l.Items()
	if len(items) != 1 {
		t.Fatalf("got %d items", len(items))
	}
	it := items[0]
	if !uuidRe.MatchString(it.Stem()) || filepath.Ext(it.Name) != ".jpg" {
		t.Fatalf("not renamed to a UUID: %s", it.Name)
	}
	if it.Orientation != "portrait" || it.Width != 900 || it.Height != 1200 {
		t.Fatalf("metadata %+v", it)
	}
	if _, err := os.Stat(filepath.Join(root, "images", "notes.txt")); err != nil {
		t.Fatal("non-media files must be left alone")
	}
	if _, err := os.Stat(filepath.Join(root, "thumbnails", "orphan.jpg")); !os.IsNotExist(err) {
		t.Fatal("orphan thumbnail not removed")
	}
	waitFor(t, "thumbnail", func() bool { i, _ := l.Get(it.Name); return i.HasThumb && i.Status == "ready" })
	if p, err := l.BackgroundPath(it.Name); err != nil || p == "" {
		t.Fatalf("backdrop: %v", err)
	}
	l.Close()

	// A second start reuses the metadata cache and has nothing to do.
	l2 := openLib(t, root)
	if err := l2.Scan(); err != nil {
		t.Fatal(err)
	}
	if got, _ := l2.Get(it.Name); got.Status != "ready" || !got.HasThumb || l2.needsPrep(&got) {
		t.Fatalf("cache not reused: %+v", got)
	}
}

func TestImportDownscalesAndRemove(t *testing.T) {
	root := t.TempDir()
	l := openLib(t, root)
	l.SetScreen(1280, 720) // limit = 1280 on the short side

	tmp := filepath.Join(root, "upload.tmp")
	writeJPEG(t, tmp, 4000, 3000)
	it, err := l.Import(tmp, ImportOptions{OriginalName: `C:\fakepath\Beach Day.JPG`})
	if err != nil {
		t.Fatal(err)
	}
	if it.Title != "Beach Day" {
		t.Fatalf("title %q", it.Title)
	}
	if it.Width != 1707 || it.Height != 1280 {
		t.Fatalf("not downscaled to the max useful size: %dx%d", it.Width, it.Height)
	}
	if !it.HasThumb {
		t.Fatal("thumbnail should exist straight after import")
	}

	// PNG stays PNG (keeps transparency).
	pngPath := filepath.Join(root, "p.tmp")
	f, _ := os.Create(pngPath)
	png.Encode(f, image.NewNRGBA(image.Rect(0, 0, 3000, 2000)))
	f.Close()
	pit, err := l.Import(pngPath, ImportOptions{OriginalName: "logo.png"})
	if err != nil || !strings.HasSuffix(pit.Name, ".png") {
		t.Fatalf("png import: %v %s", err, pit.Name)
	}

	// Unknown content is rejected.
	junk := filepath.Join(root, "j.tmp")
	os.WriteFile(junk, []byte("definitely not media"), 0o644)
	if _, err := l.Import(junk, ImportOptions{OriginalName: "x.bin"}); err != ErrUnsupported {
		t.Fatalf("expected ErrUnsupported, got %v", err)
	}

	thumb, _ := l.ThumbPath(it.Name)
	if err := l.Remove(it.Name); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{l.OriginalPath(it.Name), thumb, l.bgPath(it.Stem())} {
		if _, err := os.Stat(p); !os.IsNotExist(err) {
			t.Errorf("%s not removed", p)
		}
	}
	if _, ok := l.Get(it.Name); ok {
		t.Fatal("still in library")
	}
}

func TestSafeName(t *testing.T) {
	for _, bad := range []string{"", "../config.json", `..\x`, "a/b.jpg", ".hidden"} {
		if _, ok := SafeName(bad); ok {
			t.Errorf("SafeName(%q) accepted", bad)
		}
	}
	if _, ok := SafeName("5c895fb7-c000-4d12-8ed5-6fcc55ebfd9b.jpg"); !ok {
		t.Error("valid name rejected")
	}
}
