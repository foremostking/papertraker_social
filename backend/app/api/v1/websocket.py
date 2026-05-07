"""
WebSocket API 端点

提供实时进度推送功能。
"""

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import db as database
from app.models.task import Task as TaskModel
from app.models.user import User
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


async def get_user_from_token(token: str, db: Session) -> Optional[User]:
    """
    从 JWT token 获取用户

    这是一个简化的版本，生产环境应该使用 FastAPI 的依赖注入系统

    Args:
        token: JWT token
        db: 数据库会话

    Returns:
        用户对象或 None
    """
    try:
        # 这里应该验证 JWT token
        # 暂时简化处理：假设 token 格式为 "user_id:{user_id}"
        if token.startswith("user_id:"):
            user_id = int(token.split(":")[1])
            user = db.query(User).filter(User.id == user_id).first()
            return user

        # TODO: 实现真正的 JWT 验证
        # from jose import jwt
        # from app.core.config import settings
        # payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        # user_id = payload.get("sub")
        # user = db.query(User).filter(User.id == user_id).first()

        logger.warning(f"Invalid token format: {token[:20]}...")
        return None

    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        return None


@router.websocket("/tasks/{task_id}")
async def task_progress_websocket(
    websocket: WebSocket,
    task_id: str,
    token: str = Query(...)
):
    """
    任务进度实时推送 WebSocket 端点

    连接格式: ws://localhost:8000/ws/tasks/{task_id}?token={jwt_token}

    Args:
        websocket: WebSocket 连接
        task_id: 任务ID
        token: JWT token (通过查询参数传递)
    """
    await websocket.accept()

    db = database.SessionLocal()
    last_progress = None

    try:
        # 验证用户和任务
        user = await get_user_from_token(token, db)
        if not user:
            await websocket.send_json({'error': 'Invalid token'})
            await websocket.close(code=1008, reason="Invalid token")
            return

        task = db.query(TaskModel).filter(
            TaskModel.id == task_id,
            TaskModel.user_id == user.id
        ).first()

        if not task:
            await websocket.send_json({'error': 'Task not found'})
            await websocket.close(code=1008, reason="Task not found")
            return

        # 发送初始状态
        await websocket.send_json({
            'task_id': task.id,
            'type': task.type,
            'status': task.status,
            'progress': task.progress,
            'result': task.result,
            'error': task.error,
            'created_at': task.created_at.isoformat() if task.created_at else None,
        })

        # 轮询任务状态
        poll_count = 0
        max_polls = 600  # 最多轮询 10 分钟 (600 * 1秒)

        while task.status in ['PENDING', 'STARTED'] and poll_count < max_polls:
            await asyncio.sleep(1)  # 每秒检查一次

            db.refresh(task)

            # 只在进度变化时发送
            if task.progress != last_progress:
                try:
                    await websocket.send_json({
                        'task_id': task.id,
                        'status': task.status,
                        'progress': task.progress,
                        'result': task.result,
                    })
                    last_progress = task.progress
                except Exception as e:
                    logger.warning(f"Failed to send WebSocket message: {e}")
                    break

            if task.status not in ['PENDING', 'STARTED']:
                break

            poll_count += 1

        # 发送最终状态
        try:
            await websocket.send_json({
                'task_id': task.id,
                'status': task.status,
                'progress': task.progress,
                'result': task.result,
                'error': task.error,
                'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            })
        except Exception as e:
            logger.warning(f"Failed to send final WebSocket message: {e}")

        logger.info(f"WebSocket for task {task_id} completed")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for task {task_id}")
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}", exc_info=True)
        try:
            await websocket.send_json({'error': str(e)})
        except:
            pass
    finally:
        db.close()
        try:
            await websocket.close()
        except:
            pass
