"""中文社交媒体短文本 6 分类情感分析的训练 / 评估管线。

子模块:
    config   - 标签映射、默认 max_length、模型名（项目内单一来源）
    device   - 设备探测、混合精度类型选择
    data     - 从 parquet 读数据、预编码、计算类权重
    model    - 模型工厂（BERT / ERNIE）
    metrics  - macro-F1、混淆矩阵等评估指标
    trainer  - 训练循环
"""
