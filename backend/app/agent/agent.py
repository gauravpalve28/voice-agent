"""
agent.py — LangChain agent for customer support voice pipeline.

Architecture:
  - Uses ChatGroq with tool binding (bind_tools)
  - Manual agent loop instead of AgentExecutor for streaming control:
    1. Send messages → LLM
    2. If LLM returns tool_calls → execute tools → feed results back → re-invoke LLM
    3. Final response (no tool_calls) → stream token by token
  - Conversation history is managed by the caller (call_controller) and passed in

Why manual loop over AgentExecutor:
  AgentExecutor doesn't support token-level streaming during the final response,
  which we need for the sentence splitter → TTS prefetch pipeline. The manual loop
  gives us full control: tool calls run synchronously, then the final answer streams.
"""

import json
from typing import AsyncGenerator

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from datetime import datetime

from ..config.env import env
from .tools import ALL_TOOLS
from .logger import SessionLogger


# ── System prompt (customer support persona) ─────────────────────────────────

SYSTEM_PROMPT = """\
You are Flash, a friendly and professional customer support voice assistant.

Your role:
- Help customers check order status, cancel orders, get delivery estimates, and create support tickets.
- You can ONLY help with order-related queries. If the user asks about anything unrelated (weather, math, general knowledge, etc.), politely decline using words to the effect of: "I can only help with order-related queries like checking status, cancellations, or delivery estimates."
- Exception: basic questions about yourself as the assistant (e.g. "what's your name", "are you a bot", "can you hear me") are fine to answer directly and briefly, then steer back to helping with their order. These are not the "unrelated" questions the rule above is about.

Available order IDs in the system: ORD-1001 through ORD-1010.

Conversation rules:
- Respond in 1 to 3 short, spoken sentences. Never more unless the user explicitly asks.
- Do NOT use markdown, bullet points, numbered lists, or any formatting that sounds unnatural aloud.
- Do NOT start with filler phrases like "Certainly!", "Of course!", "Great question!", or "Sure!".
- Be helpful, direct, and conversational — like a knowledgeable support agent, not a robot.
- Keep sentences short. Avoid compound sentences that are hard to parse while listening.

CRITICAL RULES for tool usage:
- NEVER fabricate order data. If a tool returns an error or no data, tell the customer exactly that.
- For cancel_order: You MUST first ask the user to explicitly confirm before calling it with confirmed=true. Say something like "Are you sure you want to cancel order ORD-XXXX?" and ONLY proceed after they say yes.
- If a tool call fails, apologize and offer to create a support ticket to escalate the issue.
- If you don't know the order ID, ask the customer for it.
"""

GREETING_PROMPT = (
    "Greet the user in exactly one warm, natural sentence. "
    "Introduce yourself as Flash, a customer support assistant. "
    "Ask how you can help with their order. Keep it under 15 words."
)

FALLBACK_STT_RESPONSE = "Sorry, I didn't catch that. Could you repeat what you said?"
FALLBACK_ERROR_RESPONSE = "I'm having a technical issue right now. Let me try again — could you repeat that?"
FALLBACK_UNRELATED_RESPONSE = "I can only help with order-related queries like checking status, cancellations, or delivery estimates."


# ── Agent setup ──────────────────────────────────────────────────────────────

def create_agent_llm():
    """Create a ChatGroq LLM with tools bound."""
    llm = ChatGroq(
        model=env.GROQ_MODEL,
        api_key=env.GROQ_API_KEY,
        temperature=0.7,
        max_tokens=200,
    )
    return llm.bind_tools(ALL_TOOLS)


# ── Agent runner (manual tool loop + streaming final answer) ─────────────────

MAX_TOOL_ROUNDS = 3   # prevent infinite tool loops


async def run_agent_streaming(
    conversation_history: list[dict],
    user_text: str | None,
    session_logger: SessionLogger,
) -> AsyncGenerator[str, None]:
    """Run the agent and yield tokens of the final response.

    Args:
        conversation_history: List of {"role": ..., "content": ...} dicts (existing turns)
        user_text: The user's latest message, or None for the greeting turn
        session_logger: SessionLogger instance for structured event logging

    Yields:
        str tokens of the agent's final text response (for sentence splitting → TTS)
    """
    llm = create_agent_llm()

    # Build LangChain message list from conversation history
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    for msg in conversation_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    # Add the current turn
    if user_text is None:
        messages.append(HumanMessage(content=GREETING_PROMPT))
    else:
        messages.append(HumanMessage(content=user_text))

    # ── Agent loop: invoke → tool calls → re-invoke → ... → stream final ────
    for _round in range(MAX_TOOL_ROUNDS):
        # Non-streaming invoke to check for tool calls
        response = await llm.ainvoke(messages)
        messages.append(response)  # append AIMessage with tool_calls

        # If no tool calls, this is the final response — stream it
        if not response.tool_calls:
            # Stream the final response token by token
            # We already have the full text from ainvoke, but we need to
            # re-invoke with streaming for token-level output
            messages.pop()  # remove the non-streamed response

            async for chunk in llm.astream(messages):
                if chunk.content:
                    yield chunk.content
            return

        # Execute each tool call
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            await session_logger.log_tool_call(tool_name, tool_args)

            # Find and execute the tool
            tool_fn = _get_tool_by_name(tool_name)
            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(tool_args)
                except Exception as e:
                    result = {"success": False, "data": None, "error": str(e)}
            else:
                result = {"success": False, "data": None, "error": f"Unknown tool: {tool_name}"}

            await session_logger.log_tool_response(tool_name, result)

            # Feed tool result back to the LLM
            messages.append(ToolMessage(
                content=json.dumps(result) if isinstance(result, dict) else str(result),
                tool_call_id=tool_call["id"],
            ))

    # Exhausted MAX_TOOL_ROUNDS without a final answer — stop calling tools
    # and give a deterministic fallback rather than risking another
    # unexecuted tool call from an unbounded extra round.
    await session_logger.log_error("agent", "Exceeded MAX_TOOL_ROUNDS without a final response")
    yield FALLBACK_ERROR_RESPONSE


def _get_tool_by_name(name: str):
    """Look up a tool function by name."""
    for t in ALL_TOOLS:
        if t.name == name:
            return t
    return None
