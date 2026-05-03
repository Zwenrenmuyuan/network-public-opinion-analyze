"""设备探测 + 混合精度类型选择。

设计目标：训练代码 device-agnostic，无论 Mac MPS、Win/Linux CUDA、还是 CPU 都能跑同一份。
"""

from __future__ import annotations

import logging
import os

import torch

logger = logging.getLogger(__name__)

# Mac MPS 上某些 BERT 算子未实现（layer_norm 的某些 backward path 等），
# 设置 fallback 到 CPU 即可继续训练（性能略降但能跑通）。
# setdefault 而非赋值，允许用户在外面覆盖。
os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')


def get_device() -> torch.device:
    """优先级 cuda > mps > cpu。"""
    if torch.cuda.is_available():
        return torch.device('cuda')
    if torch.backends.mps.is_available():
        return torch.device('mps')
    return torch.device('cpu')


def select_amp_dtype(device: torch.device, requested: str) -> torch.dtype | None:
    """根据设备和请求决定混合精度 dtype，None 表示走 fp32（不开 autocast）。

    auto 规则:
        cuda: 优先 fp16（消费级 Ampere bf16 比 fp16 略慢；A100/H100 bf16 更稳）
        mps:  fp32（fp16 autocast 历史上不稳定，bf16 部分算子缺失）
        cpu:  fp32（fp16 在 CPU 上没有性能意义）
    """
    requested = requested.lower()
    if requested == 'fp32':
        return None

    if requested == 'fp16':
        if device.type == 'cuda':
            return torch.float16
        logger.warning(f'fp16 在 {device.type} 上不推荐，回退 fp32')
        return None

    if requested == 'bf16':
        if device.type == 'cuda' and torch.cuda.is_bf16_supported():
            return torch.bfloat16
        logger.warning(f'bf16 在 {device.type} 上不可用，回退 fp32')
        return None

    if requested == 'auto':
        if device.type == 'cuda':
            return torch.float16
        return None

    raise ValueError(f'未知 mixed_precision: {requested!r}，应为 auto/fp32/fp16/bf16')
