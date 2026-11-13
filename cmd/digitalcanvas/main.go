// Command digitalcanvas runs the Digital Canvas photo frame: a web control
// panel, a GPU-composited kiosk display, MQTT, Plex, DDC/CI and I2C sensors.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/olkham/DigitalCanvas/internal/app"
)

// version is set at build time with -ldflags "-X main.version=..."
var version = "dev"

func main() {
	var opts app.Options
	flag.StringVar(&opts.ConfigPath, "config", "config.json", "path to config.json (media folders are relative to it)")
	flag.BoolVar(&opts.Simulate, "simulate", false, "do not touch the monitor, sensors or system power (development)")
	flag.BoolVar(&opts.NoBrowser, "no-browser", false, "do not launch the kiosk browser (open /display yourself)")
	flag.StringVar(&opts.Listen, "listen", "", "override the listen address, e.g. 127.0.0.1:7000")
	showVersion := flag.Bool("version", false, "print the version and exit")
	logFile := flag.String("log", "", "also write the log to this file (truncated at 5 MB on start)")
	flag.Parse()
	if *showVersion {
		fmt.Println(version)
		return
	}
	opts.Version = version
	log.SetFlags(log.LstdFlags)
	if *logFile != "" {
		if st, err := os.Stat(*logFile); err == nil && st.Size() > 5<<20 {
			_ = os.Truncate(*logFile, 0)
		}
		f, err := os.OpenFile(*logFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			log.Fatalf("opening log file: %v", err)
		}
		defer f.Close()
		log.SetOutput(io.MultiWriter(os.Stderr, f))
	}
	log.Printf("Digital Canvas %s", version)

	a, err := app.New(opts)
	if err != nil {
		log.Fatalf("startup failed: %v", err)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := a.Run(ctx); err != nil {
		log.Fatalf("%v", err)
	}
	if a.RestartRequested() {
		stop()
		if err := restartSelf(); err != nil {
			log.Printf("restart failed: %v", err)
			os.Exit(75) // EX_TEMPFAIL: a supervisor (systemd) will restart us
		}
	}
}
