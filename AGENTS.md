# AGENTS.md

## Sources Of Truth
- Use Python 3.12 with `uv`; run repo Python entrypoints as `uv run python ...`, not bare `python`/`python3`.
- Prefer executable sources (`pyproject.toml`, `frontend/package.json`, `scripts/`, `src/npo/`, `dashboard/`) over prose when commands or behavior conflict.
- `src/npo/config.py` owns `LABELS_ZH`, `LABEL2ID`, `MODEL_NAMES`, and `DEFAULT_MAX_LENGTH`; label order is logits/`label_id` order: `0=积极, 1=愤怒, 2=悲伤, 3=恐惧, 4=惊讶, 5=中性`.
- `dashboard/api/config.py` owns dashboard model versions and data-quality notices; current production display model is ERNIE `ernie-usual-mixed-v2`, with BERT only for contrast/disagreement.
- `docs/dashboard-design.md` is the dashboard API/metric contract, `docs/dashboard-runbook.md` is ops sequence, and `docs/labeling-guideline.md` is the label-repair rubric.
- `legacy/model_training/` is migrated reference code only; do not import from it.

## Architecture Boundaries
- `src/npo/` is installable library code; `scripts/` are the sanctioned CLIs and intentionally import sibling `dataset_paths.py` before `npo.*`.
- Training uses the repo’s hand-rolled `npo.trainer.Trainer`, not HuggingFace `Trainer`.
- Data repair lives under `scripts/data_repair/`; generated roots such as `data/processed_silver/` and `data/processed_mixed*/` are consumed by `scripts/train.py --processed-root`.
- Dashboard serving flow is `weibo.{post,comment}` -> `scripts/dashboard/predict_business_emotions.py` -> `dashboard.sentiment_prediction` -> Flask `/api/dashboard/*` -> Vue SPA.
- `scripts/dashboard/predict_business_emotions.py` inserts both `dashboard/` and `scripts/` to reuse `ck.py` and `preprocess.clean_text`; preserve that wiring instead of duplicating CK or cleaning logic.
- `frontend/` is Vue 3 + TypeScript + Vite + Pinia + Vue Router + ECharts and must talk only to `/api/dashboard/*`.
- `dashboard/server.py` serves `frontend/dist/` in prod and falls back to legacy `dashboard/index.html`; keep `dashboard/static/*` fallback-only.

## Core Commands
- Install/sync Python deps: `uv sync`; install frontend deps in `frontend/`: `npm install`.
- Extract SMP zip: `uv run python scripts/extract_dataset.py` (zip password default: `smp2020ewect`).
- Explore data without side effects: `uv run python scripts/explore_dataset.py`.
- Build processed parquet: `uv run python scripts/preprocess.py` or `uv run python scripts/preprocess.py --raw-root <path> --out-root <path>`.
- Train current main line: `uv run python scripts/train.py --track usual --model ernie --processed-root data/processed_mixed_v2`; default output is `runs/<model>-<track>-<timestamp>/` with `best/`, `last/`, `eval_history.jsonl`.
- Evaluate checkpoint: `uv run python scripts/evaluate.py --checkpoint runs/<run>/best --track usual`; use `--split eval` for validation and `--split business_eval --processed-root data/processed_mixed_v2` for held-out business eval.
- Compare runs: `uv run python scripts/compare_runs.py --pick best`; `--pick latest` means intentionally ignoring best test macro-F1.
- Dashboard CK prep order: `uv run python scripts/dashboard/export_dashboard_business_data.py`, then `uv run python scripts/dashboard/import_to_local_ck.py --host <local-ck>`, then `uv run python scripts/dashboard/init_dashboard_schema.py`.
- Dashboard inference smoke: `uv run python scripts/dashboard/predict_business_emotions.py --limit 100 --dry-run`; remove `--dry-run` only after sample rows look right.
- Run dashboard backend: `uv run python dashboard/server.py --port 8000`; run frontend dev in `frontend/` with `npm run dev` (`:5173` proxies `/api` to `:8000`).
- Build prod frontend: `npm run build` in `frontend/`; it runs `vue-tsc -b` then Vite and writes ignored `frontend/dist/` for Flask to serve.

## Verification
- There is no Python pytest/lint/typecheck config, CI workflow, task runner, or pre-commit config.
- Use focused Python checks: relevant CLI `--help`, `uv run python -m py_compile dashboard/server.py dashboard/api/*.py dashboard/ck.py`, or small smoke commands; full training is not a smoke test.
- Use `npm run build` for frontend typecheck/build; only use `node --check dashboard/static/js/pages/dashboard.js` when touching the legacy fallback JS.

## Data And Labels
- Processed parquet schema is exactly `content`, `label`, `label_id`; `eval` is validation/early-stop, `test` is final-only, and `business_eval` must stay held out from training mixes.
- `scripts/preprocess.py:clean_text` is order-sensitive: NFKC -> 繁转简 -> lowercase -> strip URLs -> strip retweets -> strip @mentions -> unwrap `#话题#` -> collapse whitespace; keep Weibo emoji like `[心]`.
- Preprocess only applies a 512-character defensive truncation; tokenizer `max_length` comes from training config (`usual=128`, `virus=192` by default).
- Duplicate conflict policy is `drop_duplicates(subset=['content'], keep='first')`; train rows overlapping eval/test are removed for leakage prevention.
- `scripts/dataset_paths.py:labeled_files()` is the train/eval/test source; `mixed_test_files()` is explore-only and not consumed by preprocess.

## Dashboard Contracts
- Risk score logic is centralized in `dashboard/api/risk.py:compute_window_caps` and `risk_factor_points`; `risk-topics` and topic detail must share the same formula/caps.
- Key actors are multi-dimensional OR candidates in `dashboard/api/actors.py`; do not collapse to a single top-N influence query.
- `actor_id = blake2b(uid)` is irreversible public ID; `evidence_token = base64(uid)` is reversible only for `evidence?actor_id=` filtering. Never expose raw uid or swap these identifiers.
- Treat `topic_id`, `post_id`, `comment_id`, and `source_id` as strings in API/frontend because ClickHouse `UInt64` may exceed JS safe integers.
- Comments are sampled CK data, not full-platform opinion; UI/API copy must keep the “采样评论/当前 CK 已采集评论” caveat.
- Frontend emotion color/order is fixed in `frontend/src/api/echarts-theme.ts` and must stay `['积极','愤怒','悲伤','恐惧','惊讶','中性']`.
- LLM insights/QA are interpretation layers only: no direct CK access, no SQL generation, no emotion relabeling, no risk-score rewriting, and no external facts beyond supplied JSON/tool results.
- QA Agent (`/api/dashboard/qa*`) uses `dashboard/api/qa_tools.py` read-only whitelist, max 3 tools per planner call; QA session history requires real Redis and returns `503 qa_store_unavailable` if `REDIS_URL` is absent/unreachable.

## Runtime Quirks
- `pyproject.toml` uses platform markers: macOS uses PyPI torch/MPS, Windows uses explicit `pytorch-cu128`. Do not add a permanent default index/mirror that bypasses this; use one-off `UV_INDEX_URL=...` if needed.
- `src/npo/device.py` sets `PYTORCH_ENABLE_MPS_FALLBACK=1`; AMP `auto` is CUDA fp16 and MPS/CPU fp32. Keep training `--num-workers 0` on MPS unless measured otherwise.
- `extract_dataset.py:_decode_name` handles official zip UTF-8 filename flag bugs; do not simplify it.
- The mixed `usual_test_labeled.xlsx` is actually OLE2 `.xls`; `explore_dataset.py` falls back to `xlrd`, and preprocess ignores it.
- `dashboard/server.py` sets `FLASK_SKIP_DOTENV=1` before importing Flask because `dashboard/ck.py:load_env_file` is the canonical `.env` loader; do not add/reorder around `python-dotenv`.
- `dashboard/ck.py` uses `CKNetworkError` only for transport failures; dashboard inference retries those and lets SQL/logic `CKError`s fail fast.
- Flask is not in debug-reload mode by default; restart `dashboard/server.py` after Python changes.
- Dashboard cache may fall back to in-memory, but QA history may not. Redis cache keys use `dashboard:` and QA keys use `dashboard:qa:`; clear Redis or wait TTL after changing aggregations/formulas.
- Vite HMR covers normal `.vue`/`.ts` edits; changes to `vite.config.ts`, `tsconfig*.json`, or `package.json` need a frontend dev-server restart.
- `frontend/tsconfig.app.json` uses TS6 `paths` without `baseUrl`; keep `paths: { "@/*": ["./src/*"] }` and do not add `baseUrl`.

## Generated Files And Git
- Do not commit `.env`, `data/raw/`, `data/processed*/`, `data/annotation/`, `data/business/`, `data/dashboard/`, `runs/`, `artifacts/`, model weights, `frontend/node_modules/`, `frontend/dist/`, or `results/model_disagreement/*_details.csv`.
- `results/comparison-*.md` is generated by `scripts/compare_runs.py` and may be an intentional report artifact.
- Commit style is short Chinese Conventional Commit, e.g. `feat: 添加训练入口`.
- Do not bundle unrelated edits to `AGENTS.md`, `CLAUDE.md`, `TODO.md`, `任务书.md`, or `dashboard/redesign-preview/` unless explicitly requested.
