"""
call_controller.py — Ultra-low-latency voice pipeline for the customer support voice agent.

Pipeline:
  WebSocket audio (PCM) → DSP preprocessing → STT (Lemonfox)
  → Groq LLM stream → sentence splitter → concurrent TTS prefetch
  → ordered audio sender → WebSocket PCM → browser speaker

Key design decisions:
  - `tts_gen`: monotonically-increasing generation counter used as a
    lightweight cancellation token. Any task that captures `gen = tts_gen`
    at start time can self-cancel by checking `gen != tts_gen`.
  - Parallel TTS prefetch: as soon as a sentence is split from the LLM
    stream, a background task fetches its TTS audio while the LLM keeps
    streaming the next sentence. This hides TTS latency completely.
  - audio_segments_queue: ordered queue of AudioSegment objects. The
    audio_sender_worker drains them in order, ensuring correct playback
    sequence even when TTS prefetch tasks finish out of order.
  - asyncio.shield() on STT: protects the HTTP request from being
    cancelled mid-flight during barge-in, preventing partial WAV uploads.
"""

import asyncio
import json
import struct
import time
from typing import Optional

import httpx
from fastapi import WebSocket, WebSocketDisconnect

from ..agent.agent import run_agent_streaming, FALLBACK_STT_RESPONSE, FALLBACK_ERROR_RESPONSE
from ..agent.logger import SessionLogger

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

# Safety-net timeout. Micdrop VAD fires StopSpeaking at ~1200ms silence;
# this only triggers if the client never sends StopSpeaking.
SILENCE_TIMEOUT_MS    = 2000

# Fast energy gate: chunk RMS must exceed this before we bother running
# the full speech detection scan. Avoids wasting CPU on pure-silence frames.
RMS_NOISE_FLOOR       = 60

# Samples-above-threshold gate for _has_speech()
# SPEECH_THRESHOLD lowered from 500 → 300: 500 rejected normal conversational
# speech amplitudes from many real microphones.
# MIN_SAMPLES_ABOVE kept at 25 for robust noise rejection.
SPEECH_THRESHOLD      = 300
MIN_SAMPLES_ABOVE     = 15

# PCM format expected by Lemonfox STT (what the browser/Micdrop sends us)
PCM_SAMPLE_RATE       = 16_000
PCM_CHANNELS          = 1
PCM_BIT_DEPTH         = 16

# Minimum audio duration (in bytes) before we bother calling STT.
# Whisper hallucinates on sub-second audio — it produces phantom words
# like "Wow" or "Thanks" from noise. 0.5s at 16kHz/16bit = 16000 bytes.
MIN_AUDIO_BYTES       = 16_000

# TTS HTTP read timeout. Generous to handle slow Lemonfox cold-starts.
TTS_READ_TIMEOUT      = 20.0


# Prompts (STT only — agent prompt lives in agent/agent.py)
# ─────────────────────────────────────────────────────────────────────────────

# Calibrated for conversational English voice input.
_STT_INITIAL_PROMPT = (
    "Transcript of a voice conversation with a customer support agent. "
    "The speaker uses natural conversational English. "
    "Common topics include orders, deliveries, cancellations, and support tickets."
)


# ─────────────────────────────────────────────────────────────────────────────
# Fast energy-gate speech detector
# ─────────────────────────────────────────────────────────────────────────────

def _has_speech(data: bytes) -> bool:
    """Return True if `data` contains likely human speech.

    Two-stage gate:
    1. Fast RMS check — reject frames below noise floor (avoids scanning silence).
    2. Sample-level amplitude scan — require MIN_SAMPLES_ABOVE consecutive peaks.

    Bulk struct.unpack for performance on large chunks.
    """
    if len(data) < 4:
        return False

    num_samples = len(data) // 2
    # Stage 1: quick RMS check using first 200 samples
    probe_count = min(num_samples, 200)
    probe       = struct.unpack(f'<{probe_count}h', data[:probe_count * 2])
    rms_sq      = sum(s * s for s in probe) / probe_count
    import math
    if math.sqrt(rms_sq) < RMS_NOISE_FLOOR:
        return False

    # Stage 2: count samples exceeding threshold
    all_samples = struct.unpack(f'<{num_samples}h', data[:num_samples * 2])
    hits = 0
    for s in all_samples:
        if abs(s) > SPEECH_THRESHOLD:
            hits += 1
            if hits >= MIN_SAMPLES_ABOVE:
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Audio segment — carries async TTS PCM queue for one sentence
# ─────────────────────────────────────────────────────────────────────────────

class AudioSegment:
    """Represents a single TTS sentence being fetched asynchronously.

    The `queue` receives PCM byte chunks as they stream from TTS.
    A None sentinel signals that the segment is complete (or errored).
    """
    __slots__ = ('queue', 'text_preview')

    def __init__(self, text_preview: str = ''):
        self.queue        : asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=256)
        self.text_preview : str = text_preview


# ─────────────────────────────────────────────────────────────────────────────
# LLM token → sentence splitter (async generator)
# ─────────────────────────────────────────────────────────────────────────────

async def stream_sentences(token_gen):
    """Split a streaming token generator into complete, TTS-ready sentences.

    Yielding strategy (in priority order):
    1. Sentence-ending punctuation (. ! ? newline) followed by whitespace.
    2. Clause boundaries (, ; :) when buffer exceeds 120 chars (faster first audio).
    3. Remaining buffer after token stream ends.

    Abbreviation guard: skips splits after common abbreviations (Mr., Dr., etc.)
    to avoid cutting mid-title.
    """
    SENT_END   = frozenset('.?!\n')
    CLAUSE_END = frozenset(',;:')
    ABBREVS    = frozenset({
        'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'vs',
        'eg', 'ie', 'etc', 'approx', 'fig', 'est',
    })
    CLAUSE_MIN_LEN = 120    # chars before we split at clause boundaries

    buf = ''

    async for delta in token_gen:
        if not delta:
            continue
        buf += delta

        # ── Sentence-boundary scan ───────────────────────────────────────────
        i = 0
        while i < len(buf):
            ch = buf[i]
            if ch in SENT_END:
                # Abbreviation guard: check the word immediately before the dot
                if ch == '.':
                    word_start = i - 1
                    while word_start >= 0 and buf[word_start].isalpha():
                        word_start -= 1
                    word_before = buf[word_start + 1:i].lower()
                    if word_before in ABBREVS:
                        i += 1
                        continue

                # Require whitespace after terminator (or end of buffer)
                is_end   = (i == len(buf) - 1)
                after_ok = (i < len(buf) - 1 and buf[i + 1] in ' \n\r\t')
                if not (is_end or after_ok):
                    i += 1
                    continue

                sentence = buf[:i + 1].strip()
                buf      = buf[i + 1:]
                i        = 0
                if sentence:
                    yield sentence
                continue
            i += 1

        # ── Clause-boundary split for long buffers ───────────────────────────
        if len(buf) > CLAUSE_MIN_LEN:
            for ct in CLAUSE_END:
                idx = buf.find(ct)
                if idx > 30:    # minimum 30 chars so we don't clip very short phrases
                    sentence = buf[:idx + 1].strip()
                    buf      = buf[idx + 1:]
                    if sentence:
                        yield sentence
                    break

    # ── Flush remaining buffer ───────────────────────────────────────────────
    leftover = buf.strip()
    if leftover:
        yield leftover


# ─────────────────────────────────────────────────────────────────────────────
# Main voice pipeline controller
# ─────────────────────────────────────────────────────────────────────────────

async def call_controller(websocket: WebSocket, lang: str = 'english') -> None:
    """Full ultra-low-latency voice pipeline: audio → STT → Agent → TTS → audio."""

    conversation_history : list[dict] = []
    session_logger       = SessionLogger()

    # ── Session mutable state ────────────────────────────────────────────────
    state              : str                      = 'listening'
    audio_chunks       : list[bytes]              = []
    silence_task       : Optional[asyncio.Task]   = None
    tts_gen            : int                      = 0            # cancellation token
    llm_stream_task    : Optional[asyncio.Task]   = None
    audio_sender_task  : Optional[asyncio.Task]   = None
    audio_segments_q   : asyncio.Queue            = asyncio.Queue(maxsize=32)
    user_stop_time     : Optional[float]          = None

    # Post-speaking echo cooldown: after the assistant finishes speaking,
    # the mic picks up residual speaker echo for ~200-400ms before the
    # browser's echoCancellation fully suppresses it. During this window
    # we ignore all incoming audio to prevent phantom STT turns.
    ECHO_COOLDOWN_MS   : float                    = 400.0
    echo_cooldown_until: float                    = 0.0

    # ── Latency metric collection variables ──────────────────────────────────
    stt_latency_ms     : float                    = 0.0
    llm_latency_ms     : float                    = 0.0
    tts_latency_ms     : float                    = 0.0

    # ── Terminal logging flags ───────────────────────────────────────────────
    user_speaking_logged : bool                   = False
    tts_started_logged   : bool                   = False

    _call_id = f'CALL-{int(time.monotonic() * 1000) % 100_000:05d}'

    # ── Console logging formatting (ANSI colors + Timestamps) ────────────────
    C_GREEN  = '\033[92m'
    C_CYAN   = '\033[96m'
    C_YELLOW = '\033[93m'
    C_RED    = '\033[91m'
    C_GRAY   = '\033[90m'
    C_RESET  = '\033[0m'
    C_BOLD   = '\033[1m'

    def _ts() -> str:
        return time.strftime('%H:%M:%S')

    def log_header(tag: str, color: str = C_GREEN) -> None:
        print(f"\n{color}{C_BOLD}[{tag}]{C_RESET}")

    def log_body(text: str, color: str = C_GREEN) -> None:
        print(f"{color}{text}{C_RESET}\n")

    # ─────────────────────────────────────────────────────────────────────────
    # WebSocket helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _send_json(data: dict) -> None:
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            pass

    async def _set_state(next_state: str) -> None:
        nonlocal state
        state = next_state
        await _send_json({'type': 'state', 'value': next_state})

    # ─────────────────────────────────────────────────────────────────────────
    # Silence timer (server-side safety net)
    # ─────────────────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────────
    # Active generation cancellation
    # ─────────────────────────────────────────────────────────────────────────

    def _cancel_active_generation() -> None:
        nonlocal tts_gen, llm_stream_task, audio_sender_task
        old_gen  = tts_gen
        tts_gen += 1

        # Only log cancellation if a previous turn's tasks were actually
        # still running. `state` can't be used here — the caller (e.g.
        # _trigger_stt) has often already flipped it to 'processing' for
        # the CURRENT turn before this runs, which would always look like
        # something was cancelled even on a fresh turn with nothing live.
        had_live_task = (
            (llm_stream_task and not llm_stream_task.done()) or
            (audio_sender_task and not audio_sender_task.done())
        )
        if had_live_task:
            log_header("TASK CANCELLED", C_RED)
            log_body("Previous AI response cancelled successfully", C_RED)

        if llm_stream_task and not llm_stream_task.done():
            llm_stream_task.cancel()
        llm_stream_task = None

        if audio_sender_task and not audio_sender_task.done():
            audio_sender_task.cancel()
        audio_sender_task = None

        # Drain any pending segments from the queue without blocking
        drained = 0
        while True:
            try:
                audio_segments_q.get_nowait()
                audio_segments_q.task_done()
                drained += 1
            except (asyncio.QueueEmpty, ValueError):
                break

    # ─────────────────────────────────────────────────────────────────────────
    # STT
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_stt() -> Optional[str]:
        """Transcribe buffered audio via Lemonfox Whisper STT."""
        nonlocal stt_latency_ms
        if not audio_chunks:
            return None

        raw_pcm = b''.join(audio_chunks)

        # ── DSP pre-processing ───────────────────────────────────────────────
        processed_pcm = preprocess_for_stt(raw_pcm, PCM_SAMPLE_RATE)
        wav = build_wav_buffer(processed_pcm, PCM_SAMPLE_RATE, PCM_CHANNELS, PCM_BIT_DEPTH)

        t_stt = time.monotonic()

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=8.0)
            ) as client:
                response = await client.post(
                    f'{env.LEMONFOX_BASE_URL}/v1/audio/transcriptions',
                    headers={'Authorization': f'Bearer {env.LEMONFOX_API_KEY}'},
                    files={'file': ('audio.wav', wav, 'audio/wav')},
                    data={
                        'language':        lang,
                        'response_format': 'verbose_json',   # returns confidence + segments
                        'temperature':     '0',              # deterministic; fewer hallucinations
                        'initial_prompt':  _STT_INITIAL_PROMPT,
                    },
                )

            if not response.is_success:
                log_header("ERROR", C_RED)
                log_body(f"STT HTTP {response.status_code}: {response.text[:200]}", C_RED)
                await _send_json({'type': 'error', 'message': f'STT error {response.status_code}'})
                return None

            data = response.json()
            text = (data.get('text') or '').strip()
            stt_latency_ms = (time.monotonic() - t_stt) * 1000

            confidence = _extract_confidence(data)
            log_body(f"STT result: '{text}' (confidence={confidence:.2f}, {len(raw_pcm)} bytes)", C_GRAY)

            return text or None

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_header("ERROR", C_RED)
            log_body(f"STT Exception: {exc}", C_RED)
            await _send_json({'type': 'error', 'message': str(exc)})
            return None

    def _extract_confidence(stt_data: dict) -> float:
        """Extract average segment confidence from verbose_json STT response."""
        try:
            segments = stt_data.get('segments') or []
            if not segments:
                return 1.0   # no segments = assume OK
            avg = sum(seg.get('avg_logprob', -0.5) for seg in segments) / len(segments)
            import math
            return min(1.0, math.exp(avg))
        except Exception:
            return 1.0

    async def _trigger_stt() -> None:
        nonlocal state, user_stop_time, user_speaking_logged, tts_started_logged
        nonlocal stt_latency_ms, llm_latency_ms, tts_latency_ms
        if state != 'listening':
            return

        if not audio_chunks:
            return

        raw_audio = b''.join(audio_chunks)

        # Reject audio shorter than 0.5s — Whisper hallucinates on tiny clips
        if len(raw_audio) < MIN_AUDIO_BYTES:
            audio_chunks.clear()
            return

        # Fast RMS gate — skip STT if audio is essentially silence
        rms = compute_rms(raw_audio)
        if rms < RMS_NOISE_FLOOR:
            audio_chunks.clear()
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
        llm_latency_ms       = 0.0
        tts_latency_ms       = 0.0

        try:
            text = await asyncio.shield(_run_stt())
        except asyncio.CancelledError:
            text = None

        audio_chunks.clear()

        if text:
            await _handle_user_turn(text)
        else:
            # STT returned empty — speak fallback instead of going silent
            await _handle_empty_stt()

    # ─────────────────────────────────────────────────────────────────────────
    # TTS concurrent prefetcher
    # ─────────────────────────────────────────────────────────────────────────

    async def _prefetch_tts(text: str, gen: int, segment: AudioSegment) -> None:
        """Stream TTS audio for `text` into `segment.queue`.

        Runs concurrently with sibling prefetch tasks and with the LLM reader.
        Self-cancels if `gen != tts_gen` (stale generation).
        """
        nonlocal tts_latency_ms, tts_started_logged
        if gen != tts_gen:
            await segment.queue.put(None)
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
                        'Content-Type':  'application/json',
                    },
                    json={
                        'input':           text,
                        'voice':           env.LEMONFOX_VOICE,
                        'language':        env.LEMONFOX_LANGUAGE,
                        'response_format': 'pcm',         # 24 kHz raw PCM
                        'speed':           env.LEMONFOX_SPEED,
                    },
                ) as response:

                    if not response.is_success:
                        await response.aread()
                        log_header("ERROR", C_RED)
                        log_body(f"TTS HTTP {response.status_code}", C_RED)
                        await segment.queue.put(None)
                        return

                    carry      = b''
                    first_byte = True

                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        if gen != tts_gen:
                            break

                        if first_byte:
                            first_byte = False
                            # Store TTS first-byte latency of the first prefetch request in this turn
                            if tts_latency_ms == 0.0:
                                tts_latency_ms = (time.monotonic() - t_tts) * 1000

                        downsampled, carry = downsample24to16(chunk, carry)
                        if downsampled:
                            await segment.queue.put(downsampled)

                    # Flush any remaining carry bytes
                    if gen == tts_gen and len(carry) >= 2:
                        await segment.queue.put(carry)

        except httpx.ReadTimeout:
            pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log_header("ERROR", C_RED)
            log_body(f"TTS prefetch exception: {exc}", C_RED)
        finally:
            await segment.queue.put(None)    # always signal completion

    # ─────────────────────────────────────────────────────────────────────────
    # Audio sender (drains segment queue in order → WebSocket)
    # ─────────────────────────────────────────────────────────────────────────

    async def _audio_sender(gen: int) -> None:
        """Drain the ordered segment queue and forward PCM to the client.

        Transitions to 'speaking' on the first byte, then back to 'listening'
        when all segments are exhausted.
        """
        nonlocal echo_cooldown_until
        speaking_started = False
        total_bytes      = 0

        try:
            while gen == tts_gen:
                segment = await audio_segments_q.get()
                audio_segments_q.task_done()

                if segment is None:          # end-of-turn sentinel
                    break

                # Drain one segment
                while gen == tts_gen:
                    try:
                        chunk = await asyncio.wait_for(segment.queue.get(), timeout=TTS_READ_TIMEOUT)
                    except asyncio.TimeoutError:
                        log_header("ERROR", C_RED)
                        log_body(f"Segment queue timeout for: {segment.text_preview[:25]}", C_RED)
                        break

                    if chunk is None:        # segment complete
                        break

                    if gen != tts_gen:
                        break

                    if not speaking_started:
                        await _set_state('speaking')
                        speaking_started = True
                        log_header("AUDIO STREAMING", C_CYAN)
                        log_body("Streaming audio chunks to frontend...", C_CYAN)

                        # Output full latency stats at audio playback start
                        if user_stop_time:
                            total_time_ms = (time.monotonic() - user_stop_time) * 1000
                            log_header("LATENCY", C_YELLOW)
                            print(f"{C_YELLOW}STT: {stt_latency_ms:.0f}ms{C_RESET}")
                            print(f"{C_YELLOW}LLM: {llm_latency_ms:.0f}ms{C_RESET}")
                            print(f"{C_YELLOW}TTS: {tts_latency_ms:.0f}ms{C_RESET}")
                            print(f"{C_YELLOW}TOTAL: {total_time_ms:.0f}ms{C_RESET}\n")

                    try:
                        await websocket.send_bytes(chunk)
                        total_bytes += len(chunk)
                    except Exception as exc:
                        log_header("ERROR", C_RED)
                        log_body(f"WebSocket send_bytes error: {exc}", C_RED)
                        return

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log_header("ERROR", C_RED)
            log_body(f"Audio sender error: {exc}", C_RED)
        finally:
            if gen == tts_gen:
                # Set echo cooldown so the mic ignores residual speaker echo
                echo_cooldown_until = time.monotonic() + (ECHO_COOLDOWN_MS / 1000)
                audio_chunks.clear()   # discard any echo frames buffered during playback
                await _set_state('listening')

    # ─────────────────────────────────────────────────────────────────────────
    # LLM streaming reader
    # ─────────────────────────────────────────────────────────────────────────

    async def _agent_stream_reader(user_text: str | None, gen: int) -> None:
        """Run LangChain agent, stream tokens, split into sentences, prefetch TTS."""
        nonlocal conversation_history, llm_latency_ms

        t_llm = time.monotonic()

        try:
            # Token generator from the LangChain agent
            async def _token_gen():
                nonlocal llm_latency_ms
                first_token = True
                async for token in run_agent_streaming(
                    conversation_history, user_text, session_logger
                ):
                    if gen != tts_gen:
                        break
                    if token:
                        if first_token:
                            first_token = False
                            llm_latency_ms = (time.monotonic() - t_llm) * 1000
                        yield token

            # ── Sentence streaming + concurrent TTS prefetch ─────────────────
            collected_sentences : list[str] = []

            async for sentence in stream_sentences(_token_gen()):
                if gen != tts_gen:
                    break

                collected_sentences.append(sentence)

                seg = AudioSegment(text_preview=sentence)
                asyncio.create_task(_prefetch_tts(sentence, gen, seg))
                await audio_segments_q.put(seg)

            # ── End-of-turn handling ─────────────────────────────────────────
            if gen == tts_gen:
                full_reply = ' '.join(collected_sentences).strip()

                if full_reply:
                    conversation_history.append({'role': 'assistant', 'content': full_reply})
                    if len(conversation_history) > 40:
                        conversation_history = conversation_history[-40:]

                    # Send transcript to frontend conversation panel
                    await websocket.send_text(
                        'Message ' + json.dumps({'role': 'assistant', 'content': full_reply})
                    )
                    log_header("ASSISTANT", C_CYAN)
                    log_body(full_reply, C_CYAN)

                    # Log agent response
                    total_ms = (time.monotonic() - t_llm) * 1000
                    await session_logger.log_agent_response(full_reply, total_ms)

                    await audio_segments_q.put(None)   # end-of-turn sentinel
                else:
                    # Agent produced no text (e.g. empty LLM response) — speak a
                    # fallback instead of leaving the caller with dead air.
                    log_header("AGENT EMPTY", C_YELLOW)
                    log_body("Agent produced no text — speaking fallback", C_YELLOW)
                    await session_logger.log_error("agent", "Empty agent response")

                    seg = AudioSegment(text_preview=FALLBACK_ERROR_RESPONSE)
                    asyncio.create_task(_prefetch_tts(FALLBACK_ERROR_RESPONSE, gen, seg))
                    await audio_segments_q.put(seg)
                    await audio_segments_q.put(None)   # end-of-turn sentinel

        except asyncio.CancelledError:
            try:
                audio_segments_q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        except Exception as exc:
            log_header("ERROR", C_RED)
            log_body(f"Agent stream reader error: {exc}", C_RED)
            await session_logger.log_error("agent", str(exc))

            # Fallback: speak a generic error message instead of crashing
            try:
                seg = AudioSegment(text_preview=FALLBACK_ERROR_RESPONSE)
                asyncio.create_task(_prefetch_tts(FALLBACK_ERROR_RESPONSE, gen, seg))
                await audio_segments_q.put(seg)
                await audio_segments_q.put(None)
            except Exception:
                try:
                    audio_segments_q.put_nowait(None)
                except asyncio.QueueFull:
                    pass

    # ─────────────────────────────────────────────────────────────────────────
    # Turn pipeline
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_user_turn(text: str) -> None:
        conversation_history.append({'role': 'user', 'content': text})
        if len(conversation_history) > 40:
            conversation_history[:] = conversation_history[-40:]

        log_header("USER", C_GREEN)
        log_body(text, C_GREEN)

        # Send user transcript to frontend
        await websocket.send_text(
            'Message ' + json.dumps({'role': 'user', 'content': text})
        )

        # Log user speech
        await session_logger.log_user_speech(text, stt_latency_ms)

        await _start_assistant_turn(user_text=text)

    async def _handle_empty_stt() -> None:
        """Handle empty/unclear STT — speak a fallback instead of going silent."""
        log_header("STT EMPTY", C_YELLOW)
        log_body("No clear speech detected — speaking fallback", C_YELLOW)
        await session_logger.log_error("stt", "Empty or unclear transcription")
        await _start_assistant_turn(user_text=FALLBACK_STT_RESPONSE)

    async def _start_assistant_turn(user_text: Optional[str]) -> None:
        nonlocal llm_stream_task, audio_sender_task
        nonlocal tts_started_logged

        _cancel_active_generation()
        gen = tts_gen

        await _set_state('processing')

        log_header("AGENT START", C_CYAN)
        log_body("Running LangChain agent...", C_CYAN)

        log_header("TTS START", C_CYAN)
        log_body("Generating voice audio...", C_CYAN)
        tts_started_logged = True

        # Launch sender FIRST so it's ready to receive segments immediately
        audio_sender_task  = asyncio.create_task(_audio_sender(gen))
        llm_stream_task = asyncio.create_task(_agent_stream_reader(user_text, gen))

    # ─────────────────────────────────────────────────────────────────────────
    # WebSocket main receive loop
    # ─────────────────────────────────────────────────────────────────────────

    log_header("WS CONNECTED", C_GREEN)
    log_body("Client connected successfully", C_GREEN)

    await session_logger.log_session_start()
    await _start_assistant_turn(None)   # immediate greeting

    try:
        while True:
            message = await websocket.receive()

            if message['type'] == 'websocket.disconnect':
                break

            data_bytes : Optional[bytes] = message.get('bytes') or None
            data_text  : Optional[str]   = message.get('text')  or None

            # ── Echo cooldown check ────────────────────────────────────────
            in_cooldown = time.monotonic() < echo_cooldown_until

            # ── Binary PCM audio frames ──────────────────────────────────────
            if data_bytes:
                if state == 'speaking':
                    # Barge-in: user speaks while AI is playing TTS audio.
                    # This is the ONLY valid barge-in — the user can hear the
                    # audio and is choosing to interrupt it.
                    log_header("INTERRUPTION DETECTED", C_RED)
                    log_body("User started speaking while assistant talking", C_RED)
                    _cancel_active_generation()
                    await _set_state('listening')
                    await session_logger.log_interruption()

                # NOTE: No barge-in during 'processing' state.
                # The user hasn't heard anything yet (LLM/TTS are still
                # generating), so there's nothing to interrupt. Mic noise
                # during this window would just kill the response before
                # the user ever hears it.

                if state == 'listening':
                    # During echo cooldown, silently discard frames — they are
                    # residual speaker output, not real user speech.
                    if in_cooldown:
                        continue

                    audio_chunks.append(data_bytes)
                    if _has_speech(data_bytes):
                        if not user_speaking_logged:
                            log_header("USER SPEAKING", C_GREEN)
                            log_body("Voice detected from microphone", C_GREEN)
                            user_speaking_logged = True
                        _reset_silence_timer()

            # ── Text control messages ────────────────────────────────────────
            elif data_text:

                # Micdrop VAD boundary signals (not JSON)
                if data_text == 'StartSpeaking':
                    # Ignore echo-triggered speech during cooldown
                    if in_cooldown:
                        continue
                    # Only interrupt if the assistant is actively speaking
                    if state == 'speaking':
                        log_header("INTERRUPTION DETECTED", C_RED)
                        log_body("User started speaking while assistant talking", C_RED)
                        _cancel_active_generation()
                        audio_chunks.clear()
                        await _set_state('listening')
                    continue

                if data_text == 'StopSpeaking':
                    # Ignore echo-triggered stop during cooldown
                    if in_cooldown:
                        audio_chunks.clear()
                        continue
                    _cancel_silence_timer()   # prevent double-fire with safety-net
                    log_header("STT START", C_GRAY)
                    log_body("Transcribing audio...", C_GRAY)
                    asyncio.create_task(_trigger_stt())
                    continue

                # JSON messages
                try:
                    msg = json.loads(data_text)
                except Exception:
                    continue

                msg_type = msg.get('type')

                if msg_type == 'audio_end':
                    log_header("STT START", C_GRAY)
                    log_body("Transcribing audio...", C_GRAY)
                    asyncio.create_task(_trigger_stt())

                elif msg_type == 'interrupt':
                    log_header("INTERRUPTION DETECTED", C_RED)
                    log_body("Explicit interrupt command received", C_RED)
                    _cancel_active_generation()
                    audio_chunks.clear()
                    await _set_state('listening')

                elif msg_type == 'stop':
                    _cancel_active_generation()
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
        _cancel_active_generation()
        await session_logger.log_session_end()
        log_header("WS DISCONNECTED", C_GREEN)
        log_body(f"Client disconnected | Session: {session_logger.session_id}", C_GREEN)
