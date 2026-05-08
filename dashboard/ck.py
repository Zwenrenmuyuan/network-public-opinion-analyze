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
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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


class CKNetworkError(CKError):
    """网络层异常（超时、连接断开、读写中断等）。

    专门分一类是为了让调用方区分「该重试」和「该放弃」：
      - CKNetworkError    → 网络抖动 / CK 重启，外层可指数退避重试
      - 其它 CKError       → SQL 错、权限错、协议错，重试也是同样错，应直接抛
    """
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

    def _post(self, sql: str, body: bytes | None = None) -> httpx.Response:
        """body=None：SQL 走 body（普通查询）；body!=None：SQL 走 URL，body 是数据（INSERT FORMAT）。"""
        try:
            if body is None:
                resp = self._client.post(self._url, content=sql, auth=self._auth)
            else:
                url = f'{self._url}?{urlencode({"query": sql})}'
                resp = self._client.post(url, content=body, auth=self._auth)
        except httpx.RequestError as e:
            raise CKNetworkError(f'CK 网络异常: {type(e).__name__}: {e}') from e
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

    def stream_json(self, sql: str) -> Iterator[dict[str, Any]]:
        """流式拉行（FORMAT JSONEachRow），用于扫整表不让响应全进内存。

        调用方式与 query_json 相同；返回生成器，逐行 yield dict。
        网络型异常会被转成 CKNetworkError 抛出（包括 stream 中途断开）。
        但已 yield 出去的行无法回滚——调用方若要重试必须从头再调一次。
        大批量场景更推荐"分页 query_json + 调用方重试"，丢失粒度只到一页。

        手动按 '\\n' 拼缓冲分行——httpx 的 iter_lines() 在某些 chunk 边界
        会把多行拼到一行返回，导致 json.loads 报 Extra data。
        """
        if 'FORMAT' not in sql.upper():
            sql = sql + '\nFORMAT JSONEachRow'
        try:
            with self._client.stream('POST', self._url, content=sql, auth=self._auth) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode('utf-8', 'replace')[:500]
                    raise CKError(f'CK {resp.status_code}: {body}')
                buf = ''
                for chunk in resp.iter_text(chunk_size=65536):
                    buf += chunk
                    while True:
                        nl = buf.find('\n')
                        if nl < 0:
                            break
                        line, buf = buf[:nl], buf[nl + 1:]
                        if line:
                            yield json.loads(line)
                if buf.strip():
                    yield json.loads(buf)
        except httpx.RequestError as e:
            raise CKNetworkError(f'CK 流式异常: {type(e).__name__}: {e}') from e

    def insert_jsoneachrow(self, table: str, rows: list[dict[str, Any]]) -> None:
        """批量 INSERT FORMAT JSONEachRow；空 rows 直接返回。

        SQL 走 URL query 参数，body 全部留给数据本体（CK HTTP API 标准用法）。
        """
        if not rows:
            return
        body = '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows).encode('utf-8')
        self._post(f'INSERT INTO {table} FORMAT JSONEachRow', body=body)

    def close(self) -> None:
        self._client.close()
