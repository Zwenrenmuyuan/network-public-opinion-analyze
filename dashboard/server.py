"""Dashboard 后端入口。

启动：
    uv run python dashboard/server.py --port 8000

职责：托管 dashboard 静态页面，并注册 `/api/dashboard/*` API blueprint。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

# 我们自己用 ck.load_env_file 加载 .env；让 Flask 别再重复加载并抱怨没装 python-dotenv。
# 必须在 import flask 之前设。
os.environ.setdefault('FLASK_SKIP_DOTENV', '1')

from flask import Flask, send_from_directory

from api import create_dashboard_api
from ck import CKClient

DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DASHBOARD_DIR.parent

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False
ck = CKClient()
app.register_blueprint(create_dashboard_api(ck, PROJECT_ROOT))


@app.route('/')
def index():
    return send_from_directory(DASHBOARD_DIR, 'index.html')


@app.route('/static/<path:filename>')
def static_files(filename: str):
    return send_from_directory(DASHBOARD_DIR / 'static', filename)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=8000)
    p.add_argument('--debug', action='store_true')
    args = p.parse_args()
    print(f'Dashboard 后端启动: http://localhost:{args.port}/  ->  CK={ck.host}:{ck.port}')
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
