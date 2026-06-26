# QueueStorm Investigator

QueueStorm Investigator is a Docker-ready FastAPI backend for the SUST QueueStorm Investigator preliminary challenge. It analyzes a support complaint together with supplied transaction history and returns an official-schema JSON triage response.

The service is deterministic, offline, and rule-based. It does not call external APIs, does not use an LLM, does not require a database, and does not download models during startup.

## Architecture

- FastAPI app entrypoint: `app/main.py`
- API routes: `app/api.py`
- Pydantic v2 request/response schemas and enums: `app/models.py`
- Rule-based reasoning engine: `app/services/analyzer.py`
- Tests and hidden-style judge runner: `tests/`
- Docker fallback runtime: `Dockerfile`

## Folder Structure

```text
.
├── app/
│   ├── api.py
│   ├── main.py
│   ├── models.py
│   └── services/
│       └── analyzer.py
├── tests/
│   ├── QueueStorm_300_Hidden_Style_Cases.json
│   ├── hidden_cases.json
│   ├── test_api.py
│   ├── test_hidden_judge.py
│   └── test_judging_hardening.py
├── Dockerfile
├── requirements.txt
├── .env.example
├── .dockerignore
└── SUBMISSION.md
```

## Python Version

Python 3.12+ is required. The Docker image uses the lightweight official `python:3.12-slim` base image.

## Local Installation

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run locally:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker Build

```bash
docker build -t queuestorm-investigator .
```

## Docker Run

Create a local `.env` file from `.env.example` and set non-secret values if desired:

```text
PORT=8000
LOG_LEVEL=info
ENVIRONMENT=production
```

Run the container:

```bash
docker run --rm -p 8000:8000 --env-file .env queuestorm-investigator
```

The container starts FastAPI with Uvicorn, binds to `0.0.0.0`, and exposes port `8000`.

## Environment Variables

`.env.example` lists variable names only and contains no secrets:

```text
PORT=
LOG_LEVEL=
ENVIRONMENT=
```

- `PORT`: service port, defaults to `8000`
- `LOG_LEVEL`: Uvicorn log level, defaults to `info`
- `ENVIRONMENT`: deployment label for operators

## API Endpoints

### `GET /health`

Returns exactly:

```json
{"status":"ok"}
```

### `POST /analyze-ticket`

Analyzes one ticket and returns the official response schema. No authentication is required.

## Request Schema

Required fields:

- `ticket_id`: string
- `complaint`: string

Optional fields:

- `language`: `en`, `bn`, `mixed`
- `channel`: `in_app_chat`, `call_center`, `email`, `merchant_portal`, `field_agent`
- `user_type`: `customer`, `merchant`, `agent`, `unknown`
- `campaign_context`: string
- `transaction_history`: array
- `metadata`: object

Transaction fields:

- `transaction_id`: string
- `timestamp`: ISO 8601 string
- `type`: `transfer`, `payment`, `cash_in`, `cash_out`, `settlement`, `refund`
- `amount`: number
- `counterparty`: string
- `status`: `completed`, `failed`, `pending`, `reversed`

Example:

```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm.",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "campaign_context": "campaign_day_1",
  "transaction_history": [
    {
      "transaction_id": "TXN-9101",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ],
  "metadata": {}
}
```

## Response Schema

Required response fields:

- `ticket_id`: string
- `relevant_transaction_id`: string or null
- `evidence_verdict`: `consistent`, `inconsistent`, `insufficient_data`
- `case_type`: `wrong_transfer`, `payment_failed`, `refund_request`, `duplicate_payment`, `merchant_settlement_delay`, `agent_cash_in_issue`, `phishing_or_social_engineering`, `other`
- `severity`: `low`, `medium`, `high`, `critical`
- `department`: `customer_support`, `dispute_resolution`, `payments_ops`, `merchant_operations`, `agent_operations`, `fraud_risk`
- `agent_summary`: string
- `recommended_next_action`: string
- `customer_reply`: string
- `human_review_required`: boolean

Optional response fields:

- `confidence`: number between `0` and `1`
- `reason_codes`: array of strings

No extra response fields are emitted. `ticket_id` is echoed exactly, and `relevant_transaction_id` is selected only from supplied `transaction_history`.

## Running Pytest

```bash
pytest
```

The suite covers endpoint exactness, schema and enum validation, all case types, evidence verdicts, Bangla/Banglish/typo-heavy complaints, malformed input, safety traps, ambiguous evidence, deterministic output, and the hidden-style judge runner.

## Rule-Based Reasoning Engine

The analyzer combines complaint signals with transaction evidence. It never invents transaction IDs and returns `null` when no transaction confidently matches.

Evidence matching considers:

- amount clues
- transaction type
- transaction status
- timestamp hints
- counterparty hints
- transaction ID hints
- duplicate-payment patterns
- merchant and agent context

Verdicts:

- `consistent`: transaction data supports the complaint
- `inconsistent`: transaction data contradicts the complaint
- `insufficient_data`: evidence is missing, ambiguous, or not enough to prove the claim

## Safety Guardrails

Complaint text is untrusted input. Prompt-injection instructions inside complaints are ignored.

The service never asks for:

- OTP
- PIN
- password or passcode
- full card number
- CVV
- secret credentials

The service never promises refund, reversal, recovery, account unblock, approval, or guaranteed account action. It uses safe wording such as:

```text
Eligible cases will be reviewed through official channels after verification.
```

Customers are directed only to official support channels and are never told to contact suspicious third parties.

## Hidden Test Readiness

The project includes `tests/test_hidden_judge.py`, which reads hidden-style cases from:

```text
tests/QueueStorm_300_Hidden_Style_Cases.json
```

It validates official fields, enums, confidence range, reason codes, safety wording, prompt-injection resistance, controlled errors, and no extra response fields.

## Known Limitations

- Rule-based language coverage cannot capture every spelling or phrasing.
- The service does not connect to real ledgers, payment APIs, account state, or KYC systems.
- Refund eligibility cannot be proven from complaint text alone.
- Very vague complaints may be classified as `other` with `insufficient_data`.
- Timestamp reasoning uses simple ISO timestamp and hour/minute clues.
