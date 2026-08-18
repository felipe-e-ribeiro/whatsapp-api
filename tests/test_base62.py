import pytest

from src.base62 import encode


class TestEncode:
    def test_zero(self):
        assert encode(0) == "0"

    def test_seed_value_516_encodes_to_8k(self):
        assert encode(516) == "8k"

    def test_value_requiring_multiple_digits(self):
        # 62**2 = 3844 is the smallest value that needs three base62 digits
        assert encode(3844) == "100"

    def test_negative_input_raises(self):
        with pytest.raises(ValueError):
            encode(-1)
