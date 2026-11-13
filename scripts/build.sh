#!/usr/bin/env bash
# Cross-compile Digital Canvas for every supported target into dist/.
# Works on Linux, macOS and Windows (Git Bash). Needs Go 1.26+; no C compiler.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=${VERSION:-$(git describe --tags --always --dirty 2>/dev/null || echo dev)}
TARGETS=${TARGETS:-"linux/arm64 linux/arm/7 linux/arm/6 linux/amd64 windows/amd64"}
mkdir -p dist

for t in $TARGETS; do
  IFS=/ read -r os arch arm <<<"$t"
  out="dist/digitalcanvas-$os-$arch${arm:+v$arm}"
  [ "$os" = windows ] && out="$out.exe"
  printf 'building %-40s' "$out"
  CGO_ENABLED=0 GOOS=$os GOARCH=$arch GOARM=${arm:-} \
    go build -trimpath -ldflags "-s -w -X main.version=$VERSION" -o "$out" ./cmd/digitalcanvas
  ls -l "$out" | awk '{printf " %.1f MB\n", $5/1048576}'
done
