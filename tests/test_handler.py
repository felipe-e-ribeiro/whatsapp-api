import json

from src.handler import lambda_handler


def _event(number):
    return {"pathParameters": {"number": number}}


class TestLambdaHandler:
    def test_valid_number_returns_url(self):
        response = lambda_handler(_event("11987654321"), None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {
            "result": "https://wa.me/5511987654321"
        }

    def test_invalid_number_returns_false(self):
        response = lambda_handler(_event("123"), None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"result": False}

    def test_missing_path_parameters_key(self):
        response = lambda_handler({}, None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"result": False}

    def test_null_path_parameters(self):
        response = lambda_handler({"pathParameters": None}, None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"result": False}

    def test_missing_number_key(self):
        response = lambda_handler({"pathParameters": {}}, None)

        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"result": False}

    def test_formatted_number_is_normalized_before_validation(self):
        response = lambda_handler(_event("(11) 98765-4321"), None)

        assert json.loads(response["body"]) == {
            "result": "https://wa.me/5511987654321"
        }

    def test_number_without_country_code_defaults_to_br(self):
        response = lambda_handler(_event("11 0000-0000"), None)

        assert json.loads(response["body"]) == {
            "result": "https://wa.me/551100000000"
        }

    def test_number_with_explicit_country_code_is_accepted(self):
        response = lambda_handler(_event("+55 11 0000-0000"), None)

        assert json.loads(response["body"]) == {
            "result": "https://wa.me/551100000000"
        }

    def test_number_with_country_code_and_no_formatting(self):
        response = lambda_handler(_event("5511987654321"), None)

        assert json.loads(response["body"]) == {
            "result": "https://wa.me/5511987654321"
        }
