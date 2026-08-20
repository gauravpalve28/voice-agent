import secrets
from datetime import datetime, timezone
from typing import Optional, TypedDict

from .env import env


class AppConfig(TypedDict):
    app_id: str
    api_key: str
    name: str
    created_at: str


_APP_REGISTRY: dict[str, AppConfig] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Default demo apps ─────────────────────────────────────────────────────────

_APP_REGISTRY['nue_demo_key_change_me_in_production'] = AppConfig(
    app_id='demo-app',
    api_key='nue_demo_key_change_me_in_production',
    name='Demo Application',
    created_at=_now(),
)

_APP_REGISTRY['content_iq_voice_key_2024_xyz'] = AppConfig(
    app_id='content-iq',
    api_key='content_iq_voice_key_2024_xyz',
    name='Content IQ',
    created_at=_now(),
)

# ── Seed API keys from env (survive server restarts) ─────────────────────────
if env.SEEDED_API_KEYS:
    for _i, _raw_key in enumerate(env.SEEDED_API_KEYS.split(',')):
        _key = _raw_key.strip()
        if not _key:
            continue
        _APP_REGISTRY[_key] = AppConfig(
            app_id=f'seeded-app-{_i + 1}',
            api_key=_key,
            name=f'Seeded App {_i + 1}',
            created_at=_now(),
        )
    print(f'[apps] Seeded {len(env.SEEDED_API_KEYS.split(","))} API key(s) from env')


# ── CRUD operations ───────────────────────────────────────────────────────────

def get_app_by_api_key(api_key: str) -> Optional[AppConfig]:
    return _APP_REGISTRY.get(api_key)


def create_app(name: str) -> AppConfig:
    app = AppConfig(
        app_id=f'app_{secrets.token_hex(8)}',
        api_key=f'nue_{secrets.token_hex(20)}',
        name=name,
        created_at=_now(),
    )
    _APP_REGISTRY[app['api_key']] = app
    return app


def delete_app(api_key: str) -> bool:
    return _APP_REGISTRY.pop(api_key, None) is not None


def list_apps() -> list[dict]:
    return [
        {'app_id': app['app_id'], 'name': app['name'], 'created_at': app['created_at']}
        for app in _APP_REGISTRY.values()
    ]
