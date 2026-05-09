"""TTL cache 装饰器，给重 CK 查询加进程内缓存。

dashboard.sentiment_prediction 和 weibo.* 是离线静态数据，演示场景下没有写入；
默认 5 分钟内同一 URL 的重复请求直接命中缓存，避免重复扫描和 JOIN。

key = (name, request.path, request.query_string)，参数变化（range/limit/topic_id）
自动落到不同 key；不需要手动失效。要强制失效调 `clear_cache()`。

只缓存 200 成功响应；endpoint 抛异常会冒泡给 __init__.py 的 errorhandler，不进缓存。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import jsonify, request


class TTLCache:
    def __init__(self, ttl: float = 300.0):
        self.ttl = ttl
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key):
        record = self._store.get(key)
        if record is None:
            return None
        ts, data = record
        if time.monotonic() - ts > self.ttl:
            return None
        return data

    def set(self, key, data):
        self._store[key] = (time.monotonic(), data)

    def clear(self):
        self._store.clear()


_default = TTLCache(300.0)


def cached_endpoint(name: str, *, ttl: float | None = None, cache: TTLCache | None = None):
    """对 endpoint 返回的 JSON 数据做 TTL 缓存；命中重新 jsonify 出 Response。

    `name` 用于日志和 key 区分；`ttl` 不传则用默认 cache 的 ttl。
    `cache` 可注入自定义实例（测试或独立 ttl 用）。
    """
    used = cache or _default

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (name, request.path, request.query_string)
            hit = used.get(key)
            if hit is not None:
                return jsonify(hit)
            resp = fn(*args, **kwargs)
            data = resp.get_json(silent=True)
            if data is not None and resp.status_code == 200:
                used.set(key, data)
            return resp
        return wrapper
    return decorator


def clear_cache() -> None:
    """清空默认 cache；debug / 数据更新后手动调。"""
    _default.clear()
