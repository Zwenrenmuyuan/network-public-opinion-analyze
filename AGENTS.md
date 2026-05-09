# AGENTS.md

## Sources Of Truth
- Use Python 3.12 with `uv`; run Python entrypoints as `uv run python ...`, not bare `python` or `python3`.
- Trust executable sources (`pyproject.toml`, `frontend/package.json`, `scripts/`, `src/npo/`, `dashboard/`) over README prose; root `README.md` is stale for training, data-repair, and dashboard work.
- Active package code is `src/npo/`; CLI entrypoints live in `scripts/`; dashboard API is `dashboard/server.py` plus `dashboard/api/`; production SPA is `frontend/`.
- `src/npo/config.py` owns `LABELS_ZH`, label maps, model short keys, and default max lengths. `LABELS_ZH` order is the model logits/`label_id` order.
- `dashboard/api/config.py` owns dashboard primary/secondary model versions; current model-choice context is also in `results/model-selection-20260505.md`.
- `scripts/dataset_paths.py` owns raw SMP paths. Use `labeled_files()` for train/eval/test; `mixed_test_files()` is explore-only.
- `docs/dashboard-design.md` owns dashboard API contracts/metric definitions, `docs/dashboard-runbook.md` owns ops sequence, and `docs/labeling-guideline.md` owns label-repair rubric.
- `legacy/model_training/` is migrated reference code only; do not import from it.

## Architecture
- `src/npo/` is library code (`config`, `data`, `device`, `model`, `metrics`, `trainer`); `scripts/train.py` uses the repo's hand-rolled `Trainer`, not HuggingFace `Trainer`.
- `scripts/` are the sanctioned CLIs. They insert `scripts/` for sibling `dataset_paths.py`, then import package code from `npo`.
- `scripts/data_repair/` builds derived datasets; its outputs (`data/processed_silver/`, `data/processed_mixed*/`, annotation files) are ignored and consumed via `train.py --processed-root`.
- Dashboard serving flow is `weibo.{post,comment}` -> `scripts/dashboard/predict_business_emotions.py` -> `dashboard.sentiment_prediction` -> Flask `/api/dashboard/*` -> Vue SPA.
- `scripts/dashboard/predict_business_emotions.py` intentionally inserts both `dashboard/` and `scripts/` to reuse `ck.py` and `preprocess.clean_text`; preserve that wiring instead of duplicating CK or cleaning logic.
- `frontend/` is Vue 3 + TypeScript + Vite + Pinia + Vue Router + ECharts and talks only to `/api/dashboard/*`.
- `dashboard/server.py` serves `frontend/dist/` in prod and falls back to legacy `dashboard/index.html`; keep `dashboard/static/*` fallback-only.

## Commands
- Sync Python dependencies: `uv sync`; sync frontend dependencies in `frontend/` with `npm install`.
- Extract data: `uv run python scripts/extract_dataset.py` (default zip password is `smp2020ewect`).
- Explore data without side effects: `uv run python scripts/explore_dataset.py`.
- Build parquet data: `uv run python scripts/preprocess.py` or `uv run python scripts/preprocess.py --raw-root <path> --out-root <path>`.
- Train: `uv run python scripts/train.py --track usual --model ernie`; add `--processed-root data/processed_mixed_v2` for current mixed-v2 experiments. Valid tracks are `usual|virus`, valid models are `bert|ernie`; defaults include weighted CE, eval macro-F1 early stop, and `runs/<model>-<track>-<timestamp>/` output.
- Evaluate a checkpoint: `uv run python scripts/evaluate.py --checkpoint runs/<run>/best --track usual`; default split is `test`, use `--split eval` for validation-set checks.
- Compare completed runs: `uv run python scripts/compare_runs.py --pick best`; use `--pick latest` only when the newest experiment should win over best test macro-F1.
- Analyze two-checkpoint disagreements: `uv run python scripts/analyze_model_disagreement.py --primary-checkpoint runs/ernie-usual-mixed-v2/best --secondary-checkpoint runs/bert-usual-mixed-v2/best --track usual --processed-root data/processed_mixed_v2 --split business_eval`.
- Export business data read-only from ClickHouse: set `.env`/env vars from `.env.example`, then `uv run python scripts/data_repair/export_business_data.py --source both` writes `data/business/{posts,comments}.parquet`.
- Build SMP relabel candidates: `uv run python scripts/data_repair/build_smp_relabel_candidates.py --per-label-sample 120` writes ignored `data/annotation/smp_relabel_candidates.parquet`.
- Build business label candidates from exported CK Parquet: `uv run python scripts/data_repair/build_business_label_candidates.py --source comment --input data/business/comments.parquet --sample-size 5000`.
- Build targeted second-round business candidates: `uv run python scripts/data_repair/build_business_targeted_candidates.py`; its default checkpoint is old `runs/ernie-usual-mixed/best`, so pass `--checkpoint runs/ernie-usual-mixed-v2/best` when scoring against the current primary.
- Merge candidate files when needed: `uv run python scripts/data_repair/merge_label_candidates.py --input <a.parquet> <b.parquet> --out <merged.parquet>`.
- LLM pre-label candidates: `LLM_BASE_URL=<url> uv run python scripts/data_repair/llm_label_candidates.py --input data/annotation/smp_relabel_candidates.parquet --output data/annotation/llm_labels.jsonl --model mimo-v2-flash --concurrency 8`; it also loads `.env` and resumes from existing successful `sample_id`s unless `--no-resume` is passed.
- Prepare second-pass labels: `uv run python scripts/data_repair/adjudicate_llm_labels.py prepare-review --primary data/annotation/llm_labels.jsonl --out data/annotation/pro_review.parquet`; run `llm_label_candidates.py` on that parquet with the review model, then `adjudicate --primary <primary.jsonl> --review <review.jsonl> --out-csv <out.csv> --out-jsonl <out.jsonl>`.
- Build silver repaired SMP data: `uv run python scripts/data_repair/build_smp_silver_dataset.py --adjudicated data/annotation/smp_adjudicated.jsonl --out-root data/processed_silver`; defaults to repairing `train` only and copying `eval/test` unchanged.
- Build business eval/train pool after business adjudication: `uv run python scripts/data_repair/build_business_eval.py`; `business_eval` is held out and the remaining accepted samples become `usual_business_train_pool.parquet`.
- Build mixed train data: `uv run python scripts/data_repair/build_mixed_training_dataset.py --base-root data/processed_silver --out-root data/processed_mixed`; it preserves eval/test and excludes business eval from train.
- Extend a business train pool with second-round adjudication: `uv run python scripts/data_repair/build_business_second_round_train_pool.py`; pass `--include-human-required` only after human confirmation.
- Dashboard CK prep: `uv run python scripts/dashboard/export_dashboard_business_data.py`, then `uv run python scripts/dashboard/import_to_local_ck.py --host <local-ck>`, then `uv run python scripts/dashboard/init_dashboard_schema.py`.
- Dashboard inference smoke: `uv run python scripts/dashboard/predict_business_emotions.py --limit 100 --dry-run`; remove `--dry-run` only after the sample rows look right.
- Run dashboard backend: `uv run python dashboard/server.py --port 8000`; run frontend dev in `frontend/` with `npm run dev` (`:5173` proxies `/api` to `:8000`).
- Build frontend for Flask prod mode: `npm run build` in `frontend/`; it runs `vue-tsc -b` before Vite and writes `frontend/dist/`.
- No pytest, Python lint/typecheck, CI workflow, or pre-commit config is present. For focused verification use the relevant CLI `--help`, `uv run python -m py_compile dashboard/server.py dashboard/api/*.py dashboard/ck.py`, `npm run build`, or legacy `node --check dashboard/static/js/pages/dashboard.js` only if touching the fallback page; full training is not a smoke test.

## Data And Labels
- Data flow is `data/评测数据集加密.zip` -> `data/raw/评测数据集/...` -> `data/processed/{usual,virus}_{train,eval,test}.parquet` -> `runs/<model>-<track>-<timestamp>/`.
- Processed parquet schema is exactly `content`, `label`, `label_id`; labels are Chinese names with ids `0=积极, 1=愤怒, 2=悲伤, 3=恐惧, 4=惊讶, 5=中性`.
- `eval` is validation for early stopping and best-checkpoint selection. `test` is final evaluation only. Mixed/noise test data is not used for training or evaluation.
- Preprocess only does a 512-character sanity truncation; tokenizer `max_length` is decided during training, defaulting to `usual=128` and `virus=192`.
- Preserve existing cleaning semantics unless intentionally changing the data contract: keep Weibo emoji like `[心]`, strip URL/retweet chains/@mentions, turn `#话题#` into `话题`, and convert Traditional Chinese to Simplified.
- Current conflict policy is `drop_duplicates(subset=['content'], keep='first')`; train samples overlapping eval/test are removed to prevent leakage.
- Six-class label repair uses `docs/labeling-guideline.md` as the shared LLM/human rubric. LLM output is pre-label data only; human-confirmed gold data must be stored as a derived dataset, not by editing raw SMP files.
- Crawler data is an offline business-sample source only. Model training consumes exported Parquet, not the crawler runtime or direct training-time ClickHouse queries.
- `business_eval` must stay held out; mixed training builders explicitly exclude eval/test/business_eval contents from business train pools.

## Dashboard Contracts
- Main line is ERNIE + usual: `ernie-usual-mixed-v2` / `runs/ernie-usual-mixed-v2/best`; BERT is a contrast model and disagreement-mining tool, not the primary display model.
- Browser code must never receive CK credentials or direct SQL access; `.env` is loaded backend-side by `dashboard/ck.py` and follows `.env.example`.
- Dashboard queries default to `dashboard/api/config.py:PRIMARY_MODEL_VERSION`; BERT should appear only in model-quality/disagreement flows unless requirements change.
- Risk score logic is centralized in `dashboard/api/risk.py:compute_window_caps` and `risk_factor_points`; `risk-topics` and topic detail must share the same caps/formula.
- Key actors are multi-dimensional OR candidates in `dashboard/api/actors.py`, sorted by `(role_count, actor_influence_score, sample_count)`; do not collapse this to a single top-N influence query.
- `actor_id` is an irreversible `blake2b(uid)` public hash, while `evidence_token` is reversible base64 for `evidence?actor_id=` filtering; never expose raw uid and do not swap the two identifiers.
- API and frontend treat `topic_id`, `post_id`, `comment_id`, and `source_id` as strings because ClickHouse UInt64 can exceed JS safe integers.
- Comments are sampled business data, not full-platform opinion; UI/API copy must keep the “采样评论” caveat.
- Frontend emotion colors/order are fixed in `frontend/src/api/echarts-theme.ts`: `['积极','愤怒','悲伤','恐惧','惊讶','中性']`.

## Runtime Quirks
- `pyproject.toml` uses platform markers so Mac installs PyPI torch with MPS support and Windows installs torch from the official `pytorch-cu128` index. Do not add a permanent default mirror/index that bypasses this.
- If PyPI is slow, use a one-off env var such as `UV_INDEX_URL=... uv add ...`; keep `uv.lock` as one universal lockfile.
- Device selection is `cuda > mps > cpu` in `src/npo/device.py`; AMP `auto` means CUDA fp16 and MPS/CPU fp32. MPS fallback is set there with `PYTORCH_ENABLE_MPS_FALLBACK=1`.
- `scripts/train.py` defaults `--num-workers 0`; keep that on MPS unless there is a measured reason to change it.
- The encrypted zip has UTF-8 filenames without the UTF-8 flag; `extract_dataset.py:_decode_name` handles the cp437-to-utf8 recovery.
- The mixed `usual_test_labeled.xlsx` is actually OLE2 `.xls`; `explore_dataset.py:load` falls back to `xlrd`, and preprocess does not read this file.
- PyArrow-backed pandas regex rejects `\u` escapes in `Series.str.contains`; `explore_dataset.py` intentionally uses compiled `re` loops for those feature checks.
- `dashboard/server.py` sets `FLASK_SKIP_DOTENV=1` before importing Flask because `dashboard/ck.py:load_env_file` is the canonical `.env` loader; do not reorder those imports or add `python-dotenv`.
- `dashboard/ck.py` raises `CKNetworkError` only for transport failures; `predict_business_emotions.py` retries those and lets SQL/logic `CKError`s fail fast.
- Flask is not in debug reload mode by default; restart `dashboard/server.py` after Python changes.
- Dashboard cache is Redis when `REDIS_URL` works and in-memory otherwise, with `dashboard:` keys and 300s default TTL; after changing aggregation/formula code, clear cache or wait for TTL.
- Vite HMR covers normal `.vue`/`.ts` edits, but `vite.config.ts`, `tsconfig*.json`, and `package.json` changes need a frontend dev-server restart.
- `frontend/tsconfig.app.json` uses TS6 `paths` without `baseUrl`; keep `paths: { "@/*": ["./src/*"] }` and do not add `baseUrl` back.

## Artifacts And Git
- `data/raw/`, `data/processed*/`, `data/annotation/`, `data/business/`, `data/dashboard/`, `runs/`, `artifacts/`, `frontend/node_modules/`, `frontend/dist/`, checkpoint/model weight files, and `results/model_disagreement/*_details.csv` are generated, bulky, or contain business text; do not commit them.
- `results/comparison-*.md` is generated by `scripts/compare_runs.py` and may be a deliberate report artifact.
- If asked to commit, use Chinese Conventional Commit style as a short single line, for example `feat: 添加训练入口`.
- Do not stage auxiliary notes like `TODO.md`, `任务书.md`, `dashboard/redesign-preview/`, or unrelated `AGENTS.md` edits unless the user explicitly asks for them.
