"""
Hotel MCP Server

Standalone MCP server exposing hotel capabilities (list, search, book) as MCP tools.
Runs as its own process, independent of the agent/graph code. Wraps the existing
hotel REST API — this is the ONLY place that talks to that API directly.

Run:
    python mcp_servers/hotel_server.py

Env:
    HOTEL_API_BASE   (default: https://standing-fish-574.convex.site/hotels)
    HOTEL_MCP_HOST    (default: 0.0.0.0)
    HOTEL_MCP_PORT    (default: 8001)
"""

import os
from typing import Any, List, Optional

import requests
from mcp.server.fastmcp import FastMCP

HOTEL_API_BASE = os.environ.get("HOTEL_API_BASE", "https://standing-fish-574.convex.site/hotels")
HOST = os.environ.get("HOTEL_MCP_HOST", "0.0.0.0")
# Render (and most PaaS providers) inject $PORT and require binding to it.
# HOTEL_MCP_PORT is the local-dev-friendly override; PORT wins if both are set.
PORT = int(os.environ.get("PORT", os.environ.get("HOTEL_MCP_PORT", "8001")))

mcp = FastMCP("hotel-service", host=HOST, port=PORT)


def _get(url: str, params: Optional[dict] = None) -> Any:
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": True, "message": f"Hotel service request failed: {e}"}


def _post(url: str, payload: dict) -> Any:
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": True, "message": f"Hotel service request failed: {e}"}


@mcp.tool()
def list_hotels() -> dict:
    """List all available hotels, with no filtering.

    Use this when the user wants to browse every hotel in the system
    (e.g. "show me all hotels").
    """
    data = _get(HOTEL_API_BASE)
    if isinstance(data, dict) and data.get("error"):
        return data
    if isinstance(data, dict):
        return {"hotels": data.get("hotels", [])}
    if isinstance(data, list):
        return {"hotels": data}
    return {"hotels": []}


@mcp.tool()
def search_hotels(
    city: str,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
) -> dict:
    """Search hotels by city and optional check-in/check-out dates.

    Args:
        city: City to search hotels in, e.g. "Colombo", "Bangkok".
        check_in: Optional check-in date, format YYYY-MM-DD.
        check_out: Optional check-out date, format YYYY-MM-DD.
    """
    params = {"city": city}
    if check_in:
        params["checkIn"] = check_in
    if check_out:
        params["checkOut"] = check_out

    data = _get(f"{HOTEL_API_BASE}/search", params=params)
    if isinstance(data, dict) and data.get("error"):
        return data
    if isinstance(data, dict):
        return {"hotels": data.get("hotels", [])}
    if isinstance(data, list):
        return {"hotels": data}
    return {"hotels": []}


@mcp.tool()
def book_hotel(
    hotel_id: str,
    guest_name: str,
    guest_email: str,
    check_in_date: str,
    check_out_date: str,
    room_type: str,
) -> dict:
    """Book a room at a specific hotel.

    Args:
        hotel_id: ID of the hotel to book (from a prior list/search result).
        guest_name: Full name of the guest.
        guest_email: Email address of the guest.
        check_in_date: Check-in date, format YYYY-MM-DD.
        check_out_date: Check-out date, format YYYY-MM-DD.
        room_type: Room type, e.g. "single", "double", "suite".
    """
    payload = {
        "hotelId": hotel_id,
        "guestName": guest_name,
        "guestEmail": guest_email,
        "checkInDate": check_in_date,
        "checkOutDate": check_out_date,
        "roomType": room_type,
    }
    return _post(f"{HOTEL_API_BASE}/book", payload)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
