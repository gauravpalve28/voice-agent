import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Ensure stdout and stderr use UTF-8 encoding on Windows to prevent UnicodeEncodeError
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config.env import env
from .routes.voice import router as voice_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: validate required API keys
    missing = []
    if not env.GROQ_API_KEY:
        missing.append('GROQ_API_KEY')
    if not env.LEMONFOX_API_KEY:
        missing.append('LEMONFOX_API_KEY')
    if missing:
        raise RuntimeError(
            f'Missing required environment variables: {", ".join(missing)}. '
            'Set them in backend/.env before starting.'
        )
    print('[startup] Config OK - Groq + Lemonfox keys present')
    yield


app = FastAPI(title='Voice Bot API', version='1.0.0', lifespan=lifespan)

# CORS: allow all origins so external apps can call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['GET', 'POST', 'DELETE', 'OPTIONS'],
    allow_headers=['Content-Type', 'X-API-Key', 'Authorization'],
)

# Routes
app.include_router(voice_router, prefix='/api')


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'timestamp': datetime.now(timezone.utc).isoformat()}
