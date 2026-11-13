// Package imaging holds the (pure Go) pixel work: decoding, EXIF orientation,
// high quality downscaling, blurred backgrounds and canvas composition.
//
// All of it runs once per file at import time or on demand for /canvas; the
// display itself is composited by the GPU, so nothing here is on a hot path.
package imaging

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
	"image/gif"
	"image/jpeg"
	"image/png"
	"io"
	"os"
	"path/filepath"

	_ "golang.org/x/image/bmp" // register decoder
	"golang.org/x/image/draw"
	_ "golang.org/x/image/webp" // register decoder
)

var _ = gif.Decode // image/gif registers the GIF decoder

// Info is the cheap, header-only description of an image file.
type Info struct {
	Width, Height int    // display dimensions (after EXIF orientation)
	Format        string // jpeg, png, gif, bmp, webp
	Orientation   int    // EXIF orientation 1..8
}

// ReadInfo reads dimensions and EXIF orientation without decoding pixels.
func ReadInfo(path string) (Info, error) {
	f, err := os.Open(path)
	if err != nil {
		return Info{}, err
	}
	defer f.Close()
	cfg, format, err := image.DecodeConfig(f)
	if err != nil {
		return Info{}, err
	}
	info := Info{Width: cfg.Width, Height: cfg.Height, Format: format, Orientation: 1}
	if format == "jpeg" {
		if _, err := f.Seek(0, io.SeekStart); err == nil {
			info.Orientation = ExifOrientation(f)
		}
	}
	if info.Orientation >= 5 {
		info.Width, info.Height = info.Height, info.Width
	}
	return info, nil
}

// Decoded is a decoded image together with its EXIF orientation, which is
// applied lazily (after downscaling) to keep memory use low.
type Decoded struct {
	Img         image.Image
	Format      string
	Orientation int
}

// Size returns the display size (after orientation).
func (d *Decoded) Size() (int, int) {
	b := d.Img.Bounds()
	if d.Orientation >= 5 {
		return b.Dy(), b.Dx()
	}
	return b.Dx(), b.Dy()
}

// Decode decodes image bytes.
func Decode(data []byte) (*Decoded, error) {
	img, format, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	o := 1
	if format == "jpeg" {
		o = ExifOrientation(bytes.NewReader(data))
	}
	return &Decoded{Img: img, Format: format, Orientation: o}, nil
}

// DecodeFile decodes an image file.
func DecodeFile(path string) (*Decoded, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	d, err := Decode(data)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", filepath.Base(path), err)
	}
	return d, nil
}

// ScaleTo returns the image scaled to exactly w x h display pixels with the
// EXIF orientation applied. Downscaling only touches the source once.
func (d *Decoded) ScaleTo(w, h int) *image.RGBA {
	sw, sh := w, h
	if d.Orientation >= 5 {
		sw, sh = h, w
	}
	return Orient(Resize(d.Img, sw, sh), d.Orientation)
}

// Fit returns the image scaled to fit within maxW x maxH (never upscaled).
func (d *Decoded) Fit(maxW, maxH int) *image.RGBA {
	w, h := d.Size()
	nw, nh := FitSize(w, h, maxW, maxH)
	return d.ScaleTo(nw, nh)
}

// FitSize returns w x h scaled down (preserving aspect) to fit max bounds.
func FitSize(w, h, maxW, maxH int) (int, int) {
	if w <= maxW && h <= maxH {
		return w, h
	}
	r := minf(float64(maxW)/float64(w), float64(maxH)/float64(h))
	return max(1, int(float64(w)*r+0.5)), max(1, int(float64(h)*r+0.5))
}

// MinSideSize scales w x h so the shorter side is at most minSide and the
// longer side at most maxLong (never upscaled).
func MinSideSize(w, h, minSide, maxLong int) (int, int) {
	r := 1.0
	if s := min(w, h); s > minSide {
		r = float64(minSide) / float64(s)
	}
	if l := float64(max(w, h)) * r; maxLong > 0 && l > float64(maxLong) {
		r *= float64(maxLong) / l
	}
	if r >= 1 {
		return w, h
	}
	return max(1, int(float64(w)*r+0.5)), max(1, int(float64(h)*r+0.5))
}

// Resize scales src to w x h with a box prefilter for large reductions
// followed by Catmull-Rom, which is both fast and alias free.
func Resize(src image.Image, w, h int) *image.RGBA {
	b := src.Bounds()
	if b.Dx() == w && b.Dy() == h {
		return toRGBA(src)
	}
	k := min(b.Dx()/(2*w), b.Dy()/(2*h))
	if k >= 2 {
		src = boxShrink(src, k)
	}
	dst := image.NewRGBA(image.Rect(0, 0, w, h))
	draw.CatmullRom.Scale(dst, dst.Bounds(), src, src.Bounds(), draw.Src, nil)
	return dst
}

func toRGBA(src image.Image) *image.RGBA {
	if r, ok := src.(*image.RGBA); ok && r.Rect.Min == (image.Point{}) {
		return r
	}
	b := src.Bounds()
	dst := image.NewRGBA(image.Rect(0, 0, b.Dx(), b.Dy()))
	draw.Draw(dst, dst.Bounds(), src, b.Min, draw.Src)
	return dst
}

// boxShrink averages k x k blocks. It has a fast path for YCbCr (what the
// JPEG decoder produces) so huge photos are never expanded to RGBA.
func boxShrink(src image.Image, k int) *image.RGBA {
	b := src.Bounds()
	w, h := b.Dx()/k, b.Dy()/k
	dst := image.NewRGBA(image.Rect(0, 0, w, h))
	n := uint32(k * k)
	switch s := src.(type) {
	case *image.YCbCr:
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				var sy, scb, scr uint32
				for j := 0; j < k; j++ {
					py := b.Min.Y + y*k + j
					yi := s.YOffset(b.Min.X+x*k, py)
					for i := 0; i < k; i++ {
						sy += uint32(s.Y[yi+i])
						ci := s.COffset(b.Min.X+x*k+i, py)
						scb += uint32(s.Cb[ci])
						scr += uint32(s.Cr[ci])
					}
				}
				r, g, bb := color.YCbCrToRGB(uint8(sy/n), uint8(scb/n), uint8(scr/n))
				o := dst.PixOffset(x, y)
				dst.Pix[o], dst.Pix[o+1], dst.Pix[o+2], dst.Pix[o+3] = r, g, bb, 255
			}
		}
	case *image.RGBA, *image.NRGBA:
		var pix []uint8
		var stride int
		if r, ok := s.(*image.RGBA); ok {
			pix, stride = r.Pix[r.PixOffset(b.Min.X, b.Min.Y):], r.Stride
		} else {
			r := s.(*image.NRGBA)
			pix, stride = r.Pix[r.PixOffset(b.Min.X, b.Min.Y):], r.Stride
		}
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				var a [4]uint32
				for j := 0; j < k; j++ {
					row := (y*k+j)*stride + x*k*4
					for i := 0; i < k; i++ {
						p := row + i*4
						a[0] += uint32(pix[p])
						a[1] += uint32(pix[p+1])
						a[2] += uint32(pix[p+2])
						a[3] += uint32(pix[p+3])
					}
				}
				o := dst.PixOffset(x, y)
				dst.Pix[o], dst.Pix[o+1], dst.Pix[o+2], dst.Pix[o+3] =
					uint8(a[0]/n), uint8(a[1]/n), uint8(a[2]/n), uint8(a[3]/n)
			}
		}
		if _, ok := s.(*image.NRGBA); ok {
			premultiply(dst)
		}
	case *image.Gray:
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				var sum uint32
				for j := 0; j < k; j++ {
					row := s.PixOffset(b.Min.X+x*k, b.Min.Y+y*k+j)
					for i := 0; i < k; i++ {
						sum += uint32(s.Pix[row+i])
					}
				}
				v := uint8(sum / n)
				o := dst.PixOffset(x, y)
				dst.Pix[o], dst.Pix[o+1], dst.Pix[o+2], dst.Pix[o+3] = v, v, v, 255
			}
		}
	default:
		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {
				var a [4]uint32
				for j := 0; j < k; j++ {
					for i := 0; i < k; i++ {
						r, g, bb, al := src.At(b.Min.X+x*k+i, b.Min.Y+y*k+j).RGBA()
						a[0] += r >> 8
						a[1] += g >> 8
						a[2] += bb >> 8
						a[3] += al >> 8
					}
				}
				o := dst.PixOffset(x, y)
				dst.Pix[o], dst.Pix[o+1], dst.Pix[o+2], dst.Pix[o+3] =
					uint8(a[0]/n), uint8(a[1]/n), uint8(a[2]/n), uint8(a[3]/n)
			}
		}
	}
	return dst
}

func premultiply(m *image.RGBA) {
	for i := 0; i+3 < len(m.Pix); i += 4 {
		a := uint32(m.Pix[i+3])
		if a == 255 {
			continue
		}
		m.Pix[i] = uint8(uint32(m.Pix[i]) * a / 255)
		m.Pix[i+1] = uint8(uint32(m.Pix[i+1]) * a / 255)
		m.Pix[i+2] = uint8(uint32(m.Pix[i+2]) * a / 255)
	}
}

// Orient applies an EXIF orientation (1..8) to img.
func Orient(img *image.RGBA, o int) *image.RGBA {
	if o <= 1 || o > 8 {
		return img
	}
	w, h := img.Rect.Dx(), img.Rect.Dy()
	dw, dh := w, h
	if o >= 5 {
		dw, dh = h, w
	}
	dst := image.NewRGBA(image.Rect(0, 0, dw, dh))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			var dx, dy int
			switch o {
			case 2:
				dx, dy = w-1-x, y
			case 3:
				dx, dy = w-1-x, h-1-y
			case 4:
				dx, dy = x, h-1-y
			case 5:
				dx, dy = y, x
			case 6:
				dx, dy = h-1-y, x
			case 7:
				dx, dy = h-1-y, w-1-x
			case 8:
				dx, dy = y, w-1-x
			}
			s := img.PixOffset(x, y)
			d := dst.PixOffset(dx, dy)
			copy(dst.Pix[d:d+4], img.Pix[s:s+4])
		}
	}
	return dst
}

// Rotate rotates clockwise by a multiple of 90 degrees.
func Rotate(img *image.RGBA, deg int) *image.RGBA {
	switch ((deg % 360) + 360) % 360 {
	case 90:
		return Orient(img, 6)
	case 180:
		return Orient(img, 3)
	case 270:
		return Orient(img, 8)
	}
	return img
}

// Background builds the small, blurred, darkened backdrop shown behind
// letterboxed ("fit") media. The browser upscales it with bilinear filtering,
// which adds further smoothing for free.
func Background(src *image.RGBA, longSide int) *image.RGBA {
	w, h := src.Rect.Dx(), src.Rect.Dy()
	bw, bh := FitSize(w, h, longSide, longSide)
	small := image.NewRGBA(image.Rect(0, 0, bw, bh))
	draw.ApproxBiLinear.Scale(small, small.Bounds(), src, src.Bounds(), draw.Src, nil)
	radius := max(2, max(bw, bh)/80)
	BoxBlur(small, radius, 3)
	Darken(small, 0.55)
	return small
}

// BoxBlur approximates a gaussian blur with repeated separable box blurs.
func BoxBlur(m *image.RGBA, radius, passes int) {
	w, h := m.Rect.Dx(), m.Rect.Dy()
	if w == 0 || h == 0 || radius < 1 {
		return
	}
	tmp := make([]uint8, len(m.Pix))
	for p := 0; p < passes; p++ {
		blur1D(m.Pix, tmp, w, h, 4, m.Stride, radius) // rows: samples 4 bytes apart
		blur1D(tmp, m.Pix, h, w, m.Stride, 4, radius) // columns: samples a stride apart
	}
}

// blur1D blurs along lines of length n; lines are `lines` apart by lineStep
// and samples are step bytes apart. Edges are clamped.
func blur1D(src, dst []uint8, n, lines, step, lineStep, r int) {
	if n == 0 {
		return
	}
	div := uint32(2*r + 1)
	for l := 0; l < lines; l++ {
		base := l * lineStep
		for c := 0; c < 3; c++ {
			var sum uint32
			for i := -r; i <= r; i++ {
				sum += uint32(src[base+clampi(i, 0, n-1)*step+c])
			}
			for i := 0; i < n; i++ {
				dst[base+i*step+c] = uint8(sum / div)
				out := clampi(i-r, 0, n-1)
				in := clampi(i+r+1, 0, n-1)
				sum += uint32(src[base+in*step+c]) - uint32(src[base+out*step+c])
			}
		}
		for i := 0; i < n; i++ {
			dst[base+i*step+3] = 255
		}
	}
}

// Darken multiplies RGB by f.
func Darken(m *image.RGBA, f float64) {
	k := uint32(f * 256)
	for i := 0; i+3 < len(m.Pix); i += 4 {
		m.Pix[i] = uint8(uint32(m.Pix[i]) * k >> 8)
		m.Pix[i+1] = uint8(uint32(m.Pix[i+1]) * k >> 8)
		m.Pix[i+2] = uint8(uint32(m.Pix[i+2]) * k >> 8)
	}
}

// Flatten composites any transparency onto black (JPEG has no alpha).
func Flatten(m *image.RGBA) *image.RGBA {
	for i := 3; i < len(m.Pix); i += 4 {
		if m.Pix[i] != 255 {
			// RGBA is premultiplied, so dropping alpha == compositing on black.
			m.Pix[i] = 255
		}
	}
	return m
}

// Canvas composes media exactly as the display shows it: rotated, then fitted
// (on a blurred backdrop) or filled into a W x H screen.
func Canvas(d *Decoded, W, H int, mode string, rotation int) *image.RGBA {
	tw, th := W, H
	if rotation == 90 || rotation == 270 {
		tw, th = H, W
	}
	sw, sh := d.Size()
	out := image.NewRGBA(image.Rect(0, 0, tw, th))
	draw.Draw(out, out.Bounds(), image.Black, image.Point{}, draw.Src)
	if mode == "fill" {
		r := maxf(float64(tw)/float64(sw), float64(th)/float64(sh))
		cw, ch := int(float64(sw)*r+0.5), int(float64(sh)*r+0.5)
		fg := d.ScaleTo(max(cw, 1), max(ch, 1))
		draw.Draw(out, out.Bounds(), fg, image.Pt((cw-tw)/2, (ch-th)/2), draw.Src)
	} else {
		fw, fh := fitAny(sw, sh, tw, th)
		fg := d.ScaleTo(fw, fh)
		if fw < tw || fh < th {
			bg := Background(fg, 256)
			r := maxf(float64(tw)/float64(bg.Rect.Dx()), float64(th)/float64(bg.Rect.Dy()))
			cw, ch := int(float64(bg.Rect.Dx())*r+0.5), int(float64(bg.Rect.Dy())*r+0.5)
			dst := image.Rect((tw-cw)/2, (th-ch)/2, (tw-cw)/2+cw, (th-ch)/2+ch)
			draw.BiLinear.Scale(out, dst, bg, bg.Bounds(), draw.Src, nil)
		}
		off := image.Pt((tw-fw)/2, (th-fh)/2)
		draw.Draw(out, fg.Bounds().Add(off), fg, image.Point{}, draw.Over)
	}
	return Rotate(out, rotation)
}

// fitAny fits w x h into maxW x maxH, upscaling if needed.
func fitAny(w, h, maxW, maxH int) (int, int) {
	r := minf(float64(maxW)/float64(w), float64(maxH)/float64(h))
	return max(1, int(float64(w)*r+0.5)), max(1, int(float64(h)*r+0.5))
}

// EncodeJPEG encodes img as JPEG.
func EncodeJPEG(img image.Image, quality int) ([]byte, error) {
	var buf bytes.Buffer
	buf.Grow(64 << 10)
	if err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: quality}); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// EncodePNG encodes img as PNG (used to keep PNG uploads lossless).
func EncodePNG(img image.Image) ([]byte, error) {
	var buf bytes.Buffer
	enc := png.Encoder{CompressionLevel: png.BestSpeed}
	if err := enc.Encode(&buf, img); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// SaveJPEG atomically writes img as a JPEG file.
func SaveJPEG(path string, img image.Image, quality int) error {
	data, err := EncodeJPEG(img, quality)
	if err != nil {
		return err
	}
	return writeAtomic(path, data)
}

func writeAtomic(path string, data []byte) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func clampi(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func minf(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func maxf(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}
