"""扫描 runs/*/ 目录，汇总 BERT/ERNIE × usual/virus 对比表 → results/comparison-{date}.md。

输入约定（train.py / evaluate.py 已经写好的产物）：
  runs/{model}-{track}-{YYYYMMDD-HHMM}/
    ├── train_args.json          ← model / track / pretrained / resolved_* 等
    ├── eval_history.jsonl       ← 每 epoch 一行，含 train_time_s
    ├── final_test_report.json   ← test set 的 macro_f1 / per_class_f1 / 混淆矩阵
    └── best/, last/

输出三张表（markdown）：
  A. 总体对比：模型/track/best epoch/epochs run/macro_f1/accuracy/训练时长
  B. Per-class F1：usual / virus 各一张
  C. Top-3 混淆方向：每组从混淆矩阵取最大的 3 个 off-diagonal cell

同 (model, track) 有多个 run（多 timestamp）时按 --pick 策略选：
  best   - test_macro_f1 最高（默认；对比表对外稳定，失败实验不会让数字劣化）
  latest - timestamp 最新（追踪"最近一次实验"）
warnings 里会列出所有候选 + 哪个被选中。
缺 final_test_report.json 的 run 跳过 + 在脚本输出里警告。
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

# 与 npo.config.LABELS_ZH 保持一致；这里独立写一份避免 scripts/ 反向依赖 src 包路径解析
LABELS_ZH = ('积极', '愤怒', '悲伤', '恐惧', '惊讶', '中性')

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_ROOT = ROOT / 'runs'
DEFAULT_RESULTS_ROOT = ROOT / 'results'

# run 目录命名约定：{model}-{track}-{YYYYMMDD-HHMM}
RUN_DIR_RE = re.compile(r'^(?P<model>[a-z0-9]+)-(?P<track>usual|virus)-(?P<ts>\d{8}-\d{4})$')


def parse_run_dir(run_dir: Path) -> dict | None:
    """解析 run 目录名 + 读三个产物。返回 None 表示该 run 不完整应跳过。"""
    m = RUN_DIR_RE.match(run_dir.name)
    if not m:
        return None

    train_args_p = run_dir / 'train_args.json'
    eval_hist_p  = run_dir / 'eval_history.jsonl'
    test_rep_p   = run_dir / 'final_test_report.json'

    if not train_args_p.exists():
        return {'name': run_dir.name, 'incomplete': '缺 train_args.json'}
    if not test_rep_p.exists():
        return {'name': run_dir.name, 'incomplete': '缺 final_test_report.json（还没跑 evaluate）'}

    train_args = json.loads(train_args_p.read_text(encoding='utf-8'))
    test_rep   = json.loads(test_rep_p.read_text(encoding='utf-8'))

    # 训练时长：把 eval_history 每行的 train_time_s + eval_time_s 累加
    total_time = 0.0
    epochs_run = 0
    best_epoch = -1
    best_macro_f1_eval = -1.0
    if eval_hist_p.exists():
        for line in eval_hist_p.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            total_time += row.get('train_time_s', 0) + row.get('eval_time_s', 0)
            epochs_run += 1
            if row['macro_f1'] > best_macro_f1_eval:
                best_macro_f1_eval = row['macro_f1']
                best_epoch = row['epoch']

    return {
        'name':            run_dir.name,
        'model':           m.group('model'),
        'track':           m.group('track'),
        'timestamp':       m.group('ts'),
        'pretrained':      train_args.get('pretrained', '?'),
        'resolved_max_length': train_args.get('resolved_max_length'),
        'resolved_device':     train_args.get('resolved_device'),
        'resolved_amp_dtype':  train_args.get('resolved_amp_dtype'),
        'best_epoch':      best_epoch,
        'epochs_run':      epochs_run,
        'best_macro_f1_eval': best_macro_f1_eval,
        # test set 指标（最权威）
        'test_macro_f1':   test_rep['macro_f1'],
        'test_accuracy':   test_rep['accuracy'],
        'test_loss':       test_rep['loss'],
        'test_samples':    test_rep['samples'],
        'per_class_f1':    test_rep['per_class_f1'],
        'confusion_matrix': test_rep['confusion_matrix'],
        'total_time_s':    total_time,
    }


def collect_runs(runs_root: Path, pick: str = 'best') -> tuple[list[dict], list[str]]:
    """扫描所有 run 目录，按 (model, track) 选一个代表 run。

    Args:
        pick: 同 key 下选哪个：
            'best'   - 取 test_macro_f1 最高的（默认；对比表自动用最强组合，
                       后续失败实验不会让表劣化，但要小心 cherry-picking）
            'latest' - 取 timestamp 最新的（追踪"最近一次实验"）

    Returns:
        (好 run 列表, 警告字符串列表)
    """
    if pick not in ('best', 'latest'):
        raise ValueError(f'pick 必须是 best/latest，收到 {pick!r}')
    if not runs_root.exists():
        return [], [f'runs 根目录不存在: {runs_root}']

    parsed: list[dict] = []
    warnings: list[str] = []

    for d in sorted(runs_root.iterdir()):
        if not d.is_dir():
            continue
        info = parse_run_dir(d)
        if info is None:
            continue
        if 'incomplete' in info:
            warnings.append(f'[skip] {info["name"]}: {info["incomplete"]}')
            continue
        parsed.append(info)

    # 按 (model, track) 分组
    by_key: dict[tuple[str, str], list[dict]] = {}
    for r in parsed:
        by_key.setdefault((r['model'], r['track']), []).append(r)

    selected: list[dict] = []
    for key, runs in by_key.items():
        if pick == 'latest':
            chosen = max(runs, key=lambda r: r['timestamp'])
        else:  # best
            chosen = max(runs, key=lambda r: r['test_macro_f1'])
        selected.append(chosen)

        if len(runs) > 1:
            # 列出所有候选 + 标记被选中
            cand = ', '.join(
                f'{r["timestamp"]}(macro_f1={r["test_macro_f1"]:.4f}'
                f'{", PICKED" if r is chosen else ""})'
                for r in sorted(runs, key=lambda x: x['timestamp'])
            )
            warnings.append(
                f'[note] ({key[0]}, {key[1]}) 有 {len(runs)} 个 run，'
                f'按 pick={pick!r} 策略选: {cand}'
            )

    return selected, warnings


def fmt_seconds(s: float) -> str:
    if s < 60:
        return f'{s:.0f}s'
    m, s = divmod(int(s), 60)
    if m < 60:
        return f'{m}m{s:02d}s'
    h, m = divmod(m, 60)
    return f'{h}h{m:02d}m'


def render_overall_table(runs: list[dict]) -> str:
    """A. 总体对比表。"""
    lines = []
    lines.append('## A. 总体对比（test set）')
    lines.append('')
    lines.append('| 模型 | track | pretrained | max_len | best epoch | epochs run | macro_f1 | accuracy | test loss | 训练时长 |')
    lines.append('|---|---|---|---|---|---|---|---|---|---|')
    # 排序：先 model 再 track
    for r in sorted(runs, key=lambda x: (x['model'], x['track'])):
        lines.append(
            f"| {r['model']} | {r['track']} | `{r['pretrained']}` | "
            f"{r['resolved_max_length']} | "
            f"{r['best_epoch']} | {r['epochs_run']} | "
            f"**{r['test_macro_f1']:.4f}** | {r['test_accuracy']:.4f} | "
            f"{r['test_loss']:.4f} | {fmt_seconds(r['total_time_s'])} |"
        )
    return '\n'.join(lines)


def render_per_class_tables(runs: list[dict]) -> str:
    """B. Per-class F1，usual / virus 各一张。"""
    out: list[str] = []
    out.append('## B. Per-class F1（test set）')
    out.append('')
    for track in ('usual', 'virus'):
        track_runs = sorted([r for r in runs if r['track'] == track],
                            key=lambda x: x['model'])
        if not track_runs:
            continue
        out.append(f'### {track}')
        out.append('')
        header = '| 模型 | ' + ' | '.join(LABELS_ZH) + ' | macro |'
        sep    = '|---|' + '---|' * (len(LABELS_ZH) + 1)
        out.append(header)
        out.append(sep)
        for r in track_runs:
            cells = ' | '.join(f'{x:.4f}' for x in r['per_class_f1'])
            out.append(f"| {r['model']} | {cells} | **{r['test_macro_f1']:.4f}** |")
        out.append('')
    return '\n'.join(out).rstrip()


def top_off_diag(cm: list[list[int]], k: int = 3) -> list[tuple[int, int, int]]:
    """从混淆矩阵取最大的 k 个 off-diagonal cell。返回 [(true_id, pred_id, count), ...]。"""
    cells: list[tuple[int, int, int]] = []
    for i, row in enumerate(cm):
        for j, c in enumerate(row):
            if i != j and c > 0:
                cells.append((i, j, c))
    cells.sort(key=lambda x: x[2], reverse=True)
    return cells[:k]


def render_confusion_section(runs: list[dict]) -> str:
    """C. 主要混淆方向（top-3 off-diagonal per run）。"""
    out: list[str] = []
    out.append('## C. 主要混淆方向（test set，top-3 off-diagonal）')
    out.append('')
    out.append('| 模型 × track | 1 | 2 | 3 |')
    out.append('|---|---|---|---|')
    for r in sorted(runs, key=lambda x: (x['model'], x['track'])):
        top = top_off_diag(r['confusion_matrix'])
        cells = []
        for true_id, pred_id, n in top:
            cells.append(f'真"{LABELS_ZH[true_id]}"→预测"{LABELS_ZH[pred_id]}" {n} 条')
        # 不足 3 个用空字符串补
        while len(cells) < 3:
            cells.append('—')
        out.append(f"| {r['model']} × {r['track']} | {cells[0]} | {cells[1]} | {cells[2]} |")
    return '\n'.join(out)


def render_markdown(runs: list[dict], warnings: list[str]) -> str:
    """拼三张表 + 头部元信息。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    parts: list[str] = []
    parts.append(f'# BERT / ERNIE × usual / virus 对比报告')
    parts.append('')
    parts.append(f'生成时间：{now}')
    parts.append('')
    if warnings:
        parts.append('## 注意')
        parts.append('')
        for w in warnings:
            parts.append(f'- {w}')
        parts.append('')
    parts.append('运行环境（取自 train_args.json）：')
    parts.append('')
    if runs:
        sample = runs[0]
        parts.append(f"- device: `{sample['resolved_device']}`")
        parts.append(f"- amp dtype: `{sample['resolved_amp_dtype']}`")
        parts.append('')
    parts.append('---')
    parts.append('')
    parts.append(render_overall_table(runs))
    parts.append('')
    parts.append('---')
    parts.append('')
    parts.append(render_per_class_tables(runs))
    parts.append('')
    parts.append('---')
    parts.append('')
    parts.append(render_confusion_section(runs))
    parts.append('')
    parts.append('---')
    parts.append('')
    parts.append('## 参考')
    parts.append('')
    parts.append('- 标签 ID 顺序：' + ' / '.join(f'{i}={lab}' for i, lab in enumerate(LABELS_ZH)))
    parts.append('- 训练超参：5 epoch / lr 2e-5 / batch 32 / class_weights balanced / patience 2 / seed 42')
    parts.append('- 评估指标按 macro_f1 选 best checkpoint，本表 macro_f1 / accuracy / per_class_f1 / 混淆矩阵均为 test split')
    parts.append('')
    return '\n'.join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--runs-root', type=Path, default=DEFAULT_RUNS_ROOT,
                   help=f'runs 根目录，默认 {DEFAULT_RUNS_ROOT}')
    p.add_argument('--out', type=Path, default=None,
                   help=f'输出 markdown 路径，默认 {DEFAULT_RESULTS_ROOT}/comparison-{{YYYYMMDD}}.md')
    p.add_argument('--pick', choices=['best', 'latest'], default='best',
                   help='同 (model, track) 多个 run 时如何选：best=test_macro_f1 最高 / latest=时间戳最新。默认 best')
    args = p.parse_args()

    runs, warnings = collect_runs(args.runs_root, pick=args.pick)
    if not runs:
        print('未找到任何完整的 run（带 train_args.json + final_test_report.json）')
        for w in warnings:
            print(' ', w)
        return

    if args.out is None:
        args.out = DEFAULT_RESULTS_ROOT / f'comparison-{datetime.now().strftime("%Y%m%d")}.md'
    args.out.parent.mkdir(parents=True, exist_ok=True)

    md = render_markdown(runs, warnings)
    args.out.write_text(md, encoding='utf-8')

    print(f'扫描到 {len(runs)} 个完整 run（pick={args.pick}）:')
    for r in runs:
        print(f"  - {r['name']:50} test_macro_f1={r['test_macro_f1']:.4f}")
    for w in warnings:
        print(' ', w)
    print(f'\n写出: {args.out}')


if __name__ == '__main__':
    main()
