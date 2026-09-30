from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from typing import Protocol

_ALPHABET = string.ascii_letters + string.digits


class CodeStore(Protocol):
    def save(self, long_url: str) -> str:
        """Mint a new short code for long_url, store the mapping, return the code."""
        ...

    def resolve(self, code: str) -> str | None:
        """Return the long URL for code, or None if code is unknown."""
        ...


@dataclass
class InMemoryCodeStore:
    """CodeStore backed by a process-local dict. Not thread-safe across
    multiple WSGI worker threads sharing one instance beyond the GIL's
    per-bytecode-op atomicity; acceptable for this minimal, single-process
    scope."""

    _codes: dict[str, str] = field(default_factory=dict)
    _code_length: int = 7

    def save(self, long_url: str) -> str:
        code = generate_code(self._code_length)
        while code in self._codes:
            code = generate_code(self._code_length)
        self._codes[code] = long_url
        return code

    def resolve(self, code: str) -> str | None:
        return self._codes.get(code)


def generate_code(length: int = 7) -> str:
    """Return a random base62 string of the given length using secrets.choice."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
