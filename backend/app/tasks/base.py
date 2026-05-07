"""
Celery 任务基类和工具函数

提供数据库会话管理和任务状态更新功能。
"""

from celery import Task
from app.core.database import db as database
from app.models.task import Task as TaskModel
from sqlalchemy.orm import Session
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """
    带数据库会话的 Celery 任务基类

    自动管理数据库连接，任务结束后自动关闭会话。
    """
    _db: Session = None

    @property
    def db(self) -> Session:
        """获取或创建数据库会话"""
        if self._db is None:
            self._db = database.SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        """任务结束后关闭数据库连接"""
        if self._db is not None:
            self._db.close()
            self._db = None


def update_task_status(
    task_id: str,
    status: str = None,
    progress: dict = None,
    result: dict = None,
    error: str = None,
    db: Session = None
):
    """
    更新任务状态到数据库

    Args:
        task_id: 任务ID
        status: 任务状态 (PENDING, STARTED, SUCCESS, FAILURE, REVOKED)
        progress: 进度信息字典
        result: 结果数据
        error: 错误信息
        db: 数据库会话（可选，如果不提供则创建新会话）
    """
    close_db = False
    if db is None:
        db = database.SessionLocal()
        close_db = True

    try:
        task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if task:
            if status:
                task.status = status
                if status == 'STARTED':
                    task.started_at = datetime.utcnow()
                elif status in ['SUCCESS', 'FAILURE', 'REVOKED']:
                    task.completed_at = datetime.utcnow()

            if progress is not None:
                task.progress = progress

            if result is not None:
                task.result = result

            if error is not None:
                task.error = error

            db.commit()
        else:
            logger.warning(f"Task {task_id} not found in database")
    except Exception as e:
        logger.error(f"Failed to update task status: {e}", exc_info=True)
        if db:
            db.rollback()
    finally:
        if close_db and db:
            db.close()
