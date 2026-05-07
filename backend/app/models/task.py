"""
任务模型

存储异步任务的执行状态、进度和结果。
"""

from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base
from app.models.user import User  # noqa: F401


class Task(Base):
    """
    异步任务记录

    用于追踪 Celery 执行的异步任务状态，包括：
    - 期刊栏目刷新任务
    - 论文获取任务
    - 批量更新任务
    """
    __tablename__ = 'tasks'

    # 主键
    id = Column(String(36), primary_key=True)  # UUID / Celery task ID

    # 用户关联
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)

    # 任务信息
    type = Column(String(50), nullable=False, index=True)  # 任务类型：fetch_columns, fetch_papers, etc.
    name = Column(String(200))  # 任务名称（用户可读描述）
    priority = Column(Integer, default=5)  # 优先级 1-10（数字越小优先级越高）

    # 任务参数
    params = Column(JSON)  # 任务参数（JSON格式）

    # 状态
    status = Column(String(20), default='PENDING', index=True)  # PENDING, STARTED, SUCCESS, FAILURE, REVOKED

    # 进度和结果
    progress = Column(JSON)  # 进度信息：{"current": 10, "total": 100, "message": "...", "current_item": "..."}
    result = Column(JSON)  # 任务结果
    error = Column(Text)  # 错误信息

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime)  # 任务开始时间
    completed_at = Column(DateTime)  # 任务完成时间

    # 关系
    user = relationship("User", back_populates="tasks")

    def __repr__(self):
        return f"<Task(id={self.id}, type={self.type}, status={self.status}, name={self.name})>"

    @property
    def duration(self) -> float:
        """任务执行时长（秒）"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self.status in ['PENDING', 'STARTED']

    @property
    def is_completed(self) -> bool:
        """是否已完成（成功或失败）"""
        return self.status in ['SUCCESS', 'FAILURE', 'REVOKED']
