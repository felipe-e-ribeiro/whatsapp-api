from src.phone import build_whatsapp_url, is_valid_br_number, normalize


class TestNormalize:
    def test_strips_punctuation_and_spaces(self):
        assert normalize("(11) 98765-4321") == "11987654321"

    def test_already_digits_only(self):
        assert normalize("11987654321") == "11987654321"

    def test_empty_string(self):
        assert normalize("") == ""

    def test_none_input(self):
        assert normalize(None) == ""

    def test_letters_only(self):
        assert normalize("abcdefghijk") == ""


class TestIsValidBrNumber:
    def test_valid_mobile_number(self):
        assert is_valid_br_number("11987654321") is True

    def test_valid_landline_number(self):
        assert is_valid_br_number("1133334444") is True

    def test_ddd_below_range(self):
        assert is_valid_br_number("0987654321") is False

    def test_ddd_above_range_is_still_two_digits_but_invalid_prefix(self):
        # 100 as a DDD isn't representable in 2 digits, so this exercises
        # a DDD of 00, which is below range.
        assert is_valid_br_number("00987654321") is False

    def test_too_short(self):
        assert is_valid_br_number("119876543") is False

    def test_too_long(self):
        assert is_valid_br_number("119876543210") is False

    def test_mobile_missing_nine_prefix(self):
        assert is_valid_br_number("11887654321") is False

    def test_empty_string(self):
        assert is_valid_br_number("") is False

    def test_non_numeric_junk(self):
        assert is_valid_br_number("abcdefghijk") is False

    def test_digits_with_leftover_letters(self):
        assert is_valid_br_number("1198765432a") is False


class TestBuildWhatsappUrl:
    def test_builds_expected_url(self):
        assert build_whatsapp_url("11987654321") == "https://wa.me/5511987654321"

    def test_builds_url_for_landline(self):
        assert build_whatsapp_url("1133334444") == "https://wa.me/551133334444"
