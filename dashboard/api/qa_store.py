"""Redis-backed QA conversation store.

QA history is intentionally separate from the dashboard cache. Unlike cached
aggregations, multi-turn QA requires a real shared Redis backend; if Redis is
missing or unreachable, the QA feature is unavailable instead of falling back to
process memory.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover - dependency is declared in pyproject
    redis = None  # type: ignore


DEFAULT_QA_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_CONTEXT_PAIRS = 10
DEFAULT_MAX_MESSAGES = 200
KEY_PREFIX = 'dashboard:qa:'


class QAStoreUnavailableError(Exception):
    """QA session storage is not configured or unavailable."""


def qa_ttl_seconds() -> int:
    return _int_env('DASHBOARD_QA_SESSION_TTL_SECONDS', DEFAULT_QA_TTL_SECONDS)


def qa_context_pairs() -> int:
    return _int_env('DASHBOARD_QA_CONTEXT_PAIRS', DEFAULT_CONTEXT_PAIRS)


def qa_max_messages() -> int:
    return _int_env('DASHBOARD_QA_MAX_MESSAGES', DEFAULT_MAX_MESSAGES)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class RedisQAStore:
    def __init__(self, client):
        self._r = client

    def ping(self) -> None:
        self._call(self._r.ping)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        raw = self._call(self._r.get, _session_key(session_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def save_session(self, session: dict[str, Any]) -> None:
        ttl = qa_ttl_seconds()
        session_id = str(session['session_id'])
        payload = json.dumps(session, ensure_ascii=False, separators=(',', ':'))
        score = float(session.get('updated_ts') or time.time())
        self._call(self._r.setex, _session_key(session_id), ttl, payload)
        self._call(self._r.zadd, _sessions_key(), {session_id: score})
        self._call(self._r.expire, _sessions_key(), ttl)
        self._prune_index(score - ttl)
        self.refresh(session_id)

    def append_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        if not messages:
            return
        key = _messages_key(session_id)
        payloads = [json.dumps(item, ensure_ascii=False, separators=(',', ':')) for item in messages]
        self._call(self._r.rpush, key, *payloads)
        self._call(self._r.ltrim, key, -qa_max_messages(), -1)
        self._call(self._r.expire, key, qa_ttl_seconds())

    def load_messages(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        key = _messages_key(session_id)
        if limit is None:
            raw_items = self._call(self._r.lrange, key, 0, -1)
        else:
            raw_items = self._call(self._r.lrange, key, -max(1, limit), -1)
        out: list[dict[str, Any]] = []
        for raw in raw_items or []:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        if out:
            self.refresh(session_id)
        return out

    def list_sessions(self, limit: int) -> list[dict[str, Any]]:
        now = time.time()
        self._prune_index(now - qa_ttl_seconds())
        session_ids = self._call(self._r.zrevrange, _sessions_key(), 0, max(0, limit - 1)) or []
        sessions: list[dict[str, Any]] = []
        missing: list[str] = []
        for session_id in session_ids:
            session = self.load_session(str(session_id))
            if session is None:
                missing.append(str(session_id))
                continue
            sessions.append(session)
        if missing:
            self._call(self._r.zrem, _sessions_key(), *missing)
        return sessions

    def refresh(self, session_id: str) -> None:
        ttl = qa_ttl_seconds()
        self._call(self._r.expire, _session_key(session_id), ttl)
        self._call(self._r.expire, _messages_key(session_id), ttl)

    def _prune_index(self, older_than_ts: float) -> None:
        self._call(self._r.zremrangebyscore, _sessions_key(), 0, older_than_ts)

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if redis is not None and isinstance(exc, redis.RedisError):
                raise QAStoreUnavailableError('QA 会话功能需要可用的 Redis') from exc
            raise


_store: RedisQAStore | None = None
_store_url: str | None = None


def get_qa_store() -> RedisQAStore:
    global _store, _store_url
    url = os.getenv('REDIS_URL')
    if not url:
        raise QAStoreUnavailableError('QA 会话功能需要可用的 Redis')
    if redis is None:
        raise QAStoreUnavailableError('QA 会话功能需要 redis Python 包')
    if _store is None or _store_url != url:
        _store = RedisQAStore(redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=2.0))
        _store_url = url
    _store.ping()
    return _store


def _session_key(session_id: str) -> str:
    return KEY_PREFIX + 'session:' + session_id


def _messages_key(session_id: str) -> str:
    return KEY_PREFIX + 'messages:' + session_id


def _sessions_key() -> str:
    return KEY_PREFIX + 'sessions'
