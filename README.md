# Fred Zulip Bot

Fred is a FastAPI service that integrates a generative AI model with Zulip. It classifies user intent, generates safe read-only SQL queries against an unfoldingWord database, and posts natural-language answers back to Zulip.

---

## Usage
To use fred-bot in Zulip, simply @fred-bot <some-message> and he will respond. First by saying "Fred is thinking..." then later with the actual response to the users message/query.

---

## Features
- Intent classification using Google Gemini models.
- Read-only SQL generation with safety checks against destructive commands.
- FastAPI endpoint for asynchronous message processing.
- Automatic chat history storage and rotating file logging.
- Dockerfile for containerized deployment.

---

## Requirements
- Python 3.13 or compatible.
- Access to a MySQL database with schema matching `data/DDLs.rtf`.
- Google Generative AI API key.
- Zulip bot credentials and auth token.

Required environment variables:
- `ZULIP_BOT_TOKEN`
- `ZULIP_BOT_EMAIL`
- `ZULIP_SITE`
- `DB_HOST`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `GENAI_API_KEY`
- `ZULIP_AUTH_TOKEN`

These can be placed in `.venv/.env` for local development.

---

## Setup
1. Clone the repository and navigate into it.
2. (Optional) create and activate a virtual environment.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Ensure the required environment variables are available.

---

## Running the Service
### Local
Start the FastAPI app with Uvicorn:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Docker
```bash
docker build -t fred-zulip-bot .
docker run --env-file .env -p 8000:8000 fred-zulip-bot
```

---

## API
`POST /chat`

Request body:
```json
{
  "message": {
    "content": "Your question here",
    "sender_email": "user@example.com",
    "subject": "topic",
    "type": "private"
  },
  "token": "ZULIP_AUTH_TOKEN"
}
```
If authenticated, the service returns an acknowledgment immediately and sends the generated response back to Zulip.

---

## User Intents
The bot recognizes three categories of requests:
- **Database lookup:** Ask about information stored in the unfoldingWord database. Fred generates a safe read-only SQL query, runs it, and summarizes the result in plain language.
- **Chatbot questions:** Ask about Fred itself—its name, purpose, or how it works—and it will reply conversationally without querying the database.
- **Other requests:** For anything outside the above categories, Fred explains that the request isn’t supported and reminds you what it can do.

---

## Data and Logs
- Chat histories are stored in `data/chat_histories`.
- Application logs rotate in `logs/app.log`.

---

## Testing
Run the available test suite:
```bash
pytest
```

---

## License
This project does not currently include an explicit license file.
