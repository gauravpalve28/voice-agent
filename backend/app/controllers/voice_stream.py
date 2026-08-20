"""
voice_stream.py — Streaming controller for bring-your-own-LLM clients.

Provides raw audio-to-text (STT) and text-to-audio (TTS) pipelines over a
single WebSocket interface without integrated LLM flow.
"""

import asyncio
import json
import struct
import time
from typing import Optional

import httpx
from fastapi import WebSocket, WebSocketDisconnect

from ..config.env import env
from ..utils.audio import (
    build_wav_buffer,
    compute_rms,
    downsample24to16,
    preprocess_for_stt,
)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration constants
# ─────────────────────────────────────────────────────────────────────────────

# Safety-net timeout. Micdrop VAD fires StopSpeaking at ~700ms silence.
SILENCE_TIMEOUT_MS    = 1200

# Fast energy gate
RMS_NOISE_FLOOR       = 60
SPEECH_THRESHOLD      = 300
MIN_SAMPLES_ABOVE     = 15

# PCM format
PCM_SAMPLE_RATE       = 16_000
PCM_CHANNELS          = 1
PCM_BIT_DEPTH         = 16

# TTS read timeout
TTS_READ_TIMEOUT      = 20.0

# Calibrated Whisper prompt
_STT_INITIAL_PROMPT = (
    "Transcript of a voice conversation with an AI assistant. "
    "The speaker uses natural conversational English. "
    "If there is only background noise, breathing, or silence, return empty. "
    "Do not invent words, greetings, or filler phrases."
)


# ─────────────────────────────────────────────────────────────────────────────
# Fast energy-gate speech detector
# ─────────────────────────────────────────────────────────────────────────────

def _has_speech(data: bytes) -> bool:
    """Fast two-stage energy and peak amplitude speech detector."""
    if len(data) < 4:
        return False

    num_samples = len(data) // 2
    probe_count = min(num_samples, 200)
    probe       = struct.unpack(f'<{probe_count}h', data[:probe_count * 2])
    rms_sq      = sum(s * s for s in probe) / probe_count
    import math
    if math.sqrt(rms_sq) < RMS_NOISE_FLOOR:
        return False

    all_samples = struct.unpack(f'<{num_samples}h', data[:num_samples * 2])
    hits = 0
    for s in all_samples:
        if abs(s) > SPEECH_THRESHOLD:
            hits += 1
            if hits >= MIN_SAMPLES_ABOVE:
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Controller implementation
# ─────────────────────────────────────────────────────────────────────────────

async def voice_stream_controller(websocket: WebSocket, lang: str = 'english') -> None:
    # ── Session state ────────────────────────────────────────────────────────
    state              : str                    = 'listening'
    audio_chunks       : list[bytes]            = []
    silence_task       : Optional[asyncio.Task] = None
    queue_task         : Optional[asyncio.Task] = None
    speech_queue       : list[str]              = []
    tts_gen            : int                    = 0
    user_stop_time     : Optional[float]        = None

    # ── Latency metric collection variables ──────────────────────────────────
    stt_latency_ms     : float                  = 0.0
    tts_latency_ms     : float                  = 0.0

    # ── Terminal logging flags ───────────────────────────────────────────────
    user_speaking_logged : bool                 = False
    tts_started_logged   : bool                 = False

    _call_id = f'STREAM-{int(time.monotonic() * 1000) % 100_000:05d}'

    # ── Console logging formatting (ANSI colors + Timestamps) ────────────────
    C_GREEN  = '\033[92m'
    C_CYAN   = '\033[96m'
    C_YELLOW = '\033[93m'
    C_RED    = '\033[91m'
    C_GRAY   = '\033[90m'
    C_RESET  = '\033[0m'
    C_BOLD   = '\033[1m'

    def log_header(tag: str, color: str = C_GREEN) -> None:
        print(f"\n{color}{C_BOLD}[{tag}]{C_RESET}")

    def log_body(text: str, color: str = C_GREEN) -> None:
        print(f"{color}{text}{C_RESET}\n")

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _send_json(data: dict) -> None:
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            pass

    async def _set_state(next_state: str) -> None:
        nonlocal state
        state = next_state
        await _send_json({'type': 'state', 'value': next_state})

    def _cancel_silence_timer() -> None:
        nonlocal silence_task
        if silence_task and not silence_task.done():
            silence_task.cancel()
        silence_task = None

    def _reset_silence_timer() -> None:
        nonlocal silence_task
        _cancel_silence_timer()
        silence_task = asyncio.create_task(_silence_timeout_task())

    async def _silence_timeout_task() -> None:
        try:
            await asyncio.sleep(SILENCE_TIMEOUT_MS / 1000)
            log_header("STT START", C_GRAY)
            log_body("Transcribing audio...", C_GRAY)
            await _trigger_stt()
        except asyncio.CancelledError:
            pass

    # ── STT ──────────────────────────────────────────────────────────────────

    async def _run_stt() -> Optional[str]:
        nonlocal stt_latency_ms
        if not audio_chunks:
            return None

        raw_pcm = b''.join(audio_chunks)
        processed_pcm = preprocess_for_stt(raw_pcm, PCM_SAMPLE_RATE)
        wav = build_wav_buffer(processed_pcm, PCM_SAMPLE_RATE, PCM_CHANNELS, PCM_BIT_DEPTH)

        t_stt = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f'{env.LEMONFOX_BASE_URL}/v1/audio/transcriptions',
                    headers={'Authorization': f'Bearer {env.LEMONFOX_API_KEY}'},
                    files={'file': ('audio.wav', wav, 'audio/wav')},
                    data={
                        'language': lang,
                        'response_format': 'json',
                        'temperature': '0',
                        'initial_prompt': _STT_INITIAL_PROMPT,
                    },
                )

                if not response.is_success:
                    log_header("ERROR", C_RED)
                    log_body(f"STT HTTP {response.status_code}: {response.text[:200]}", C_RED)
                    await _send_json({'type': 'error', 'message': f'STT service error: {response.status_code}'})
                    return None

                data = response.json()
                text = (data.get('text') or '').strip()
                stt_latency_ms = (time.monotonic() - t_stt) * 1000
                return text or None

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_header("ERROR", C_RED)
            log_body(f"STT Exception: {exc}", C_RED)
            await _send_json({'type': 'error', 'message': str(exc)})
            return None

    async def _trigger_stt() -> None:
        nonlocal state, user_stop_time, user_speaking_logged, tts_started_logged
        nonlocal stt_latency_ms, tts_latency_ms
        if state != 'listening':
            return

        has_speech = any(_has_speech(chunk) for chunk in audio_chunks)
        if not has_speech:
            audio_chunks.clear()
            return

        _cancel_silence_timer()
        await _set_state('processing')
        user_stop_time = time.monotonic()

        # Reset per-turn logging metrics
        user_speaking_logged = False
        tts_started_logged   = False
        stt_latency_ms       = 0.0
        tts_latency_ms       = 0.0

        try:
            text = await asyncio.shield(_run_stt())
        except asyncio.CancelledError:
            text = None

        audio_chunks.clear()

        if text:
            log_header("USER", C_GREEN)
            log_body(text, C_GREEN)
            await _send_json({'type': 'transcript', 'text': text, 'isFinal': True})
            await websocket.send_text('Message ' + json.dumps({'role': 'user', 'content': text}))
        
        await _set_state('listening')

    # ── TTS ──────────────────────────────────────────────────────────────────

    async def _synthesize(text: str, gen: int) -> None:
        nonlocal tts_latency_ms
        if gen != tts_gen:
            return

        t_tts = time.monotonic()

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(TTS_READ_TIMEOUT, connect=8.0)
            ) as client:
                async with client.stream(
                    'POST',
                    f'{env.LEMONFOX_BASE_URL}/v1/audio/speech',
                    headers={
                        'Authorization': f'Bearer {env.LEMONFOX_API_KEY}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'input': text,
                        'voice': env.LEMONFOX_VOICE,
                        'language': env.LEMONFOX_LANGUAGE,
                        'response_format': 'pcm',
                        'speed': env.LEMONFOX_SPEED,
                    },
                ) as response:
                    if not response.is_success:
                        await response.aread()
                        log_header("ERROR", C_RED)
                        log_body(f"TTS HTTP {response.status_code}", C_RED)
                        await _send_json({'type': 'error', 'message': f'TTS HTTP {response.status_code}'})
                        return

                    carry = b''
                    first_byte = True
                    total_bytes = 0

                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        if gen != tts_gen:
                            break

                        if first_byte:
                            first_byte = False
                            tts_latency_ms = (time.monotonic() - t_tts) * 1000
                            log_header("AUDIO STREAMING", C_CYAN)
                            log_body("Streaming audio chunks to frontend...", C_CYAN)

                            # Output latency metrics
                            if user_stop_time:
                                total_time_ms = (time.monotonic() - user_stop_time) * 1000
                                log_header("LATENCY", C_YELLOW)
                                print(f"{C_YELLOW}STT: {stt_latency_ms:.0f}ms{C_RESET}")
                                print(f"{C_YELLOW}TTS: {tts_latency_ms:.0f}ms{C_RESET}")
                                print(f"{C_YELLOW}TOTAL: {total_time_ms:.0f}ms{C_RESET}\n")

                        downsampled, carry = downsample24to16(chunk, carry)
                        if downsampled:
                            await websocket.send_bytes(downsampled)
                            total_bytes += len(downsampled)

                    if gen == tts_gen and len(carry) >= 2:
                        await websocket.send_bytes(carry)
                        total_bytes += len(carry)

        except httpx.ReadTimeout:
            pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log_header("ERROR", C_RED)
            log_body(f"TTS Synthesizer error: {exc}", C_RED)
            await _send_json({'type': 'error', 'message': str(exc)})

    async def _process_queue() -> None:
        nonlocal queue_task
        gen = tts_gen
        await _set_state('speaking')

        while speech_queue and gen == tts_gen:
            text = speech_queue.pop(0)
            log_header("ASSISTANT", C_CYAN)
            log_body(text, C_CYAN)
            await websocket.send_text('Message ' + json.dumps({'role': 'assistant', 'content': text}))
            await _synthesize(text, gen)
            gen = tts_gen

        queue_task = None
        if state != 'processing':
            await _set_state('listening')

    async def _start_queue() -> None:
        nonlocal queue_task, tts_started_logged
        log_header("TTS START", C_CYAN)
        log_body("Generating voice audio...", C_CYAN)
        tts_started_logged = True
        if queue_task and not queue_task.done():
            return
        queue_task = asyncio.create_task(_process_queue())

    # ── WebSocket main loop ───────────────────────────────────────────────────

    log_header("WS CONNECTED", C_GREEN)
    log_body("Client connected successfully", C_GREEN)

    await _set_state('listening')

    try:
        while True:
            message = await websocket.receive()

            if message['type'] == 'websocket.disconnect':
                break

            data_bytes: Optional[bytes] = message.get('bytes') or None
            data_text: Optional[str]   = message.get('text')  or None

            if data_bytes:
                if state == 'speaking':
                    log_header("INTERRUPTION DETECTED", C_RED)
                    log_body("User started speaking while assistant talking", C_RED)
                    speech_queue.clear()
                    tts_gen += 1
                    await _set_state('listening')

                elif state == 'processing' and _has_speech(data_bytes):
                    log_header("INTERRUPTION DETECTED", C_RED)
                    log_body("User started speaking while assistant talking", C_RED)
                    audio_chunks.clear()
                    tts_gen += 1
                    await _set_state('listening')

                if state == 'listening':
                    audio_chunks.append(data_bytes)
                    if _has_speech(data_bytes):
                        if not user_speaking_logged:
                            log_header("USER SPEAKING", C_GREEN)
                            log_body("Voice detected from microphone", C_GREEN)
                            user_speaking_logged = True
                        _reset_silence_timer()

            elif data_text:
                if data_text == 'StartSpeaking':
                    if state in ('speaking', 'processing'):
                        log_header("INTERRUPTION DETECTED", C_RED)
                        log_body("User started speaking while assistant talking", C_RED)
                        speech_queue.clear()
                        tts_gen += 1
                        audio_chunks.clear()
                        await _set_state('listening')
                    continue

                if data_text == 'StopSpeaking':
                    log_header("STT START", C_GRAY)
                    log_body("Transcribing audio...", C_GRAY)
                    asyncio.create_task(_trigger_stt())
                    continue

                try:
                    msg = json.loads(data_text)
                except Exception:
                    continue

                msg_type = msg.get('type')

                if msg_type == 'audio_end':
                    log_header("STT START", C_GRAY)
                    log_body("Transcribing audio...", C_GRAY)
                    asyncio.create_task(_trigger_stt())

                elif msg_type == 'speak':
                    text = (msg.get('text') or '').strip()
                    if text:
                        _cancel_silence_timer()
                        speech_queue.append(text)
                        await _start_queue()

                elif msg_type == 'interrupt':
                    log_header("INTERRUPTION DETECTED", C_RED)
                    log_body("Explicit interrupt command received", C_RED)
                    speech_queue.clear()
                    tts_gen += 1
                    audio_chunks.clear()
                    await _set_state('listening')

                elif msg_type == 'stop':
                    tts_gen += 1
                    try:
                        await websocket.close()
                    except Exception:
                        pass
                    break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log_header("ERROR", C_RED)
        log_body(f"WebSocket loop crash: {exc}", C_RED)
    finally:
        _cancel_silence_timer()
        tts_gen += 1
        if queue_task and not queue_task.done():
            queue_task.cancel()
        log_header("WS DISCONNECTED", C_GREEN)
        log_body("Client disconnected", C_GREEN)
