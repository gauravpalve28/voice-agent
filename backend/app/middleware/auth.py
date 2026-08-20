import os
from typing import Optional

from fastapi import Header, Query, HTTPException

from ..config.apps import get_app_by_api_key


async def require_api_key(
    x_api_key: Optional[str] = Header(None, alias='X-API-Key'),
    apiKey: Optional[str] = Query(None),
) -> dict:
    """FastAPI dependency — validates the API key on REST endpoints.

    Accepts the key from either:
      - HTTP header:  X-API-Key: nue_xxxx
      - Query param:  ?apiKey=nue_xxxx

    Checks (in order):
      1. In-memory app registry (createApp / POST /api/apps)
      2. SEEDED_API_KEYS env var (comma-separated list, survives restarts)
    """
    api_key = x_api_key or apiKey

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={
                'error': 'UNAUTHORIZED',
                'message': 'Missing API key. Pass X-API-Key header or ?apiKey= query param.',
            },
        )

    app = get_app_by_api_key(api_key)
    if app:
        return dict(app)

    seeded_keys = [k.strip() for k in os.getenv('SEEDED_API_KEYS', '').split(',') if k.strip()]
    if api_key in seeded_keys:
        return {'app_id': 'seeded', 'api_key': api_key, 'name': 'Seeded App'}

    raise HTTPException(
        status_code=401,
        detail={'error': 'UNAUTHORIZED', 'message': 'Invalid API key.'},
    )


def validate_api_key(api_key: str) -> bool:
    """Synchronous key check for WebSocket auth (before accept)."""
    if not api_key:
        return False
    if get_app_by_api_key(api_key):
        return True
    seeded_keys = [k.strip() for k in os.getenv('SEEDED_API_KEYS', '').split(',') if k.strip()]
    return api_key in seeded_keys
