## Purpose

Provides an authenticated, asynchronous, event-driven way to resolve a Brazilian phone number to a WhatsApp deep link: a request is submitted and queued, processed independently, and its result retrieved later by polling.

## ADDED Requirements

### Requirement: Authenticate all v2 requests
The system SHALL require a valid API key on every `v2` request, supplied via the `x-api-key` header, checked against a secret value stored in AWS Secrets Manager. A request with a missing or incorrect key SHALL be rejected with HTTP 403 (the standard API Gateway HttpApi response for a Lambda authorizer denial) before any business logic (submission, processing, or status lookup) runs.

#### Scenario: Missing API key on submit
- **WHEN** a `POST /v2/links` request is made without an `x-api-key` header
- **THEN** the response is HTTP 403 and no request is queued or stored

#### Scenario: Incorrect API key on status lookup
- **WHEN** a `GET /v2/links/{requestId}` request is made with an `x-api-key` header that does not match the stored secret
- **THEN** the response is HTTP 403

#### Scenario: Valid API key is accepted
- **WHEN** a request to any `v2` endpoint includes an `x-api-key` header matching the stored secret
- **THEN** the request proceeds to its normal handling

### Requirement: Submit a link request for asynchronous processing
The system SHALL accept `POST /v2/links` with a JSON body containing a `number` field (string). On a syntactically valid body, the system SHALL assign a new request ID, record the request with status `pending`, queue it for processing, and respond with HTTP 202 and a JSON body `{"requestId": "<id>", "status": "pending"}`. The submission step SHALL NOT itself determine whether the number is a recognizable Brazilian phone number — that determination happens during asynchronous processing.

#### Scenario: Valid submission is accepted
- **WHEN** `POST /v2/links` is made with a valid API key and body `{"number": "11987654321"}`
- **THEN** the response is HTTP 202 with a JSON body containing `requestId` and `"status": "pending"`

#### Scenario: Missing number field is rejected
- **WHEN** `POST /v2/links` is made with a valid API key and a body without a `number` field
- **THEN** the response is HTTP 400 and no request is queued or stored

#### Scenario: Non-string number field is rejected
- **WHEN** `POST /v2/links` is made with a valid API key and a body where `number` is not a string
- **THEN** the response is HTTP 400 and no request is queued or stored

### Requirement: Assign non-decimal-looking, collision-free request IDs
The system SHALL generate each request ID by base62-encoding (alphabet `0-9`, `a-z`, `A-Z`) a value from a single shared counter seeded so the first ever request ID is `8k` (decimal 516). Each new submission SHALL receive the next counter value, guaranteeing no two requests ever share an ID.

#### Scenario: First request ID issued by the system
- **WHEN** the very first `POST /v2/links` request is ever accepted
- **THEN** the assigned `requestId` is `8k`

#### Scenario: Sequential requests receive distinct IDs
- **WHEN** two `POST /v2/links` requests are accepted one after another
- **THEN** the second request's `requestId` is different from the first's

### Requirement: Process queued requests and resolve the phone number
The system SHALL process each queued request using the same number-recognition rules as the `whatsapp-link-api` capability (DDD 11-99, 10 digits for a landline or 11 digits for a mobile number starting with `9`, formatting characters ignored, optional `+55`/`55` country code stripped). Once processed, the system SHALL update the stored request to status `completed` with a `result` field: the `wa.me` URL for a recognized number, or `false` for an unrecognized one.

#### Scenario: Queued request resolves to a valid link
- **WHEN** a queued request for number `11987654321` finishes processing
- **THEN** the stored request has `"status": "completed"` and `"result": "https://wa.me/5511987654321"`

#### Scenario: Queued request resolves to an unrecognized number
- **WHEN** a queued request for number `123` finishes processing
- **THEN** the stored request has `"status": "completed"` and `"result": false`

### Requirement: Retrieve request status and result
The system SHALL accept `GET /v2/links/{requestId}`. If a request with that ID exists, the system SHALL respond with HTTP 200 and the request's current status (`pending`, with no `result` field, or `completed`, with the `result` field). If no request with that ID exists, the system SHALL respond with HTTP 404.

#### Scenario: Poll before processing finishes
- **WHEN** `GET /v2/links/{requestId}` is called for a request that has been queued but not yet processed
- **THEN** the response is HTTP 200 with body `{"requestId": "<id>", "status": "pending"}`

#### Scenario: Poll after processing finishes
- **WHEN** `GET /v2/links/{requestId}` is called for a request that has finished processing
- **THEN** the response is HTTP 200 with body including `"status": "completed"` and the `result` field

#### Scenario: Poll for a request ID that does not exist
- **WHEN** `GET /v2/links/{requestId}` is called with an ID that was never issued
- **THEN** the response is HTTP 404

### Requirement: Retry transient processing failures before dead-lettering
The system SHALL retry a queued request that fails processing due to a transient error, up to a bounded number of attempts. If all retries are exhausted, the message SHALL be moved to a dead-letter queue instead of being retried indefinitely, and the corresponding stored request SHALL remain in status `pending` until the failure is investigated and the message redriven.

#### Scenario: Processing fails repeatedly
- **WHEN** a queued request fails processing on every delivery attempt up to the configured retry limit
- **THEN** the message is moved to the dead-letter queue and the stored request's status remains `pending`
