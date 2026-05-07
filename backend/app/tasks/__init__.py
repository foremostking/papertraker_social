"""
Celery 任务模块

用于异步执行耗时操作，如期刊栏目获取、论文爬取等。
"""

from .celery_app import celery_app

__all__ = ['celery_app']
