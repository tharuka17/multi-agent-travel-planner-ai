# Stretch: Containerisation. One shared image for all four services
# (backend, hotel-mcp, flight-mcp, frontend) — they all need the exact same
# Python dependencies, so building one image and overriding the *command*
# per service (see docker-compose.yml) avoids maintaining four near-identical
# Dockerfiles that would drift out of sync with each other and with
# requirements.txt over time.

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first, separately from the app code, so Docker's
# layer cache only reinstalls packages when requirements.txt actually
# changes — not on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# No CMD here on purpose: which of the four processes this container runs
# (uvicorn main:app / mcp_servers/hotel_server.py / etc.) is decided by the
# `command:` override on each service in docker-compose.yml, not baked into
# the image itself.
