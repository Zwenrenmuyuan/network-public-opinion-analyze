# 业务情感模型选择记录

生成时间：2026-05-05

## 结论

- 最终业务候选模型：`runs/ernie-usual-mixed-v2/best`
- BERT 保留为对照模型和分歧样本发现工具，不作为主模型。
- 第二轮定向业务样本补充有效提升真实业务验证集表现，同时没有降低 SMP test 表现。

## 数据与模型

- 基础数据：SMP usual silver repaired train/eval/test。
- 业务验证集：`data/processed/usual_business_eval.parquet`，不参与训练。
- 第一轮业务训练池：`data/processed/usual_business_train_pool.parquet`。
- 第二轮业务定向训练池：`data/processed/usual_business_train_pool_v2.parquet`。
- 混合训练数据：`data/processed_mixed_v2/`。

## 总体结果

| 模型 | business_eval macro-F1 | business_eval acc | SMP test macro-F1 | SMP test acc |
|---|---:|---:|---:|---:|
| ERNIE silver baseline | 0.6674 | 0.7373 | 0.7686 | 0.7934 |
| ERNIE mixed-v1 | 0.7207 | 0.7913 | 0.7689 | 0.7968 |
| ERNIE mixed-v2 | **0.7738** | **0.8260** | **0.7702** | **0.7994** |
| BERT mixed-v2 | 0.7165 | 0.7720 | 0.7514 | 0.7769 |

## ERNIE mixed-v2 业务验证集 Per-Class F1

| 标签 | F1 |
|---|---:|
| 积极 | 0.9138 |
| 愤怒 | 0.7565 |
| 悲伤 | 0.7761 |
| 恐惧 | 0.7299 |
| 惊讶 | 0.6881 |
| 中性 | 0.7785 |

## BERT / ERNIE 双模型说明

在相同的 `processed_mixed_v2` 数据上，ERNIE 在业务验证集和 SMP test 上均优于 BERT。BERT 不适合作为最终主模型，但可作为对照模型和分歧样本发现工具。

论文中可表述为：

> 本文构建了 BERT 与 ERNIE 双模型对照实验框架，并利用双模型预测差异辅助发现困难样本。实验结果表明，ERNIE 在业务验证集和通用测试集上均取得更优表现，因此最终选取 ERNIE mixed-v2 作为主模型，保留 BERT 作为对照模型和困难样本分析工具。

## 后续分歧分析

可运行以下命令生成逐样本分歧报告：

```bash
uv run python scripts/analyze_model_disagreement.py \
  --primary-checkpoint runs/ernie-usual-mixed-v2/best \
  --secondary-checkpoint runs/bert-usual-mixed-v2/best \
  --primary-name ernie \
  --secondary-name bert \
  --track usual \
  --processed-root data/processed_mixed_v2 \
  --split business_eval
```

输出目录：

```text
results/model_disagreement/
```

重点关注：

- `bert_only_correct` 是否足够多；若很少，说明没有部署级互补价值。
- `oracle_accuracy` 相比 ERNIE accuracy 的提升幅度；若提升明显，可用于主动学习候选筛选。
- 两模型不一致样本可作为下一轮 LLM/人工复核候选。
