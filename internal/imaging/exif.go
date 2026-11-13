package imaging

import (
	"bufio"
	"encoding/binary"
	"io"
	"os"
)

// ExifOrientation returns the EXIF orientation tag (1..8) of a JPEG stream,
// or 1 when absent. Only the APP1 segment is read; pixel data is skipped.
func ExifOrientation(r io.Reader) int {
	br := bufio.NewReaderSize(r, 4096)
	var soi [2]byte
	if _, err := io.ReadFull(br, soi[:]); err != nil || soi[0] != 0xFF || soi[1] != 0xD8 {
		return 1
	}
	for {
		b, err := br.ReadByte()
		if err != nil {
			return 1
		}
		if b != 0xFF {
			continue
		}
		marker, err := br.ReadByte()
		if err != nil {
			return 1
		}
		for marker == 0xFF { // fill bytes
			if marker, err = br.ReadByte(); err != nil {
				return 1
			}
		}
		if marker == 0xD8 || (marker >= 0xD0 && marker <= 0xD7) || marker == 0x01 {
			continue // markers without a length
		}
		if marker == 0xDA || marker == 0xD9 { // start of scan / end: no EXIF
			return 1
		}
		var lb [2]byte
		if _, err := io.ReadFull(br, lb[:]); err != nil {
			return 1
		}
		n := int(binary.BigEndian.Uint16(lb[:])) - 2
		if n < 0 {
			return 1
		}
		if marker == 0xE1 && n >= 14 {
			seg := make([]byte, n)
			if _, err := io.ReadFull(br, seg); err != nil {
				return 1
			}
			if string(seg[:6]) == "Exif\x00\x00" {
				if o := tiffOrientation(seg[6:]); o >= 1 && o <= 8 {
					return o
				}
				return 1
			}
			continue
		}
		if _, err := br.Discard(n); err != nil {
			return 1
		}
	}
}

func tiffOrientation(t []byte) int {
	if len(t) < 8 {
		return 1
	}
	var bo binary.ByteOrder
	switch string(t[:2]) {
	case "II":
		bo = binary.LittleEndian
	case "MM":
		bo = binary.BigEndian
	default:
		return 1
	}
	if bo.Uint16(t[2:]) != 42 {
		return 1
	}
	ifd := int(bo.Uint32(t[4:]))
	if ifd < 8 || ifd+2 > len(t) {
		return 1
	}
	count := int(bo.Uint16(t[ifd:]))
	for i := 0; i < count; i++ {
		e := ifd + 2 + i*12
		if e+12 > len(t) {
			return 1
		}
		if bo.Uint16(t[e:]) == 0x0112 {
			typ := bo.Uint16(t[e+2:])
			if typ == 3 { // SHORT
				return int(bo.Uint16(t[e+8:]))
			}
			if typ == 4 { // LONG (non-standard but seen in the wild)
				return int(bo.Uint32(t[e+8:]))
			}
			return 1
		}
	}
	return 1
}

// GIFInfo reports the frame count and the length of one loop of an animated
// GIF by walking its block structure (no LZW decoding).
func GIFInfo(path string) (frames int, seconds float64, err error) {
	f, err := os.Open(path)
	if err != nil {
		return 0, 0, err
	}
	defer f.Close()
	r := bufio.NewReaderSize(f, 32<<10)
	hdr := make([]byte, 13)
	if _, err := io.ReadFull(r, hdr); err != nil {
		return 0, 0, err
	}
	if string(hdr[:3]) != "GIF" {
		return 0, 0, io.ErrUnexpectedEOF
	}
	if hdr[10]&0x80 != 0 { // global colour table
		if _, err := r.Discard(3 << ((hdr[10] & 7) + 1)); err != nil {
			return 0, 0, err
		}
	}
	skipSubBlocks := func() error {
		for {
			n, err := r.ReadByte()
			if err != nil {
				return err
			}
			if n == 0 {
				return nil
			}
			if _, err := r.Discard(int(n)); err != nil {
				return err
			}
		}
	}
	delay := 0
	total := 0
	for {
		b, err := r.ReadByte()
		if err != nil {
			break
		}
		switch b {
		case 0x21: // extension
			label, err := r.ReadByte()
			if err != nil {
				return frames, float64(total) / 100, nil
			}
			if label == 0xF9 { // graphic control extension
				// size(=4), packed, delay(2), transparent index, terminator
				blk := make([]byte, 6)
				if _, err := io.ReadFull(r, blk); err != nil {
					return frames, float64(total) / 100, nil
				}
				delay = int(binary.LittleEndian.Uint16(blk[2:4]))
				continue
			}
			if err := skipSubBlocks(); err != nil {
				return frames, float64(total) / 100, nil
			}
		case 0x2C: // image descriptor
			desc := make([]byte, 9)
			if _, err := io.ReadFull(r, desc); err != nil {
				return frames, float64(total) / 100, nil
			}
			if desc[8]&0x80 != 0 {
				if _, err := r.Discard(3 << ((desc[8] & 7) + 1)); err != nil {
					return frames, float64(total) / 100, nil
				}
			}
			if _, err := r.ReadByte(); err != nil { // LZW minimum code size
				return frames, float64(total) / 100, nil
			}
			if err := skipSubBlocks(); err != nil {
				return frames, float64(total) / 100, nil
			}
			frames++
			if delay <= 1 { // browsers clamp tiny delays to 100ms
				delay = 10
			}
			total += delay
			delay = 0
		case 0x3B: // trailer
			return frames, float64(total) / 100, nil
		default:
			return frames, float64(total) / 100, nil
		}
	}
	return frames, float64(total) / 100, nil
}
