"""Dashboard API package."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException

from ck import CKError, CKNetworkError

from .actors import register_actor_routes
from .evidence import register_evidence_routes
from .model_quality import register_model_quality_routes
from .risk import register_risk_routes
from .summary import register_summary_routes
from .topics import register_topic_routes


def create_dashboard_api(ck, project_root: Path) -> Blueprint:
    """创建 `/api/dashboard/*` API blueprint。"""
    api = Blueprint('dashboard_api', __name__, url_prefix='/api/dashboard')

    @api.before_request
    def _mark_request_started():
        g.dashboard_api_started_at = perf_counter()

    @api.after_request
    def _log_request_duration(response):
        started_at = getattr(g, 'dashboard_api_started_at', None)
        if started_at is not None:
            elapsed_ms = (perf_counter() - started_at) * 1000
            print(f'dashboard_api {request.path} status={response.status_code} elapsed_ms={elapsed_ms:.1f}')
        return response

    @api.errorhandler(HTTPException)
    def _handle_http_error(error: HTTPException):
        code = error.code or 500
        error_code = 'not_found' if code == 404 else 'bad_request' if code == 400 else 'http_error'
        return jsonify({'error': {'code': error_code, 'message': error.description}}), code

    @api.errorhandler(CKNetworkError)
    def _handle_ck_network_error(error: CKNetworkError):
        current_app.logger.warning('dashboard CK network error: %s', error)
        return jsonify({'error': {'code': 'clickhouse_unavailable', 'message': 'ClickHouse 暂时不可用'}}), 503

    @api.errorhandler(CKError)
    def _handle_ck_error(error: CKError):
        current_app.logger.warning('dashboard CK error: %s', error)
        return jsonify({'error': {'code': 'clickhouse_error', 'message': 'ClickHouse 查询失败'}}), 502

    @api.errorhandler(Exception)
    def _handle_unexpected_error(error: Exception):
        current_app.logger.exception('dashboard API unexpected error')
        return jsonify({'error': {'code': 'internal_error', 'message': 'Dashboard API 内部错误'}}), 500

    register_summary_routes(api, ck)
    register_risk_routes(api, ck)
    register_topic_routes(api, ck)
    register_actor_routes(api, ck)
    register_evidence_routes(api, ck)
    register_model_quality_routes(api, project_root)

    @api.route('/<path:_unused>')
    def _api_not_found(_unused: str):
        return jsonify({'error': {'code': 'not_found', 'message': 'Dashboard API 路由不存在'}}), 404

    return api
