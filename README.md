# WhatsApp Link API

[![CD](https://github.com/felipe-e-ribeiro/whatsapp-api/actions/workflows/cd.yml/badge.svg)](https://github.com/felipe-e-ribeiro/whatsapp-api/actions/workflows/cd.yml)
[![CloudFormation](https://img.shields.io/badge/CloudFormation-OK-brightgreen)](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks?filteringText=whatsapp-api)

A tiny AWS Lambda API that turns a Brazilian phone number into a WhatsApp
Web deep link.

## What it does

`GET /{number}`, where `{number}` is a Brazilian DDD (area code) + local
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
GET /11987654321          -> {"result": "https://wa.me/5511987654321"}
GET /1133334444           -> {"result": "https://wa.me/551133334444"}
GET /(11) 98765-4321      -> {"result": "https://wa.me/5511987654321"}
GET /11 0000-0000         -> {"result": "https://wa.me/551100000000"}
GET /+55 11 0000-0000     -> {"result": "https://wa.me/551100000000"}
GET /5511987654321        -> {"result": "https://wa.me/5511987654321"}
GET /123                  -> {"result": false}
```

## Project layout

```
src/
  handler.py   # Lambda entry point
  phone.py     # pure validation/formatting logic (no AWS deps)
tests/
  test_handler.py
  test_phone.py
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

