"""Dashboard 后端网关 (Flask)。

启动：
    uv run python dashboard/server.py
    uv run python dashboard/server.py --port 8000 --debug

路由：
    GET /                       托管 dashboard/index.html
    GET /static/<path>          托管 dashboard/static/
    GET /api/dashboard/meta     数据窗口、模型版本、标签

设计依据：docs/dashboard-design.md § 9.1。
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 我们自己用 ck.load_env_file 加载 .env；让 Flask 别再重复加载并抱怨没装 python-dotenv。
# 必须在 import flask 之前设。
os.environ.setdefault('FLASK_SKIP_DOTENV', '1')

from flask import Flask, jsonify, send_from_directory

# dashboard/ 不是 Python 包；脚本运行时 sys.path[0] = dashboard/，
# 所以可以直接 import 同目录的 ck.py。
from ck import CKClient

# src/npo 由 hatch wheel editable 安装，import 直接走包。
from npo.config import LABELS_ZH

DASHBOARD_DIR = Path(__file__).resolve().parent
NEGATIVE_LABELS = ('愤怒', '悲伤', '恐惧')
PRIMARY_MODEL_NAME = 'ERNIE mixed-v2'
PRIMARY_CHECKPOINT = 'runs/ernie-usual-mixed-v2/best'
DISPLAY_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai
# 把 first_crawled_at 当天 < 该阈值的日期视为爬虫尚未稳定运行 / 历史尾巴，
# 用于算 data_window.start。当前数据：4-23 = 4 行 (试运行)，4-25 起每天 3 万+，阈值 10000 干净分隔。
STABLE_DAY_THRESHOLD = 10000

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False  # JSON 响应里中文标签不要转义成 \u
ck = CKClient()


@app.route('/')
def index():
    return send_from_directory(DASHBOARD_DIR, 'index.html')


@app.route('/static/<path:filename>')
def static_files(filename: str):
    return send_from_directory(DASHBOARD_DIR / 'static', filename)


@app.route('/api/dashboard/meta')
def api_meta():
    # data_window.start = 第一天 first_crawled_at 行数 >= STABLE_DAY_THRESHOLD 的日期 (CST)
    #   作用：跳过爬虫试运行 / 后续从转发链补抓的稀疏历史尾巴 (~0.2%)，
    #         避免趋势图前若干天近似 0 后突然爆涨的视觉错觉。
    # data_window.end = max(created_at) (UTC)
    row = ck.query_one(
        f"""
        SELECT
          (SELECT min(d) FROM (
            SELECT toDate(first_crawled_at, 'Asia/Shanghai') AS d, count() AS n
            FROM weibo.post GROUP BY d HAVING n >= {STABLE_DAY_THRESHOLD}
          )) AS stable_start_cst,
          max(created_at) AS end_utc
        FROM weibo.post
        """
    )
    if not row or not row.get('end_utc'):
        return jsonify({'error': 'no data'}), 500

    # stable_start_cst 是 CST Date (序列化 'YYYY-MM-DD')；阈值取不到 (新部署/小数据集) 时
    # 回退到 min(first_crawled_at)。
    raw_start = row.get('stable_start_cst')
    if raw_start and raw_start != '0000-00-00':
        start_cst = datetime.strptime(raw_start, '%Y-%m-%d').replace(tzinfo=DISPLAY_TZ)
    else:
        fb = ck.query_one('SELECT min(first_crawled_at) AS m FROM weibo.post')
        start_cst = (datetime.strptime(fb['m'], '%Y-%m-%d %H:%M:%S')
                     .replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ))

    end_cst = (datetime.strptime(row['end_utc'], '%Y-%m-%d %H:%M:%S')
               .replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ))
    available_days = max(1, (end_cst.date() - start_cst.date()).days + 1)

    time_range_options = ['all_available']
    if available_days >= 1:
        time_range_options.append('24h')
    if available_days >= 7:
        time_range_options.append('7d')

    return jsonify({
        'schema_version': 'dashboard.v1',
        'generated_at': datetime.now(DISPLAY_TZ).isoformat(timespec='seconds'),
        'data_window': {
            'start': start_cst.isoformat(timespec='seconds'),
            'end': end_cst.isoformat(timespec='seconds'),
            'available_days': available_days,
            'is_partial_history': available_days < 30,
        },
        'time_range_options': time_range_options,
        'model': {
            'name': PRIMARY_MODEL_NAME,
            'checkpoint': PRIMARY_CHECKPOINT,
        },
        'labels': list(LABELS_ZH),
        'negative_labels': list(NEGATIVE_LABELS),
    })


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
