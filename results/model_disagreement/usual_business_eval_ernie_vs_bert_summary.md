# ernie / bert 分歧分析

- split: `business_eval`
- samples: 1500
- primary: `runs\ernie-usual-mixed-v2\best`
- secondary: `runs\bert-usual-mixed-v2\best`

## 总体指标

| 模型 | accuracy | macro-F1 |
|---|---:|---:|
| ernie | 0.8260 | 0.7738 |
| bert | 0.7720 | 0.7165 |

## 互补性

- agreement: 1223 (81.53%)
- disagreement: 277 (18.47%)
- both_correct: 1083
- ernie_only_correct: 156
- bert_only_correct: 75
- both_wrong: 186
- oracle_accuracy: 0.8760
- disagreement ernie accuracy: 0.5632
- disagreement bert accuracy: 0.2708

## secondary-only correct by label

- 积极: 17
- 愤怒: 13
- 悲伤: 9
- 恐惧: 2
- 惊讶: 10
- 中性: 24
