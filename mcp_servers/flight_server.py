"""
Flight MCP Server

Standalone MCP server exposing flight capabilities (list, search, book) as MCP
tools. Runs as its own process, independent of the agent/graph code. Wraps the
existing flight REST API — this is the ONLY place that talks to that API directly.

Run:
    python mcp_servers/flight_server.py

Env:
    FLIGHT_API_BASE   (default: https://standing-fish-574.convex.site/flights)
    FLIGHT_MCP_HOST    (default: 0.0.0.0)
    FLIGHT_MCP_PORT    (default: 8002)
"""

import os
from typing import Any, Optional

import requests
from mcp.server.fastmcp import FastMCP

FLIGHT_API_BASE = os.environ.get("FLIGHT_API_BASE", "https://standing-fish-574.convex.site/flights")
HOST = os.environ.get("FLIGHT_MCP_HOST", "0.0.0.0")
# Render (and most PaaS providers) inject $PORT and require binding to it.
# FLIGHT_MCP_PORT is the local-dev-friendly override; PORT wins if both are set.
PORT = int(os.environ.get("PORT", os.environ.get("FLIGHT_MCP_PORT", "8002")))

mcp = FastMCP("flight-service", host=HOST, port=PORT)


def _get(url: str, params: Optional[dict] = None) -> Any:
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": True, "message": f"Flight service request failed: {e}"}


def _post(url: str, payload: dict) -> Any:
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": True, "message": f"Flight service request failed: {e}"}


@mcp.tool()
def list_flights() -> dict:
    """List all available flights, with no filtering.

    Use this when the user wants to browse every flight in the system
    (e.g. "show me all flights").
    """
    data = _get(FLIGHT_API_BASE)
    if isinstance(data, dict) and data.get("error"):
        return data
    if isinstance(data, dict):
        return {"flights": data.get("flights", [])}
    if isinstance(data, list):
        return {"flights": data}
    return {"flights": []}


@mcp.tool()
def search_flights(
    origin: str,
    destination: str,
    date: Optional[str] = None,
) -> dict:
    """Search flights by origin, destination, and optional travel date.

    Args:
        origin: Origin city or 3-letter airport code, e.g. "CMB" or "Colombo".
        destination: Destination city or 3-letter airport code, e.g. "BKK".
        date: Optional travel date, format YYYY-MM-DD.
    """
    normalized_origin = origin.upper() if origin and len(origin) == 3 and origin.isalpha() else origin
    normalized_destination = (
        destination.upper() if destination and len(destination) == 3 and destination.isalpha() else destination
    )

    params = {"origin": normalized_origin, "destination": normalized_destination}
    if date:
        params["date"] = date

    data = _get(f"{FLIGHT_API_BASE}/search", params=params)
    if isinstance(data, dict) and data.get("error"):
        return data
    if isinstance(data, dict):
        return {"flights": data.get("flights", [])}
    if isinstance(data, list):
        return {"flights": data}
    return {"flights": []}


@mcp.tool()
def book_flight(flight_id: str, passenger_name: str, passenger_email: str) -> dict:
    """Book a seat on a specific flight.

    Args:
        flight_id: ID of the flight to book (from a prior list/search result).
        passenger_name: Full name of the passenger.
        passenger_email: Email address of the passenger.
    """
    payload = {
        "flightId": flight_id,
        "passengerName": passenger_name,
        "passengerEmail": passenger_email,
    }
    return _post(f"{FLIGHT_API_BASE}/book", payload)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
