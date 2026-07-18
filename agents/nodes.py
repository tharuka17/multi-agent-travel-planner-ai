import json
import time
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from .entity import GraphState
from .llm import llm
from .mcp_client import get_flight_tools, get_hotel_tools
from .observability import log_routing_decision, timed_tool_call
from .prompts import (
    FLIGHT_AGENT_SYSTEM_PROMPT,
    GENERAL_QA_SYSTEM_PROMPT,
    HOTEL_AGENT_SYSTEM_PROMPT,
    INTENT_SYSTEM_PROMPT,
    build_history_messages,
)


# ---------------------------------------------------------------------------
# Router: intent classification only (E2 — the graph decides, not a fixed path)
# ---------------------------------------------------------------------------

class IntentClassification(BaseModel):
    intent: Literal["hotel", "flight", "general_qa"] = Field(
        description="Which agent should handle this message."
    )


intent_classifier = llm.with_structured_output(IntentClassification)


def _extract_tool_result(raw) -> dict:
    """Normalize an MCP tool call's return value back into the plain dict our
    MCP servers actually return.

    langchain-mcp-adapters' StructuredTool.ainvoke() does not hand back the
    Python dict a FastMCP tool function returns — it hands back the MCP
    content list (typically one text block containing that dict JSON-encoded).
    Without unwrapping this, every `isinstance(tool_result, dict)` check below
    would silently be False, so a real tool error would never set
    `tool_error=True` and a real success would never populate
    hotel_results/flight_results — even though the LLM itself still reads the
    right text and responds sensibly. This keeps the *app-level* state (not
    just the LLM's own reasoning) honest about what the tool actually returned.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        for block in raw:
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if text:
                try:
                    parsed = json.loads(text)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(parsed, dict):
                    return parsed
    return {"error": True, "message": "Unexpected tool result format from MCP server."}


def _build_messages(system_prompt: str, state: GraphState) -> list:
    user_message = state["messages"][-1]
    history_lines = state["messages"][:-1]

    messages = [SystemMessage(content=system_prompt)]
    for role, text in build_history_messages(history_lines):
        messages.append(HumanMessage(content=text) if role == "user" else AIMessage(content=text))
    messages.append(HumanMessage(content=user_message))
    return messages


async def router(state: GraphState, config: RunnableConfig) -> dict:
    thread_id = config["configurable"].get("thread_id", "default")
    messages = _build_messages(INTENT_SYSTEM_PROMPT, state)

    start = time.perf_counter()
    try:
        result = await intent_classifier.ainvoke(messages)
        intent = result.intent
    except Exception:
        # E3: never let a classification failure crash the turn — fall back safely.
        intent = "general_qa"
    log_routing_decision(thread_id, intent, (time.perf_counter() - start) * 1000)

    return {
        "intent": intent,
        "activity": "routing",
        "hotel_results": [],
        "flight_results": [],
        "response_text": "",
        "tool_error": False,
    }


def route_after_intent(state: GraphState) -> str:
    return state.get("intent", "general_qa")


# ---------------------------------------------------------------------------
# Shared tool-calling loop used by both the Hotel Agent and the Flight Agent.
# Each agent reasons over the conversation, picks a tool (or asks a follow-up
# question instead of guessing), calls it via MCP, then composes the final
# reply from the real tool result. This is what makes E2 "agent decides" real
# rather than a router pre-filling slots.
# ---------------------------------------------------------------------------

async def _run_tool_calling_agent(
    state: GraphState,
    config: RunnableConfig,
    system_prompt: str,
    tools: list[BaseTool],
    result_key: str,  # "hotel_results" or "flight_results"
    node_name: str,  # "hotel_agent" or "flight_agent", for activity events
) -> dict:
    thread_id = config["configurable"].get("thread_id", "default")
    base = {"hotel_results": [], "flight_results": [], "response_text": "", "tool_error": False}

    try:
        messages = _build_messages(system_prompt, state)
        llm_with_tools = llm.bind_tools(tools)
        ai_msg = await llm_with_tools.ainvoke(messages)

        # No tool call chosen -> the agent is asking a clarifying question
        # rather than fabricating data (spec section 4, step 6). Re-run as a
        # plain streaming call (no tools bound) so the question streams
        # token-by-token to the frontend, same as any other reply.
        if not getattr(ai_msg, "tool_calls", None):
            content = ""
            async for chunk in llm.astream(messages):
                content += chunk.content
            reply = content or ai_msg.content
            return {**base, "activity": "clarifying", "response_text": reply, "messages": [reply]}

        tools_by_name = {t.name: t for t in tools}
        tool_messages = []
        structured_results: list[dict] = []
        had_error = False

        # E2/section 6: SEARCHING vs BOOKING is a real intermediate state, not
        # just metadata attached to the final response. Emit it *before* the
        # tool call actually runs (via LangGraph's custom stream writer) so
        # the frontend can show "Searching hotels…" / "Booking hotel…" while
        # the MCP call is in flight, not only after the whole node finishes.
        activity = "booking" if any("book" in c["name"] for c in ai_msg.tool_calls) else "searching"
        try:
            writer = get_stream_writer()
            writer({"type": "activity", "node": node_name, "activity": activity})
        except Exception:
            pass  # custom stream writer only exists when invoked via .astream(); harmless if unavailable

        for call in ai_msg.tool_calls:
            tool = tools_by_name.get(call["name"])

            if tool is None:
                tool_result = {"error": True, "message": f"Unknown tool: {call['name']}"}
            else:
                with timed_tool_call(thread_id, node_name, call["name"]) as mark_status:
                    try:
                        raw_result = await tool.ainvoke(call["args"])
                        tool_result = _extract_tool_result(raw_result)
                        mark_status("failed" if tool_result.get("error") else "succeeded")
                    except Exception as e:
                        # E3: a failing MCP/external call degrades gracefully, never crashes.
                        tool_result = {"error": True, "message": f"The service is temporarily unavailable ({e})."}
                        mark_status("failed")

            if isinstance(tool_result, dict) and tool_result.get("error"):
                had_error = True
            elif isinstance(tool_result, dict):
                structured_results.extend(tool_result.get("hotels", []) or tool_result.get("flights", []) or [])

            tool_messages.append(
                ToolMessage(content=json.dumps(tool_result, default=str), tool_call_id=call["id"])
            )

        # Stream the final synthesis so tokens reach the frontend as they're
        # generated, rather than waiting for the whole reply to complete.
        final_content = ""
        async for chunk in llm.astream([*messages, ai_msg, *tool_messages]):
            final_content += chunk.content

        return {
            **base,
            "activity": "responding",
            "response_text": final_content,
            "messages": [final_content],
            "tool_error": had_error,
            result_key: structured_results,
        }

    except Exception as e:
        # E3: absolute last line of defense — the app must keep working.
        fallback = (
            "Sorry, something went wrong reaching that service just now. "
            "Please try again in a moment."
        )
        return {
            **base,
            "activity": "responding",
            "tool_error": True,
            "response_text": fallback,
            "messages": [fallback],
        }


async def hotel_agent_node(state: GraphState, config: RunnableConfig) -> dict:
    tools = await get_hotel_tools()
    return await _run_tool_calling_agent(
        state, config, HOTEL_AGENT_SYSTEM_PROMPT, tools, "hotel_results", "hotel_agent"
    )


async def flight_agent_node(state: GraphState, config: RunnableConfig) -> dict:
    tools = await get_flight_tools()
    return await _run_tool_calling_agent(
        state, config, FLIGHT_AGENT_SYSTEM_PROMPT, tools, "flight_results", "flight_agent"
    )


# ---------------------------------------------------------------------------
# General QA agent — no tools, holds the conversation together (spec 2.2)
# ---------------------------------------------------------------------------

async def general_qa_node(state: GraphState) -> dict:
    try:
        messages = _build_messages(GENERAL_QA_SYSTEM_PROMPT, state)
        content = ""
        async for chunk in llm.astream(messages):
            content += chunk.content
        return {
            "hotel_results": [],
            "flight_results": [],
            "activity": "responding",
            "response_text": content,
            "messages": [content],
            "tool_error": False,
        }
    except Exception:
        fallback = "Sorry, I couldn't process that just now. Please try again."
        return {
            "hotel_results": [],
            "flight_results": [],
            "activity": "responding",
            "tool_error": True,
            "response_text": fallback,
            "messages": [fallback],
        }
