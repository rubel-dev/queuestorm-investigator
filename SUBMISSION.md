# QueueStorm Investigator Submission

## Repository

`queuestorm-investigator`

GitHub repository:

```text
https://github.com/rubel-dev/queuestorm-investigator
```

## Python Version

Python 3.12+

Docker base image:

```text
python:3.12-slim
```

## Docker Build Command

```bash
docker build -t queuestorm-investigator .
```

## Docker Run Command

Create a local `.env` file with non-secret values:

```text
PORT=8000
LOG_LEVEL=info
ENVIRONMENT=production
```

Run:

```bash
docker run --rm -p 8000:8000 --env-file .env queuestorm-investigator
```

## Port

The API listens on port `8000` inside the container and binds to `0.0.0.0`.

## Environment Variables

`.env.example` contains variable names only:

```text
PORT=
LOG_LEVEL=
ENVIRONMENT=
```

No secrets are required.

## Project Structure Summary

```text
app/main.py                 FastAPI app factory and controlled error handlers
app/api.py                  Official API routes: GET /health, POST /analyze-ticket
app/models.py               Pydantic v2 schemas and official enums
app/services/analyzer.py    Offline deterministic evidence reasoning engine
tests/                      Pytest suite and hidden-style judge runner
Dockerfile                  Docker fallback runtime
requirements.txt            Python dependencies
README.md                   Setup, Docker, API, reasoning, and safety docs
```

## Judge Reproduction Notes

1. Clone the repository.
2. Build the Docker image:

   ```bash
   docker build -t queuestorm-investigator .
   ```

3. Create `.env`:

   ```text
   PORT=8000
   LOG_LEVEL=info
   ENVIRONMENT=production
   ```

4. Run the container:

   ```bash
   docker run --rm -p 8000:8000 --env-file .env queuestorm-investigator
   ```

5. Verify health:

   ```bash
   curl http://localhost:8000/health
   ```

   Expected response:

   ```json
   {"status":"ok"}
   ```

6. Submit requests to:

   ```text
   POST http://localhost:8000/analyze-ticket
   ```

The project is fully offline and rule-based. It does not require GPU, model downloads, external APIs, database services, or secrets.
