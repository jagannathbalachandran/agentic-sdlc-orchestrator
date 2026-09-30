import pytest

from service.validation import ValidationError, parse_shorten_body


def test_valid_http_url_is_returned():
    assert parse_shorten_body(b'{"url": "http://example.com/page"}') == "http://example.com/page"


def test_valid_https_url_is_returned():
    assert parse_shorten_body(b'{"url": "https://example.com"}') == "https://example.com"


def test_unparsable_json_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_shorten_body(b"not json")


def test_non_object_json_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_shorten_body(b'["http://example.com"]')


def test_missing_url_field_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_shorten_body(b"{}")


def test_empty_url_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_shorten_body(b'{"url": ""}')


def test_non_string_url_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_shorten_body(b'{"url": 123}')


def test_scheme_missing_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_shorten_body(b'{"url": "example.com/page"}')


def test_non_http_scheme_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_shorten_body(b'{"url": "ftp://example.com/file"}')


def test_missing_netloc_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_shorten_body(b'{"url": "http://"}')
