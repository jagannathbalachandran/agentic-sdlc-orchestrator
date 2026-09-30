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
    app = create_app(InMemoryCodeStore())
    server: WSGIServer = make_server("127.0.0.1", 0, app)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        host_str = host.decode("ascii") if isinstance(host, bytes) else host
        yield f"http://{host_str}:{port}"
    finally:
        server.shutdown()
        thread.join()
