# TODO

## 已完成
- 数据解压（`scripts/extract_dataset.py`）
- 数据探索（标签 / 长度 / 重复 / 泄露 / 文本特征）
- 预处理：清洗 + 去重 + 去泄露 + parquet 化
- README + 数据流水线文档
- 模型训练 / 评估管线（`src/npo/` + `scripts/{train,evaluate}.py`）：
  - 预编码 `EmotionDataset`（一次性 tokenize 缓存）
  - device 自动 cuda/mps/cpu，AMP `--mixed-precision auto`（cuda→fp16）
  - weighted CE（sklearn balanced），可 `--class-weights none` 关
  - 按 `macro_f1` 选 best，patience=2 early stop，best/last 双 checkpoint
  - eval 当 validation，test 仅 final 评估（`scripts/evaluate.py`）
  - 训练产物 `runs/{model}-{track}-{timestamp}/`：train.log / train_args.json / eval_history.jsonl / final_test_report.json
- **BERT-usual baseline**（Mac MPS fp32）：test `macro_f1=0.7331` / `accuracy=0.7614`（best @ epoch 2）
- **3060 上铺齐 BERT/ERNIE × usual/virus 四组**（CUDA fp16，2026-05-03）：

  | 模型 | track | best epoch | test macro_f1 | test accuracy | 训练时长 |
  |---|---|---|---|---|---|
  | BERT  | usual | 2 | 0.7412 | 0.7722 | 11m |
  | BERT  | virus | 2 | 0.6157 | 0.7411 | 4m |
  | ERNIE | usual | 3 | **0.7709** | **0.7972** | 14m |
  | ERNIE | virus | 5 | **0.6623** | **0.7820** | 6m |

  详细 per-class F1 + 主要混淆方向见 `results/comparison-20260503.md`。
  - ERNIE 全面 > BERT：usual +0.030，virus +0.047（macro_f1）
  - 3060 上 BERT-usual 0.7412 vs Mac 0.7331 → +0.008，硬件 / 精度差异在合理范围
  - usual 顽疾：愤怒↔悲伤（BERT 212+74=286 条 / ERNIE 224+59=283 条，换模型没缓解）
  - virus 顽疾：积极↔中性 / 积极↔悲伤（数据 51% 是积极，模型偏向积极）
- ✅ ~~ERNIE × virus 重跑 `--epochs 8`~~（2026-05-03 已验证：**假设否定**）
  - 新 run `ernie-virus-20260504-0252` test macro_f1 = 0.6619（vs 旧 5 epoch 的 0.6623，几乎打平）
  - 新 run 早停在 epoch 8，best @ epoch 6 = 0.6485（eval set，比旧 5-epoch 的 0.6587 还低 0.01）
  - epoch 上限改大没有收益，且更容易过拟合；不继续把 lr schedule 当主线优化方向
  - train_loss 从 0.55→0.30，eval_loss 从 0.95→1.16，新 run 实际**更过拟合**
  - `compare_runs.py` 改成 `--pick best/latest` 双策略，默认 best，保留两次 run 让对比表自动用更强的

## 当前

- **主线收敛到通用舆情模型：`ernie` + `usual`**。
  - 线上/业务默认不使用 `virus` 训练模型；疫情语料和当前场景不适配，容易引入 domain bias。
  - `virus` 结果保留为专项场景参考，不再围绕 `virus` 做调参、采样或合训实验。
- **六分类效果优化先走数据治理，不继续优先调参**。
  - ✅ 六分类 LLM/人工统一标注规范：`docs/labeling-guideline.md`
  - ✅ SMP 高风险重标候选生成：`scripts/data_repair/build_smp_relabel_candidates.py`
  - ✅ 业务离线 Parquet 候选生成：`scripts/data_repair/build_business_label_candidates.py`
  - ✅ OpenAI-compatible LLM 并发预标注：`scripts/data_repair/llm_label_candidates.py`
  - ✅ 两级 LLM 复核 / 自动仲裁：`scripts/data_repair/adjudicate_llm_labels.py`
  - ✅ Silver 派生训练集生成：`scripts/data_repair/build_smp_silver_dataset.py`
  - [ ] 跑一批 `usual` 重标候选，人工抽查 LLM 标注质量
  - [ ] 从爬虫 ClickHouse 离线导出业务 `post/comment` Parquet，先建业务 sanity/eval set
- [ ] 推理接口（CLI 单条 + 批量 parquet → parquet）
- [ ] 部署形态（API / 离线批处理 / 二者皆可）
- [ ] 错误分析：usual 上 "愤怒↔悲伤" 互混 ~280 条，ERNIE 没解决，先看这块
  - 可能和冲突标签相关（usual_train 82 处）—— spot-check 几条

## 远期

- [ ] 收集少量真实业务样本做 sanity set，优先验证 `ernie-usual` 在实际场景的错误类型
- [ ] 若业务样本暴露系统性偏差，再考虑增量标注 / 微调；不要优先回到 `virus` 数据集补训练
- [ ] 整理 `legacy/model_training/`：四组跑完后决定保留 / 重写 / 删除

## 已敲定决策（之前的"待定"）

| 决策 | 落地 |
|---|---|
| 主线训练数据 | **usual 通用数据集**；`virus` 仅保留为疫情专项参考，不作为默认训练数据 |
| 默认模型 | **ERNIE + usual**，当前 test macro-F1 `0.7709` / accuracy `0.7972` |
| `max_length` | 主线 usual 默认 128；virus 参考实验仍用 192 |
| 混合精度 | `--mixed-precision auto/fp32/fp16/bf16`，auto 规则按 device |
| tokenize 缓存 vs 动态 | **一次性预编码**（数据小，内存可忽略） |
| 类权重策略 | sklearn `balanced` 默认，`--class-weights none` 关闭 |
| 模型选型 | **ERNIE > BERT**；主线不再继续 BERT/virus 调参 |
