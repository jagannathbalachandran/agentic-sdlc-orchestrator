import secrets

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def generate_code(length: int = 7) -> str:
    """Return a random base62 string of the given length using secrets
    (CSPRNG), not random — codes must not be guessable/collidable in
    practice."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
