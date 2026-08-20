import httpx
from fastapi import HTTPException, Response
from pydantic import BaseModel
from typing import Optional

from ..config.env import env
from ..utils.audio import build_wav_buffer


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    language: Optional[str] = None
    speed: Optional[float] = None


async def tts_handler(body: TTSRequest) -> Response:
    """POST /api/tts

    Accepts text and returns synthesized speech as a WAV file (24 kHz, mono).

    Request:
      Content-Type: application/json
      X-API-Key:    nue_xxxx
      Body: {
        "text":     "Text to synthesize",   // required
        "voice":    "santa",                // optional, default from env
        "language": "en-us",               // optional, default from env
        "speed":    1.0                    // optional, default from env
      }

    Response:
      Content-Type: audio/wav
      Body: WAV audio binary (24 kHz, 16-bit, mono)
    """
    if not body.text.strip():
        raise HTTPException(
            status_code=400,
            detail={
                'error': 'BAD_REQUEST',
                'message': 'Request body must include a non-empty "text" field.',
            },
        )

    voice = body.voice or env.LEMONFOX_VOICE
    language = body.language or env.LEMONFOX_LANGUAGE
    speed = body.speed if body.speed is not None else env.LEMONFOX_SPEED

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f'{env.LEMONFOX_BASE_URL}/v1/audio/speech',
                headers={
                    'Authorization': f'Bearer {env.LEMONFOX_API_KEY}',
                    'Content-Type': 'application/json',
                },
                json={
                    'input': body.text.strip(),
                    'voice': voice,
                    'language': language,
                    'response_format': 'pcm',   # 24 kHz raw PCM from Lemonfox
                    'speed': speed,
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                'error': 'TTS_UNAVAILABLE',
                'message': f'Could not reach Lemonfox TTS: {exc}',
            },
        )

    if not response.is_success:
        raise HTTPException(
            status_code=502,
            detail={
                'error': 'TTS_FAILED',
                'message': f'Lemonfox TTS returned {response.status_code}: {response.text}',
            },
        )

    pcm_buffer = response.content
    # Wrap PCM in WAV header so clients can play it directly (24 kHz, mono, 16-bit)
    wav_buffer = build_wav_buffer(pcm_buffer, 24_000, 1, 16)

    return Response(
        content=wav_buffer,
        media_type='audio/wav',
        headers={'Content-Disposition': 'inline; filename="speech.wav"'},
    )
