# BERT / ERNIE × usual / virus 对比报告

生成时间：2026-05-03 23:50

## 注意

- [note] (ernie, virus) 有 2 个 run，按 pick='best' 策略选: 20260504-0231(macro_f1=0.6623, PICKED), 20260504-0252(macro_f1=0.6619)

运行环境（取自 train_args.json）：

- device: `cuda`
- amp dtype: `torch.float16`

---

## A. 总体对比（test set）

| 模型 | track | pretrained | max_len | best epoch | epochs run | macro_f1 | accuracy | test loss | 训练时长 |
|---|---|---|---|---|---|---|---|---|---|
| bert | usual | `bert-base-chinese` | 128 | 2 | 4 | **0.7412** | 0.7722 | 0.6640 | 10m42s |
| bert | virus | `bert-base-chinese` | 192 | 2 | 4 | **0.6157** | 0.7411 | 0.7603 | 4m26s |
| ernie | usual | `nghuyong/ernie-3.0-base-zh` | 128 | 3 | 5 | **0.7709** | 0.7972 | 0.6105 | 13m58s |
| ernie | virus | `nghuyong/ernie-3.0-base-zh` | 192 | 5 | 5 | **0.6623** | 0.7820 | 0.6662 | 5m53s |

---

## B. Per-class F1（test set）

### usual

| 模型 | 积极 | 愤怒 | 悲伤 | 恐惧 | 惊讶 | 中性 | macro |
|---|---|---|---|---|---|---|---|
| bert | 0.7982 | 0.8154 | 0.7008 | 0.6533 | 0.6320 | 0.8477 | **0.7412** |
| ernie | 0.8282 | 0.8363 | 0.7281 | 0.7012 | 0.6796 | 0.8520 | **0.7709** |

### virus

| 模型 | 积极 | 愤怒 | 悲伤 | 恐惧 | 惊讶 | 中性 | macro |
|---|---|---|---|---|---|---|---|
| bert | 0.8896 | 0.7230 | 0.4979 | 0.5314 | 0.4108 | 0.6417 | **0.6157** |
| ernie | 0.9034 | 0.7860 | 0.5745 | 0.5908 | 0.4318 | 0.6874 | **0.6623** |

---

## C. 主要混淆方向（test set，top-3 off-diagonal）

| 模型 × track | 1 | 2 | 3 |
|---|---|---|---|
| bert × usual | 真"愤怒"→预测"悲伤" 212 条 | 真"愤怒"→预测"惊讶" 81 条 | 真"悲伤"→预测"愤怒" 74 条 |
| bert × virus | 真"积极"→预测"中性" 89 条 | 真"积极"→预测"悲伤" 51 条 | 真"愤怒"→预测"悲伤" 51 条 |
| ernie × usual | 真"愤怒"→预测"悲伤" 224 条 | 真"中性"→预测"积极" 70 条 | 真"积极"→预测"悲伤" 62 条 |
| ernie × virus | 真"积极"→预测"中性" 69 条 | 真"中性"→预测"积极" 50 条 | 真"积极"→预测"悲伤" 45 条 |

---

## 参考

- 标签 ID 顺序：0=积极 / 1=愤怒 / 2=悲伤 / 3=恐惧 / 4=惊讶 / 5=中性
- 训练超参：5 epoch / lr 2e-5 / batch 32 / class_weights balanced / patience 2 / seed 42
- 评估指标按 macro_f1 选 best checkpoint，本表 macro_f1 / accuracy / per_class_f1 / 混淆矩阵均为 test split
