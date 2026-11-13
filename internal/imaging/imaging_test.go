package imaging

import (
	"bytes"
	"encoding/binary"
	"image"
	"image/color"
	"image/color/palette"
	"image/gif"
	"image/jpeg"
	"os"
	"path/filepath"
	"testing"
)

func testImage(w, h int) *image.RGBA {
	m := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			// Left half red, right half blue: lets tests check orientation.
			c := color.RGBA{220, 20, 20, 255}
			if x >= w/2 {
				c = color.RGBA{20, 20, 220, 255}
			}
			m.SetRGBA(x, y, c)
		}
	}
	return m
}

// jpegWithOrientation builds a JPEG carrying an EXIF orientation tag.
func jpegWithOrientation(t *testing.T, img image.Image, o uint16) []byte {
	t.Helper()
	var raw bytes.Buffer
	if err := jpeg.Encode(&raw, img, &jpeg.Options{Quality: 90}); err != nil {
		t.Fatal(err)
	}
	tiff := []byte("MM\x00\x2a\x00\x00\x00\x08\x00\x01")
	entry := make([]byte, 12)
	binary.BigEndian.PutUint16(entry[0:], 0x0112)
	binary.BigEndian.PutUint16(entry[2:], 3)
	binary.BigEndian.PutUint32(entry[4:], 1)
	binary.BigEndian.PutUint16(entry[8:], o)
	tiff = append(tiff, entry...)
	tiff = append(tiff, 0, 0, 0, 0)
	app1 := append([]byte("Exif\x00\x00"), tiff...)
	seg := []byte{0xFF, 0xE1, 0, 0}
	binary.BigEndian.PutUint16(seg[2:], uint16(len(app1)+2))
	b := raw.Bytes()
	out := append([]byte{}, b[:2]...)
	out = append(out, seg...)
	out = append(out, app1...)
	return append(out, b[2:]...)
}

func TestExifOrientation(t *testing.T) {
	for _, o := range []uint16{1, 3, 6, 8} {
		data := jpegWithOrientation(t, testImage(64, 32), o)
		if got := ExifOrientation(bytes.NewReader(data)); got != int(o) {
			t.Errorf("orientation %d: got %d", o, got)
		}
		d, err := Decode(data)
		if err != nil {
			t.Fatal(err)
		}
		w, h := d.Size()
		if (o >= 5) != (h > w) {
			t.Errorf("orientation %d: display size %dx%d", o, w, h)
		}
	}
	if ExifOrientation(bytes.NewReader([]byte("not a jpeg"))) != 1 {
		t.Error("garbage should give 1")
	}
}

func TestReadInfoAppliesOrientation(t *testing.T) {
	p := filepath.Join(t.TempDir(), "p.jpg")
	os.WriteFile(p, jpegWithOrientation(t, testImage(400, 300), 6), 0o644)
	info, err := ReadInfo(p)
	if err != nil {
		t.Fatal(err)
	}
	if info.Width != 300 || info.Height != 400 || info.Orientation != 6 {
		t.Fatalf("got %+v; a phone portrait shot must be classified portrait", info)
	}
}

func TestOrientRotate(t *testing.T) {
	img := testImage(4, 2)
	r := Rotate(img, 90) // clockwise: left (red) ends up on top
	if r.Rect.Dx() != 2 || r.Rect.Dy() != 4 {
		t.Fatalf("size %v", r.Rect)
	}
	if c := r.RGBAAt(0, 0); c.R < 200 {
		t.Fatalf("expected red at top after 90° CW, got %v", c)
	}
	if c := Rotate(img, 180).RGBAAt(0, 0); c.B < 200 {
		t.Fatalf("expected blue at left after 180°, got %v", c)
	}
}

func TestResizeAndSizes(t *testing.T) {
	big := testImage(4000, 3000)
	r := Resize(big, 400, 300)
	if r.Rect.Dx() != 400 || r.Rect.Dy() != 300 {
		t.Fatalf("resize size %v", r.Rect)
	}
	if c := r.RGBAAt(10, 150); c.R < 180 || c.B > 60 {
		t.Fatalf("colour not preserved: %v", c)
	}
	if w, h := MinSideSize(4000, 3000, 1920, 8192); w != 2560 || h != 1920 {
		t.Fatalf("MinSideSize = %dx%d", w, h)
	}
	if w, h := MinSideSize(800, 600, 1920, 8192); w != 800 || h != 600 {
		t.Fatal("must not upscale")
	}
	if w, h := FitSize(1000, 4000, 512, 512); w != 128 || h != 512 {
		t.Fatalf("FitSize = %dx%d", w, h)
	}
	ycc := image.NewYCbCr(image.Rect(0, 0, 1000, 800), image.YCbCrSubsampleRatio420)
	for i := range ycc.Y {
		ycc.Y[i] = 128
	}
	for i := range ycc.Cb {
		ycc.Cb[i], ycc.Cr[i] = 128, 128
	}
	if g := Resize(ycc, 100, 80).RGBAAt(50, 40); g.R < 120 || g.R > 136 {
		t.Fatalf("YCbCr fast path grey = %v", g)
	}
}

func TestBackgroundAndCanvas(t *testing.T) {
	src := testImage(300, 400)
	bg := Background(src, 256)
	if bg.Rect.Dx() != 192 || bg.Rect.Dy() != 256 {
		t.Fatalf("bg size %v", bg.Rect)
	}
	if c := bg.RGBAAt(5, 128); c.R > 140 { // darkened
		t.Fatalf("background not darkened: %v", c)
	}
	d := &Decoded{Img: src, Orientation: 1}
	for _, rot := range []int{0, 90} {
		for _, mode := range []string{"fit", "fill"} {
			c := Canvas(d, 640, 360, mode, rot)
			if c.Rect.Dx() != 640 || c.Rect.Dy() != 360 {
				t.Fatalf("%s/%d canvas size %v", mode, rot, c.Rect)
			}
		}
	}
	// fit + no rotation: a portrait image leaves blurred side bars.
	c := Canvas(d, 640, 360, "fit", 0)
	if px := c.RGBAAt(5, 180); px.R == 0 && px.B == 0 {
		t.Fatal("expected a blurred backdrop, got black bars")
	}
}

func TestGIFInfo(t *testing.T) {
	g := &gif.GIF{}
	for i := 0; i < 3; i++ {
		g.Image = append(g.Image, image.NewPaletted(image.Rect(0, 0, 8, 8), palette.Plan9))
		g.Delay = append(g.Delay, 50) // 0.5s
	}
	p := filepath.Join(t.TempDir(), "a.gif")
	f, _ := os.Create(p)
	if err := gif.EncodeAll(f, g); err != nil {
		t.Fatal(err)
	}
	f.Close()
	frames, secs, err := GIFInfo(p)
	if err != nil || frames != 3 || secs != 1.5 {
		t.Fatalf("GIFInfo = %d, %v, %v", frames, secs, err)
	}
}
