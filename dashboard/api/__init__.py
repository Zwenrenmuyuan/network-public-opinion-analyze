"""Dashboard API package."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from flask import Blueprint, g, request

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

    register_summary_routes(api, ck)
    register_risk_routes(api, ck)
    register_topic_routes(api, ck)
    register_actor_routes(api, ck)
    register_evidence_routes(api, ck)
    register_model_quality_routes(api, project_root)
    return api
