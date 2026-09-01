## 1. v1 route migration

- [x] 1.1 In `template.yaml`, change `WhatsappLinkFunction`'s event path from `/{number}` to `/v1/{number}` (method and handler unchanged)
- [x] 1.2 Update `tests/test_handler.py` event fixtures/assertions if they encode the path, and update `README.md`'s examples/manual-testing section to use `/v1/...`
- [x] 1.3 Run `pytest` to confirm v1 behavior is otherwise unchanged

## 2. `src/base62.py` (pure module)

- [x] 2.1 Implement `encode(n: int) -> str` using alphabet `0-9a-zA-Z`, matching `516 -> "8k"`
- [x] 2.2 Add `tests/test_base62.py`: `0`, `516`, a value requiring multiple digits, and a negative-input error case

## 3. Infrastructure: storage and messaging (`template.yaml`)

- [x] 3.1 Add `LinksTable` (DynamoDB, PK `requestId` string)
- [x] 3.2 Add `LinksCounterTable` (DynamoDB, PK `counterId` string, single item)
- [x] 3.3 Add `LinksQueue` (SQS) and `LinksDLQ` (SQS) with a redrive policy (`maxReceiveCount: 3`) from `LinksQueue` to `LinksDLQ`
- [x] 3.4 Add `LinksApiKeySecret` (`AWS::SecretsManager::Secret`) with a generated random string value

## 4. `src/links_authorizer.py`

- [x] 4.1 Implement the Lambda Request Authorizer: read the secret value from Secrets Manager (cache across warm invocations), compare to the `x-api-key` header, return an HttpApi v2.0 authorizer response (`isAuthorized`)
- [x] 4.2 Add `tests/test_links_authorizer.py` (mock the Secrets Manager client): matching key, missing header, mismatched key
- [x] 4.3 In `template.yaml`, add `LinksAuthorizerFunction` with a read-only IAM policy scoped to `LinksApiKeySecret`'s ARN, and register it as the HttpApi Lambda authorizer for later use on `/v2/*` routes

## 5. `src/links_submit.py` (`POST /v2/links`)

- [x] 5.1 Validate the request body: `number` present and a string; return 400 otherwise without touching DynamoDB or SQS
- [x] 5.2 Allocate the next `requestId`: atomic `UpdateItem` on `LinksCounterTable` (`SET #v = if_not_exists(#v, :start) + :incr`, start 515) piped through `base62.encode`
- [x] 5.3 `PutItem` into `LinksTable`: `requestId`, `number`, `status: "pending"`, `requestedAt`
- [x] 5.4 `SendMessage` to `LinksQueue` with `{requestId, number}`
- [x] 5.5 Return `202 {"requestId": ..., "status": "pending"}`
- [x] 5.6 Add `tests/test_links_submit.py` (moto for DynamoDB + SQS): valid submission, missing `number`, non-string `number`, first-ever id is `"8k"`, sequential ids differ

## 6. `src/links_processor.py` (SQS consumer)

- [x] 6.1 Parse the SQS record body (`requestId`, `number`)
- [x] 6.2 Run the existing `src/phone.py` pipeline (`normalize`, `strip_country_code`, `is_valid_br_number`, `build_whatsapp_url`) — no changes to `phone.py` itself
- [x] 6.3 `UpdateItem` on `LinksTable`: `status: "completed"`, `result` (URL or `false`), `completedAt`
- [x] 6.4 Add `tests/test_links_processor.py` (moto for DynamoDB): valid number resolves to URL, unrecognized number resolves to `false`, malformed record raises (so SQS retries) instead of silently swallowing the error
- [x] 6.5 In `template.yaml`, add `LinksProcessorFunction` with `DynamoDBCrudPolicy` on `LinksTable` and an SQS event source on `LinksQueue` (`BatchSize: 1`)

## 7. `src/links_status.py` (`GET /v2/links/{requestId}`)

- [x] 7.1 `GetItem` from `LinksTable` by `requestId`; 404 if absent
- [x] 7.2 Return `200` with `status: "pending"` (no `result`) or `status: "completed"` (with `result`)
- [x] 7.3 Add `tests/test_links_status.py` (moto for DynamoDB): pending, completed, not-found

## 8. Wire up `template.yaml` (routes, auth, policies)

- [x] 8.1 Add `LinksSubmitFunction` (`POST /v2/links`) and `LinksStatusFunction` (`GET /v2/links/{requestId}`) HttpApi events, both with `Auth: Authorizer: LinksApiKeyAuthorizer`
- [x] 8.2 Grant `LinksSubmitFunction`: `DynamoDBCrudPolicy` on `LinksTable` and `LinksCounterTable`, `SQSSendMessagePolicy` on `LinksQueue`
- [x] 8.3 Grant `LinksStatusFunction`: read access (`DynamoDBReadPolicy` or equivalent) on `LinksTable`
- [x] 8.4 `sam validate --lint` passes with the full template (had to rename the HttpApi's logical ID off the magic `ServerlessHttpApi` — see comment in `template.yaml`)

## 9. Test dependencies and full suite

- [x] 9.1 Add `moto` to `requirements-dev.txt` (done early, group 4 needed it for the authorizer's tests)
- [x] 9.2 Run the full `pytest` suite (v1 + v2) and confirm the coverage threshold in `pytest.ini` still passes with the new modules included (55 passed, 100% coverage)

## 10. Documentation

- [x] 10.1 Add a "v2 (event-driven)" section to `README.md`: request/response shapes for `POST /v2/links` and `GET /v2/links/{requestId}`, the `x-api-key` requirement, and a manual-testing walkthrough — verified for real against `sam local start-api` (see note below), including invoking `links_processor.lambda_handler` directly with a synthetic SQS record
- [x] 10.2 Update the "Project layout" section in `README.md` to list the new `src/` modules
