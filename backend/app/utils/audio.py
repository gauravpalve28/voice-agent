"""
audio.py — Advanced PCM audio processing utilities for the voice agent.

Provides:
  - WAV header construction
  - High-quality 24kHz → 16kHz downsampling (streaming, carry-aware)
  - PCM normalization (prevents clipping and low-volume issues)
  - IIR high-pass filter (removes DC offset, rumble, fan noise below 80Hz)
  - Silence trimming (shrinks WAV payload sent to STT for faster transcription)
  - RMS energy computation (used by VAD / noise gate)
"""

import struct
import math


# ─────────────────────────────────────────────────────────────────────────────
# WAV container builder
# ─────────────────────────────────────────────────────────────────────────────

def build_wav_buffer(
    pcm: bytes,
    sample_rate: int,
    channels: int,
    bit_depth: int,
) -> bytes:
    """Wraps raw PCM bytes in a RIFF/WAV header so any decoder can identify the format."""
    byte_rate   = sample_rate * channels * (bit_depth // 8)
    block_align = channels * (bit_depth // 8)
    data_size   = len(pcm)

    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,
        b'WAVE',
        b'fmt ',
        16,           # subchunk1 size (PCM = 16)
        1,            # audio format  (1 = PCM, uncompressed)
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bit_depth,
        b'data',
        data_size,
    )
    return header + pcm


# ─────────────────────────────────────────────────────────────────────────────
# 24 kHz → 16 kHz downsampler (streaming, linear-interpolation, carry-aware)
# ─────────────────────────────────────────────────────────────────────────────

def downsample24to16(chunk: bytes, carry: bytes) -> tuple[bytes, bytes]:
    """Streaming linear-interpolation downsampler: 24 kHz → 16 kHz.

    Ratio 3:2 — every 3 input samples produce 2 output samples.
    Returns (downsampled_bytes, leftover_carry_for_next_call).

    Performance: uses bulk struct.unpack / struct.pack for maximum throughput.
    """
    data         = carry + chunk
    num_samples  = len(data) // 2
    full_blocks  = num_samples // 3
    bytes_needed = full_blocks * 6          # 3 input samples × 2 bytes each
    new_carry    = data[bytes_needed:]

    if full_blocks == 0:
        return b'', new_carry

    # Bulk unpack all input 16-bit signed samples at once
    samples = struct.unpack(f'<{full_blocks * 3}h', data[:bytes_needed])

    out_count   = full_blocks * 2
    out_samples = [0] * out_count

    for b in range(full_blocks):
        i = b * 3
        o = b * 2
        s0, s1, s2 = samples[i], samples[i + 1], samples[i + 2]
        # First output: take sample 0 directly (no interpolation needed)
        out_samples[o]     = s0
        # Second output: linear interpolation between s1 and s2
        out_samples[o + 1] = (s1 + s2) >> 1   # integer divide by 2

    return struct.pack(f'<{out_count}h', *out_samples), new_carry


# ─────────────────────────────────────────────────────────────────────────────
# RMS energy — noise gate / VAD helper
# ─────────────────────────────────────────────────────────────────────────────

def compute_rms(data: bytes) -> float:
    """Compute Root Mean Square energy of 16-bit PCM data.

    Returns a float in [0, 32767]. Values below ~200 indicate near-silence.
    Used as a fast pre-filter before invoking the STT API.
    """
    if len(data) < 2:
        return 0.0
    num_samples = len(data) // 2
    samples     = struct.unpack(f'<{num_samples}h', data[:num_samples * 2])
    mean_sq     = sum(s * s for s in samples) / num_samples
    return math.sqrt(mean_sq)


# ─────────────────────────────────────────────────────────────────────────────
# IIR single-pole high-pass filter  (removes DC offset, rumble, fan noise)
# ─────────────────────────────────────────────────────────────────────────────

def high_pass_filter_pcm(
    data: bytes,
    sample_rate: int = 16_000,
    cutoff_hz: float = 80.0,
) -> bytes:
    """Apply a 1st-order IIR high-pass filter to raw 16-bit signed PCM.

    Removes:
      - DC offset (0 Hz bias from some microphones)
      - Low-frequency rumble (HVAC, traffic, desk vibration)
      - Fan hum below cutoff_hz

    Default cutoff: 80 Hz  — safe for all voice frequencies (voice: 100-8000 Hz).
    Adds negligible latency (single-sample filter delay).
    """
    if len(data) < 2:
        return data

    # Compute RC coefficient: alpha = RC / (RC + 1/sample_rate)
    rc    = 1.0 / (2.0 * math.pi * cutoff_hz)
    dt    = 1.0 / sample_rate
    alpha = rc / (rc + dt)           # typically ~0.969 at 80 Hz / 16 kHz

    num_samples = len(data) // 2
    samples     = struct.unpack(f'<{num_samples}h', data[:num_samples * 2])

    out     = [0] * num_samples
    prev_in = samples[0]
    prev_out = samples[0]

    for i, s in enumerate(samples):
        filtered   = alpha * (prev_out + s - prev_in)
        clamped    = max(-32768, min(32767, int(filtered)))
        out[i]     = clamped
        prev_in    = s
        prev_out   = filtered

    return struct.pack(f'<{num_samples}h', *out)


# ─────────────────────────────────────────────────────────────────────────────
# PCM normalization — prevents clipping and boosts quiet recordings
# ─────────────────────────────────────────────────────────────────────────────

def normalize_pcm(data: bytes, target_peak: int = 24_000) -> bytes:
    """Normalize 16-bit signed PCM to a target peak amplitude.

    Scales all samples so that the peak absolute value equals `target_peak`.
    Prevents:
      - Audio clipping when recording is too loud
      - STT misses when recording is too quiet

    Default target_peak: 24000 (~73% of 32767 full-scale) — headroom for TTS mixing.
    If the audio is near-silence (peak < 100), returns unchanged (avoid amplifying noise).
    """
    if len(data) < 2:
        return data

    num_samples = len(data) // 2
    samples     = struct.unpack(f'<{num_samples}h', data[:num_samples * 2])

    peak = max(abs(s) for s in samples)
    if peak < 100:                       # near-silence — don't amplify noise floor
        return data

    scale = target_peak / peak
    if abs(scale - 1.0) < 0.02:         # within 2% — skip processing overhead
        return data

    out = [max(-32768, min(32767, int(s * scale))) for s in samples]
    return struct.pack(f'<{num_samples}h', *out)


# ─────────────────────────────────────────────────────────────────────────────
# Silence trimmer — reduces WAV payload size sent to STT
# ─────────────────────────────────────────────────────────────────────────────

def trim_silence_pcm(
    data: bytes,
    threshold: int   = 150,
    frame_ms: int    = 20,
    sample_rate: int = 16_000,
    keep_padding_ms: int = 50,
) -> bytes:
    """Trim leading and trailing silence from 16-bit signed PCM.

    Operates on fixed-size frames (default 20ms). A frame is considered
    'silent' if its peak amplitude is below `threshold`.

    Keeps `keep_padding_ms` of silence at the start and end to preserve
    natural speech onset/offset — avoids cutting off the first/last word.

    Benefits:
      - Reduces WAV bytes sent to STT API → shorter round-trip time.
      - Prevents hallucinated transcriptions from long silence segments.
    """
    if len(data) < 2:
        return data

    samples_per_frame = int(sample_rate * frame_ms / 1000)
    bytes_per_frame   = samples_per_frame * 2
    num_samples       = len(data) // 2

    if num_samples < samples_per_frame * 2:
        return data  # too short to trim

    frames      = []
    num_frames  = num_samples // samples_per_frame
    raw_samples = struct.unpack(f'<{num_frames * samples_per_frame}h',
                                data[:num_frames * samples_per_frame * 2])

    for f in range(num_frames):
        start = f * samples_per_frame
        frame = raw_samples[start:start + samples_per_frame]
        peak  = max(abs(s) for s in frame)
        frames.append((peak, data[f * bytes_per_frame:(f + 1) * bytes_per_frame]))

    # Find first and last active frames
    first_active = next((i for i, (p, _) in enumerate(frames) if p >= threshold), None)
    last_active  = next((i for i, (p, _) in enumerate(reversed(frames)) if p >= threshold), None)

    if first_active is None:
        return data  # entire audio is silence — return as-is for STT to handle

    last_active  = num_frames - 1 - last_active

    # Add padding frames
    padding_frames = max(1, int(keep_padding_ms / frame_ms))
    first_keep     = max(0, first_active - padding_frames)
    last_keep      = min(num_frames - 1, last_active + padding_frames)

    trimmed = b''.join(f for _, f in frames[first_keep:last_keep + 1])

    # Only return trimmed if we actually saved > 10% — avoids overhead for marginal gains
    if len(trimmed) < len(data) * 0.9:
        return trimmed
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Full pre-processing pipeline for STT input
# ─────────────────────────────────────────────────────────────────────────────

def preprocess_for_stt(
    pcm: bytes,
    sample_rate: int = 16_000,
) -> bytes:
    """Apply the full DSP chain to PCM before STT transcription.

    Chain:
      1. High-pass filter (remove DC / rumble below 80 Hz)
      2. Normalize (boost quiet recordings, prevent clipping)
      3. Trim silence (shrink payload, reduce hallucinations)

    Returns processed PCM bytes (same format: 16-bit signed LE mono).
    """
    if len(pcm) < 4:
        return pcm

    pcm = high_pass_filter_pcm(pcm, sample_rate)
    pcm = normalize_pcm(pcm)
    pcm = trim_silence_pcm(pcm, sample_rate=sample_rate)
    return pcm
