# -*- coding: utf-8 -*-
"""
投资组合监控框架(港股 / 美股)。

依据《AI-Powered Portfolio Monitoring Assistant》提案,将「低 / 中 / 高风险规则集」
编码为可评估的指标告警体系。当前实现提案的三大类:
  1. 技术分析与动量触发(RSI、均线金叉死叉、成交量异动)
  2. 基本面与估值参数(前瞻 P/E、P/B、预测盈利增长、CAPEX 占营收)
  4. 股息与股东回报(股息率、派息比率)

第 3 类「衍生品与流动性」(Call/Put、累积沽空、CBBC 庄家集中度)因缺乏免费数据源,
暂未实现,在报告中以占位形式标注。
"""

from .rules import (
    TIERS,
    TIER_LABELS,
    DEFAULT_TIER,
    CATEGORY_LABELS,
    DEFERRED_CATEGORIES,
)
from .evaluator import evaluate_monitoring, compute_technical_indicators

__all__ = [
    "TIERS",
    "TIER_LABELS",
    "DEFAULT_TIER",
    "CATEGORY_LABELS",
    "DEFERRED_CATEGORIES",
    "evaluate_monitoring",
    "compute_technical_indicators",
]
