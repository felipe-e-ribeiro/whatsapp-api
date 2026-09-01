## Why

This is a class project. The goal is to explore an event-driven redesign of
the WhatsApp Link API using SQS, as a learning exercise in decoupling the
write path from the processing path via a queue — not because the current
synchronous API has an operational problem to solve. Full rationale and
architecture are recorded in
`docs/superpowers/specs/2026-08-18-event-driven-v2-design.md`.

## What Changes

- Add a new `v2` API surface that is event-driven: `POST /v2/links` enqueues
  a validation request and returns immediately with a `requestId`; a queue
  consumer performs the actual validation/link-building asynchronously;
  `GET /v2/links/{requestId}` polls for the result.
- Require authentication (`x-api-key` header, checked against a secret in
  AWS Secrets Manager) on every `v2` route.
- Generate `v2` request IDs as a base62-encoded atomic counter seeded at
  516 (first id `"8k"`) — sequential internally, not decimal-looking
  externally.
- **BREAKING**: move the existing endpoint from `GET /{number}` to
  `GET /v1/{number}`. Behavior, response shape, and lack of authentication
  are otherwise unchanged.

## Capabilities

### New Capabilities
- `whatsapp-link-api-v2`: asynchronous, event-driven submission and polling
  of WhatsApp link requests via SQS, with API-key authentication and
  base62 request IDs.

### Modified Capabilities
- `whatsapp-link-api`: the existing synchronous endpoint's path changes
  from `GET /{number}` to `GET /v1/{number}`. Validation logic, response
  shapes, and status codes are unchanged.

## Impact

- **Code**: new modules `src/base62.py`, `src/links_authorizer.py`,
  `src/links_submit.py`, `src/links_processor.py`, `src/links_status.py`.
  `src/handler.py` and `src/phone.py` unchanged (reused as-is by the new
  processor).
- **Infrastructure** (`template.yaml`): new DynamoDB tables (`LinksTable`,
  `LinksCounterTable`), SQS queues (`LinksQueue`, `LinksDLQ`), a Secrets
  Manager secret, four new Lambda functions, new HttpApi routes under
  `/v2/*` with a Lambda authorizer attached, and the existing route
  re-pointed to `/v1/{number}`.
- **Tests**: `moto` added as a dev-only dependency for DynamoDB/SQS/Secrets
  Manager test coverage.
- **Docs**: README gains a "v2 (event-driven)" manual-testing section.
- **Clients**: anyone calling the current `GET /{number}` must switch to
  `GET /v1/{number}` — this is a breaking path change.
