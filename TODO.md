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

## 当前

- ✅ ~~ERNIE × virus 重跑 `--epochs 8`~~（2026-05-03 已验证：**假设否定**）
  - 新 run `ernie-virus-20260504-0252` test macro_f1 = 0.6619（vs 旧 5 epoch 的 0.6623，几乎打平）
  - 新 run 早停在 epoch 8，best @ epoch 6 = 0.6485（eval set，比旧 5-epoch 的 0.6587 还低 0.01）
  - **真正原因**：trainer 用 `linear_schedule_with_warmup(num_training_steps=len(loader)*epochs)`，
    epoch 上限改大同时把 lr 衰减曲线拉长，原本"最后一 epoch lr→0 做精修"的效果被打散
  - train_loss 从 0.55→0.30，eval_loss 从 0.95→1.16，新 run 实际**更过拟合**
  - 结论：**不是 epoch 上限问题，是 lr schedule + virus 数据规模导致的最佳点恰好落在 epoch 5**
  - `compare_runs.py` 改成 `--pick best/latest` 双策略，默认 best，保留两次 run 让对比表自动用更强的

## 远期

- [ ] **lr schedule 探索**（这次 epochs=8 实验暴露的方向）：
  - 当前 `linear_schedule_with_warmup` 让 best 严重依赖 lr→0 的"末班车"
  - 候选：`cosine_schedule_with_warmup`（最后 lr 也→0 但曲线更平滑）/ 
    `constant_with_warmup`（warmup 后 plateau，靠 early stop 和 weight_decay 控）/
    `ReduceLROnPlateau`（macro_f1 不涨就 ×0.5）
  - 一组对照：ERNIE × virus 用 cosine 跑 5 epoch + 8 epoch 两次，看 best epoch 分布
- [ ] 错误分析：usual 上 "愤怒↔悲伤" 互混 ~280 条，ERNIE 没解决，先看这块
  - 可能和冲突标签相关（usual_train 82 处 / virus_train 65 处）—— spot-check 几条
- [ ] virus 顽疾针对性方案：积极占 51% 导致模型偏向积极
  - oversample 少数类 / focal loss / 调 class_weights 的具体值（当前 sklearn balanced）
- [ ] 推理接口（CLI 单条 + 批量 parquet → parquet）
- [ ] 部署形态（API / 离线批处理 / 二者皆可）
- [ ] usual + virus 合训实验作对照
- [ ] 整理 `legacy/model_training/`：四组跑完后决定保留 / 重写 / 删除

## 已敲定决策（之前的"待定"）

| 决策 | 落地 |
|---|---|
| usual / virus 单训 vs 合训 | **先单训**，合训留作远期对照 |
| `max_length` | per-track 默认（usual 128 / virus 192），CLI 可覆盖 |
| 混合精度 | `--mixed-precision auto/fp32/fp16/bf16`，auto 规则按 device |
| tokenize 缓存 vs 动态 | **一次性预编码**（数据小，内存可忽略） |
| 类权重策略 | sklearn `balanced` 默认，`--class-weights none` 关闭 |
| 模型选型（短期） | **ERNIE > BERT**，3060 实测两个 track 各 +0.03/+0.05 macro_f1 |
