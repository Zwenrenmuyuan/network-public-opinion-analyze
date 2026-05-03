"""文本预处理。训练和推理必须用同一份实现，否则有 train/inference skew。

旧仓库里这个函数有两份不一致的实现：
  - 数据预处理/文本预处理.py   （训练时跑）：只去掉 '@' 符号，保留用户名
  - predict_from_hbase.py      （推理时跑）：去掉整个 '@username'

本文件采用**推理侧**的实现作为新的 canonical 版本，理由见 README 的
"已知问题：训练 / 推理预处理不一致" 一节。如需精确复现旧 checkpoint 的训练时行为，
把 _remove_at_mentions 改成 re.sub(r'@', '', text) 即可。
"""

from __future__ import annotations

import re
import unicodedata

from zhconv import convert


_URL_RE = re.compile(
    r'http[s]?://(?:[a-zA-Z]|[0-9]|[$\-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
)
_EMAIL_RE = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
_AT_MENTION_RE = re.compile(r'@[\w\-]+')
_WHITESPACE_RE = re.compile(r'\s+')


def _remove_at_mentions(text: str) -> str:
    """去掉 @username 整个 mention。

    若要复现旧 checkpoint 的训练时行为（只去掉 @ 符号、保留用户名），
    把这里改成 return text.replace('@', '')。
    """
    return _AT_MENTION_RE.sub('', text)


def process_text(text: str, max_length: int = 140) -> str:
    """对一条社交媒体文本做训练 / 推理一致的清洗。

    步骤（顺序敏感，不要改）：
      1. NFKC 归一化（全角转半角）
      2. 繁体转简体
      3. 英文小写
      4. 去 URL（必须在 email 之前，否则 URL 里的子串会被误判成 email）
      5. 去 email
      6. 去 @username mention（见 _remove_at_mentions）
      7. 折叠空白
      8. 截断到 max_length

    Args:
        text: 原始文本，非 str 会被原样返回。
        max_length: 截断长度，默认 140（微博旧版限制）。改这个值需要重训模型。

    Returns:
        清洗后的文本。空字符串可能返回，调用方需要自己过滤。
    """
    if not isinstance(text, str):
        return text

    text = unicodedata.normalize('NFKC', text)
    text = convert(text, 'zh-cn')
    text = text.lower()
    text = _URL_RE.sub('', text)
    text = _EMAIL_RE.sub('', text)
    text = _remove_at_mentions(text)
    text = _WHITESPACE_RE.sub(' ', text).strip()
    text = text[:max_length]

    return text
