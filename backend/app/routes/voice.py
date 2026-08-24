from fastapi import APIRouter, HTTPException, WebSocket

from ..controllers.call_controller import call_controller
from ..agent.db import get_db

router = APIRouter()


# ── Conversation trace / logging ──────────────────────────────────────────────

@router.get('/sessions')
async def list_sessions():
    """List recent conversation sessions (most recent first, max 20)."""
    db = await get_db()
    sessions = await db.conversation_logs.find(
        {}, {"session_id": 1, "started_at": 1, "updated_at": 1, "_id": 0}
    ).sort("started_at", -1).limit(20).to_list(20)
    return {"sessions": sessions}


@router.get('/sessions/{session_id}')
async def get_session_trace(session_id: str):
    """Get the full conversation trace for a session."""
    db = await get_db()
    doc = await db.conversation_logs.find_one(
        {"session_id": session_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return doc



# ── WebSocket: Full pipeline (STT → Agent → TTS) ─────────────────────────────

@router.websocket('/call')
async def call_ws(
    websocket: WebSocket,
    lang: str = 'english',
):
    print(f'[WS:/call] connect lang={lang}')
    await websocket.accept()
    await call_controller(websocket, lang)
