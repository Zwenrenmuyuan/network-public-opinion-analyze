"""Dashboard cache 中间件：Redis 主，进程内 dict 降级。

接口：
  - `init_cache(url)`：server 启动时调一次。url 为空或 redis 不可达时落到 InMemoryCache。
  - `get_cache()`：拿当前后端单例。
  - `cached_endpoint(name, ttl=...)`：装饰 endpoint，命中重新 jsonify 出 Response。
  - `clear_cache()`：清空 (Redis 端按 'dashboard:' 前缀 SCAN，不影响其他业务)。

设计：
  - cache 后端故障不阻塞请求：get/set 异常被装饰器吞掉，原 endpoint 照常跑。
  - key = (name, request.path, request.query_string)，参数变化自动落不同 key。
  - value = json dumps 后的字符串；不可序列化静默跳过。
  - TTL 由调用方传，每个 endpoint 可独立。Redis 走 SETEX，dict 走 expire_at 比较。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from flask import jsonify, request

try:
    import redis  # type: ignore
except ImportError:
    redis = None  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_TTL = 300.0
KEY_PREFIX = 'dashboard:'


class TTLCache:
    """后端抽象。"""

    def get(self, key: tuple) -> Any | None:
        raise NotImplementedError

    def set(self, key: tuple, data: Any, ttl: float) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    @property
    def backend_label(self) -> str:
        return type(self).__name__


class InMemoryCache(TTLCache):
    """进程内 dict cache。多 worker 不共享，仅作 fallback。"""

    def __init__(self):
        self._store: dict[tuple, tuple[float, Any]] = {}

    def get(self, key):
        record = self._store.get(key)
        if record is None:
            return None
        expire_at, data = record
        if time.monotonic() > expire_at:
            self._store.pop(key, None)
            return None
        return data

    def set(self, key, data, ttl):
        self._store[key] = (time.monotonic() + ttl, data)

    def clear(self):
        self._store.clear()

    @property
    def backend_label(self) -> str:
        return 'in-memory'


class RedisCache(TTLCache):
    """Redis 后端。key 加 `dashboard:` 前缀；TTL 由 SETEX 处理；
    用 SCAN 而不是 FLUSHDB 清理，避免影响其他库。"""

    def __init__(self, client):
        self._r = client

    def _serialize_key(self, key: tuple) -> str:
        # repr(tuple) 在同一 Python 版本内稳定，且字节串原样可读，能直接看出每个 key 来源
        return KEY_PREFIX + repr(key)

    def get(self, key):
        raw = self._r.get(self._serialize_key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        return json.loads(raw)

    def set(self, key, data, ttl):
        try:
            payload = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning('cache set 跳过：数据不可 JSON 序列化 (%s)', e)
            return
        self._r.setex(self._serialize_key(key), max(1, int(ttl)), payload)

    def clear(self):
        for k in self._r.scan_iter(match=KEY_PREFIX + '*'):
            self._r.delete(k)

    @property
    def backend_label(self) -> str:
        try:
            host = self._r.connection_pool.connection_kwargs.get('host', '?')
            port = self._r.connection_pool.connection_kwargs.get('port', '?')
            return f'redis @ {host}:{port}'
        except Exception:
            return 'redis'


_cache: TTLCache = InMemoryCache()


def init_cache(url: str | None) -> str:
    """在 server 启动时调一次；返回当前后端的描述串便于打印。

    `url` 不传 / 不连接 / redis 库不在 → 落到 InMemoryCache。
    """
    global _cache
    if not url:
        _cache = InMemoryCache()
        return _cache.backend_label
    if redis is None:
        logger.warning('REDIS_URL 已设但未安装 redis 包，回退 in-memory')
        _cache = InMemoryCache()
        return _cache.backend_label + ' (redis lib missing)'
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=2.0, socket_timeout=2.0)
        client.ping()
    except Exception as e:
        logger.warning('Redis 连接失败 (%s)，回退 in-memory', e)
        _cache = InMemoryCache()
        return _cache.backend_label + f' (redis fallback: {e})'
    _cache = RedisCache(client)
    return _cache.backend_label


def get_cache() -> TTLCache:
    return _cache


def cached_endpoint(name: str, *, ttl: float | None = None):
    """对 endpoint 返回的 JSON 数据做 TTL 缓存；命中重新 jsonify 出 Response。

    cache 异常（Redis 抖动等）会被吞掉走原 endpoint，不让缓存层挂请求。
    只缓存 200 响应；endpoint 抛异常会冒泡给 errorhandler，不进缓存。
    """
    use_ttl = ttl if ttl is not None else DEFAULT_TTL

    def decorator(fn: Callable):
        # functools.wraps 在 Flask blueprint 注册路由时让端点名沿用原函数名
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            cache = get_cache()
            key = (name, request.path, request.query_string)
            try:
                hit = cache.get(key)
            except Exception as e:  # cache 后端故障不阻塞请求
                logger.warning('cache get 失败，绕过缓存：%s', e)
                hit = None
            if hit is not None:
                return jsonify(hit)
            resp = fn(*args, **kwargs)
            data = resp.get_json(silent=True)
            if data is not None and resp.status_code == 200:
                try:
                    cache.set(key, data, use_ttl)
                except Exception as e:
                    logger.warning('cache set 失败，跳过：%s', e)
            return resp
        return wrapper
    return decorator


def clear_cache() -> None:
    """清空当前 backend 的 cache；debug / 数据更新后手动调。"""
    try:
        get_cache().clear()
    except Exception as e:
        logger.warning('cache clear 失败：%s', e)
