# WhatsApp Link API — Event-Driven v2 Design

**Date:** 2026-08-18
**Status:** Approved, pending implementation plan

## Context

The API today (`v1`) is a single synchronous Lambda: `GET /{number}` validates
a Brazilian phone number and returns a `wa.me` deep link (or `false`) in the
same request/response cycle. It's stateless — nothing is persisted, nothing
is queued.

This is a class project (`aula01`). The goal of this change is to explore an
**event-driven** redesign using SQS, as a learning exercise — not because the
current use case demands it. Event *sourcing* (a persisted, replayable log of
events as the source of truth) is explicitly out of scope; this is
event-*driven* architecture: decoupling the write path from the processing
path via a queue.

## Goals

- Introduce a second, versioned API surface (`v2`) where the fila (SQS) sits
  in the critical path: submit → queue → process → poll for result.
- Keep `v1` exactly as it is today — untouched, unauthenticated, synchronous
  — as a baseline to compare against.
- Require authentication on all `v2` endpoints, backed by a secret stored in
  AWS Secrets Manager.
- Generate public request IDs that are sequential internally (no atomic
  counter contention issues, no collision risk) but not visually decimal/
  incremental — base62-encoded, seeded so the first ID isn't `"1"`.

## Non-goals

- True event sourcing (replayable event log as source of truth).
- Rate limiting, API key rotation, or multi-tenant key management.
- Alarming/observability on the DLQ (worth a follow-up, not this change).
- Changing `v1` behavior, contract, or code.

## Architecture

```
v1 (unchanged, unauthenticated)
  GET /v1/{number} → WhatsappLinkFunction (synchronous, same as today)

v2 (new, event-driven, authenticated)
  Every v2 request passes through:
    LinksAuthorizerFunction (API Gateway Lambda Request Authorizer)
      → reads the expected key from Secrets Manager (in-memory cache)
      → compares it against the `x-api-key` request header
      → denies (401) before the business Lambda ever runs, on mismatch

  POST /v2/links ──[auth]──► LinksSubmitFunction
                                ├─ UpdateItem ADD on LinksCounterTable
                                │    (atomic counter, seeded at 516)
                                ├─ base62-encode the counter → requestId
                                ├─ PutItem into LinksTable (status: pending)
                                └─ SendMessage → LinksQueue (SQS)

  LinksQueue ──► LinksProcessorFunction ──► UpdateItem on LinksTable
                                              (status: completed, result)
                    │ (after maxReceiveCount retries)
                    ▼
                 LinksDLQ

  GET /v2/links/{requestId} ──[auth]──► LinksStatusFunction → reads LinksTable
```

## Components

| File | Responsibility | AWS trigger |
|---|---|---|
| `src/handler.py` | v1 handler (unchanged) | HttpApi `GET /v1/{number}` |
| `src/phone.py` | Phone validation/formatting (unchanged, reused by v2's processor) | — (pure functions) |
| `src/base62.py` | Pure function: non-negative int → base62 string. New, unit-testable in isolation, same style as `phone.py`. | — (pure functions) |
| `src/links_authorizer.py` | Reads the API key secret from Secrets Manager (cached across warm invocations), compares to `x-api-key` header. | HttpApi Lambda Request Authorizer, attached only to `/v2/*` routes |
| `src/links_submit.py` | Validates request body shape, allocates the next id (`LinksCounterTable`), writes the initial `pending` record (`LinksTable`), enqueues the processing message (`LinksQueue`). | HttpApi `POST /v2/links` |
| `src/links_processor.py` | Consumes queue messages, runs the same validation/link-building logic as v1 (via `phone.py`), writes the final result to `LinksTable`. | SQS event source on `LinksQueue` (batch size 1) |
| `src/links_status.py` | Reads a record from `LinksTable` by `requestId`. | HttpApi `GET /v2/links/{requestId}` |

Each new Lambda has one job and one AWS dependency it talks to directly
(Secrets Manager, DynamoDB, or SQS) — no component reaches into another
component's storage.

## Data model

**`LinksTable`** (DynamoDB, PK: `requestId` string)

| Attribute | Type | Notes |
|---|---|---|
| `requestId` | S | Base62 string, e.g. `"8k"` |
| `number` | S | Raw input as submitted |
| `status` | S | `"pending"` \| `"completed"` |
| `result` | S \| BOOL | Only present once `completed` — the `wa.me` URL, or `false` |
| `requestedAt` | S (ISO 8601) | Set by `links_submit` |
| `completedAt` | S (ISO 8601) | Set by `links_processor`, only once completed |

**`LinksCounterTable`** (DynamoDB, PK: fixed literal, e.g. `"GLOBAL"`)

A single-item table dedicated to the atomic counter, kept separate from
`LinksTable` so each table has one clear purpose.

| Attribute | Type | Notes |
|---|---|---|
| `counterId` | S | Always `"GLOBAL"` |
| `value` | N | Current counter value |

Allocating an id is one atomic `UpdateItem`:

```
UpdateExpression: "SET #v = if_not_exists(#v, :start) + :incr"
ExpressionAttributeValues: { ":start": 515, ":incr": 1 }
ReturnValues: UPDATED_NEW
```

First call: attribute doesn't exist yet → `if_not_exists` yields `515`, `+1`
→ **516**. Every subsequent call increments from the stored value. No
pre-seeding step needed, and it's safe under concurrent invocations because
DynamoDB's `ADD`/arithmetic `UpdateItem` is atomic.

## ID generation (`src/base62.py`)

- Alphabet: `0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ`
  (digits, then lowercase, then uppercase — 62 symbols).
- `requestId = base62_encode(counter_value)`.
- Seed of 516 → first id is `"8k"`.
- IDs are still enumerable in principle (an attacker who knows the scheme
  could walk `"8k"`, `"8l"`, `"8m"`, …) — this is accepted because every
  `v2` request, including `GET`, requires a valid `x-api-key`. Rate limiting
  or a non-enumerable scheme is out of scope for this change (see
  Non-goals).

## Authentication

- A secret (a single opaque string, the API key) lives in **AWS Secrets
  Manager**, created as a `AWS::SecretsManager::Secret` resource in
  `template.yaml` with a generated random value.
- `LinksAuthorizerFunction` is registered as an HttpApi **Lambda Request
  Authorizer** on both `/v2/links` (POST) and `/v2/links/{requestId}` (GET).
  It is not attached to the `/v1/{number}` route.
- On each (cold) invocation it fetches the secret value and caches it in
  memory for the life of the execution environment, to avoid a Secrets
  Manager call on every request.
- Request must include header `x-api-key: <value>`. Missing or mismatched
  key → authorizer denies → API Gateway returns `401`.
- IAM: `LinksAuthorizerFunction` gets read-only access scoped to that one
  secret's ARN (not a wildcard `SecretsManagerReadWrite`).

## Data flow (happy path)

1. Client: `POST /v2/links` with header `x-api-key: <key>` and body
   `{"number": "11987654321"}`.
2. Authorizer validates the key; request proceeds.
3. `LinksSubmitFunction`:
   - Validates the body shape only (`number` present and a string) — it does
     **not** validate the phone number itself here.
   - Allocates `requestId` from `LinksCounterTable`.
   - Writes `{requestId, number, status: "pending", requestedAt}` to
     `LinksTable`.
   - Sends `{requestId, number}` to `LinksQueue`.
   - Responds `202 {"requestId": "8k", "status": "pending"}`.
4. `LinksQueue` triggers `LinksProcessorFunction`, which runs the same
   validation/formatting logic as `v1` (via `phone.py`) and updates the
   `LinksTable` record: `status: "completed"`, `result: <url|false>`,
   `completedAt`.
5. Client polls `GET /v2/links/8k` (with `x-api-key`) until `status` flips
   from `"pending"` to `"completed"`, then reads `result`.

## Error handling

| Case | Behavior |
|---|---|
| Missing/incorrect `x-api-key` on any `v2` route | `401`, request never reaches the business Lambda |
| `POST /v2/links` body missing `number` or not a string | `400`, nothing written, nothing enqueued |
| Number doesn't resolve to a valid BR number | **Not an error** — same semantics as `v1`: `status: "completed"`, `result: false` |
| Transient/bug failure inside `LinksProcessorFunction` | Exception → SQS redelivers up to `maxReceiveCount` (3) → then the message moves to `LinksDLQ`; the `LinksTable` record stays `"pending"` until someone inspects/redrives the DLQ (alarming is future work) |
| `GET /v2/links/{requestId}` for an id that doesn't exist | `404` |

## Testing

- `src/base62.py`, `src/links_submit.py`, `src/links_status.py`,
  `src/links_authorizer.py`: unit tests calling `lambda_handler` directly
  with synthetic events, same style as today's `test_handler.py`.
- `src/links_processor.py`: reuses `phone.py`'s existing coverage for the
  validation logic; adds tests for SQS record parsing and the DynamoDB
  update call.
- **`moto`** is added as a dev-only dependency (`requirements-dev.txt`) to
  back higher-fidelity tests against an in-memory DynamoDB/SQS/Secrets
  Manager instead of mocking every boto3 call by hand. Doesn't touch
  runtime/production dependencies.
- README gets a new "v2 (event-driven)" manual-testing section: how to hit
  `POST`/`GET /v2/links` locally (`sam local start-api`, with the
  `x-api-key` header), and how to invoke `links_processor.lambda_handler`
  directly with a synthetic SQS event record, without a real queue.

## Infrastructure additions (`template.yaml`)

- `LinksTable`, `LinksCounterTable` (DynamoDB).
- `LinksQueue`, `LinksDLQ` (SQS, redrive policy `maxReceiveCount: 3`).
- `LinksApiKeySecret` (Secrets Manager).
- `LinksAuthorizerFunction`, `LinksSubmitFunction`, `LinksProcessorFunction`,
  `LinksStatusFunction`, each with least-privilege SAM policy templates
  (`DynamoDBCrudPolicy`, `SQSSendMessagePolicy`/`SQSPollerPolicy`, a scoped
  Secrets Manager read policy).
- HttpApi routes: `/v2/links` (POST), `/v2/links/{requestId}` (GET), both
  with `Auth: Authorizer: LinksApiKeyAuthorizer`.
- Existing route changes from `/{number}` to `/v1/{number}` (no code change,
  just the path).
