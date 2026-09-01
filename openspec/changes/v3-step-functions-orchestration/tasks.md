## 1. Shared DynamoDB helper (refactor, v2 + v3)

- [x] 1.1 Create `src/links_store.py` with generic `get_item`, `put_item` (with optional conditional-expression support), and `update_item` helpers wrapping `boto3.resource("dynamodb").Table(...)`
- [x] 1.2 Migrate `src/links_submit.py` to use `links_store` instead of inline `boto3` calls, preserving identical behavior
- [x] 1.3 Migrate `src/links_processor.py` to use `links_store`, preserving identical behavior
- [x] 1.4 Migrate `src/links_status.py` to use `links_store`, preserving identical behavior
- [x] 1.5 Update `tests/test_links_submit.py`, `tests/test_links_processor.py`, `tests/test_links_status.py` mocks to target `links_store` where needed, without changing what is asserted
- [x] 1.6 Run the full existing test suite and confirm 100%/≥90% coverage and all v1/v2 assertions still pass unchanged

## 2. v3 pipeline Lambdas

- [x] 2.1 Create `src/links_v3_validate.py` — Step Functions task input `{requestId, number}`, uses `phone.normalize`/`strip_country_code`/`is_valid_br_number`; returns a result indicating valid/invalid without raising for an invalid (non-retryable) number
- [x] 2.2 Create `src/links_v3_resolve.py` — uses `phone.build_whatsapp_url`; increments `attempts` via `links_store.update_item` on every invocation; honors an optional `simulateFailures` input field by raising a named error for the first N invocations; records `lastError` on failure
- [x] 2.3 Create `src/links_v3_persist.py` — writes final `status` (`completed`/`invalid`/`failed`), `result`, and `completedAt` to `LinksV3Table` via `links_store`
- [x] 2.4 Create `src/links_v3_start.py` — `POST /v3/links` handler: validates request body shape, resolves the idempotency key (from `Idempotency-Key` header or generated), conditionally `put_item`s a `pending` record, calls `StartExecution` with `name=<idempotency key>`, treats `ExecutionAlreadyExists` as success, returns 202
- [x] 2.5 Create `src/links_v3_status.py` — `GET /v3/links/{requestId}` handler: reads `LinksV3Table`, returns 404 if missing, otherwise returns `status`/`result`/`attempts`/`lastError` as applicable

## 3. Step Functions state machine

- [x] 3.1 Create `statemachine/links_pipeline.asl.yaml` defining `Validate` → `Resolve` → `Persist` states
- [x] 3.2 Add `Retry` (exponential backoff) to the `Resolve` state for transient/simulated failures
- [x] 3.3 Add `Catch` on each state routing to a failure path: send payload to `LinksV3DLQ`, then invoke `links_v3_persist` (or an equivalent failure-marking step) to set `status: failed` with `lastError`, then end in a `Fail` state
- [x] 3.4 Route an invalid-number result from `Validate` directly to `Persist` with `status: invalid`, bypassing `Resolve`'s retry logic

## 4. Infrastructure (`template.yaml`)

- [x] 4.1 Add `LinksV3Table` (DynamoDB, PAY_PER_REQUEST, partition key `requestId`)
- [x] 4.2 Add `LinksV3DLQ` (SQS)
- [x] 4.3 Add the five new `AWS::Serverless::Function` resources with their environment variables and least-privilege `Policies` (DynamoDB CRUD on `LinksV3Table`, SQS send on `LinksV3DLQ`, Step Functions `StartExecution` on `LinksV3StateMachine`)
- [x] 4.4 Add `LinksV3StateMachine` (`AWS::Serverless::StateMachine`, `DefinitionUri: statemachine/links_pipeline.asl.yaml`, `DefinitionSubstitutions` for the Lambda ARNs)
- [x] 4.5 Add `POST /v3/links` and `GET /v3/links/{requestId}` routes on the existing `WhatsappHttpApi`, both using `Auth: Authorizer: LinksApiKeyAuthorizer`
- [ ] 4.6 `sam build` and `sam deploy` to a dev/test stack; confirm no diff/changes are proposed for existing v1/v2 resources — **not run in this session** (no AWS credentials/SAM CLI here); the user runs this themselves before submitting the checkpoint

## 5. Tests

- [x] 5.1 Unit tests for `links_store.py`
- [x] 5.2 Unit tests for `links_v3_validate.py` (valid, invalid, malformed input)
- [x] 5.3 Unit tests for `links_v3_resolve.py` (success on first try, success after simulated failures, attempts/lastError persisted)
- [x] 5.4 Unit tests for `links_v3_persist.py` (completed/invalid/failed paths)
- [x] 5.5 Unit tests for `links_v3_start.py` (happy path, malformed body, missing api key handled by authorizer layer, idempotent resubmission via `ExecutionAlreadyExists`)
- [x] 5.6 Unit tests for `links_v3_status.py` (pending/completed/invalid/failed/404)
- [x] 5.7 Confirm overall coverage stays ≥90% per `pytest.ini` — 99.2% overall (87 passed)

## 6. Documentation

- [x] 6.1 Add a "v3 (orchestrated)" section to `README.md`: architecture summary, request/response examples for `POST`/`GET /v3/links`, and the project layout additions
- [x] 6.2 Document the `simulateFailures` field and the exact expected outcome for a within-budget vs. exceeds-budget value
- [x] 6.3 Document how to inspect `LinksV3DLQ` and how to read a Step Functions execution's retry history (`aws stepfunctions get-execution-history`), consistent with the professor's "no public URLs in the repo" requirement
