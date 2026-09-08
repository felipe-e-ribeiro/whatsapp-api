"""Structured logging and CloudWatch metrics helpers, shared by every
Lambda handler in this project (v1, v2, and v3).

Deliberately stdlib-only — no aws-lambda-powertools or similar dependency,
matching the "only the Python standard library" policy already stated in
requirements.txt. Two things live here:

- `get_logger`/`log_event`: one JSON line per log record, directly
  queryable in CloudWatch Logs Insights (e.g. `filter step = "resolve" and
  outcome = "failed"`) with zero extra infrastructure — Lambda ships
  stdout/stderr to CloudWatch Logs automatically, as part of every
  invocation, at no cost beyond normal log ingestion/storage.
- `emit_metric`: one CloudWatch Embedded Metric Format (EMF) JSON line per
  metric. CloudWatch Logs recognizes the `_aws` envelope below and turns
  it into a real custom metric on its own — no `PutMetricData` API call,
  so no added latency and no cost beyond the log line itself. See
  https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html

Both write straight to stdout via `print`/a dedicated `StreamHandler`
rather than relying on whatever root-logger configuration a test runner
or the Lambda runtime happens to install, so every line lands in
CloudWatch exactly once and in the same shape in every environment.
"""
import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

_METRIC_NAMESPACE = "WhatsappLinkApi"


class _StdoutHandler(logging.Handler):
    """Writes each record to whatever `sys.stdout` currently is, looked up
    at emit time rather than bound once at handler-construction time.

    `logging.StreamHandler(sys.stdout)` captures that reference eagerly:
    fine in Lambda, where stdout never changes after import, but it
    breaks test runners (e.g. pytest's `capsys`) that swap `sys.stdout`
    in and out per test — a logger configured once at module-import time
    would otherwise keep writing to a stream no later test is watching.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


class _JsonFormatter(logging.Formatter):
    """Renders each LogRecord as a single-line JSON object instead of
    plain text, so CloudWatch Logs Insights can filter/aggregate on
    individual fields instead of grepping message strings.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes one JSON object per line to stdout.

    Idempotent on purpose: a warm Lambda execution environment reuses the
    same module-level logger across invocations, so repeated calls must
    not stack a new handler each time — `_json_configured` guards that.
    """
    logger = logging.getLogger(name)
    if not getattr(logger, "_json_configured", False):
        handler = _StdoutHandler()
        handler.setFormatter(_JsonFormatter())
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger._json_configured = True  # type: ignore[attr-defined]
    return logger


def log_event(
    logger: logging.Logger,
    message: str,
    *,
    level: str = "INFO",
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Emit one structured log line: `message` plus arbitrary extra
    fields (requestId, step, outcome, durationMs, ...) as top-level JSON
    keys rather than interpolated into the message text, so each field
    is independently queryable. Pass `exc_info=True` from an `except`
    block to attach the current exception's traceback.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, message, extra={"fields": fields}, exc_info=exc_info)


def emit_metric(
    metric_name: str,
    value: float = 1,
    *,
    unit: str = "Count",
    dimensions: Optional[dict[str, str]] = None,
    **extra_fields: Any,
) -> None:
    """Emit one CloudWatch Embedded Metric Format (EMF) log line to
    stdout. `extra_fields` are attached to the same log line (e.g.
    `requestId`) for correlation with the logs above, without becoming
    part of the metric itself.
    """
    dimensions = dimensions or {}
    document: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": _METRIC_NAMESPACE,
                    "Dimensions": [list(dimensions.keys())],
                    "Metrics": [{"Name": metric_name, "Unit": unit}],
                }
            ],
        },
        metric_name: value,
        **dimensions,
        **extra_fields,
    }
    print(json.dumps(document, default=str))


@contextmanager
def timer() -> Iterator[dict[str, float]]:
    """Context manager yielding a dict that gains an `ms` key — elapsed
    wall-clock milliseconds — once the `with` block exits. Read it after
    the block, not inside it:

        with timer() as t:
            do_work()
        log_event(logger, "done", durationMs=round(t["ms"], 2))
    """
    state: dict[str, float] = {}
    start = time.perf_counter()
    try:
        yield state
    finally:
        state["ms"] = (time.perf_counter() - start) * 1000


def mask_phone_number(value: str) -> str:
    """Redact all but the last 4 digits before a phone number reaches a
    log or metric line. Logs/metrics are comparatively low-friction to
    read (CloudWatch console, any IAM principal with read access) next to
    the DynamoDB record itself, so the full number has no business
    appearing there.
    """
    if not value:
        return value
    tail = value[-4:] if len(value) > 4 else value
    return f"{'*' * max(len(value) - len(tail), 0)}{tail}"
