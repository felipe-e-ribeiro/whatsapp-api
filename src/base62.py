"""Pure base62 encoding helper.

Used to turn the v2 request counter (see `links_submit.py`) into a public
`requestId` that is sequential internally but doesn't read as a plain
decimal counter externally.
"""

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_BASE = len(_ALPHABET)


def encode(n: int) -> str:
    """Encode a non-negative integer as a base62 string.

    >>> encode(0)
    '0'
    >>> encode(516)
    '8k'
    """
    if n < 0:
        raise ValueError("base62.encode requires a non-negative integer")

    if n == 0:
        return _ALPHABET[0]

    digits = []
    while n > 0:
        n, remainder = divmod(n, _BASE)
        digits.append(_ALPHABET[remainder])

    return "".join(reversed(digits))
