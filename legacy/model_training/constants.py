"""6 类情感分类的 taxonomy 和相关常量。

来源：旧仓库 network-public-opinion-analyze-web 的 BERT/ERNIE 训练管线。
所有训练、推理、统计聚合都应当 import 这个模块，避免在多处复刻同样的字典导致漂移。
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# 标签定义
# ---------------------------------------------------------------------------

# 6 类情感的中文标签，顺序即模型输出 logits 的索引顺序。
# 不要随意调整顺序，会让已有 checkpoint 失效。
LABELS: tuple[str, ...] = (
    '积极',   # 0
    '愤怒',   # 1
    '悲伤',   # 2
    '恐惧',   # 3
    '惊讶',   # 4
    '中性',   # 5
)

ID2LABEL: dict[int, str] = {i: label for i, label in enumerate(LABELS)}
LABEL2ID: dict[str, int] = {label: i for i, label in enumerate(LABELS)}

NUM_LABELS: int = len(LABELS)

# 负面情感聚合定义。系统所有 "negative_percent" 之类的指标都以这个为准。
# 不包括 "惊讶"，因为惊讶可正可负，旧产品定义里归入中性侧。
NEGATIVE_LABELS: frozenset[str] = frozenset({'愤怒', '悲伤', '恐惧'})

# SMP2020-EWECT 数据集的英文标签到中文标签的映射。
# 数据集原始字段 "情绪标签" 是英文，预处理时转成中文。
LABEL_MAP_EN_TO_ZH: dict[str, str] = {
    'happy':    '积极',
    'angry':    '愤怒',
    'sad':      '悲伤',
    'fear':     '恐惧',
    'surprise': '惊讶',
    'neutral':  '中性',
}

# ---------------------------------------------------------------------------
# 模型超参
# ---------------------------------------------------------------------------

# 文本截断长度。BERT/ERNIE 训练和推理都用这个值。
# 微博单条限制是 140 字（旧版限制），所以选 140 是合理的领域常量。
# 改这个会让已有 checkpoint 的有效输入长度变化，需要重训。
MAX_LENGTH: int = 140

# 训练超参的默认值（train.py 里也复制了一份，这里作为 spec 参考）
DEFAULT_BATCH_SIZE: int = 32
DEFAULT_LEARNING_RATE: float = 2e-5
DEFAULT_NUM_EPOCHS: int = 5

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

# 本目录的根路径，子模块拼路径时用。
ROOT_DIR: Path = Path(__file__).resolve().parent

# 数据集根目录。预处理脚本和 Dataset 类都从这里读。
DATA_DIR: Path = ROOT_DIR / 'datasets'

# 各 train.py 默认保存 checkpoint 的位置（每个模型放在自己的子目录下）
BERT_CHECKPOINT_DIR: Path = ROOT_DIR / 'bert' / 'saved_models'
ERNIE_CHECKPOINT_DIR: Path = ROOT_DIR / 'ernie' / 'saved_models'

# ---------------------------------------------------------------------------
# 预训练模型 ID（HuggingFace Hub）
# ---------------------------------------------------------------------------

BERT_PRETRAINED: str = 'bert-base-chinese'
ERNIE_PRETRAINED: str = 'nghuyong/ernie-3.0-base-zh'
