# AGENTS.md

## Sources Of Truth
- Use Python 3.12 with `uv`; run project entrypoints as `uv run python ...`, not bare `python` or `python3`.
- Active code includes `src/npo/` and `scripts/{train,evaluate,compare_runs}.py`; older prose in `README.md`/`CLAUDE.md` may still imply training has not started.
- `src/npo/config.py` owns label order, label maps, model short keys, and default max lengths. The `LABELS_ZH` order is the model logits order.
- `scripts/dataset_paths.py` owns raw dataset paths. Use `labeled_files()` for train/eval/test; `mixed_test_files()` is explore-only.
- `legacy/model_training/` is migrated reference code only and is not in the main import chain.

## Commands
- Sync dependencies: `uv sync`.
- Extract data: `uv run python scripts/extract_dataset.py` (default zip password is `smp2020ewect`).
- Explore data without side effects: `uv run python scripts/explore_dataset.py`.
- Build parquet data: `uv run python scripts/preprocess.py` or `uv run python scripts/preprocess.py --raw-root <path> --out-root <path>`.
- Train: `uv run python scripts/train.py --track usual --model bert`; valid tracks are `usual|virus`, valid models are `bert|ernie`.
- Evaluate a checkpoint: `uv run python scripts/evaluate.py --checkpoint runs/<run>/best --track usual`; default split is `test`, use `--split eval` for validation-set checks.
- Compare completed runs: `uv run python scripts/compare_runs.py --pick best`; use `--pick latest` only when the newest experiment should win over best test macro-F1.
- Build SMP relabel candidates: `uv run python scripts/data_repair/build_smp_relabel_candidates.py --per-label-sample 120` writes ignored `data/annotation/smp_relabel_candidates.parquet`.
- Build business label candidates from exported CK Parquet: `uv run python scripts/data_repair/build_business_label_candidates.py --source comment --input data/business/comments.parquet --sample-size 5000`.
- LLM pre-label candidates: `LLM_BASE_URL=<url> uv run python scripts/data_repair/llm_label_candidates.py --input data/annotation/smp_relabel_candidates.parquet --output data/annotation/llm_labels.jsonl --model mimo-v2-flash --concurrency 8`.
- Prepare/reconcile second-pass labels: `uv run python scripts/data_repair/adjudicate_llm_labels.py prepare-review --primary data/annotation/llm_labels.jsonl --out data/annotation/pro_review.parquet`; then run `adjudicate` after the pro pass.
- Build silver repaired SMP data: `uv run python scripts/data_repair/build_smp_silver_dataset.py --adjudicated data/annotation/smp_adjudicated.jsonl --out-root data/processed_silver`; defaults to repairing `train` only and copying `eval/test` unchanged.
- No pytest, lint, typecheck, CI, or pre-commit config is present. For focused verification, prefer the relevant CLI `--help`, `explore_dataset.py`, or `preprocess.py`; full training is not a quick smoke test.

## Pipeline Rules
- Data flow is `data/评测数据集加密.zip` -> `data/raw/评测数据集/...` -> `data/processed/{usual,virus}_{train,eval,test}.parquet` -> `runs/<model>-<track>-<timestamp>/`.
- Processed parquet schema is exactly `content`, `label`, `label_id`; labels are Chinese names with ids `0=积极, 1=愤怒, 2=悲伤, 3=恐惧, 4=惊讶, 5=中性`.
- `eval` is validation for early stopping and best-checkpoint selection. `test` is final evaluation only. Mixed/noise test data is not used for training or evaluation.
- Preprocess only does a 512-character sanity truncation; tokenizer `max_length` is decided during training, defaulting to `usual=128` and `virus=192`.
- Preserve existing cleaning semantics unless intentionally changing the data contract: keep Weibo emoji like `[心]`, strip URL/retweet chains/@mentions, turn `#话题#` into `话题`, and convert Traditional Chinese to Simplified.
- Current conflict policy is `drop_duplicates(subset=['content'], keep='first')`; train samples overlapping eval/test are removed to prevent leakage.
- Six-class label repair uses `docs/labeling-guideline.md` as the shared LLM/human rubric. LLM output is pre-label data only; human-confirmed gold data must be stored as a derived dataset, not by editing raw SMP files.
- Crawler data is an offline business-sample source only. This repo should consume exported Parquet from ClickHouse, not connect model training directly to the crawler runtime.

## Runtime Quirks
- `pyproject.toml` uses platform markers so Mac installs PyPI torch with MPS support and Windows installs torch from the official `pytorch-cu128` index. Do not add a permanent default mirror/index that bypasses this.
- If PyPI is slow, use a one-off env var such as `UV_INDEX_URL=... uv add ...`; keep `uv.lock` as one universal lockfile.
- Device selection is `cuda > mps > cpu` in `src/npo/device.py`; AMP `auto` means CUDA fp16 and MPS/CPU fp32. MPS fallback is set there with `PYTORCH_ENABLE_MPS_FALLBACK=1`.
- `scripts/train.py` defaults `--num-workers 0`; keep that on MPS unless there is a measured reason to change it.
- The encrypted zip has UTF-8 filenames without the UTF-8 flag; `extract_dataset.py:_decode_name` handles the cp437-to-utf8 recovery.
- The mixed `usual_test_labeled.xlsx` is actually OLE2 `.xls`; `explore_dataset.py:load` falls back to `xlrd`, and preprocess does not read this file.
- PyArrow-backed pandas regex rejects `\u` escapes in `Series.str.contains`; `explore_dataset.py` intentionally uses compiled `re` loops for those feature checks.

## Artifacts And Git
- `data/raw/`, `data/processed*/`, `data/annotation/`, `data/business/`, `runs/`, and checkpoint files are generated/ignored; do not try to commit regenerated data, labels, business samples, or model weights.
- `results/comparison-*.md` is generated by `scripts/compare_runs.py` and may be a deliberate report artifact.
- If asked to commit, use Chinese Conventional Commit style as a short single line, for example `feat: 添加训练入口`.
- Do not stage auxiliary notes like `TODO.md` unless the user explicitly asks for them.
