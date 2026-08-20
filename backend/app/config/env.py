import os
from dotenv import load_dotenv

load_dotenv()


class _Env:
    PORT: int = int(os.getenv('PORT', '8000'))
    GROQ_API_KEY: str = os.getenv('GROQ_API_KEY', '')
    GROQ_BASE_URL: str = os.getenv('GROQ_BASE_URL', 'https://api.groq.com/openai/v1')
    GROQ_MODEL: str = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')
    GLADIA_API_KEY: str = os.getenv('GLADIA_API_KEY', '')

    # ElevenLabs (TTS)
    ELEVENLABS_API_KEY: str = os.getenv('ELEVENLABS_API_KEY', '')
    ELEVENLABS_VOICE_ID: str = os.getenv('ELEVENLABS_VOICE_ID', 'nPczCjzI2devNBz1zQrb')

    # Lemonfox (TTS + STT) — ElevenLabs- and OpenAI-compatible, $2.50/1M chars
    LEMONFOX_API_KEY: str = os.getenv('LEMONFOX_API_KEY', '')
    LEMONFOX_VOICE: str = os.getenv('LEMONFOX_VOICE', 'adam')
    LEMONFOX_LANGUAGE: str = os.getenv('LEMONFOX_LANGUAGE', 'en')
    # MUST be 'pcm' — Lemonfox returns raw 24 kHz PCM, downsampled to 16 kHz before sending
    # to the client. Do NOT use 'pcm_16000' (ElevenLabs-only format, unsupported by Lemonfox).
    LEMONFOX_RESPONSE_FORMAT: str = os.getenv('LEMONFOX_RESPONSE_FORMAT', 'pcm')
    LEMONFOX_SPEED: float = float(os.getenv('LEMONFOX_SPEED', '1.0'))
    # Use 'https://eu-api.lemonfox.ai' for EU-based processing (+20% surcharge)
    LEMONFOX_BASE_URL: str = os.getenv('LEMONFOX_BASE_URL', 'https://api.lemonfox.ai')
    # Full language name for STT, e.g. 'english', 'french'. Empty = auto-detect.
    LEMONFOX_STT_LANGUAGE: str = os.getenv('LEMONFOX_STT_LANGUAGE', 'english')

    # Comma-separated API keys seeded into the registry on startup (survive restarts)
    SEEDED_API_KEYS: str = os.getenv('SEEDED_API_KEYS', '')


env = _Env()
