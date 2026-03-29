#!/usr/bin/env bash
# Tests with WSL system Python + TLS settings (no GitHub CPython download).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export UV_PYTHON="${UV_PYTHON:-/usr/bin/python3.12}"
export UV_PYTHON_DOWNLOADS="${UV_PYTHON_DOWNLOADS:-never}"
export UV_NATIVE_TLS="${UV_NATIVE_TLS:-1}"
cd "$ROOT"
exec uv run --no-python-downloads --python "$UV_PYTHON" pytest tests/ -v -s "$@"
