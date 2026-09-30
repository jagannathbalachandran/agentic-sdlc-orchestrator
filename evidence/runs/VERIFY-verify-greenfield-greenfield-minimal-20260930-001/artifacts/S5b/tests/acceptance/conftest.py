"""Shared fixture: a live HTTP server for the service's WSGI app.

Starts service.app.create_app(service.store.InMemoryCodeStore()) via
wsgiref.simple_server on an ephemeral port in a background thread, per
02-design.md's documented acceptance-test approach (real HTTP semantics:
status line, headers, Location).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from wsgiref.simple_server import WSGIServer, make_server

import pytest

from service.app import create_app
from service.store import InMemoryCodeStore


@pytest.fixture
def base_url() -> Iterator[str]:
    server: WSGIServer = make_server("127.0.0.1", 0, create_app(InMemoryCodeStore()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()
