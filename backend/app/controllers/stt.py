import httpx
from fastapi import HTTPException, Request

from ..config.env import env
from ..utils.audio import build_wav_buffer

PCM_SAMPLE_RATE = 16_000
PCM_CHANNELS = 1
PCM_BIT_DEPTH = 16


async def stt_handler(request: Request) -> dict:
    """POST /api/stt

    Accepts a raw audio file (WAV or raw 16 kHz PCM) as the request body
    and returns the transcript as JSON.

    Request:
      Content-Type: audio/wav | audio/pcm | application/octet-stream
      X-API-Key:    nue_xxxx
      ?lang=english (optional, default: english)
      Body: raw audio bytes

    Response:
      { "text": "transcribed text here" }
    """
    audio_buffer = await request.body()

    if not audio_buffer:
        raise HTTPException(
            status_code=400,
            detail={
                'error': 'BAD_REQUEST',
                'message': 'Request body must be a non-empty audio file (WAV or raw PCM).',
            },
        )

    # Detect WAV (RIFF header) vs raw PCM — wrap PCM in WAV if needed
    is_wav = audio_buffer[:4] == b'RIFF'
    wav_buffer = audio_buffer if is_wav else build_wav_buffer(
        audio_buffer, PCM_SAMPLE_RATE, PCM_CHANNELS, PCM_BIT_DEPTH
    )

    lang = request.query_params.get('lang', 'english')

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f'{env.LEMONFOX_BASE_URL}/v1/audio/transcriptions',
                headers={'Authorization': f'Bearer {env.LEMONFOX_API_KEY}'},
                files={'file': ('audio.wav', wav_buffer, 'audio/wav')},
                data={'language': lang, 'response_format': 'json'},
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                'error': 'STT_UNAVAILABLE',
                'message': f'Could not reach Lemonfox STT: {exc}',
            },
        )

    if not response.is_success:
        raise HTTPException(
            status_code=502,
            detail={
                'error': 'STT_FAILED',
                'message': f'Lemonfox STT returned {response.status_code}: {response.text}',
            },
        )

    data = response.json()
    transcript = (data.get('text') or '').strip()
    return {'text': transcript}
