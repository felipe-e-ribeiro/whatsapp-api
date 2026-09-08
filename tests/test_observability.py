import json
import time

import pytest

from src.observability import emit_metric, get_logger, log_event, mask_phone_number, timer


class TestGetLogger:
    def test_returns_same_instance_and_handler_on_repeated_calls(self):
        first = get_logger("test.observability.idempotent")
        second = get_logger("test.observability.idempotent")

        assert first is second
        assert len(first.handlers) == 1

    def test_does_not_propagate_to_root(self):
        logger = get_logger("test.observability.no-propagate")

        assert logger.propagate is False


class TestLogEvent:
    def test_writes_one_json_line_with_message_and_fields(self, capsys):
        logger = get_logger("test.observability.log-event")

        log_event(logger, "link submitted", requestId="8k", step="submit", outcome="accepted")

        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["message"] == "link submitted"
        assert payload["level"] == "INFO"
        assert payload["requestId"] == "8k"
        assert payload["step"] == "submit"
        assert payload["outcome"] == "accepted"

    def test_level_parameter_controls_log_level(self, capsys):
        logger = get_logger("test.observability.log-level")

        log_event(logger, "denied", level="WARNING", step="authorizer")

        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["level"] == "WARNING"

    def test_exc_info_attaches_the_active_exception(self, capsys):
        logger = get_logger("test.observability.log-exc")

        try:
            raise ValueError("boom")
        except ValueError:
            log_event(logger, "processing failed", level="ERROR", exc_info=True, step="process")

        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["level"] == "ERROR"
        assert "boom" in payload["error"]
        assert "ValueError" in payload["error"]


class TestEmitMetric:
    def test_emits_valid_embedded_metric_format_with_dimensions(self, capsys):
        emit_metric("LinksSubmitted", dimensions={"Version": "v2"}, requestId="8k")

        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["LinksSubmitted"] == 1
        assert payload["Version"] == "v2"
        assert payload["requestId"] == "8k"

        directive = payload["_aws"]["CloudWatchMetrics"][0]
        assert directive["Namespace"] == "WhatsappLinkApi"
        assert directive["Dimensions"] == [["Version"]]
        assert directive["Metrics"] == [{"Name": "LinksSubmitted", "Unit": "Count"}]
        assert isinstance(payload["_aws"]["Timestamp"], int)

    def test_emits_valid_embedded_metric_format_without_dimensions(self, capsys):
        emit_metric("AuthorizationDenied")

        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["AuthorizationDenied"] == 1
        assert payload["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]

    def test_custom_value_and_unit_are_honored(self, capsys):
        emit_metric("PipelineDurationMs", 123.4, unit="Milliseconds")

        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["PipelineDurationMs"] == 123.4
        assert payload["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Unit"] == "Milliseconds"


class TestTimer:
    def test_measures_elapsed_milliseconds(self):
        with timer() as t:
            time.sleep(0.01)

        assert t["ms"] >= 10


class TestMaskPhoneNumber:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("11987654321", "*******4321"),
            ("1234", "1234"),
            ("12", "12"),
            ("", ""),
        ],
    )
    def test_keeps_only_the_last_four_digits(self, value, expected):
        assert mask_phone_number(value) == expected
