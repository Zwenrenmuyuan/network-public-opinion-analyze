"""Dashboard API package."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint

from .evidence import register_evidence_routes
from .model_quality import register_model_quality_routes
from .risk import register_risk_routes
from .summary import register_summary_routes


def create_dashboard_api(ck, project_root: Path) -> Blueprint:
    """创建 `/api/dashboard/*` API blueprint。"""
    api = Blueprint('dashboard_api', __name__, url_prefix='/api/dashboard')
    register_summary_routes(api, ck)
    register_risk_routes(api, ck)
    register_evidence_routes(api, ck)
    register_model_quality_routes(api, project_root)
    return api
