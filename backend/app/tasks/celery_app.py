"""
Celery 应用配置

配置 Celery 应用、任务队列、路由和定时任务。
"""

import os
from celery import Celery
from celery.schedules import crontab

# 从环境变量读取配置，兼容 Docker 部署
broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')

# 创建 Celery 应用
celery_app = Celery(
    'papertracker',
    broker=broker_url,
    backend=result_backend,
    include=[
        'app.tasks.journal_tasks',
        'app.tasks.paper_tasks',
    ]
)

# Celery 配置
celery_app.conf.update(
    # ===== 序列化配置 =====
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    content_encoding='utf-8',

    # ===== 时区配置 =====
    timezone='Asia/Shanghai',
    enable_utc=True,

    # ===== 结果配置 =====
    result_expires=604800,  # 结果过期时间（7天）
    result_extended=True,

    # ===== 任务执行配置 =====
    task_acks_late=True,  # 任务执行完成后才确认
    worker_prefetch_multiplier=1,  # 每次只预取1个任务
    task_reject_on_worker_lost=True,  # Worker丢失时拒绝任务

    # ===== 重试配置 =====
    task_default_max_retries=3,  # 默认最大重试次数
    task_retry_delay=60,  # 重试延迟（秒）
    task_retry_backoff=True,  # 启用指数退避
    task_retry_backoff_max=600,  # 最大退避时间（10分钟）

    # ===== 优先级队列配置 =====
    task_default_queue='default',
    task_create_missing_queues=True,

    # ===== 路由配置 =====
    task_routes={
        # 高优先级任务：栏目刷新
        'app.tasks.journal_tasks.fetch_journal_columns_task': {
            'queue': 'high',
            'priority': 5
        },
        # 默认队列：论文获取
        'app.tasks.paper_tasks.fetch_papers_by_column_task': {
            'queue': 'default',
            'priority': 7
        },
        # 批量任务
        'app.tasks.journal_tasks.batch_fetch_columns_task': {
            'queue': 'default',
            'priority': 8
        },
    },

    # ===== 定时任务配置 =====
    beat_schedule={
        # 每天凌晨2点计算统计数据
        'daily-stats': {
            'task': 'app.tasks.system_tasks.calculate_daily_stats',
            'schedule': crontab(hour=2, minute=0),
        },
    },

    # ===== Worker 配置 =====
    worker_max_tasks_per_child=100,  # 每个 Worker 子进程最多执行100个任务后重启
    worker_disable_rate_limits=False,  # 不禁用速率限制

    # ===== 监控配置 =====
    worker_send_task_events=True,  # 发送任务事件
    task_send_sent_event=True,  # 发送任务发送事件
)

# ===== 队列定义 =====
from kombu import Queue

task_queues = [
    Queue('high', routing_key='high.priority'),
    Queue('default', routing_key='default'),
]

if __name__ == '__main__':
    # 启动 Celery Worker（用于开发测试）
    celery_app.start()
