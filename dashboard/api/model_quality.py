"""Model quality route."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify

from npo.config import LABELS_ZH

from .cache import cached_endpoint
from .config import BERT_USAGE, PRIMARY_CHECKPOINT, PRIMARY_MODEL_NAME, SECONDARY_MODEL_NAME
from .utils import extract_eval, load_json, top_confusions


def register_model_quality_routes(api: Blueprint, project_root: Path) -> None:
    @api.route('/model-quality')
    @cached_endpoint('model-quality')
    def api_model_quality():
        return jsonify(model_quality_payload(project_root))


def model_quality_payload(project_root: Path) -> dict:
    sources = _model_quality_sources(project_root)
    business = load_json(sources['business_eval'])
    smp_test = load_json(sources['smp_test'])
    disagreement = load_json(sources['disagreement'])

    cm_source = business or smp_test
    matrix = cm_source.get('confusion_matrix') if cm_source else None
    cm_labels = (cm_source.get('labels') if cm_source else None) or list(LABELS_ZH)

    bert_cmp = None
    if disagreement:
        bert = disagreement.get('bert', {})
        bert_cmp = {
            'name': SECONDARY_MODEL_NAME,
            'usage': BERT_USAGE,
            'agreement_rate': round(disagreement.get('agreement_rate', 0.0), 4),
            'oracle_accuracy': round(disagreement.get('oracle_accuracy', 0.0), 4),
            'bert_accuracy': round(bert.get('accuracy', 0.0), 4),
            'bert_macro_f1': round(bert.get('macro_f1', 0.0), 4),
            'ernie_only_correct': disagreement.get('ernie_only_correct'),
            'bert_only_correct': disagreement.get('bert_only_correct'),
        }

    return {
        'primary_model': PRIMARY_MODEL_NAME,
        'checkpoint': PRIMARY_CHECKPOINT,
        'business_eval': extract_eval(business),
        'smp_test': extract_eval(smp_test),
        'confusion_matrix': matrix,
        'confusion_labels': cm_labels,
        'top_confusions': top_confusions(matrix, cm_labels, top_n=3),
        'bert_comparison': bert_cmp,
    }


def _model_quality_sources(project_root: Path) -> dict[str, Path]:
    return {
        'business_eval': project_root / 'runs' / 'ernie-usual-mixed-v2' / 'final_business_eval_report.json',
        'smp_test': project_root / 'runs' / 'ernie-usual-mixed-v2' / 'final_test_report.json',
        'disagreement': project_root / 'results' / 'model_disagreement' / 'usual_business_eval_ernie_vs_bert_summary.json',
    }
