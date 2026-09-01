## 1. Project scaffolding

- [x] 1.1 Create `src/` and `tests/` directories with `__init__.py` as needed
- [x] 1.2 Add `requirements.txt` (runtime — empty or stdlib-only) and `requirements-dev.txt` (`pytest`, `pytest-cov`)
- [x] 1.3 Add `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]`) configuring `--cov=src --cov-report=term-missing --cov-fail-under=90`

## 2. Core validation logic (`src/phone.py`)

- [x] 2.1 Implement `normalize(raw: str) -> str` — strips all non-digit characters
- [x] 2.2 Implement `is_valid_br_number(digits: str) -> bool` — DDD 11–99, length 10 (landline) or 11 with 9-prefix (mobile)
- [x] 2.3 Implement `build_whatsapp_url(digits: str) -> str` — returns `https://wa.me/55<digits>`

## 3. Lambda handler (`src/handler.py`)

- [x] 3.1 Implement `lambda_handler(event, context)` — reads `event.get("pathParameters") or {}`, gets `number`
- [x] 3.2 Wire normalize → validate → build URL, returning `{"statusCode": 200, "body": json.dumps({"result": <url or false>})}`
- [x] 3.3 Ensure missing/empty `pathParameters` or `number` is handled without raising, resolving to `{"result": false}`

## 4. Tests (`tests/`)

- [x] 4.1 `test_phone.py`: valid mobile number (11 digits, 9-prefix)
- [x] 4.2 `test_phone.py`: valid landline number (10 digits)
- [x] 4.3 `test_phone.py`: DDD below 11 and above 99 (out of range)
- [x] 4.4 `test_phone.py`: wrong digit counts (too short, too long)
- [x] 4.5 `test_phone.py`: 11-digit number missing the mobile 9-prefix
- [x] 4.6 `test_phone.py`: empty string and non-numeric junk input
- [x] 4.7 `test_phone.py`: `normalize` strips punctuation/spaces (e.g. `"(11) 98765-4321"`)
- [x] 4.8 `test_phone.py`: `build_whatsapp_url` produces the exact expected URL string
- [x] 4.9 `test_handler.py`: valid number event → 200 + `{"result": "https://wa.me/55..."}`
- [x] 4.10 `test_handler.py`: invalid number event → 200 + `{"result": false}`
- [x] 4.11 `test_handler.py`: event with missing `pathParameters` key entirely → 200 + `{"result": false}`
- [x] 4.12 Run `pytest --cov=src --cov-report=term-missing` and confirm ≥90% coverage; add tests for any uncovered branch (achieved 100%)

## 5. Infrastructure (`template.yaml`)

- [x] 5.1 Define `AWS::Serverless::Function` pointing at `src/handler.lambda_handler`, Python runtime
- [x] 5.2 Add HTTP API event source mapped to `GET /{number}`
- [x] 5.3 Validate template locally with `sam validate` (`sam validate` and `sam validate --lint` both pass)

## 6. Documentation

- [x] 6.1 Add a short `README.md` covering: what the API does, example request/response, how to run tests locally (`pytest`), how to deploy (`sam build && sam deploy --guided`)
