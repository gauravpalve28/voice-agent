"""
logger.py — Structured conversation logging to MongoDB.

Each call/session gets one document in the `conversation_logs` collection
with a timestamped array of events. Event types:

  - user_speech: STT transcript
  - agent_response: Final agent text
  - tool_call: Tool name + arguments
  - tool_response: Tool result
  - error: Any error in the pipeline
  - interruption: User barge-in events
  - session_start / session_end: Call lifecycle
"""

import time
import uuid
from datetime import datetime, timezone
from .db import get_db


class SessionLogger:
    """Logs events for a single voice conversation session."""

    def __init__(self):
        self.session_id = f"sess-{uuid.uuid4().hex[:12]}"
        self.start_time = time.monotonic()
        self.events: list[dict] = []

    def _make_event(self, event_type: str, payload: dict, latency_ms: float | None = None) -> dict:
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        if latency_ms is not None:
            event["latency_ms"] = round(latency_ms, 1)
        return event

    async def log(self, event_type: str, payload: dict, latency_ms: float | None = None):
        """Append an event and persist to MongoDB."""
        event = self._make_event(event_type, payload, latency_ms)
        self.events.append(event)
        try:
            db = await get_db()
            await db.conversation_logs.update_one(
                {"session_id": self.session_id},
                {
                    "$setOnInsert": {
                        "session_id": self.session_id,
                        "started_at": self.events[0]["timestamp"],
                    },
                    "$push": {"events": event},
                    "$set": {"updated_at": event["timestamp"]},
                },
                upsert=True,
            )
        except Exception as e:
            print(f"[logger] Failed to persist event: {e}")

    # ── Convenience methods ──────────────────────────────────────────────────

    async def log_session_start(self):
        await self.log("session_start", {"session_id": self.session_id})

    async def log_session_end(self):
        duration_s = round(time.monotonic() - self.start_time, 1)
        await self.log("session_end", {"duration_seconds": duration_s})

    async def log_user_speech(self, transcript: str, stt_latency_ms: float = 0):
        await self.log("user_speech", {"transcript": transcript}, stt_latency_ms)

    async def log_agent_response(self, text: str, total_latency_ms: float = 0):
        await self.log("agent_response", {"text": text}, total_latency_ms)

    async def log_tool_call(self, tool_name: str, args: dict):
        await self.log("tool_call", {"tool": tool_name, "arguments": args})

    async def log_tool_response(self, tool_name: str, result: dict):
        await self.log("tool_response", {"tool": tool_name, "result": result})

    async def log_error(self, source: str, message: str):
        await self.log("error", {"source": source, "message": message})

    async def log_interruption(self):
        await self.log("interruption", {"description": "User interrupted agent speech"})


# ── Trace exporter ───────────────────────────────────────────────────────────

async def print_conversation_trace(session_id: str):
    """Print a full conversation trace for debugging/demo."""
    db = await get_db()
    doc = await db.conversation_logs.find_one({"session_id": session_id})
    if not doc:
        print(f"No session found with ID: {session_id}")
        return

    print(f"\n{'='*60}")
    print(f"  Session: {doc['session_id']}")
    print(f"  Started: {doc.get('started_at', '?')}")
    print(f"{'='*60}\n")

    for event in doc.get("events", []):
        ts = event["timestamp"][11:19]  # HH:MM:SS
        etype = event["type"]
        payload = event.get("payload", {})
        latency = event.get("latency_ms")
        lat_str = f" ({latency:.0f}ms)" if latency else ""

        if etype == "user_speech":
            print(f"  [{ts}] 👤 USER: \"{payload.get('transcript', '')}\"{lat_str}")
        elif etype == "agent_response":
            print(f"  [{ts}] 🤖 AGENT: \"{payload.get('text', '')}\"{lat_str}")
        elif etype == "tool_call":
            print(f"  [{ts}] 🔧 TOOL CALL: {payload.get('tool', '')}({payload.get('arguments', {})})")
        elif etype == "tool_response":
            result = payload.get("result", {})
            status = "✅" if result.get("success") else "❌"
            print(f"  [{ts}] {status} TOOL RESULT: {payload.get('tool', '')} → {result}")
        elif etype == "error":
            print(f"  [{ts}] ❌ ERROR [{payload.get('source', '')}]: {payload.get('message', '')}")
        elif etype == "interruption":
            print(f"  [{ts}] ⚡ INTERRUPTION")
        elif etype == "session_start":
            print(f"  [{ts}] 📞 SESSION START")
        elif etype == "session_end":
            dur = payload.get("duration_seconds", "?")
            print(f"  [{ts}] 📴 SESSION END (duration: {dur}s)")
        else:
            print(f"  [{ts}] {etype}: {payload}")

    print(f"\n{'='*60}\n")
