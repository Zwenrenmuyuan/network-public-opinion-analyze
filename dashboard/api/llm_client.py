"""OpenAI-compatible client for dashboard LLM insights."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


DEFAULT_DASHBOARD_MODEL = 'mimo-v2.5-pro'
DEFAULT_TIMEOUT = 300.0
DEFAULT_MAX_TOKENS = 8192


class LLMError(Exception):
    """Base class for dashboard LLM failures."""


class LLMUnavailableError(LLMError):
    """LLM feature is disabled or not configured."""


class LLMResponseError(LLMError):
    """LLM transport or response parsing failed."""


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {'0', 'false', 'no', 'off', 'disabled'}


def dashboard_llm_model() -> str:
    """Model used for dashboard insights; can differ from labeling jobs."""
    return (
        os.getenv('DASHBOARD_LLM_MODEL')
        or os.getenv('LLM_MODEL')
        or DEFAULT_DASHBOARD_MODEL
    )


def ensure_dashboard_llm_available() -> None:
    """Fail fast before expensive CK context assembly."""
    if not _env_bool('DASHBOARD_LLM_ENABLED', True):
        raise LLMUnavailableError('Dashboard LLM insights are disabled')
    if not os.getenv('LLM_BASE_URL'):
        raise LLMUnavailableError('Missing LLM_BASE_URL')


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from a strict or fenced model response."""
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, flags=re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError('LLM response is not a JSON object')
    return parsed


def _message_content(message: dict[str, Any], finish_reason: str | None) -> str:
    """Extract final assistant content from common OpenAI-compatible shapes.

    Reasoning models may return `reasoning_content` while `content` is still empty
    when the completion budget is exhausted. We intentionally do not parse
    reasoning_content as final JSON; it is chain-of-thought, not an answer.
    """
    content = message.get('content')
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get('text') or item.get('content')
                if isinstance(text, str):
                    parts.append(text)
        joined = ''.join(parts).strip()
        if joined:
            return joined

    reasoning = message.get('reasoning_content')
    if isinstance(reasoning, str) and reasoning.strip():
        suffix = '；请调大 DASHBOARD_LLM_MAX_TOKENS' if finish_reason == 'length' else ''
        raise LLMResponseError(f'LLM returned reasoning but no final content{suffix}')
    raise LLMResponseError('LLM returned empty content')


def call_dashboard_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Call a chat-completions compatible model and return parsed JSON."""
    ensure_dashboard_llm_available()
    base_url = os.getenv('LLM_BASE_URL')
    model = dashboard_llm_model()
    headers = {'Content-Type': 'application/json'}
    api_key = os.getenv('LLM_API_KEY')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': temperature,
        'max_tokens': _int_env('DASHBOARD_LLM_MAX_TOKENS', DEFAULT_MAX_TOKENS),
    }
    timeout = _float_env('DASHBOARD_LLM_TIMEOUT', _float_env('LLM_TIMEOUT', DEFAULT_TIMEOUT))
    url = base_url.rstrip('/') + '/chat/completions'

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            choice = data['choices'][0]
            content = _message_content(choice.get('message') or {}, choice.get('finish_reason'))
    except httpx.RequestError as exc:
        raise LLMResponseError(f'LLM network error: {type(exc).__name__}') from exc
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300]
        if exc.response.status_code in (502, 503, 504) and body.lstrip().startswith('<!DOCTYPE html>'):
            body = 'upstream gateway timeout'
        raise LLMResponseError(f'LLM HTTP {exc.response.status_code}: {body}') from exc
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LLMResponseError('Invalid LLM API response') from exc

    try:
        return extract_json_object(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMResponseError('LLM did not return valid JSON') from exc
