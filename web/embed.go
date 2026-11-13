// Package web embeds the control panel and display page into the binary.
package web

import "embed"

// Static holds the files under static/.
//
//go:embed static
var Static embed.FS
