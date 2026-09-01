## Why

Checkpoint 3 requires evolving the serverless pipeline built in previous checkpoints into a fully orchestrated flow — one YAML-defined workflow that calls functions in the correct order, manages responses, applies idempotency rules, and handles failures with retries and a dead-letter queue. The course material frames this around Google Cloud Workflows, but this project runs on AWS, so the same requirements need an AWS-native orchestrator instead of a GCP one.

## What Changes

- Add a new, parallel `v3` API surface (`POST /v3/links`, `GET /v3/links/{requestId}`) that orchestrates the number-resolution pipeline through an **AWS Step Functions** Standard Workflow, defined in YAML (Amazon States Language) as the AWS equivalent of Cloud Workflows.
- Split the pipeline into three orchestrated steps, each a small dedicated Lambda: `Validate` → `Resolve` → `Persist`, reusing the existing pure logic in `src/phone.py` (no business-rule duplication).
- Add per-step `Retry` (exponential backoff) and `Catch` handling in the state machine; on exhausted retries, the failing payload is sent to a new, dedicated SQS dead-letter queue and the request's stored status is marked `failed`.
- Add an optional `simulateFailures` field on `POST /v3/links` to deterministically demonstrate the retry mechanism during evaluation, without depending on a real transient failure occurring.
- Add idempotency: an `Idempotency-Key` header (or a generated fallback) is used both as the DynamoDB partition key (conditional put) and as the Step Functions execution `name`, so a repeated submission is not reprocessed.
- Track retry evidence (`attempts`, `lastError`) directly in DynamoDB so it's inspectable via the existing `GET` endpoint, not only via the Step Functions console/execution history.
- Extract a small shared `src/links_store.py` DynamoDB helper module and migrate the existing v2 handlers (`links_submit.py`, `links_processor.py`, `links_status.py`) to use it, removing duplicated boto3 boilerplate. This is a behavior-preserving refactor — v1 and v2 external behavior does not change.
- Add a "v3" section to the README documenting the architecture, local run instructions, and how to use `simulateFailures` to demonstrate retry/DLQ behavior — no public URLs, per the course's security requirements.

## Capabilities

### New Capabilities
- `whatsapp-link-orchestration`: Orchestrated (Step Functions), idempotent, retryable v3 pipeline for resolving a Brazilian phone number to a WhatsApp deep link, exposed via `POST /v3/links` and `GET /v3/links/{requestId}`.

### Modified Capabilities
(none — the `links_store.py` extraction changes only internal implementation of the existing `whatsapp-link-api` capability's v2 behavior; no request/response contract or requirement changes.)

## Impact

- **New infrastructure** (`template.yaml`): `LinksV3Table` (DynamoDB), `LinksV3DLQ` (SQS), `LinksV3StateMachine` (Step Functions, defined in `statemachine/links_pipeline.asl.yaml`), and five new Lambda functions (`LinksV3StartFunction`, `LinksV3ValidateFunction`, `LinksV3ResolveFunction`, `LinksV3PersistFunction`, `LinksV3StatusFunction`). No existing v1/v2 resources are removed or reconfigured.
- **Reused infrastructure**: the existing `WhatsappHttpApi`, `LinksApiKeyAuthorizer`, and `LinksApiKeySecret` are reused for the new `/v3/*` routes — no duplicate auth stack.
- **New code**: `src/links_v3_start.py`, `src/links_v3_validate.py`, `src/links_v3_resolve.py`, `src/links_v3_persist.py`, `src/links_v3_status.py`, `src/links_store.py`, `statemachine/links_pipeline.asl.yaml`, plus corresponding tests under `tests/`.
- **Modified code (behavior-preserving)**: `src/links_submit.py`, `src/links_processor.py`, `src/links_status.py` refactored to use `src/links_store.py`; their existing tests are updated only to the extent the refactor requires (mocking `links_store` instead of inline `boto3`), with no assertion on request/response behavior changed.
- **Dependencies**: no new third-party dependencies; uses `boto3`'s existing Step Functions client (`boto3.client("stepfunctions")`) alongside the DynamoDB/SQS clients already in use.
