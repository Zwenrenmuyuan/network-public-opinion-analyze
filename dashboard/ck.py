"""Dashboard 后端共享的 ClickHouse 客户端。

设计：
  - 配置从 .env 读：CLICKHOUSE_HOST、CLICKHOUSE_PORT（默认 8123）、
    CLICKHOUSE_DATABASE（默认 weibo）、READONLY_USER、READONLY_PASSWORD。
    所有脚本和 dashboard 后端共用同一份 .env 连接信息；切换 dev/生产时只改 .env。
  - 单例 httpx.Client，连接复用。
  - query_json(sql) → list[dict]：默认追加 FORMAT JSONEachRow。SQL 自带 FORMAT 时不再追加。
  - 客户端不做 SQL 白名单；权限交给 CK 服务端账户做 RBAC（dev 容器有写权限，生产用 readonly）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"\'')
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(ROOT / '.env')


class CKError(Exception):
    pass


class CKClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        timeout: float = 30.0,
    ):
        self.host = host or os.getenv('CLICKHOUSE_HOST')
        self.port = port or int(os.getenv('CLICKHOUSE_PORT', '8123'))
        self.user = user or os.getenv('READONLY_USER')
        self.password = password or os.getenv('READONLY_PASSWORD')
        self.database = database or os.getenv('CLICKHOUSE_DATABASE', 'weibo')
        missing = [k for k, v in [('CLICKHOUSE_HOST', self.host),
                                  ('READONLY_USER', self.user),
                                  ('READONLY_PASSWORD', self.password)] if not v]
        if missing:
            raise CKError(f'缺少 .env 配置: {", ".join(missing)}')
        self._url = f'http://{self.host}:{self.port}/'
        self._auth = httpx.BasicAuth(self.user, self.password)
        self._client = httpx.Client(timeout=timeout)

    def _post(self, sql: str) -> httpx.Response:
        resp = self._client.post(self._url, content=sql, auth=self._auth)
        if resp.status_code != 200:
            raise CKError(f'CK {resp.status_code}: {resp.text[:500]}')
        return resp

    def query_text(self, sql: str) -> str:
        return self._post(sql).text.strip()

    def query_json(self, sql: str) -> list[dict[str, Any]]:
        if 'FORMAT' not in sql.upper():
            sql = sql + '\nFORMAT JSONEachRow'
        text = self._post(sql).text
        return [json.loads(line) for line in text.splitlines() if line]

    def query_one(self, sql: str) -> dict[str, Any] | None:
        rows = self.query_json(sql)
        return rows[0] if rows else None

    def close(self) -> None:
        self._client.close()
