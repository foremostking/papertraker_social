"""
任务管理 API 端点

提供任务的创建、查询、取消、删除等功能的API。
"""

import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.models.task import Task as TaskModel
from app.models.user import User
from app.tasks.journal_tasks import fetch_journal_columns_task, batch_fetch_columns_task
from app.tasks.paper_tasks import fetch_papers_by_column_task
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 常量
MAX_CONCURRENT_TASKS = 5  # 每用户最大并发任务数


# ==================== Pydantic 模型 ====================

class TaskCreateRequest(BaseModel):
    """创建任务请求"""
    type: str  # 'fetch_columns', 'batch_fetch_columns', 'fetch_papers'
    params: dict
    priority: int = 5
    name: Optional[str] = None


class TaskResponse(BaseModel):
    """任务响应"""
    id: str
    type: str
    name: Optional[str]
    status: str
    priority: int
    progress: Optional[dict]
    result: Optional[dict]
    error: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]

    class Config:
        from_attributes = True


# ==================== 辅助函数 ====================

def can_create_task(db: Session, user_id: int) -> bool:
    """检查用户是否可以创建新任务"""
    running_count = db.query(TaskModel).filter(
        TaskModel.user_id == user_id,
        TaskModel.status.in_(['PENDING', 'STARTED'])
    ).count()

    return running_count < MAX_CONCURRENT_TASKS


def get_default_task_name(task_type: str, params: dict) -> str:
    """生成默认任务名称"""
    if task_type == 'fetch_columns':
        return f"获取期刊栏目 #{params.get('journal_id', '')}"
    elif task_type == 'batch_fetch_columns':
        return f"批量获取栏目 (最多 {params.get('limit', 100)} 个)"
    elif task_type == 'fetch_papers':
        return f"获取论文: {params.get('column_name', '')}"
    return '未命名任务'


async def get_current_user_temp(token: str, db: Session) -> Optional[User]:
    """
    临时获取当前用户函数

    TODO: 替换为真正的 JWT 认证
    """
    try:
        if token.startswith("user_id:"):
            user_id = int(token.split(":")[1])
            return db.query(User).filter(User.id == user_id).first()
    except:
        pass
    return None


# ==================== API 端点 ====================

@router.post("/", response_model=dict)
async def create_task(
    request: TaskCreateRequest,
    token: str,
    db: Session = Depends(get_db)
):
    """
    创建新任务

    Args:
        request: 任务创建请求
        token: 用户认证 token (临时方案)
        db: 数据库会话
    """
    # 获取用户
    user = await get_current_user_temp(token, db)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="无效的认证信息"
        )

    # 检查并发限制
    if not can_create_task(db, user.id):
        raise HTTPException(
            status_code=429,
            detail=f"任务数已达上限 ({MAX_CONCURRENT_TASKS})，请等待现有任务完成"
        )

    # 验证任务类型
    valid_types = ['fetch_columns', 'batch_fetch_columns', 'fetch_papers']
    if request.type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"无效的任务类型，必须是: {', '.join(valid_types)}"
        )

    # 创建任务记录
    task_id = str(uuid.uuid4())

    task = TaskModel(
        id=task_id,
        user_id=user.id,
        type=request.type,
        name=request.name or get_default_task_name(request.type, request.params),
        priority=request.priority,
        params=request.params,
        status='PENDING'
    )
    db.add(task)
    db.commit()

    # 提交到 Celery
    queue = 'high' if request.priority < 5 else 'default'

    try:
        if request.type == 'fetch_columns':
            fetch_journal_columns_task.apply_async(
                args=[request.params['journal_id'], user.id, task.name],
                task_id=task_id,
                queue=queue
            )

        elif request.type == 'batch_fetch_columns':
            batch_fetch_columns_task.apply_async(
                args=[request.params.get('limit', 100), user.id],
                task_id=task_id,
                queue=queue
            )

        elif request.type == 'fetch_papers':
            fetch_papers_by_column_task.apply_async(
                args=[
                    request.params['journal_id'],
                    request.params['column_name'],
                    user.id,
                    request.params.get('fetch_details', False),
                    request.params.get('max_papers', 500)
                ],
                task_id=task_id,
                queue=queue
            )

    except Exception as e:
        # Celery 提交失败，删除任务记录
        db.delete(task)
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"提交任务失败: {str(e)}"
        )

    return {
        'task_id': task_id,
        'status': 'PENDING',
        'message': '任务已创建'
    }


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_status(
    task_id: str,
    token: str,
    db: Session = Depends(get_db)
):
    """获取任务状态"""
    # 获取用户
    user = await get_current_user_temp(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="无效的认证信息")

    task = db.query(TaskModel).filter(
        TaskModel.id == task_id,
        TaskModel.user_id == user.id  # 用户隔离
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return TaskResponse(
        id=task.id,
        type=task.type,
        name=task.name,
        status=task.status,
        priority=task.priority,
        progress=task.progress,
        result=task.result,
        error=task.error,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    token: str,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """获取任务列表"""
    # 获取用户
    user = await get_current_user_temp(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="无效的认证信息")

    query = db.query(TaskModel).filter(TaskModel.user_id == user.id)

    if status:
        query = query.filter(TaskModel.status == status.upper())

    tasks = query.order_by(TaskModel.created_at.desc()).offset(offset).limit(limit).all()

    return [
        TaskResponse(
            id=t.id,
            type=t.type,
            name=t.name,
            status=t.status,
            priority=t.priority,
            progress=t.progress,
            result=t.result,
            error=t.error,
            created_at=t.created_at.isoformat() if t.created_at else None,
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
        )
        for t in tasks
    ]


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    token: str,
    db: Session = Depends(get_db)
):
    """取消任务"""
    from app.tasks.celery_app import celery_app

    # 获取用户
    user = await get_current_user_temp(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="无效的认证信息")

    task = db.query(TaskModel).filter(
        TaskModel.id == task_id,
        TaskModel.user_id == user.id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status not in ['PENDING', 'STARTED']:
        raise HTTPException(status_code=400, detail="任务无法取消")

    # 取消 Celery 任务
    try:
        celery_app.control.revoke(task_id, terminate=True)
    except Exception as e:
        logger.error(f"Failed to revoke Celery task {task_id}: {e}")

    task.status = 'REVOKED'
    task.completed_at = datetime.utcnow()
    db.commit()

    return {'message': '任务已取消', 'task_id': task_id}


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    token: str,
    db: Session = Depends(get_db)
):
    """删除任务记录"""
    # 获取用户
    user = await get_current_user_temp(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="无效的认证信息")

    task = db.query(TaskModel).filter(
        TaskModel.id == task_id,
        TaskModel.user_id == user.id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 只能删除已完成或失败的任务
    if task.status in ['PENDING', 'STARTED']:
        raise HTTPException(status_code=400, detail="无法删除运行中的任务，请先取消")

    db.delete(task)
    db.commit()

    return {'message': '任务已删除'}
