#!/usr/bin/env bash
# Run MCP with WSL system Python only (no GitHub CPython download).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export UV_PYTHON="${UV_PYTHON:-/usr/bin/python3.12}"
export UV_PYTHON_DOWNLOADS="${UV_PYTHON_DOWNLOADS:-never}"
# Helps TLS "UnknownIssuer" vs PyPI/GitHub when system trust store differs from uv's default.
export UV_NATIVE_TLS="${UV_NATIVE_TLS:-1}"
exec uv --directory "$ROOT" run --no-python-downloads --python "$UV_PYTHON" peoplesoft_fin_server.py
