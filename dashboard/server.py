"""Dashboard 后端入口。

启动：
    uv run python dashboard/server.py --port 8000

职责：托管 dashboard 前端（优先 frontend/dist，降级旧 dashboard/index.html），
并注册 `/api/dashboard/*` API blueprint。SPA catch-all 让 Vue Router 处理深链接。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

# 我们自己用 ck.load_env_file 加载 .env；让 Flask 别再重复加载并抱怨没装 python-dotenv。
# 必须在 import flask 之前设。
os.environ.setdefault('FLASK_SKIP_DOTENV', '1')

from flask import Flask, abort, send_from_directory

from api import create_dashboard_api
from api.cache import init_cache
from ck import CKClient

DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DASHBOARD_DIR.parent
FRONTEND_DIST = PROJECT_ROOT / 'frontend' / 'dist'

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False
ck = CKClient()
cache_backend = init_cache(os.getenv('REDIS_URL'))
app.register_blueprint(create_dashboard_api(ck, PROJECT_ROOT))


def _serve_frontend_index():
    """优先返回 frontend/dist/index.html；dist 不存在时降级到旧 dashboard/index.html。"""
    if (FRONTEND_DIST / 'index.html').is_file():
        return send_from_directory(FRONTEND_DIST, 'index.html')
    return send_from_directory(DASHBOARD_DIR, 'index.html')


@app.route('/')
def index():
    return _serve_frontend_index()


@app.route('/static/<path:filename>')
def legacy_static(filename: str):
    """保留 dashboard/static/* 兼容降级模式（旧 index.html 的 css/js）。"""
    return send_from_directory(DASHBOARD_DIR / 'static', filename)


@app.route('/<path:path>')
def spa_or_static(path: str):
    """SPA + 静态资源 catch-all。

      1. /api/* 已被 blueprint 接管，到不了这里；防御性地 abort。
      2. dist/<path> 是真实文件 → 直接 serve（assets/*.js / *.css / favicon 等）。
      3. 否则返回 index.html，让 Vue Router 处理 /topics, /actors 等 SPA 深链。
    """
    if path.startswith('api/'):
        abort(404)
    if FRONTEND_DIST.is_dir():
        target = FRONTEND_DIST / path
        if target.is_file():
            return send_from_directory(FRONTEND_DIST, path)
    return _serve_frontend_index()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=8000)
    p.add_argument('--debug', action='store_true')
    args = p.parse_args()
    mode = 'dist' if (FRONTEND_DIST / 'index.html').is_file() else 'legacy'
    print(f'Dashboard 后端启动: http://localhost:{args.port}/  ->  CK={ck.host}:{ck.port}  cache={cache_backend}  frontend={mode}')
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
