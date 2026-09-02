import json
import os

import boto3
import pytest
from moto import mock_aws


def _event(api_key=None):
    headers = {}
    if api_key is not None:
        headers["x-api-key"] = api_key
    return {"headers": headers}


@pytest.fixture
def secret_id(monkeypatch):
    with mock_aws():
        client = boto3.client("secretsmanager", region_name="us-east-1")
        response = client.create_secret(
            Name="test/links-api-key",
            SecretString=json.dumps({"apiKey": "correct-key"}),
        )
        monkeypatch.setenv("API_KEY_SECRET_ID", response["ARN"])

        # links_authorizer caches the key at module scope; reset it so each
        # test starts from a clean cache regardless of import/call order.
        import src.links_authorizer as links_authorizer

        links_authorizer._cached_api_key = None
        links_authorizer._secrets_client = client

        yield response["ARN"]


class TestLambdaHandler:
    def test_matching_key_is_authorized(self, secret_id):
        from src.links_authorizer import lambda_handler

        response = lambda_handler(_event("correct-key"), None)

        assert response == {"isAuthorized": True}

    def test_missing_header_is_not_authorized(self, secret_id):
        from src.links_authorizer import lambda_handler

        response = lambda_handler(_event(), None)

        assert response == {"isAuthorized": False}

    def test_mismatched_key_is_not_authorized(self, secret_id):
        from src.links_authorizer import lambda_handler

        response = lambda_handler(_event("wrong-key"), None)

        assert response == {"isAuthorized": False}
