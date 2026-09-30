from __future__ import annotations

import string
from unittest.mock import patch

from service.store import InMemoryCodeStore, generate_code


def test_generate_code_default_length_is_seven() -> None:
    code = generate_code()

    assert len(code) == 7


def test_generate_code_custom_length() -> None:
    code = generate_code(12)

    assert len(code) == 12


def test_generate_code_uses_base62_alphabet() -> None:
    code = generate_code(200)

    assert all(c in string.ascii_letters + string.digits for c in code)


def test_generate_code_is_random_across_calls() -> None:
    codes = {generate_code() for _ in range(50)}

    assert len(codes) > 1


def test_in_memory_code_store_save_returns_code_of_default_length() -> None:
    store = InMemoryCodeStore()

    code = store.save("https://example.com")

    assert len(code) == 7


def test_in_memory_code_store_save_stores_mapping() -> None:
    store = InMemoryCodeStore()

    code = store.save("https://example.com/path")

    assert store.resolve(code) == "https://example.com/path"


def test_in_memory_code_store_resolve_unknown_code_returns_none() -> None:
    store = InMemoryCodeStore()

    assert store.resolve("nosuch1") is None


def test_in_memory_code_store_save_mints_distinct_codes_across_calls() -> None:
    store = InMemoryCodeStore()

    code_a = store.save("https://a.example.com")
    code_b = store.save("https://b.example.com")

    assert code_a != code_b
    assert store.resolve(code_a) == "https://a.example.com"
    assert store.resolve(code_b) == "https://b.example.com"


def test_in_memory_code_store_save_rerolls_on_collision() -> None:
    store = InMemoryCodeStore()
    store._codes["aaaaaaa"] = "https://existing.example.com"

    with patch(
        "service.store.generate_code",
        side_effect=["aaaaaaa", "bbbbbbb"],
    ) as mocked_generate_code:
        code = store.save("https://new.example.com")

    assert code == "bbbbbbb"
    assert mocked_generate_code.call_count == 2
    assert store.resolve("bbbbbbb") == "https://new.example.com"
    assert store.resolve("aaaaaaa") == "https://existing.example.com"


def test_in_memory_code_store_satisfies_code_store_protocol() -> None:
    store = InMemoryCodeStore()

    assert hasattr(store, "save")
    assert hasattr(store, "resolve")
