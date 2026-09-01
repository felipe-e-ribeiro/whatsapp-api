## Why

We need a way to turn a Brazilian phone number into a clickable WhatsApp Web link (`https://wa.me/55<DDD><number>`) without hardcoding or manually formatting the URL each time. A tiny serverless API is the cheapest way to expose this as a reusable service, with no server to manage.

## What Changes

- New public HTTP endpoint `GET /{number}` that accepts a Brazilian DDD + phone number (digits only, no `55` country code) as a path parameter.
- Validates the number (DDD range 11–99; 10 digits total for landline, 11 digits total for mobile with a `9` immediately after the DDD).
- Returns `200 {"result": "https://wa.me/55<digits>"}` when valid.
- Returns `200 {"result": false}` when the number is malformed, wrong length, missing, or not recognized as Brazilian — never a 4xx/5xx for bad input.
- Deployed as a single AWS Lambda function behind API Gateway (HTTP API), packaged and deployed via AWS SAM.
- Automated test suite (pytest) covering validation logic and the Lambda handler, enforced at a minimum 90% coverage gate in CI/local runs.

## Capabilities

### New Capabilities
- `whatsapp-link-api`: Validates a Brazilian phone number supplied via a path parameter and returns the corresponding `wa.me` deep link, or `false` if the number isn't recognized.

### Modified Capabilities
(none — greenfield project, no existing specs)

## Impact

- New code: `src/phone.py` (pure validation/formatting logic), `src/handler.py` (Lambda entry point), `template.yaml` (SAM infrastructure), `tests/` (pytest suite), `requirements.txt`/`requirements-dev.txt`, pytest/coverage config.
- New AWS resources on deploy: one Lambda function, one API Gateway HTTP API with a `GET /{number}` route.
- No dependencies on other services, databases, or existing code — this is the first capability in the project.
