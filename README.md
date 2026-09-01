# WhatsApp Link API

[![CD](https://github.com/felipe-e-ribeiro/whatsapp-api/actions/workflows/cd.yml/badge.svg)](https://github.com/felipe-e-ribeiro/whatsapp-api/actions/workflows/cd.yml)
[![CloudFormation](https://img.shields.io/badge/CloudFormation-UPDATE__ROLLBACK__COMPLETE-red)](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks?filteringText=whatsapp-api)

A tiny AWS Lambda API that turns a Brazilian phone number into a WhatsApp
Web deep link.

## What it does

### v1 (synchronous)

`GET /v1/{number}`, where `{number}` is a Brazilian DDD (area code) + local
number, with an **optional** `+55`/`55` country code (formatting
characters like spaces, parentheses, `+`, and dashes are ignored).

- If the country code (`55`) isn't provided, it's assumed automatically
  — Brazil is the default.
- If the country code **is** provided, it's recognized and stripped
  before validation, so `+55 11 0000-0000` and `11 0000-0000` resolve to
  the same number.
- If the number is recognized (DDD 11–99, 10 digits total for a landline
  or 11 digits total for a mobile number starting with `9` after the
  DDD, once any country code is removed), the response is:

  ```json
  { "result": "https://wa.me/5511987654321" }
  ```

- If the number isn't recognized (wrong length, bad DDD, missing, or
  non-numeric), the response is:

  ```json
  { "result": false }
  ```

The endpoint always responds with HTTP 200 — check the `result` field to
tell success from failure.

> **Note:** DDD `55` (Santa Maria/RS) is itself a valid Brazilian area
> code. The country code is only stripped when the total digit count
> matches a country-code-prefixed number (12 digits for a landline, 13
> for a mobile) — a bare `55 9876-5432` (DDD 55, no country code) is 10
> or 11 digits and is left untouched.

### Examples

```
GET /v1/11987654321          -> {"result": "https://wa.me/5511987654321"}
GET /v1/1133334444           -> {"result": "https://wa.me/551133334444"}
GET /v1/(11) 98765-4321      -> {"result": "https://wa.me/5511987654321"}
GET /v1/11 0000-0000         -> {"result": "https://wa.me/551100000000"}
GET /v1/+55 11 0000-0000     -> {"result": "https://wa.me/551100000000"}
GET /v1/5511987654321        -> {"result": "https://wa.me/5511987654321"}
GET /v1/123                  -> {"result": false}
```

### v2 (event-driven)

An asynchronous, authenticated version of the same lookup, built to
exercise an event-driven pattern with SQS in the critical path instead of
resolving the number inline. Every `v2` request requires an `x-api-key`
header — see [Authentication](#authentication).

**`POST /v2/links`** accepts the number, queues it for processing, and
replies immediately — it does **not** validate the number itself yet:

```
POST /v2/links
x-api-key: <key>
Content-Type: application/json

{"number": "11987654321"}
```
```json
202 {"requestId": "8k", "status": "pending"}
```

**`GET /v2/links/{requestId}`** polls for the result:

```
GET /v2/links/8k
x-api-key: <key>
```
```json
200 {"requestId": "8k", "status": "pending"}
```
```json
200 {"requestId": "8k", "status": "completed", "result": "https://wa.me/5511987654321"}
```

An unknown `requestId` returns `404`. A missing/incorrect `x-api-key`
returns `403` (the standard HttpApi response for a Lambda authorizer
denial) on either endpoint. `requestId`s are assigned from a shared
counter, base62-encoded (`0-9`, `a-z`, `A-Z`) — the very first one ever
issued is `8k` (516 in base62) — so they're sequential internally but
don't read as a plain decimal counter externally.

#### Authentication

Every `v2` route is protected by a Lambda authorizer that checks the
`x-api-key` header against a secret stored in AWS Secrets Manager
(`LinksApiKeySecret` in `template.yaml`, auto-generated on deploy). Fetch
the value to use it:

```bash
aws secretsmanager get-secret-value \
  --secret-id <LinksApiKeySecret ARN or name> \
  --query SecretString --output text | python3 -c "import json,sys; print(json.load(sys.stdin)['apiKey'])"
```

### v3 (orchestrated)

Checkpoint 3: the same number-resolution problem, now driven by an
explicit, structured **orchestration** instead of choreography — an
**AWS Step Functions** state machine (the AWS-native equivalent of Google
Cloud Workflows) that calls a chain of small Lambdas in order, retries
transient failures with backoff, and routes exhausted failures to a
dead-letter queue. `v3` is entirely parallel to `v1`/`v2`: separate
Lambdas, separate DynamoDB table, separate DLQ — nothing here changes
`v1`/`v2` behavior. It reuses the same `x-api-key` authentication as `v2`
(see [Authentication](#authentication)).

**`POST /v3/links`** accepts the number and starts an orchestrated
pipeline execution, replying immediately without waiting for it to
finish:

```
POST /v3/links
x-api-key: <key>
Content-Type: application/json

{"number": "11987654321"}
```
```json
202 {"requestId": "a1b2c3d4e5f6...", "status": "pending"}
```

**`GET /v3/links/{requestId}`** polls for the result, same shape as `v2`
plus retry evidence (`attempts`, and `lastError` if a failure occurred):

```json
200 {"requestId": "a1b2c3d4e5f6...", "status": "pending"}
```
```json
200 {"requestId": "a1b2c3d4e5f6...", "status": "completed", "result": "https://wa.me/5511987654321", "attempts": 1}
```

An invalid number (fails the same validation `v1`/`v2` use) resolves to
`{"status": "invalid"}` rather than being retried — a bad input isn't a
transient failure. A `requestId` that never completes retrying resolves to
`{"status": "failed", "attempts": <n>, "lastError": <message>}`, and its
payload is on the dead-letter queue.

#### Pipeline

The orchestration is defined in one place — `statemachine/links_pipeline.asl.yaml`
(Amazon States Language, YAML) — as three ordered steps:

```
Validate  ->  Resolve  ->  Persist
```

- **Validate** (`src/links_v3_validate.py`) normalizes and validates the
  number, reusing the exact same rules as `v1`/`v2` (`src/phone.py`). An
  invalid number routes straight to `Persist` with `status: invalid`,
  skipping `Resolve` entirely — validation failures aren't retried.
- **Resolve** (`src/links_v3_resolve.py`) builds the `wa.me` link. This is
  the step with a `Retry` policy (exponential backoff, up to 3 retries)
  and a `Catch` that routes exhausted failures to the dead-letter queue.
- **Persist** (`src/links_v3_persist.py`) writes the final outcome
  (`completed`, `invalid`, or `failed`) to DynamoDB.

#### Idempotency

Submitting the same request twice doesn't start two pipeline runs.
Supply an `Idempotency-Key` header with your own stable value:

```bash
curl -i -X POST "$API_DOMAIN/v3/links" \
  -H "x-api-key: $API_KEY" \
  -H "Idempotency-Key: my-stable-key-123" \
  -H "Content-Type: application/json" \
  -d '{"number": "11987654321"}'
```

Resubmitting with the same `Idempotency-Key` returns the same
`requestId` and does not start a second execution — Step Functions
itself rejects a duplicate execution name, and `links_v3_start.py` treats
that rejection as a successful (idempotent) response rather than an
error. If you don't supply the header, a new key is generated for you
each time (no dedup guarantee in that case — the usual HTTP
idempotency-key convention).

#### Demonstrating retry and the dead-letter queue

Real transient AWS failures aren't reproducible on demand, so `Resolve`
accepts an optional `simulateFailures` field, passed straight through in
the request body, purely to exercise the `Retry`/`Catch` mechanism:

```bash
# Fails twice, then succeeds on the 3rd attempt (within the configured
# MaxAttempts: 3) — ends up "completed", with "attempts": 3.
curl -i -X POST "$API_DOMAIN/v3/links" \
  -H "x-api-key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"number": "11987654321", "simulateFailures": 2}'

# Fails more times than the retry budget allows — ends up "failed",
# and the request's payload lands on LinksV3DLQ.
curl -i -X POST "$API_DOMAIN/v3/links" \
  -H "x-api-key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"number": "11987654321", "simulateFailures": 99}'
```

Poll `GET /v3/links/{requestId}` afterward — `attempts` and (when
applicable) `lastError` are stored on the record itself, so the retry
evidence is visible without needing AWS console/CLI access.

To inspect it from the AWS side instead (useful for a deeper look):

```bash
# See every retry attempt in the execution's history:
aws stepfunctions get-execution-history --execution-arn <execution ARN>

# See the message that landed on the dead-letter queue after exhausted retries:
aws sqs receive-message --queue-url <LinksV3DLQ URL>
```

(The execution ARN and DLQ URL are stack outputs/resource identifiers —
not published in this repo; use your own deployed stack's values.)

## Project layout

```
src/
  handler.py            # v1 Lambda entry point
  phone.py              # pure validation/formatting logic (no AWS deps), shared by v1/v2/v3
  base62.py             # pure base62 encoding, used for v2 request IDs
  links_store.py        # shared DynamoDB access helpers, used by v2 and v3
  links_authorizer.py   # v2/v3 Lambda authorizer (x-api-key vs. Secrets Manager)
  links_submit.py       # v2: POST /v2/links — queues a request
  links_processor.py    # v2: SQS consumer — resolves the number, stores the result
  links_status.py       # v2: GET /v2/links/{requestId} — polls for the result
  links_v3_start.py     # v3: POST /v3/links — starts an orchestrated pipeline execution
  links_v3_validate.py  # v3: Step Functions task — validates/normalizes the number
  links_v3_resolve.py   # v3: Step Functions task — resolves the number to a wa.me link
  links_v3_persist.py   # v3: Step Functions task — writes the final outcome
  links_v3_status.py    # v3: GET /v3/links/{requestId} — polls for the result
statemachine/
  links_pipeline.asl.yaml  # v3: Step Functions state machine definition (Amazon States Language)
tests/
  test_handler.py
  test_phone.py
  test_base62.py
  test_links_store.py
  test_links_authorizer.py
  test_links_submit.py
  test_links_processor.py
  test_links_status.py
  test_links_v3_start.py
  test_links_v3_validate.py
  test_links_v3_resolve.py
  test_links_v3_persist.py
  test_links_v3_status.py
template.yaml  # AWS SAM infrastructure definition
```

## Running tests locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Coverage is enforced at a minimum of 90% (configured in `pytest.ini`);
the suite currently achieves 100%.

`tests/test_phone.py::TestStripCountryCode` covers the `+55`/`55`
country-code handling described above (with and without the code, and
the bare-DDD-55 edge case), and
`tests/test_handler.py::TestLambdaHandler::test_number_with_explicit_country_code_is_accepted`
/ `test_number_without_country_code_defaults_to_br` cover it end-to-end
through the handler.

## Testing manually

### v1

No AWS/SAM setup needed — the handler is a plain Python function, so you
can call it directly from a REPL or a one-liner to poke at the code
without running the full test suite.

```bash
python3 -c "
from src.handler import lambda_handler

event = {'pathParameters': {'number': '11987654321'}}
print(lambda_handler(event, None))
"
# {'statusCode': 200, 'body': '{\"result\": \"https://wa.me/5511987654321\"}'}
```

Swap `number` for any of the [examples](#examples) above (or an invalid
one) to check the behavior by hand. `src/phone.py` also exposes the
individual validation/formatting functions (`normalize`,
`strip_country_code`, `is_valid_br_number`, `build_whatsapp_url`) if you
want to exercise just one piece of the logic:

```bash
python3 -c "
from src.phone import normalize, strip_country_code, is_valid_br_number

digits = strip_country_code(normalize('+55 11 98765-4321'))
print(digits, is_valid_br_number(digits))
"
```

### v2

Unlike v1, v2's Lambdas talk to real AWS resources (DynamoDB, SQS,
Secrets Manager) — there's no dependency-free way to exercise the full
flow without them. `sam build && sam local start-api` runs the Lambda
*code* locally, but it still calls the real deployed DynamoDB
tables/queue/secret over the network (via your local AWS
credentials/region), and it **does** genuinely invoke
`LinksAuthorizerFunction` for every request — SAM CLI prints a warning
that local authorizer behavior isn't guaranteed to match AWS exactly, but
in practice it calls Secrets Manager for real. So testing v2 requires the
stack to be deployed at least once (`sam deploy`; see
[Deploying](#deploying)):

```bash
sam build
sam local start-api
```

Fetch the real key (see [Authentication](#authentication)) and submit a
request:

```bash
curl -i -X POST http://127.0.0.1:3000/v2/links \
  -H "x-api-key: <key from Secrets Manager>" \
  -H "Content-Type: application/json" \
  -d '{"number": "11987654321"}'
# 202 {"requestId": "8k", "status": "pending"}

curl -i http://127.0.0.1:3000/v2/links/8k -H "x-api-key: <key>"
# 200 {"requestId": "8k", "status": "pending"}   -- immediately after
# 200 {"requestId": "8k", "status": "completed", "result": "..."}  -- once processed
```

A missing/wrong key returns `403` before your code ever runs:

```bash
curl -i http://127.0.0.1:3000/v2/links/8k -H "x-api-key: wrong"
# 403 {"message":"User is not authorized to access this resource"}
```

Once the stack is deployed, the real `LinksProcessorFunction` in AWS
drains the queue automatically within seconds — no manual step needed,
even while you're driving `sam local start-api` against the same backing
resources. The one case where you *do* want a manual trigger is iterating
on `links_processor.py` itself: invoke it locally with a synthetic SQS
record to test a code change before redeploying it, without needing to
send a whole request through `POST /v2/links` first:

```bash
LINKS_TABLE_NAME=<deployed LinksTable name> python3 -c "
import json
from src.links_processor import lambda_handler

event = {'Records': [{'body': json.dumps({'requestId': '8k', 'number': '11987654321'})}]}
lambda_handler(event, None)
"
```

### Smoke-testing the deployed API

Once the stack is deployed (see [Deploying](#deploying)), the fastest way to
confirm everything is wired correctly end-to-end — API Gateway, both custom
domain and default `execute-api` URL, the Lambda authorizer, DynamoDB, and
SQS — is to hit the real deployed endpoint directly with `curl`, rather than
`sam local start-api`.

Resolve the domain the same way `template.yaml` does — from the SSM
parameter — instead of hardcoding it:

```bash
API_DOMAIN=$(aws ssm get-parameter \
  --name /infra/route53/domain_whatsapp-api \
  --query Parameter.Value --output text)
```

#### v1

No auth required:

```bash
curl -i "https://$API_DOMAIN/v1/11987654321"
# 200 {"result": "https://wa.me/5511987654321"}
```

#### v2

Fetch the real key too (see [Authentication](#authentication) —
never hardcode it):

```bash
API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id <LinksApiKeySecret ARN or name> \
  --query SecretString --output text | python3 -c "import json,sys; print(json.load(sys.stdin)['apiKey'])")
```

Submit a number and capture the `requestId` from the response:

```bash
curl -i -X POST "https://$API_DOMAIN/v2/links" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"number": "11987654321"}'
# 202 {"requestId": "8k", "status": "pending"}
```

Poll for the result (the processor drains the queue within seconds, no
manual step needed):

```bash
curl -i "https://$API_DOMAIN/v2/links/8k" \
  -H "x-api-key: $API_KEY"
# 200 {"requestId": "8k", "status": "pending"}     -- immediately after
# 200 {"requestId": "8k", "status": "completed", "result": "https://wa.me/5511987654321"}  -- once processed
```

A missing/wrong key returns `403` before your code ever runs:

```bash
curl -i "https://$API_DOMAIN/v2/links/8k" -H "x-api-key: wrong"
# 403 {"message":"User is not authorized to access this resource"}
```

## Deploying

Requires the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).

```bash
sam build
sam deploy --guided   # first deploy; creates a saved config for future deploys
```

Subsequent deploys can just run `sam build && sam deploy`.

To tear down the stack:

```bash
sam delete
```

