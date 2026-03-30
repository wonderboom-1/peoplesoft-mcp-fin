"""Smoke test: server module loads without DB (tools register)."""

import pytest

pytest.importorskip("fastmcp")


def test_import_server():
    import peoplesoft_fin_server

    assert peoplesoft_fin_server.mcp is not None
