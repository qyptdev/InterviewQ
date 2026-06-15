#!/usr/bin/env bash
# Build Tailwind CSS using standalone CLI
# Usage: ./scripts/build_css.sh [--watch]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TAILWIND_BIN="$PROJECT_ROOT/tailwindcss"
INPUT_CSS="$PROJECT_ROOT/app/static/css/input.css"
OUTPUT_CSS="$PROJECT_ROOT/app/static/css/tailwind.css"
CONFIG="$PROJECT_ROOT/tailwind.config.js"

if [ ! -x "$TAILWIND_BIN" ]; then
    echo "Error: Tailwind CLI not found at $TAILWIND_BIN" >&2
    echo "Download it from https://github.com/tailwindlabs/tailwindcss/releases" >&2
    exit 1
fi

if [ ! -f "$INPUT_CSS" ]; then
    echo "Error: Input CSS not found at $INPUT_CSS" >&2
    exit 1
fi

ARGS=("-i" "$INPUT_CSS" "-o" "$OUTPUT_CSS" "--minify")

if [[ "${1:-}" == "--watch" ]]; then
    ARGS+=("--watch")
    echo "Watching for changes..."
fi

exec "$TAILWIND_BIN" "${ARGS[@]}"
