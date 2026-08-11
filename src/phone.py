"""Pure functions for validating Brazilian phone numbers and building
WhatsApp Web (wa.me) deep links.

No AWS or third-party dependencies — kept dependency-free so it can be
unit tested directly, without mocking a Lambda event or the AWS SDK.
"""
import re

_DIGITS_ONLY = re.compile(r"\D+")

_MIN_DDD = 11
_MAX_DDD = 99
_LANDLINE_LENGTH = 10  # DDD (2) + local number (8)
_MOBILE_LENGTH = 11  # DDD (2) + local number (9, starting with '9')

_COUNTRY_CODE = "55"
_LANDLINE_WITH_CC_LENGTH = _LANDLINE_LENGTH + len(_COUNTRY_CODE)  # 12
_MOBILE_WITH_CC_LENGTH = _MOBILE_LENGTH + len(_COUNTRY_CODE)  # 13


def normalize(raw: str) -> str:
    """Strip everything but digits from the input.

    >>> normalize("(11) 98765-4321")
    '11987654321'
    """
    if raw is None:
        return ""
    return _DIGITS_ONLY.sub("", raw)


def strip_country_code(digits: str) -> str:
    """Remove a leading Brazilian country code ("55"), if present.

    The country code is only stripped when the total length matches a
    country-code-prefixed number (12 digits for a landline, 13 for a
    mobile) — a bare DDD 55 number (55 is itself a valid Brazilian area
    code) is 10 or 11 digits and is left untouched.

    >>> strip_country_code("551100000000")
    '1100000000'
    >>> strip_country_code("1100000000")
    '1100000000'
    >>> strip_country_code("55987654321")
    '55987654321'
    """
    if digits.startswith(_COUNTRY_CODE) and len(digits) in (
        _LANDLINE_WITH_CC_LENGTH,
        _MOBILE_WITH_CC_LENGTH,
    ):
        return digits[len(_COUNTRY_CODE):]
    return digits


def is_valid_br_number(digits: str) -> bool:
    """Return True if `digits` (digits-only, no country code) is a
    recognizable Brazilian phone number: DDD 11-99, and either 10 digits
    total (8-digit landline) or 11 digits total (9-digit mobile, whose
    first digit must be '9').
    """
    if not digits.isdigit():
        return False

    ddd = int(digits[:2])
    if not (_MIN_DDD <= ddd <= _MAX_DDD):
        return False

    if len(digits) == _LANDLINE_LENGTH:
        return True

    if len(digits) == _MOBILE_LENGTH:
        return digits[2] == "9"

    return False


def build_whatsapp_url(digits: str) -> str:
    """Build the wa.me deep link for a normalized Brazilian number."""
    return f"https://wa.me/55{digits}"
