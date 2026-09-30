# Traces: FR-1.AC1, FR-1.AC2, FR-1.AC3, FR-2.AC1, FR-2.AC2
"""Shared fixtures: start the real service over a socket (per 02-design.md's
"Test client" note) and drive it with stdlib HTTP clients only."""
from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as exc:  # noqa: PERF203 - polling loop
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"service did not start on {host}:{port}") from last_error


class ServiceClient:
    """Thin stdlib-only HTTP client for the acceptance-test base URL."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def shorten(self, body: bytes, content_type: str = "application/json") -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{self.base_url}/shorten",
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8")
            return exc.code, (json.loads(payload) if payload else {})

    def get_redirect(self, code: str) -> tuple[int, str | None, bytes]:
        req = urllib.request.Request(f"{self.base_url}/{code}", method="GET")

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req) as resp:
                return resp.status, resp.headers.get("Location"), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Location"), exc.read()


@pytest.fixture(scope="session")
def service_process() -> Iterator[ServiceClient]:
    host = "127.0.0.1"
    port = _free_port()
    env = dict(os.environ)
    env["HOST"] = host
    env["PORT"] = str(port)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "service"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        try:
            _wait_until_up(host, port)
        except RuntimeError:
            proc.terminate()
            out, _ = proc.communicate(timeout=5)
            raise RuntimeError(
                f"service did not start on {host}:{port}; output:\n{out.decode(errors='replace')}"
            ) from None
        yield ServiceClient(f"http://{host}:{port}")
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture()
def client(service_process: ServiceClient) -> ServiceClient:
    return service_process
