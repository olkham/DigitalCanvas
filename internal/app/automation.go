package app

import (
	"context"
	"log"
	"math"
	"time"

	"github.com/olkham/DigitalCanvas/internal/player"
	"github.com/olkham/DigitalCanvas/internal/sensors"
)

// ring is a fixed size moving-average window.
type ring struct {
	v []float64
	i int
	n int
}

func newRing(n int) *ring { return &ring{v: make([]float64, n)} }

func (r *ring) push(x float64) {
	r.v[r.i] = x
	r.i = (r.i + 1) % len(r.v)
	if r.n < len(r.v) {
		r.n++
	}
}

func (r *ring) mean() float64 {
	if r.n == 0 {
		return 0
	}
	s := 0.0
	for i := 0; i < r.n; i++ {
		s += r.v[i]
	}
	return s / float64(r.n)
}

func (r *ring) reset() { r.i, r.n = 0, 0 }

// lerp maps value from [inMin,inMax] to [outMin,outMax], clamped.
func lerp(value, inMin, inMax, outMin, outMax float64) float64 {
	if inMax == inMin {
		return outMin
	}
	v := (value-inMin)/(inMax-inMin)*(outMax-outMin) + outMin
	return math.Max(math.Min(v, math.Max(outMin, outMax)), math.Min(outMin, outMax))
}

// automation runs auto-rotation (2 Hz), auto-brightness (1 Hz) and the
// on/off schedule (every 10 s). The original polled everything at 10 Hz and
// published to MQTT on every pass; this does the same job with ~5% of the
// wake-ups and only publishes on change (plus a 30 s heartbeat).
func (a *App) automation(ctx context.Context) {
	tick := time.NewTicker(500 * time.Millisecond)
	defer tick.Stop()
	ax, ay, az := newRing(4), newRing(4), newRing(4)
	lux := newRing(10)
	sensorRotation := a.cfg.Get().Rotation
	lastBrightness, lastPublished := -1, -1
	var lastSet, lastPub time.Time
	errs := 0
	a.checkSchedule(time.Now())

	for n := 1; ; n++ {
		select {
		case <-ctx.Done():
			return
		case <-a.quit:
			return
		case <-tick.C:
		}
		s := a.cfg.Get()

		if s.AutoRotation && a.sens.AccelAvailable() {
			if x, y, z, err := a.sens.Accel(); err == nil {
				ax.push(x)
				ay.push(y)
				az.push(z)
				if rot, ok := sensors.AccelToRotation(ax.mean(), ay.mean(), az.mean()); ok && rot != sensorRotation {
					sensorRotation = rot
					if rot != s.Rotation {
						log.Printf("automation: orientation changed, rotating to %d", rot)
						_ = a.cfg.Set("rotation", rot)
					}
				}
			} else if errs++; errs%120 == 1 {
				log.Printf("automation: accelerometer read failed: %v", err)
			}
		}

		if n%2 == 0 && a.sens.LightAvailable() && s.AutoBrightness {
			if v, err := a.sens.Lux(); err == nil {
				lux.push(v)
				mean := lux.mean()
				a.mu.Lock()
				a.lux = math.Round(mean*10) / 10
				a.mu.Unlock()
				b := int(lerp(mean, s.LightSensorMinReading, s.LightSensorMaxReading, 0, 100))
				if b != lastBrightness && time.Since(lastSet) >= 2*time.Second {
					lastBrightness, lastSet = b, time.Now()
					if err := a.applyBrightness(b); err != nil && n%120 == 0 {
						log.Printf("automation: setting brightness: %v", err)
					}
				}
				if b != lastPublished || time.Since(lastPub) > 30*time.Second {
					lastPublished, lastPub = b, time.Now()
					a.mqtt.Publish("light_sensor", int(math.Round(mean)), false)
					a.mqtt.Publish("screen_brightness", b, false)
					a.statusChanged()
				}
			} else if errs++; errs%120 == 1 {
				log.Printf("automation: light sensor read failed: %v", err)
			}
		} else if !s.AutoBrightness {
			lux.reset()
			lastBrightness = -1
		}

		if n%20 == 0 {
			a.checkSchedule(time.Now())
		}
	}
}

// checkSchedule applies the on/off schedule on transitions only, so manual
// power changes stick until the next scheduled change (as in the original),
// but the correct state is also applied at startup.
func (a *App) checkSchedule(now time.Time) {
	s := a.cfg.Get()
	a.mu.Lock()
	if !s.ScheduleActive() {
		wasOff := a.schedState == 0
		a.schedState = -1
		a.mu.Unlock()
		if wasOff { // schedule switched off while it had the screen off
			log.Printf("schedule: disabled, turning the display back on")
			_ = a.SetPower(true)
			a.player.Resume(player.BySchedule)
		}
		return
	}
	want := 0
	if s.InOnWindow(now) {
		want = 1
	}
	if a.schedState == want {
		a.mu.Unlock()
		return
	}
	a.schedState = want
	a.mu.Unlock()
	if want == 1 {
		log.Printf("schedule: turning the display on (%s)", now.Format("15:04"))
		_ = a.SetPower(true)
		a.player.Resume(player.BySchedule)
	} else {
		log.Printf("schedule: turning the display off (%s)", now.Format("15:04"))
		a.player.Pause(player.BySchedule)
		_ = a.SetPower(false)
	}
}
