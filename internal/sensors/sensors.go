// Package sensors reads the optional I2C sensors: a VEML7700 ambient light
// sensor (auto brightness) and a BMI160 accelerometer (auto rotation).
package sensors

import (
	"errors"
	"log"
	"sync"
	"time"
)

// ErrUnavailable is returned when a sensor is not present.
var ErrUnavailable = errors.New("sensor not available")

// bus is a platform I2C bus.
type bus interface {
	// WriteRead writes w then reads len(r) bytes in one combined transaction.
	WriteRead(addr uint16, w, r []byte) error
	Write(addr uint16, w []byte) error
	Close() error
}

const (
	vemlAddr = 0x10
	// lux per count at gain x1, 100ms integration (0.0042 at x2/800ms).
	vemlResolution = 0.0042 * (800.0 / 100.0) * (2.0 / 1.0)
)

// Reader owns the sensors. Methods are safe for concurrent use.
type Reader struct {
	mu        sync.Mutex
	b         bus
	light     bool
	accel     bool
	accelAddr uint16
}

// Open probes the sensors on the given I2C bus number.
func Open(busNum int, simulate bool) *Reader {
	r := &Reader{}
	if simulate {
		log.Printf("sensors: simulation mode, sensors disabled")
		return r
	}
	b, err := openBus(busNum)
	if err != nil {
		log.Printf("sensors: no I2C bus %d (%v) - auto brightness/rotation unavailable", busNum, err)
		return r
	}
	r.b = b
	if err := r.initLight(); err == nil {
		r.light = true
		log.Printf("sensors: VEML7700 light sensor found")
	}
	for _, a := range []uint16{0x69, 0x68} {
		if err := r.initAccel(a); err == nil {
			r.accel, r.accelAddr = true, a
			log.Printf("sensors: BMI160 accelerometer found at 0x%02x", a)
			break
		}
	}
	if !r.light && !r.accel {
		log.Printf("sensors: no sensors detected on I2C bus %d", busNum)
	}
	return r
}

// LightAvailable reports whether a light sensor was found.
func (r *Reader) LightAvailable() bool { return r.light }

// AccelAvailable reports whether an accelerometer was found.
func (r *Reader) AccelAvailable() bool { return r.accel }

func (r *Reader) initLight() error {
	// ALS_CONF: gain x1, 100ms, interrupts off, power on. PSM off.
	if err := r.b.Write(vemlAddr, []byte{0x00, 0x00, 0x00}); err != nil {
		return err
	}
	if err := r.b.Write(vemlAddr, []byte{0x03, 0x00, 0x00}); err != nil {
		return err
	}
	buf := make([]byte, 2)
	return r.b.WriteRead(vemlAddr, []byte{0x00}, buf)
}

// Lux reads the ambient light level.
func (r *Reader) Lux() (float64, error) {
	if !r.light {
		return 0, ErrUnavailable
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	buf := make([]byte, 2)
	if err := r.b.WriteRead(vemlAddr, []byte{0x04}, buf); err != nil {
		return 0, err
	}
	return float64(uint16(buf[0])|uint16(buf[1])<<8) * vemlResolution, nil
}

func (r *Reader) initAccel(addr uint16) error {
	id := make([]byte, 1)
	if err := r.b.WriteRead(addr, []byte{0x00}, id); err != nil {
		return err
	}
	if id[0] != 0xD1 {
		return errors.New("not a BMI160")
	}
	steps := []struct {
		reg, val byte
		wait     time.Duration
	}{
		{0x7E, 0xB6, 15 * time.Millisecond}, // soft reset
		{0x7E, 0x11, 10 * time.Millisecond}, // accelerometer normal mode
		{0x41, 0x03, time.Millisecond},      // ±2g (16384 LSB/g)
		{0x40, 0x28, time.Millisecond},      // 100Hz, normal averaging
	}
	for _, s := range steps {
		if err := r.b.Write(addr, []byte{s.reg, s.val}); err != nil {
			return err
		}
		time.Sleep(s.wait)
	}
	return nil
}

// Accel reads acceleration in g.
func (r *Reader) Accel() (x, y, z float64, err error) {
	if !r.accel {
		return 0, 0, 0, ErrUnavailable
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	buf := make([]byte, 6)
	if err := r.b.WriteRead(r.accelAddr, []byte{0x12}, buf); err != nil {
		return 0, 0, 0, err
	}
	v := func(i int) float64 { return float64(int16(uint16(buf[i])|uint16(buf[i+1])<<8)) / 16384 }
	return v(0), v(2), v(4), nil
}

// Close releases the bus.
func (r *Reader) Close() {
	if r.b != nil {
		_ = r.b.Close()
	}
}

// AccelToRotation maps a gravity vector to a screen rotation, exactly as the
// original accel_to_rotation(). ok is false when the device lies flat or the
// reading is ambiguous (the caller keeps the previous rotation).
func AccelToRotation(x, y, z float64) (rotation int, ok bool) {
	x = -x // the sensor is mounted with x inverted
	switch {
	case x > 0.8:
		return 0, true
	case x < -0.8:
		return 180, true
	case y > 0.8:
		return 90, true
	case y < -0.8:
		return 270, true
	}
	return 0, false
}
