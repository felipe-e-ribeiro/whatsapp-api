## ADDED Requirements

### Requirement: Submit a number for orchestrated resolution
The system SHALL accept `POST /v3/links` with a JSON body containing a `number` field and a required `x-api-key` header. On a valid request, the system SHALL record the request as `pending`, start an orchestrated execution to resolve it, and respond immediately with HTTP 202 and a JSON body `{"requestId": <id>, "status": "pending"}` without waiting for resolution to complete.

#### Scenario: Valid submission is accepted and queued for orchestration
- **WHEN** a POST request is made to `/v3/links` with a valid `x-api-key` header and body `{"number": "11987654321"}`
- **THEN** the response is HTTP 202 with a JSON body containing a `requestId` and `"status": "pending"`, and an orchestrated execution is started for that request

#### Scenario: Missing or malformed body is rejected
- **WHEN** a POST request is made to `/v3/links` with a body that is not valid JSON, or with no `number` field, or where `number` is not a string
- **THEN** the response is HTTP 400 and no execution is started

#### Scenario: Missing or incorrect API key
- **WHEN** a POST request is made to `/v3/links` without the `x-api-key` header, or with an incorrect one
- **THEN** the response is HTTP 403 and no execution is started

### Requirement: Poll for orchestration status and result
The system SHALL accept `GET /v3/links/{requestId}` with a required `x-api-key` header and respond with the current stored status of that request: `pending` while orchestration is in progress, `completed` with a `result` field once resolution succeeds, `invalid` when the submitted number failed business validation, or `failed` when orchestration exhausted its retries. An unknown `requestId` SHALL return HTTP 404.

#### Scenario: Result available after processing completes
- **WHEN** a GET request is made to `/v3/links/{requestId}` for a request whose orchestration has completed successfully
- **THEN** the response is HTTP 200 with body `{"requestId": <id>, "status": "completed", "result": <whatsapp-url>}`

#### Scenario: Still pending
- **WHEN** a GET request is made to `/v3/links/{requestId}` for a request whose orchestration has not yet finished
- **THEN** the response is HTTP 200 with body `{"requestId": <id>, "status": "pending"}`

#### Scenario: Submitted number failed validation
- **WHEN** a GET request is made to `/v3/links/{requestId}` for a request whose number was not a recognizable Brazilian number
- **THEN** the response is HTTP 200 with body `{"requestId": <id>, "status": "invalid"}`

#### Scenario: Unknown request id
- **WHEN** a GET request is made to `/v3/links/{requestId}` for a `requestId` that was never submitted
- **THEN** the response is HTTP 404

### Requirement: Orchestrate resolution as an ordered, structured pipeline
The system SHALL resolve an accepted request through a centrally defined, ordered pipeline — validate the number, then resolve it to a WhatsApp link, then persist the final result — implemented as a state machine whose flow definition is a single structured artifact, rather than each step independently deciding what runs next.

#### Scenario: Valid number flows through all pipeline steps in order
- **WHEN** an accepted request contains a recognizable Brazilian number
- **THEN** the pipeline validates the number, then resolves it to a `https://wa.me/...` URL, then persists that result, and the stored status becomes `completed` only after all three steps finish

#### Scenario: Invalid number short-circuits without exhausting retries
- **WHEN** an accepted request contains a number that fails business validation
- **THEN** the pipeline stores `status: "invalid"` without retrying the validation step, since the failure is a client input problem rather than a transient one

### Requirement: Retry transient failures with observable evidence
The system SHALL retry a transient failure in the resolution step a bounded number of times with backoff, and SHALL record the number of attempts made and the most recent error (when any) on the stored request record, so retry behavior is verifiable by polling `GET /v3/links/{requestId}` alone.

#### Scenario: Transient failure is retried and eventually succeeds
- **WHEN** an accepted request includes an optional `simulateFailures` value that is less than the configured maximum retry attempts
- **THEN** the resolution step fails that many times, the stored `attempts` count reflects each attempt, and the request ultimately reaches `status: "completed"` with the correct result

#### Scenario: Retries are exhausted
- **WHEN** an accepted request includes a `simulateFailures` value that meets or exceeds the configured maximum retry attempts
- **THEN** the pipeline stops retrying, the stored record reflects `status: "failed"` with a non-empty `lastError`, and the request payload is sent to a dead-letter queue

### Requirement: Idempotent submission
The system SHALL treat a resubmission carrying the same idempotency key as the original request rather than starting duplicate processing for it. The idempotency key SHALL be an optional `Idempotency-Key` header supplied by the client; when omitted, the system SHALL generate one for that submission.

#### Scenario: Resubmitting the same idempotency key returns the original request
- **WHEN** two POST requests to `/v3/links` are made with the same `Idempotency-Key` header (whether or not the first has finished processing)
- **THEN** both responses reference the same `requestId`, and only one orchestrated execution is started for that key
