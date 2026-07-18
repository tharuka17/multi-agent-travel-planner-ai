"""
Observability — structured logging of routing decisions and MCP tool calls.

Stretch goal: "structured logging or tracing of routing decisions and tool
calls." This module gives every log line a consistent JSON shape (one event
per line) so they're greppable/parseable in a real log aggregator, rather
than free-form prose. It deliberately does NOT log message content (user
queries, LLM replies, tool arguments/results in full) — only metadata about
what happened and how long it took — to avoid leaking traveller PII (names,
emails) into logs.
"""

import json
import logging
import time
from contextlib import contextmanager

logger = logging.getLogger("tripweaver")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _emit(event: str, **fields) -> None:
    record = {"event": event, "ts": time.time(), **fields}
    logger.info(json.dumps(record, default=str))


def log_routing_decision(thread_id: str, intent: str, duration_ms: float) -> None:
    """E2: the graph decides where to go based on intent — this is the
    observable record of that decision, so routing behavior can be audited
    without re-reading the whole conversation."""
    _emit("routing_decision", thread_id=thread_id, intent=intent, duration_ms=round(duration_ms, 1))


def log_tool_call(
    thread_id: str,
    node: str,
    tool_name: str,
    status: str,  # "invoked" | "succeeded" | "failed" — mirrors spec section 6's Tool-Call Status
    duration_ms: float,
) -> None:
    _emit(
        "tool_call",
        thread_id=thread_id,
        node=node,
        tool_name=tool_name,
        status=status,
        duration_ms=round(duration_ms, 1),
    )


@contextmanager
def timed_tool_call(thread_id: str, node: str, tool_name: str):
    """Usage:
        with timed_tool_call(thread_id, "hotel_agent", "search_hotels") as mark_status:
            result = await tool.ainvoke(args)
            mark_status("succeeded" if not result.get("error") else "failed")
    Always logs on exit (defaults to "failed" if mark_status was never called,
    e.g. because the call raised) — so a crash mid-call still produces a
    tool_call log line instead of silently vanishing.
    """
    start = time.perf_counter()
    status_box = {"status": "failed"}

    def mark_status(status: str) -> None:
        status_box["status"] = status

    try:
        yield mark_status
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        log_tool_call(thread_id, node, tool_name, status_box["status"], duration_ms)
