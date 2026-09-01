## Context

See `proposal.md` - Why. Full architecture, data model, and rationale were
already worked out collaboratively and are recorded in
`docs/superpowers/specs/2026-08-18-event-driven-v2-design.md`; this document
summarizes the technical decisions that document contains, scoped to what
`tasks.md` needs.

Current state: `src/handler.py` is a single synchronous Lambda behind
`GET /{number}` (HttpApi), backed by dependency-free pure functions in
`src/phone.py`. Nothing is persisted or queued today.

## Goals / Non-Goals

**Goals:**
- SQS genuinely in the critical path (submit → queue → process → poll), not
  a side-channel, so the exercise demonstrates real decoupling (independent
  scaling, built-in retry, DLQ).
- Zero behavior change to the existing validation logic — v2's processor
  reuses `src/phone.py` unmodified.
- Keep each new Lambda single-purpose and independently testable, matching
  the existing project's style (`handler.py` + pure `phone.py`).

**Non-Goals:**
- True event sourcing (a persisted, replayable event log as source of
  truth) — this is event-*driven*, not event-*sourced*.
- Rate limiting, API key rotation/multi-tenant keys, DLQ alarming/observability.
  Worth a follow-up change, not this one.
- Any change to `v1`'s validation behavior or response shape — only its
  route path moves, to `/v1/{number}`.

## Decisions

**SQS in the critical path, with a submit/poll contract (not a
synchronous bridge).** Considered keeping `v2` synchronous by having the
API Lambda wait on the queue consumer — rejected because SQS isn't built
for request/response and it would fight the tool instead of demonstrating
it. Submit-then-poll is the idiomatic pattern for this kind of decoupling.

**Two DynamoDB tables, not one.** `LinksTable` (request/result records) and
`LinksCounterTable` (a single atomic-counter item) are kept separate so each
table has one clear purpose and one clear owner Lambda relationship, rather
than mixing a hot, frequently-updated counter item into the same table as
per-request records.

**Atomic counter + base62 encoding for request IDs, not UUIDs.** The
counter is a single `UpdateItem` with
`SET #v = if_not_exists(#v, :start) + :incr` (`:start = 515`, `:incr = 1`),
which is atomic under concurrent invocations and needs no pre-seeding step
— the first call yields `516`. Base62 (digits, then `a-z`, then `A-Z`)
encodes that integer into the public `requestId` (`516` → `"8k"`). This was
an explicit requirement (sequential internally, not decimal-looking
externally), not a security control by itself — see Risks below.

**Authentication via Lambda Request Authorizer + Secrets Manager, not API
Gateway's native API Keys/Usage Plans.** The latter stores keys in API
Gateway itself and isn't available the same way on HttpApi; a Lambda
authorizer reading a Secrets Manager value matches the actual requirement
("chave que fica no Secret Manager") and applies uniformly to both `v2`
routes without touching `v1`.

**`v1` untouched except its route path.** Moving it to `/v1/{number}` is a
breaking path change but requires zero code changes — confirms `v2` is
additive, not a rewrite, and gives a clean A/B baseline for the class.

## Risks / Trade-offs

- **[Risk]** Base62-encoded sequential IDs are enumerable (an attacker who
  knows the scheme can walk `8k`, `8l`, `8m`, …). → **Mitigation**: every
  `v2` request, including `GET`, requires a valid API key; enumerability
  without a valid key is not exploitable. A non-enumerable ID scheme is
  explicitly out of scope (see Non-Goals).
- **[Risk]** A processing failure that exhausts SQS retries leaves the
  stored request permanently `pending` with no automatic alerting. →
  **Mitigation**: this is a known, accepted gap for this change (DLQ
  alarming is future work); the DLQ itself still prevents infinite retry
  storms and preserves the failed message for manual redrive.
- **[Trade-off]** Two new DynamoDB tables plus SQS plus Secrets Manager is
  a meaningfully larger infrastructure footprint than the current
  single-Lambda app. Accepted because the point of this change is to
  practice exactly these AWS building blocks.

## Migration Plan

1. Add new infrastructure (tables, queues, secret) and new Lambdas
   alongside the existing function — additive, no deploy-time risk to `v1`.
2. Re-point the existing HttpApi route from `/{number}` to `/v1/{number}`
   (the one breaking change) in the same deploy, since `template.yaml` is
   deployed as a single stack.
3. No data migration needed — the current app has no persisted state.
4. Rollback: `sam deploy` a previous template revision; DynamoDB
   tables/SQS queues from this change can be deleted independently since
   nothing else depends on them yet.
