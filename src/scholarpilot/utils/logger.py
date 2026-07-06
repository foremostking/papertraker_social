"""日志配置模块.

提供统一的日志配置，支持控制台和文件输出。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "scholarpilot",
    level: int = logging.INFO,
    log_file: Optional[str | Path] = None,
) -> logging.Logger:
    """配置并返回一个 Logger 实例.

    Args:
        name: Logger 名称.
        level: 日志级别，默认 INFO.
        log_file: 日志文件路径，为 None 则不输出到文件.

    Returns:
        配置好的 Logger 实例.
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件 handler（可选）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
