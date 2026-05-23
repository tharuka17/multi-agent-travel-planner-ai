# Booking Agents Backend

A FastAPI-based booking system with hotel and flight agents powered by LangChain.


## Setup

### 1. Create Virtual Environment
```bash
python -m venv env
```

Activate the virtual environment:
- **Windows (CMD)**:
  ```bash
  env\Scripts\activate
  ```
- **Windows (PowerShell)**:
  ```bash
  env\Scripts\Activate.ps1
  ```
- **macOS/Linux**:
  ```bash
  source env/bin/activate
  ```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure API Key
Create a `.env` file in the project root and add your OpenAI API key:
```
OPENAI_API_KEY=your_actual_api_key_here
```

### 4. Run the Backend
```bash
python main.py
```

### 5. Run the Frontend
In a new terminal (with the virtual environment activated):
```bash
python frontend.py
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