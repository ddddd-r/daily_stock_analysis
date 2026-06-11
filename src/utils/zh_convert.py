# -*- coding: utf-8 -*-
"""
简体 → 繁体(香港标准)转换工具。

用于对外推送内容(邮件 / 企业微信 / Telegram / 飞书等)统一转为繁体中文,
面向香港用户。仅作用于「最终输出文本」,不影响系统内部以简体进行的逻辑比对。

依赖 opencc(配置 s2hk)。若 opencc 不可用则原样返回(fail-open)。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_converter = None
_init_done = False


def _get_converter():
    global _converter, _init_done
    if _init_done:
        return _converter
    _init_done = True
    try:
        import opencc
        _converter = opencc.OpenCC("s2hk")  # 简体 -> 繁体(香港标准)
    except Exception as exc:  # noqa: BLE001 - fail-open
        logger.warning("OpenCC 不可用,繁体转换将跳过: %s", exc)
        _converter = None
    return _converter


def to_traditional(text: Optional[str]) -> Optional[str]:
    """将文本转为繁体(香港标准);非字符串或转换失败时原样返回。"""
    if not text or not isinstance(text, str):
        return text
    conv = _get_converter()
    if conv is None:
        return text
    try:
        return conv.convert(text)
    except Exception as exc:  # noqa: BLE001 - fail-open
        logger.debug("繁体转换失败,返回原文: %s", exc)
        return text
