import os

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, WebSocket

from ..config.apps import create_app, delete_app, get_app_by_api_key, list_apps
from ..controllers.stt import stt_handler
from ..controllers.tts import TTSRequest, tts_handler
from ..controllers.call_controller import call_controller
from ..controllers.voice_stream import voice_stream_controller
from ..middleware.auth import require_api_key, validate_api_key

router = APIRouter()


# ── REST: STT + TTS ───────────────────────────────────────────────────────────

@router.post('/stt')
async def stt_route(
    request: Request,
    client_app: dict = Depends(require_api_key),
):
    return await stt_handler(request)


@router.post('/tts')
async def tts_route(
    body: TTSRequest,
    client_app: dict = Depends(require_api_key),
):
    return await tts_handler(body)


# ── WebSocket: Full pipeline (STT → OpenAI → TTS) ────────────────────────────

@router.websocket('/call')
async def call_ws(
    websocket: WebSocket,
    lang: str = 'english',
):
    print(f'[WS:/call] connect lang={lang}')
    await websocket.accept()
    await call_controller(websocket, lang)


# ── WebSocket: STT + TTS only (bring-your-own LLM) ───────────────────────────

@router.websocket('/voice')
async def voice_ws(
    websocket: WebSocket,
    apiKey: str = '',
    lang: str = 'english',
):
    is_valid = validate_api_key(apiKey)
    print(f'[WS:/voice] connect apiKey={apiKey} valid={is_valid}')

    await websocket.accept()

    if not is_valid:
        await websocket.close(code=1008, reason='Invalid API key')
        return

    await voice_stream_controller(websocket, lang)


@router.websocket('/voice-stream')
async def voice_stream_ws(
    websocket: WebSocket,
    apiKey: str = '',
    lang: str = 'english',
):
    is_valid = validate_api_key(apiKey)
    print(f'[WS:/voice-stream] connect apiKey={apiKey} valid={is_valid} lang={lang}')

    await websocket.accept()

    if not is_valid:
        await websocket.close(code=1008, reason='Invalid API key')
        return

    await voice_stream_controller(websocket, lang)


# ── Admin: App management ─────────────────────────────────────────────────────

@router.post('/apps', status_code=201)
async def create_app_route(body: dict = Body(...)):
    name = (body.get('name') or '').strip()
    if not name:
        raise HTTPException(
            status_code=400,
            detail={'error': 'BAD_REQUEST', 'message': '"name" is required.'},
        )
    return create_app(name)


@router.get('/apps')
async def list_apps_route():
    return list_apps()


@router.delete('/apps/{api_key}', status_code=204)
async def delete_app_route(api_key: str):
    deleted = delete_app(api_key)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={'error': 'NOT_FOUND', 'message': 'App not found.'},
        )
    return Response(status_code=204)
