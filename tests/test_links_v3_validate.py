from src.links_v3_validate import lambda_handler


class TestLambdaHandler:
    def test_valid_mobile_number(self):
        result = lambda_handler({"requestId": "8k", "number": "11987654321"}, None)

        assert result == {"valid": True, "digits": "11987654321"}

    def test_valid_number_with_formatting(self):
        result = lambda_handler(
            {"requestId": "8k", "number": "(11) 98765-4321"}, None
        )

        assert result == {"valid": True, "digits": "11987654321"}

    def test_invalid_number_is_not_raised_as_an_error(self):
        result = lambda_handler({"requestId": "8l", "number": "123"}, None)

        assert result == {"valid": False, "digits": None}

    def test_missing_number_is_invalid(self):
        result = lambda_handler({"requestId": "8m"}, None)

        assert result == {"valid": False, "digits": None}
