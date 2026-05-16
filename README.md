# Booking Agents Backend

A FastAPI-based booking system with hotel and flight agents powered by LangChain.

## Structure

```
backend/
├── req/
│   └── requirements.txt    # Python dependencies
├── agents/
│   ├── hotel_agent.py     # Hotel booking agent
│   ├── flight_agent.py    # Flight booking agent
│   ├── orchestrator.py    # Routes queries to correct agent
│   └── __init__.py
├── app/
│   └── main.py           # FastAPI app with endpoints
├── llm.py              # LangChain ChatOpenAI
├── config.py           # Config loader
└── .env              # Environment variables
```

## Setup

### 1. Install Dependencies
```bash
cd backend/req
pip install -r requirements.txt
```

### 2. Configure API Key
Edit `.env` and add your OpenAI API key:
```
OPENAI_API_KEY=your_actual_api_key_here
```

### 3. Run the Server
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

## API Endpoints

| Endpoint | Method | Description | Example |
|----------|--------|-------------|---------|
| `/hotels` | GET | Get all hotels | `curl http://localhost:8000/hotels` |
| `/flights` | GET | Get all flights | `curl http://localhost:8000/flights` |
| `/chat` | POST | Chat with agent | See below |

### Chat Example

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "find me a hotel in NYC"}'
```

**Other queries to try:**
- "show me all hotels"
- "book a hotel in Miami"
- "find flights from New York to London"
- "show all flights"

## Gradio Chat UI

A simple Gradio chat interface is available in `gradio_app.py`.

Run the FastAPI backend first:

```bash
python main.py
```

Then start the Gradio UI:

```bash
python gradio_app.py
```

Open the local Gradio URL shown in the terminal and ask for flights or hotels.

## Tech Stack

- **FastAPI** - Web framework
- **LangChain** - Agent framework
- **OpenAI** - LLM (GPT-4o-mini)
- **python-dotenv** - Environment config