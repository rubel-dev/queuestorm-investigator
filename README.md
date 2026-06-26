# QueueStorm Investigator

QueueStorm Investigator is a FastAPI backend for the SUST CSE Carnival 2026 Codex Community Hackathon preliminary challenge. It receives one customer support complaint plus recent transaction history and returns a schema-valid, evidence-grounded triage decision for support agents.

The service is fully offline and rule-based. It does not call external LLMs, does not load models, does not use a database, and starts quickly for automated judging.

## Official Endpoints

### `GET /health`

Returns exactly:

```json
{"status":"ok"}
```

### `POST /analyze-ticket`

Accepts one ticket per request and returns one structured JSON analysis.

## Request Schema

```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today...",
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

## Response Schema

```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Ticket appears to be wrong transfer linked to TXN-9101...",
  "recommended_next_action": "Route transaction TXN-9101 to dispute_resolution...",
  "customer_reply": "We have noted your concern for transaction TXN-9101...",
  "human_review_required": true,
  "confidence": 0.95,
  "reason_codes": ["case_wrong_transfer", "transaction_id_match"]
}
```

Response enums:

- `evidence_verdict`: `consistent`, `inconsistent`, `insufficient_data`
- `case_type`: `wrong_transfer`, `payment_failed`, `refund_request`, `duplicate_payment`, `merchant_settlement_delay`, `agent_cash_in_issue`, `phishing_or_social_engineering`, `other`
- `severity`: `low`, `medium`, `high`, `critical`
- `department`: `customer_support`, `dispute_resolution`, `payments_ops`, `merchant_operations`, `agent_operations`, `fraud_risk`

The service does not add response fields outside the official schema. `ticket_id` is echoed exactly. `relevant_transaction_id` is always selected from the supplied `transaction_history`; if no supplied transaction clearly matches, it is `null`.

## Setup

Requirements:

- Python 3.12+
- pip

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On Linux or macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run Locally

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Smoke test:

```bash
curl http://localhost:8000/health
```

Example analysis request:

```bash
curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number +8801719876543 around 2pm.",
    "language": "en",
    "channel": "in_app_chat",
    "user_type": "customer",
    "transaction_history": [
      {
        "transaction_id": "TXN-9101",
        "timestamp": "2026-04-14T14:08:22Z",
        "type": "transfer",
        "amount": 5000,
        "counterparty": "+8801719876543",
        "status": "completed"
      }
    ]
  }'
```

## Run Tests

```bash
pytest
```

The test suite covers the official endpoints, schema, enums, all case types, evidence verdicts, safety traps, malformed input, Bangla and Banglish complaints, deterministic repeated output, confidence range, and no extra response fields.

## Docker

Build:

```bash
docker build -t queuestorm-investigator .
```

Run:

```bash
docker run -p 8000:8000 --env-file .env.example queuestorm-investigator
```

The Dockerfile uses `python:3.12-slim`, installs `requirements.txt`, exposes port `8000`, and runs Uvicorn bound to `0.0.0.0`.

## Environment Variables

`.env.example` contains variable names only:

```bash
PORT=
```

No real secrets are required. Do not commit `.env` or any API keys.

## Reasoning Engine

The analyzer is deterministic and rule-based:

- Extracts complaint signals from English, Bangla, and Banglish text.
- Detects case intent for wrong transfer, failed payment, balance deducted, refund, duplicate payment, merchant settlement delay, agent cash-in issue, phishing/social engineering, and other cases.
- Scores transaction evidence using transaction ID, amount, type, status, timestamp clues, counterparty clues, and duplicate-payment patterns.
- Selects `relevant_transaction_id` only when a supplied transaction has enough evidence.
- Returns `null` when no supplied transaction clearly matches.
- Returns `consistent` when evidence supports the complaint.
- Returns `inconsistent` when evidence contradicts the complaint.
- Returns `insufficient_data` when evidence is missing, ambiguous, or not enough to prove the claim.
- Computes deterministic confidence in `[0, 1]`, with lower confidence for ambiguity, missing history, or conflicting evidence.

## Safety Guardrails

Complaint text is treated as untrusted input. The service ignores prompt-injection style instructions inside the complaint and never follows customer instructions that conflict with system safety rules.

Customer replies never ask for OTP, PIN, password, full card number, or secret credentials. Replies and next actions never promise refund, reversal, recovery, or account unblock. The wording uses safe review language such as:

```text
Eligible cases will be reviewed through official channels after verification.
```

Suspicious calls, phishing, credential requests, and account-risk complaints are routed to `fraud_risk`, marked `critical`, and require human review. Customers are directed only to official support channels.

## Human Review Rules

`human_review_required` is true for:

- Wrong transfer
- Refund dispute
- Phishing or social engineering
- Suspicious activity
- Ambiguous evidence
- `insufficient_data`
- High value transaction
- Conflicting evidence
- Merchant disputes
- Agent disputes

## Error Handling

The API returns controlled JSON errors:

- Invalid JSON or missing required fields: `400`
- Invalid enum values or invalid transaction fields: `422`
- Empty `ticket_id` or empty `complaint`: `422`
- Internal server error: `500`

Error responses do not include stack traces, raw exception details, tokens, API keys, or secrets.

## Performance Notes

- No external network calls
- No LLM or model loading
- No database connection
- Deterministic in-memory rule execution
- Fast startup and low request latency

## AI and Model Usage

No external or local AI model is used. No OpenAI, Anthropic, Hugging Face, Google AI, or other provider key is required. The project is designed to run fully offline in the judging environment.

## Assumptions

- Transaction histories are synthetic and supplied by the judge harness.
- The service is a support copilot, not a payment authority.
- A transaction can only be referenced if it appears in the supplied `transaction_history`.
- Ambiguous cases are safer as `insufficient_data` with human review than guessed transaction matches.

## Known Limitations

- Rule-based language coverage cannot catch every possible spelling or phrasing.
- The service does not access real ledgers, account state, KYC data, or payment APIs.
- Refund eligibility cannot be proven from complaint text alone.
- Very vague complaints may be classified as `other` or `insufficient_data`.
- Timestamp reasoning uses simple hour/minute clues and does not infer local timezone beyond supplied ISO timestamps.

## Deployment Notes

For live deployment, expose the base URL publicly so judges can call:

```text
GET  https://your-service.example.com/health
POST https://your-service.example.com/analyze-ticket
```

No login, private network access, manual approval, or dashboard interaction should be required.
