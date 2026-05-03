"""交互式单条预测，用于训练后 sanity check。

用法:
    python bert/predict.py                                  # 默认加载 bert/saved_models/epoch_5
    python bert/predict.py --model_path path/to/checkpoint
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import torch
from transformers import BertTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constants import BERT_CHECKPOINT_DIR, BERT_PRETRAINED, ID2LABEL, MAX_LENGTH
from preprocessing import process_text
from bert.model import EmotionClassifier


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


class EmotionPredictor:
    def __init__(self, model_path: Path):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f'使用设备: {self.device}')

        # 优先用 checkpoint 自带的 tokenizer，找不到再退回到 BERT 官方的
        try:
            self.tokenizer = BertTokenizer.from_pretrained(model_path)
        except Exception:
            logger.warning(f'{model_path} 里没有 tokenizer 文件，回退到 {BERT_PRETRAINED}')
            self.tokenizer = BertTokenizer.from_pretrained(BERT_PRETRAINED)

        logger.info(f'加载模型: {model_path}')
        self.model = EmotionClassifier.from_pretrained(model_path)
        self.model.to(self.device)
        self.model.eval()

    def predict(self, text: str) -> tuple[str, float]:
        # 推理时也要走完整的 process_text，否则跟训练数据的清洗不一致
        cleaned = process_text(text)
        if not cleaned:
            return '中性', 0.0

        inputs = self.tokenizer(
            cleaned,
            max_length=MAX_LENGTH,
            padding='max_length',
            truncation=True,
            return_tensors='pt',
            return_token_type_ids=False,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            _, logits = self.model(**inputs)
            probs = torch.softmax(logits, dim=1)
            pred = torch.argmax(probs, dim=1).item()
            confidence = probs[0][pred].item()

        return ID2LABEL[pred], confidence


def main() -> None:
    parser = argparse.ArgumentParser(description='BERT 情感预测（交互式）')
    parser.add_argument(
        '--model_path',
        type=Path,
        default=BERT_CHECKPOINT_DIR / 'epoch_5',
        help='checkpoint 路径，默认 bert/saved_models/epoch_5',
    )
    args = parser.parse_args()

    if not args.model_path.exists():
        logger.error(f'checkpoint 不存在: {args.model_path}')
        logger.info('请先跑 python bert/train.py 训练模型')
        return

    predictor = EmotionPredictor(args.model_path)

    print('\nBERT 情感预测交互模式。输入 q 退出。')
    while True:
        try:
            text = input('\n请输入文本: ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() == 'q':
            break
        if not text:
            continue

        try:
            emotion, confidence = predictor.predict(text)
            print(f'  情感: {emotion}')
            print(f'  置信度: {confidence:.2%}')
            if confidence < 0.5:
                print('  (置信度较低，结果可能不可靠)')
        except Exception as e:
            logger.error(f'预测出错: {e}')


if __name__ == '__main__':
    main()
