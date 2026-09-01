## Context

v1 is a single synchronous Lambda. v2 introduced an event-driven flow choreographed via SQS: each function (`links_submit` → `LinksQueue` → `links_processor`) knows what happens next only implicitly, through the queue wiring in `template.yaml`; there is no central definition of the flow, and retry/failure handling is entirely the queue's redrive policy (`LinksDLQ`, `maxReceiveCount: 3`).

Checkpoint 3 requires a *centrally defined, structured orchestration* — a single YAML artifact that states the call order, response handling, idempotency, retries, and dead-lettering explicitly. The course material assumes Google Cloud Workflows; this project is AWS-only, so the direct equivalent is **AWS Step Functions**, whose state machines are themselves defined in YAML/JSON (Amazon States Language) and natively support per-step `Retry`/`Catch`.

The user explicitly chose to add this as a **parallel `v3`** rather than rewrite v2, to avoid touching already-graded v1/v2 behavior, while still allowing one small, behavior-preserving refactor (`links_store.py`) shared across v2 and v3 to avoid duplicating DynamoDB boilerplate and to give v3 a place to persist retry evidence (`attempts`, `lastError`).

## Goals / Non-Goals

**Goals:**
- Provide a v3 pipeline whose call order, retries, and failure routing are defined in one YAML file (the state machine's ASL definition), satisfying the checkpoint's orchestration requirement with an AWS-native tool.
- Make retries and idempotency verifiable without requiring console access: both are inspectable through the existing `GET` polling pattern and, for idempotency, via `Idempotency-Key` semantics.
- Reuse existing pure business logic (`src/phone.py`) and existing auth infrastructure (`WhatsappHttpApi`, `LinksApiKeyAuthorizer`, `LinksApiKeySecret`) rather than duplicating them.
- Leave v1 and v2's external behavior completely unchanged.

**Non-Goals:**
- Rewriting v2's SQS choreography to use Step Functions — v2 stays as-is; v3 is additive.
- Building a new business domain/problem for this checkpoint — v3 orchestrates the same number→link resolution, per the user's decision to demonstrate evolution of the existing pipeline.
- Real, non-deterministic fault injection (e.g., actually throttling Lambda concurrency) — the `simulateFailures` hook is a deliberate, documented, opt-in mechanism instead.
- Cross-account or multi-region concerns; this mirrors v1/v2's single-region, single-account deployment.

## Decisions

**1. AWS Step Functions Standard Workflow, not Express.**
Standard Workflow persists full execution history (queryable via `DescribeExecution`/`GetExecutionHistory`), which is what makes retries and failures independently verifiable evidence, not just a side effect visible only while watching a live invocation. Express Workflows are cheaper and lower-latency but only log to CloudWatch Logs and don't durably track per-execution state — the wrong trade-off for a submit-then-poll API that may be checked minutes later. Standard's higher per-transition cost is irrelevant at this project's scale.

**2. Submit-then-poll API shape (`POST` + `GET`), matching v2's existing UX.**
`POST /v3/links` starts a Step Functions execution asynchronously (`StartExecution`, not `.sync`) and returns `202` immediately; `GET /v3/links/{requestId}` reads current state from DynamoDB. This was chosen over having `POST` block for a synchronous result, so evaluators/tests reuse the exact same interaction pattern already documented for v2, and so a slow or retried pipeline doesn't hold an HTTP connection open.

**3. Three separate Lambda tasks (Validate, Resolve, Persist) instead of one combined function.**
Splitting the pipeline lets each state have its own `Retry`/`Catch` semantics — validation failures are a client input problem (not retryable) while resolution failures are treated as potentially transient (retryable) — and makes each state's role legible in the state machine's graph view, which is part of what a grader would inspect. The trade-off is more Lambda cold starts per request; acceptable for this API's scale and consistent with v2 already being multiple functions per request.

**4. New Lambdas import `src/phone.py` directly; existing v2 handlers are not invoked from the state machine.**
Step Functions Task states send/receive plain JSON, not API Gateway proxy events or SQS `Records[]` envelopes. Pointing a Task directly at `LinksProcessorFunction` or `LinksSubmitFunction` would require those handlers to branch on invocation shape — coupling two independent invocation styles into one handler. Importing the already-AWS-independent `phone.py`/`base62.py` modules into new, purpose-built handlers keeps each handler single-shaped and avoids duplicating any validation/URL-building rule.

**5. Idempotency key doubles as the DynamoDB partition key and the Step Functions execution name.**
`LinksV3StartFunction` accepts an optional `Idempotency-Key` header (falling back to a generated key if absent — the standard HTTP idempotency-key convention, e.g. Stripe's). Using this same value as the execution's `name` param lets Step Functions itself reject/reuse a duplicate submission (`ExecutionAlreadyExists`) instead of the application needing to implement dedup logic from scratch; a conditional `PutItem` (`attribute_not_exists(requestId)`) on the same key gives a second, independent guard at the storage layer in case the two systems ever disagree (e.g., a partially failed prior attempt).

**6. Retry evidence (`attempts`, `lastError`) is persisted in DynamoDB, not only visible via Step Functions execution history.**
`LinksV3ResolveFunction` increments `attempts` via `update_item` on every invocation (whether Step Functions' native `Retry` or a `simulateFailures`-forced failure caused it) and records `lastError` when it fails. This makes retry behavior directly observable through the same `GET /v3/links/{requestId}` polling clients already use, rather than requiring AWS console/CLI access to prove the mechanism worked — directly answering the concern that retry evidence needs to be queryable, not just structurally defined.

**7. `simulateFailures` as an explicit, opt-in test hook.**
Real transient AWS failures are not reliably reproducible on demand. Rather than leave `Retry`/`Catch` blocks unverified, `POST /v3/links` accepts an optional `simulateFailures: N` field, passed through the execution input, that makes `LinksV3ResolveFunction` deliberately fail its first N invocations. This is documented in the README as the sanctioned way to exercise retry/DLQ behavior during evaluation.

**8. Dedicated `LinksV3DLQ`, not the existing `LinksDLQ`.**
v3 is parallel infrastructure; sharing v2's DLQ would mix two independently-versioned pipelines' failed payloads in one place and would require the DLQ's message shape to serve two different consumers. A dedicated queue keeps failure inspection scoped to v3.

**9. `src/links_store.py` extraction, applied to both v2 and v3.**
The v2 handlers already each duplicate the same three-line boto3 `Table(os.environ[...])` + `get_item`/`put_item`/`update_item` pattern independently. Rather than have v3 add a fourth and fifth independent copy, a small shared module (`get_item`, `put_item`, `update_item` wrapping a `boto3.resource("dynamodb").Table(...)` lookup) is extracted and used by both. This is scoped strictly to data-access boilerplate — no request/response contract, validation rule, or table schema for v1/v2 changes. Existing v2 tests continue to assert the same externally observable behavior; only their mocking target moves from `boto3` to `links_store`.

## Risks / Trade-offs

- **[Risk]** Refactoring `links_submit.py`/`links_processor.py`/`links_status.py` could regress already-working v2 behavior. → **Mitigation**: the refactor changes only how each handler talks to DynamoDB, not what it does; existing v2 test assertions (status codes, response bodies, stored item shape) must pass unchanged after the refactor, run before this change is considered complete.
- **[Risk]** `ExecutionAlreadyExists` handling in `LinksV3StartFunction` could mask a genuine naming collision if two different clients happen to pick the same generated key. → **Mitigation**: the generated fallback key uses enough entropy (e.g., a UUID-derived token) that collision odds are negligible; clients that care about strict idempotency are expected to supply their own `Idempotency-Key`.
- **[Risk]** Standard Workflow executions incur a small per-state-transition cost, and `simulateFailures` executions burn extra transitions on purpose. → **Mitigation**: acceptable at course-project scale; not a production cost concern here.
- **[Risk]** A `simulateFailures` value large enough to exceed `MaxAttempts` will route to the DLQ every time, which is the intended behavior for demonstrating dead-lettering — but could be mistaken for a bug if undocumented. → **Mitigation**: documented explicitly in the README with the exact expected outcome for both a within-budget and an exceeds-budget value.
- **[Risk]** Adding a fifth+ Lambda per request increases cold-start latency versus v1/v2. → **Mitigation**: acceptable — v3 is explicitly async (submit-then-poll), so end-to-end latency isn't user-facing the way v1's synchronous response is.

## Migration Plan

1. Add `src/links_store.py` and migrate v2 handlers to it; run the full existing test suite to confirm no behavior change before adding any v3 code.
2. Add the new DynamoDB table, SQS DLQ, five Lambdas, and the Step Functions state machine (`statemachine/links_pipeline.asl.yaml`) to `template.yaml`, plus the two new HTTP routes on the existing `WhatsappHttpApi`.
3. `sam build && sam deploy` — this is an additive stack change; no existing resource is replaced, so no downtime or data migration is required for v1/v2.
4. Verify v1/v2 still work end-to-end post-deploy (per the existing README smoke-test steps), then verify v3 via the new README section.
5. Rollback, if needed, is `sam delete`/reverting the template — since v3 resources are additive and independently named, removing them does not affect v1/v2.

## Open Questions

- None outstanding — all decisions above were validated with the user during brainstorming.
