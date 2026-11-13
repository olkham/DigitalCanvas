package sensors

import "testing"

func TestAccelToRotation(t *testing.T) {
	cases := []struct {
		x, y, z float64
		rot     int
		ok      bool
	}{
		{-1, 0, 0, 0, true},
		{1, 0, 0, 180, true},
		{0, 1, 0, 90, true},
		{0, -1, 0, 270, true},
		{0, 0, 1, 0, false}, // lying flat: keep the previous rotation
	}
	for _, c := range cases {
		rot, ok := AccelToRotation(c.x, c.y, c.z)
		if rot != c.rot || ok != c.ok {
			t.Errorf("(%v,%v,%v) = %d,%v want %d,%v", c.x, c.y, c.z, rot, ok, c.rot, c.ok)
		}
	}
}
