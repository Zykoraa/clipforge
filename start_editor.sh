#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${CLIPFORGE_PORT:-8765}"

# Default to Web UI on $PORT unless the caller explicitly passed --port or --mcp
HAS_PORT_OR_MCP=0
for arg in "$@"; do
    case "$arg" in
        --port|--port=*|--mcp|-h|--help)
            HAS_PORT_OR_MCP=1
            break
            ;;
    esac
done

EXTRA_ARGS=()
if [[ "$HAS_PORT_OR_MCP" -eq 0 ]]; then
    EXTRA_ARGS=(--port "$PORT")
fi

if [[ -x "$ROOT/dist/ClipForge/ClipForge" ]]; then
    exec "$ROOT/dist/ClipForge/ClipForge" "${EXTRA_ARGS[@]}" "$@"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    exec "$ROOT/.venv/bin/python" "$ROOT/main.py" "${EXTRA_ARGS[@]}" "$@"
elif command -v uv >/dev/null 2>&1; then
    exec uv run python "$ROOT/main.py" "${EXTRA_ARGS[@]}" "$@"
else
    echo "Error: neither dist/ClipForge/ClipForge, .venv/bin/python, nor uv was found." >&2
    exit 1
fi
