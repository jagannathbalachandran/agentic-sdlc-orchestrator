from unittest.mock import patch

from service.codegen import _ALPHABET, generate_code


def test_default_length_is_seven():
    assert len(generate_code()) == 7


def test_custom_length_is_respected():
    assert len(generate_code(length=12)) == 12


def test_zero_length_returns_empty_string():
    assert generate_code(length=0) == ""


def test_all_characters_are_from_base62_alphabet():
    code = generate_code(length=200)
    assert all(char in _ALPHABET for char in code)


def test_alphabet_is_base62_with_no_duplicates():
    assert len(_ALPHABET) == 62
    assert len(set(_ALPHABET)) == 62


def test_successive_calls_are_not_identical():
    codes = {generate_code() for _ in range(20)}
    assert len(codes) > 1


def test_uses_secrets_choice_for_csprng_generation():
    with patch("service.codegen.secrets.choice", return_value="A") as mock_choice:
        code = generate_code(length=5)
    assert code == "AAAAA"
    assert mock_choice.call_count == 5
    mock_choice.assert_called_with(_ALPHABET)
