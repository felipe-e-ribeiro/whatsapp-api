## Context

Greenfield project (no existing code, no existing specs). See proposal.md for motivation. Key constraint from the user: the codebase must be built test-first/test-friendly, with pytest coverage enforced at a minimum of 90%.

## Goals / Non-Goals

**Goals:**
- Keep the Lambda handler thin; put all validation/formatting logic in plain, dependency-free Python functions that pytest can exercise without mocking AWS.
- Deployable end-to-end with AWS SAM (`sam build && sam deploy`) with no manual console steps.
- Hit ≥90% branch/line coverage without artificial tests — the logic is simple enough that real behavioral tests should get there naturally.

**Non-Goals:**
- No persistence, auth, rate limiting, or logging infrastructure — this is a single stateless lookup/formatting endpoint.
- No support for non-Brazilian numbers or country codes other than `55`.
- No validation against the real, current list of assigned Brazilian DDDs (e.g. rejecting DDDs that are numerically in range 11–99 but not actually assigned) — range + length + mobile-prefix checks only, per the approved design.

## Decisions

- **Pure-function core + thin handler**: `src/phone.py` holds `normalize`, `is_valid_br_number`, `build_whatsapp_url` with zero AWS/library dependencies. `src/handler.py` only extracts the path parameter and shapes the HTTP response. Rationale: lets `tests/test_phone.py` cover all validation branches with plain unit tests, and keeps `tests/test_handler.py` limited to wiring/shape checks — straightforward path to 90% coverage. Alternative considered: putting validation inline in the handler — rejected because it forces every test through a fake API Gateway event and conflates two concerns.
- **Always HTTP 200**: Both success and "not recognized" cases return status 200, differing only in the JSON `result` value (URL string vs. `false`). Rationale: matches the user's explicit requirement ("just return false") and keeps the API trivial for a client to consume (always parse JSON, check `result`). Alternative considered: 400 for invalid input — rejected as contrary to the stated requirement.
- **AWS SAM for infra**: One `AWS::Serverless::Function` with an HTTP API event source (`GET /{number}`) in `template.yaml`. Rationale: minimal IaC for a single function, standard tool for this shape of project, no extra language/runtime needed beyond Python. Alternative considered: Serverless Framework (extra Node.js toolchain dependency) and CDK (more code for equivalent result) — both rejected as unnecessary overhead for one route.
- **No mocking library needed**: Since the handler never calls an AWS SDK, tests construct plain dict fixtures for `event` and assert on the returned dict — no `moto`/`boto3` test dependency.

## Risks / Trade-offs

- [Risk] DDD range check (11–99) accepts some DDDs that don't actually exist (e.g. 20, 23, 25) → Mitigation: explicitly a non-goal per approved design; acceptable because the endpoint's purpose is link formatting, not carrier-grade validation. Can be tightened later by adding a real DDD allowlist to `is_valid_br_number` without changing its signature or the spec's observable contract for in-range/out-of-range cases already covered.
- [Risk] Always-200 responses make client-side error handling reliant on body inspection rather than HTTP status → Mitigation: documented explicitly in the spec so consumers know to check `result` rather than status code.

## Migration Plan

Net-new capability, no existing deployment to migrate. Deploy steps: `sam build`, `sam deploy --guided` (first time) to create the stack; subsequent deploys use the saved config. Rollback: `sam deploy` a previous template version, or delete the CloudFormation stack (`sam delete`) since there is no persistent state to preserve.
