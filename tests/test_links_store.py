import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        region = "us-east-1"
        dynamodb = boto3.resource("dynamodb", region_name=region)

        table = dynamodb.create_table(
            TableName="store-test",
            KeySchema=[{"AttributeName": "requestId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "requestId", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        monkeypatch.setenv("TEST_TABLE_NAME", "store-test")

        import src.links_store as links_store

        links_store._dynamodb = dynamodb

        yield {"table": table}


class TestGetItem:
    def test_missing_item_returns_none(self, aws):
        from src.links_store import get_item

        assert get_item("TEST_TABLE_NAME", {"requestId": "nope"}) is None

    def test_existing_item_is_returned(self, aws):
        from src.links_store import get_item

        aws["table"].put_item(Item={"requestId": "8k", "status": "pending"})

        item = get_item("TEST_TABLE_NAME", {"requestId": "8k"})
        assert item == {"requestId": "8k", "status": "pending"}


class TestPutItem:
    def test_unconditional_put_always_succeeds(self, aws):
        from src.links_store import put_item

        assert put_item("TEST_TABLE_NAME", {"requestId": "8k", "status": "pending"}) is True
        assert put_item("TEST_TABLE_NAME", {"requestId": "8k", "status": "overwritten"}) is True

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "overwritten"

    def test_conditional_put_succeeds_when_absent(self, aws):
        from src.links_store import put_item

        created = put_item(
            "TEST_TABLE_NAME",
            {"requestId": "8k", "status": "pending"},
            if_not_exists_key="requestId",
        )

        assert created is True

    def test_conditional_put_returns_false_when_already_present(self, aws):
        from src.links_store import put_item

        put_item(
            "TEST_TABLE_NAME",
            {"requestId": "8k", "status": "pending"},
            if_not_exists_key="requestId",
        )

        created_again = put_item(
            "TEST_TABLE_NAME",
            {"requestId": "8k", "status": "should-not-apply"},
            if_not_exists_key="requestId",
        )

        assert created_again is False
        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "pending"


class TestUpdateItem:
    def test_sets_given_attributes(self, aws):
        from src.links_store import update_item

        aws["table"].put_item(Item={"requestId": "8k", "status": "pending"})

        updated = update_item(
            "TEST_TABLE_NAME",
            {"requestId": "8k"},
            {"status": "completed", "result": "https://wa.me/5511987654321"},
        )

        assert updated["status"] == "completed"
        assert updated["result"] == "https://wa.me/5511987654321"
        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "completed"

    def test_can_remove_attributes_while_setting_others(self, aws):
        from src.links_store import update_item

        aws["table"].put_item(
            Item={"requestId": "8k", "status": "failed", "lastError": "boom"}
        )

        update_item(
            "TEST_TABLE_NAME",
            {"requestId": "8k"},
            {"status": "completed"},
            remove=["lastError"],
        )

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "completed"
        assert "lastError" not in item

    def test_removing_an_absent_attribute_is_a_no_op(self, aws):
        from src.links_store import update_item

        aws["table"].put_item(Item={"requestId": "8k", "status": "pending"})

        update_item("TEST_TABLE_NAME", {"requestId": "8k"}, remove=["lastError"])

        item = aws["table"].get_item(Key={"requestId": "8k"})["Item"]
        assert item["status"] == "pending"


class TestIncrement:
    def test_starts_at_given_value(self, aws):
        from src.links_store import increment

        value = increment("TEST_TABLE_NAME", {"requestId": "counter"}, "value", start=515)

        assert value == 516

    def test_accumulates_across_calls(self, aws):
        from src.links_store import increment

        increment("TEST_TABLE_NAME", {"requestId": "counter"}, "attempts")
        second = increment("TEST_TABLE_NAME", {"requestId": "counter"}, "attempts")

        assert second == 2
