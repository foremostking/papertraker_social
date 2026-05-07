"""
用户模型

定义系统用户及其角色权限。
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class User(Base):
    """
    系统用户

    支持不同角色，具有不同的权限限制。
    """
    __tablename__ = 'users'

    # 主键
    id = Column(Integer, primary_key=True, index=True)

    # 基本信息
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=False, index=True)

    # 认证信息
    hashed_password = Column(String(200), nullable=False)

    # 角色和权限
    role = Column(String(20), default='free')  # free, pro, vip, admin
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)

    # 任务限制（基于角色的动态限制）
    max_concurrent_tasks = Column(Integer, default=1)  # 最大并发任务数
    max_papers_per_task = Column(Integer, default=500)  # 单个任务最大获取论文数

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)

    # 关系
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"

    @property
    def can_fetch_papers(self) -> bool:
        """是否有权限获取论文"""
        return self.role in ['pro', 'vip', 'admin']

    @property
    def task_limits(self) -> dict:
        """获取任务限制"""
        limits_by_role = {
            'free': {'max_concurrent': 1, 'max_papers': 200},
            'pro': {'max_concurrent': 2, 'max_papers': 1000},
            'vip': {'max_concurrent': 5, 'max_papers': 5000},
            'admin': {'max_concurrent': 10, 'max_papers': 10000},
        }
        return limits_by_role.get(self.role, limits_by_role['free'])
