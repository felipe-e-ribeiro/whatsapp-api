# WhatsApp Link API

A tiny AWS Lambda API that turns a Brazilian phone number into a WhatsApp
Web deep link.

## What it does

`GET /{number}`, where `{number}` is a Brazilian DDD (area code) + local
number, with no country code (formatting characters like spaces,
parentheses, and dashes are ignored).

- If the number is recognized (DDD 11–99, 10 digits total for a landline
  or 11 digits total for a mobile number starting with `9` after the
  DDD), the response is:

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

### Examples

```
GET /11987654321        -> {"result": "https://wa.me/5511987654321"}
GET /1133334444         -> {"result": "https://wa.me/551133334444"}
GET /(11) 98765-4321    -> {"result": "https://wa.me/5511987654321"}
GET /123                -> {"result": false}
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
