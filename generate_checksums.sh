#!/usr/bin/env bash
#
# generate_checksums.sh — produce dist/SHA256SUMS for a release.
#
# The install script verifies downloaded binaries against this file. If it is
# missing, every fresh install silently skips integrity verification, which
# defeats the checksum check. Run this at release time, then upload the result
# to Cloudflare R2 at:  releases/v1.0.0/SHA256SUMS
#
# Usage:
#   ./generate_checksums.sh            # uses ./dist
#   ./generate_checksums.sh path/dist  # custom dist dir
#
set -euo pipefail

DIST_DIR="${1:-dist}"
BINARIES=(sg.exe sg-mac-arm64 sg-mac-intel sg-linux)
OUT="SHA256SUMS"

if [[ ! -d "$DIST_DIR" ]]; then
  echo "error: dist directory '$DIST_DIR' not found" >&2
  exit 1
fi

cd "$DIST_DIR"

# Verify every expected binary is present before hashing — a partial
# checksum file is worse than none, because it looks complete.
missing=()
for b in "${BINARIES[@]}"; do
  [[ -f "$b" ]] || missing+=("$b")
done
if (( ${#missing[@]} > 0 )); then
  echo "error: missing binaries in $DIST_DIR: ${missing[*]}" >&2
  exit 1
fi

# Prefer sha256sum (Linux); fall back to shasum -a 256 (macOS).
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${BINARIES[@]}" > "$OUT"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "${BINARIES[@]}" > "$OUT"
else
  echo "error: neither sha256sum nor shasum found" >&2
  exit 1
fi

echo "Wrote $DIST_DIR/$OUT:"
cat "$OUT"
echo
echo "Next: upload $DIST_DIR/$OUT to Cloudflare R2 at releases/v1.0.0/SHA256SUMS"
