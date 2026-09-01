## Purpose

Turns a Brazilian phone number into a WhatsApp Web deep link (`https://wa.me/55<DDD><number>`), returning `false` when the supplied number cannot be recognized as a valid Brazilian phone number.

## Requirements

### Requirement: Retrieve WhatsApp link for a valid number
The system SHALL accept a phone number as a path parameter on `GET /{number}`, where `{number}` contains only a Brazilian DDD (area code) and local subscriber number — no country code. When the supplied digits form a valid Brazilian number, the system SHALL respond with HTTP 200 and a JSON body `{"result": "https://wa.me/55<digits>"}`, where `<digits>` is the normalized (digits-only) DDD + number.

#### Scenario: Valid mobile number
- **WHEN** a GET request is made to `/11987654321`
- **THEN** the response is HTTP 200 with body `{"result": "https://wa.me/5511987654321"}`

#### Scenario: Valid landline number
- **WHEN** a GET request is made to `/1133334444`
- **THEN** the response is HTTP 200 with body `{"result": "https://wa.me/551133334444"}`

#### Scenario: Number contains formatting characters
- **WHEN** a GET request is made to `/(11) 98765-4321`
- **THEN** the system normalizes the input to digits only before validating, and the response is HTTP 200 with body `{"result": "https://wa.me/5511987654321"}`

### Requirement: Reject numbers that are not recognized
The system SHALL consider a number valid only if, after stripping all non-digit characters: the leading two digits (DDD) are between 11 and 99 inclusive, and the total digit count is exactly 10 (DDD + 8-digit local number) or exactly 11 (DDD + 9-digit local number, where the first digit of the 9-digit local number MUST be `9`). Any number that does not meet these conditions, including empty or missing input, SHALL be treated as not recognized. When a number is not recognized, the system SHALL respond with HTTP 200 and a JSON body `{"result": false}` — never a 4xx or 5xx status for an invalid or malformed number.

#### Scenario: DDD out of range
- **WHEN** a GET request is made to `/05987654321`
- **THEN** the response is HTTP 200 with body `{"result": false}`

#### Scenario: Wrong digit count
- **WHEN** a GET request is made to `/119876543`
- **THEN** the response is HTTP 200 with body `{"result": false}`

#### Scenario: 11-digit number missing the mobile 9-prefix
- **WHEN** a GET request is made to `/11887654321`
- **THEN** the response is HTTP 200 with body `{"result": false}`

#### Scenario: Missing or empty path parameter
- **WHEN** a GET request is made with no number supplied (empty path segment)
- **THEN** the response is HTTP 200 with body `{"result": false}`

#### Scenario: Non-numeric input
- **WHEN** a GET request is made to `/abcdefghijk`
- **THEN** the response is HTTP 200 with body `{"result": false}`
