"""
期刊API端点

提供期刊查询、管理等功能的API
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.models.journal import Journal, JournalFramework
from app.schemas.journal import (
    JournalResponse,
    JournalListResponse,
    JournalFrameworkResponse,
    JournalStats
)

router = APIRouter(prefix="/api/journals", tags=["journals"])


@router.get("/", response_model=JournalListResponse)
async def list_journals(
    field: Optional[str] = Query(None, description="一级学科筛选"),
    is_cssci: Optional[bool] = Query(None, description="是否CSSCI来源期刊"),
    is_cssci_expansion: Optional[bool] = Query(None, description="是否CSSCI扩展期刊"),
    is_beida_core: Optional[bool] = Query(None, description="是否北大核心"),
    search: Optional[str] = Query(None, description="搜索关键词（期刊名称）"),
    skip: int = Query(0, ge=0, description="跳过条数"),
    limit: int = Query(50, ge=1, le=100, description="返回条数"),
    db: Session = Depends(get_db)
):
    """
    获取期刊列表

    支持按学科、期刊级别、关键词等条件筛选
    """
    query = db.query(Journal)

    # 应用筛选条件
    if field:
        query = query.filter(Journal.field == field)
    if is_cssci is not None:
        query = query.filter(Journal.is_cssci == is_cssci)
    if is_cssci_expansion is not None:
        query = query.filter(Journal.is_cssci_expansion == is_cssci_expansion)
    if is_beida_core is not None:
        query = query.filter(Journal.is_beida_core == is_beida_core)
    if search:
        query = query.filter(Journal.name.ilike(f"%{search}%"))

    # 获取总数
    total = query.count()

    # 分页
    journals = query.order_by(Journal.name).offset(skip).limit(limit).all()

    return JournalListResponse(
        total=total,
        journals=[JournalResponse.model_validate(j) for j in journals]
    )


@router.get("/stats", response_model=JournalStats)
async def get_journal_stats(
    db: Session = Depends(get_db)
):
    """
    获取期刊统计信息

    返回期刊总数、各级别期刊数量、按学科分类统计等
    """
    # 总期刊数
    total_journals = db.query(Journal).count()

    # 各级别期刊数
    cssci_journals = db.query(Journal).filter(Journal.is_cssci == True).count()
    cssci_expansion_journals = db.query(Journal).filter(
        Journal.is_cssci_expansion == True
    ).count()
    beida_core_journals = db.query(Journal).filter(
        Journal.is_beida_core == True
    ).count()

    # 已分析框架的期刊数
    journals_with_frameworks = db.query(Journal).filter(
        Journal.framework_analyzed == True
    ).count()

    # 按学科统计
    from sqlalchemy import func
    field_stats = db.query(
        Journal.field,
        func.count(Journal.id)
    ).group_by(Journal.field).all()

    by_field = {field or "未分类": count for field, count in field_stats}

    return JournalStats(
        total_journals=total_journals,
        cssci_journals=cssci_journals,
        cssci_expansion_journals=cssci_expansion_journals,
        beida_core_journals=beida_core_journals,
        journals_with_frameworks=journals_with_frameworks,
        by_field=by_field
    )


@router.get("/fields", response_model=List[str])
async def get_journal_fields(
    db: Session = Depends(get_db)
):
    """
    获取所有一级学科列表

    返回系统中所有存在的一级学科
    """
    from sqlalchemy import distinct

    fields = db.query(distinct(Journal.field)).filter(
        Journal.field.isnot(None)
    ).order_by(Journal.field).all()

    return [f[0] for f in fields if f[0]]


@router.get("/{journal_id}", response_model=JournalResponse)
async def get_journal(
    journal_id: int,
    db: Session = Depends(get_db)
):
    """
    获取期刊详情

    根据期刊ID获取期刊的详细信息
    """
    journal = db.query(Journal).filter(Journal.id == journal_id).first()

    if not journal:
        raise HTTPException(status_code=404, detail="期刊不存在")

    return JournalResponse.model_validate(journal)


@router.get("/{journal_id}/frameworks", response_model=List[JournalFrameworkResponse])
async def get_journal_frameworks(
    journal_id: int,
    db: Session = Depends(get_db)
):
    """
    获取期刊常见框架模式

    返回该期刊基于已发表论文分析得出的常见框架模式
    """
    # 验证期刊存在
    journal = db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal:
        raise HTTPException(status_code=404, detail="期刊不存在")

    # 获取框架模式
    frameworks = db.query(JournalFramework).filter(
        JournalFramework.journal_id == journal_id
    ).order_by(JournalFramework.frequency.desc()).all()

    return [JournalFrameworkResponse.model_validate(f) for f in frameworks]


@router.post("/{journal_id}/analyze")
async def trigger_journal_analysis(
    journal_id: int,
    db: Session = Depends(get_db)
):
    """
    触发期刊框架分析（后台任务）

    启动异步任务，分析该期刊的论文框架模式
    """
    # 验证期刊存在
    journal = db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal:
        raise HTTPException(status_code=404, detail="期刊不存在")

    # TODO: 触发Celery异步任务
    # from app.tasks.journal_tasks import analyze_journal_frameworks
    # task = analyze_journal_frameworks.delay(journal_id)

    return {
        "message": "期刊框架分析任务已启动",
        "journal_id": journal_id,
        "journal_name": journal.name,
        # "task_id": task.id
    }


@router.get("/name/{journal_name}", response_model=JournalResponse)
async def get_journal_by_name(
    journal_name: str,
    db: Session = Depends(get_db)
):
    """
    根据期刊名称获取期刊详情

    支持模糊匹配
    """
    journal = db.query(Journal).filter(
        Journal.name.ilike(f"%{journal_name}%")
    ).first()

    if not journal:
        raise HTTPException(status_code=404, detail="期刊不存在")

    return JournalResponse.model_validate(journal)


@router.post("/{journal_id}/update-cnki-details")
async def update_journal_cnki_details(
    journal_id: int,
    db: Session = Depends(get_db)
):
    """
    手动更新单个期刊的 CNKI 详情

    从 CNKI 详情页获取最新数据并更新到数据库
    """
    from app.services.cnki_detail_parser import CNKIDetailParser

    journal = db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal:
        raise HTTPException(status_code=404, detail="期刊不存在")

    parser = CNKIDetailParser(db)
    success = parser.update_journal(journal_id)

    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"更新失败，请检查期刊是否有 detail_url 或网络连接"
        )

    # 刷新并返回更新后的期刊
    db.refresh(journal)
    return JournalResponse.model_validate(journal)


@router.post("/update-cnki-batch")
async def batch_update_cnki_details(
    limit: Optional[int] = Query(None, description="更新数量限制"),
    force: bool = Query(False, description="是否强制更新"),
    skip_days: int = Query(7, description="增量更新模式下跳过天数", ge=1),
    db: Session = Depends(get_db)
):
    """
    批量更新期刊 CNKI 详情（同步，会阻塞）

    - limit: 限制更新数量，默认全部
    - force: 强制更新所有期刊（忽略更新时间）
    - skip_days: 增量更新模式下，跳过 N 天内已更新的期刊

    注意：此接口为同步执行，大量数据更新可能超时。建议使用 /update-cnki-batch-async
    """
    from app.services.cnki_detail_parser import CNKIDetailParser

    parser = CNKIDetailParser(db)
    result = parser.batch_update(limit=limit, force=force, skip_days=skip_days)

    return {
        "message": "批量更新完成",
        "stats": result
    }


@router.post("/update-cnki-batch-async")
async def batch_update_cnki_details_async(
    limit: Optional[int] = Query(None, description="更新数量限制"),
    force: bool = Query(False, description="是否强制更新"),
    db: Session = Depends(get_db)
):
    """
    批量更新期刊 CNKI 详情（异步后台任务）

    创建 Celery 后台任务，支持断点续传，终端断开不影响执行

    - limit: 限制更新数量，默认全部更新
    - force: 强制更新所有期刊，否则只更新缺少 field 的期刊

    返回任务 ID，可通过 WebSocket 监听进度
    """
    import uuid
    from app.tasks.journal_tasks import batch_update_journal_details_task
    from app.models.task import Task as TaskModel

    # 创建任务记录
    task_id = str(uuid.uuid4())
    user_id = 1  # TODO: 从认证获取

    limit_str = str(limit) if limit else "全部"
    force_str = "强制" if force else "增量"
    task_name = f"批量更新期刊详情 (数量={limit_str}, 模式={force_str})"

    task = TaskModel(
        id=task_id,
        user_id=user_id,
        type='batch_fetch_columns',
        name=task_name,
        params={'limit': limit, 'force': force},
        status='PENDING'
    )
    db.add(task)
    db.commit()

    # 提交到 Celery
    batch_update_journal_details_task.apply_async(
        args=[limit, force, user_id],
        task_id=task_id,
        queue='default'
    )

    return {
        'task_id': task_id,
        'message': '批量更新任务已创建（后台执行）',
        'note': '可通过 WebSocket 监听任务进度，终端断开不影响执行'
    }


@router.delete("/{journal_id}")
async def delete_journal(
    journal_id: int,
    db: Session = Depends(get_db)
):
    """
    删除期刊

    根据期刊ID删除期刊及相关数据
    """
    journal = db.query(Journal).filter(Journal.id == journal_id).first()

    if not journal:
        raise HTTPException(status_code=404, detail="期刊不存在")

    # 先删除关联的框架数据
    db.query(JournalFramework).filter(
        JournalFramework.journal_id == journal_id
    ).delete()

    # 删除期刊
    db.delete(journal)
    db.commit()

    return {
        "message": "期刊删除成功",
        "journal_id": journal_id,
        "journal_name": journal.name
    }


# ==================== 栏目管理相关端点 ====================

@router.post("/{journal_id}/columns/refresh")
async def refresh_journal_columns(
    journal_id: int,
    db: Session = Depends(get_db)
):
    """
    创建刷新期刊栏目的任务

    创建异步任务来刷新指定期期刊的栏目数据
    """
    journal = db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal:
        raise HTTPException(status_code=404, detail="期刊不存在")

    if not journal.detail_url:
        raise HTTPException(status_code=400, detail="该期刊没有 detail_url")

    # 创建任务
    from app.tasks.journal_tasks import fetch_journal_columns_task
    import uuid

    task_id = str(uuid.uuid4())

    # 暂时使用固定用户ID（TODO: 实现真正的认证后从请求头获取）
    user_id = 1

    from app.models.task import Task as TaskModel
    task = TaskModel(
        id=task_id,
        user_id=user_id,
        type='fetch_columns',
        name=f"刷新 {journal.name} 的栏目",
        params={'journal_id': journal_id},
        status='PENDING'
    )
    db.add(task)
    db.commit()

    # 提交到 Celery
    fetch_journal_columns_task.apply_async(
        args=[journal_id, user_id, task.name],
        task_id=task_id,
        queue='high'
    )

    return {
        'task_id': task_id,
        'message': '刷新任务已创建',
        'journal_name': journal.name
    }


@router.get("/columns/all")
async def get_all_columns(
    search: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    获取所有栏目列表（支持搜索）

    返回所有期刊的栏目汇总信息
    """
    query = db.query(Journal).filter(Journal.journal_columns_detail.isnot(None))

    columns_map = {}

    # 限制处理的期刊数量，避免查询过慢
    for journal in query.limit(1000):
        if journal.journal_columns_detail:
            for col in journal.journal_columns_detail:
                title = col.get('title', '')
                if not title:
                    continue

                if search and search.lower() not in title.lower():
                    continue

                if title not in columns_map:
                    columns_map[title] = []

                columns_map[title].append({
                    'journal_id': journal.id,
                    'journal_name': journal.name,
                    'param': col.get('param'),
                    'value': col.get('value')
                })

    # 转换为数组并排序
    result = [
        {
            'title': title,
            'journal_count': len(journals),
            'journals': journals[:10]  # 只返回前10个期刊
        }
        for title, journals in columns_map.items()
    ]
    result.sort(key=lambda x: x['journal_count'], reverse=True)

    return {'total': len(result), 'columns': result[:limit]}


class ColumnUpdateRequest(BaseModel):
    """栏目更新请求"""
    columns: Optional[List[str]] = None
    columns_detail: Optional[List[dict]] = None


@router.put("/{journal_id}/columns")
async def update_journal_columns(
    journal_id: int,
    data: ColumnUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    更新期刊栏目数据

    手动编辑期刊的栏目信息
    """
    journal = db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal:
        raise HTTPException(status_code=404, detail="期刊不存在")

    if data.columns is not None:
        journal.journal_columns = data.columns
    if data.columns_detail is not None:
        journal.journal_columns_detail = data.columns_detail

    journal.updated_at = datetime.utcnow()
    db.commit()

    return {'message': '栏目已更新'}
