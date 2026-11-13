package mqttc

import "testing"

func TestParseTopic(t *testing.T) {
	base := "1/office/canvas"
	cases := []struct {
		topic, cmd string
		ok         bool
	}{
		{"1/office/canvas/rotation", "rotation", true},
		// The original used substring matching, so "auto_rotation" also
		// triggered the rotation handler and crashed on int("on").
		{"1/office/canvas/auto_rotation", "auto_rotation", true},
		{"1/office/canvas/rotation/set", "rotation", true},
		{"1/office/canvas/cmd/slideshow", "slideshow", true},
		{"1/office/canvas/current_image", "", false}, // our own publication
		{"1/office/canvas/config", "", false},
		{"1/office/canvas", "", false},
		{"1/office/canvas-other/rotation", "", false},
		{"other/rotation", "", false},
	}
	for _, c := range cases {
		cmd, ok := ParseTopic(base, c.topic)
		if cmd != c.cmd || ok != c.ok {
			t.Errorf("ParseTopic(%q) = %q,%v want %q,%v", c.topic, cmd, ok, c.cmd, c.ok)
		}
	}
}
