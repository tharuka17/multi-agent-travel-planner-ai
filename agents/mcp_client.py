"""
Shared MCP client wiring.

This is the ONLY place in the agent/graph code that knows how to reach the MCP
servers. Agents never talk to hotel/flight REST APIs directly — they call MCP
tools obtained here. Swapping or adding a service means editing this file's
config (or adding a new server), never touching agent/graph logic.
"""

import os
from typing import List

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

HOTEL_MCP_URL = os.environ.get("HOTEL_MCP_URL", "http://127.0.0.1:8001/mcp")
FLIGHT_MCP_URL = os.environ.get("FLIGHT_MCP_URL", "http://127.0.0.1:8002/mcp")

_client = MultiServerMCPClient(
    {
        "hotel": {
            "url": HOTEL_MCP_URL,
            "transport": "streamable_http",
        },
        "flight": {
            "url": FLIGHT_MCP_URL,
            "transport": "streamable_http",
        },
    }
)

_hotel_tools_cache: List[BaseTool] | None = None
_flight_tools_cache: List[BaseTool] | None = None


async def get_hotel_tools() -> List[BaseTool]:
    """Return the MCP tools exposed by the hotel MCP server (cached after first call)."""
    global _hotel_tools_cache
    if _hotel_tools_cache is None:
        _hotel_tools_cache = await _client.get_tools(server_name="hotel")
    return _hotel_tools_cache


async def get_flight_tools() -> List[BaseTool]:
    """Return the MCP tools exposed by the flight MCP server (cached after first call)."""
    global _flight_tools_cache
    if _flight_tools_cache is None:
        _flight_tools_cache = await _client.get_tools(server_name="flight")
    return _flight_tools_cache


async def get_all_tools() -> List[BaseTool]:
    """Return every MCP tool across both servers (used by /hotels, /flights REST helpers)."""
    hotel_tools = await get_hotel_tools()
    flight_tools = await get_flight_tools()
    return hotel_tools + flight_tools
