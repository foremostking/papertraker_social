"""
期刊相关的 Celery 任务

包含期刊栏目刷新、批量更新等任务。
"""

import asyncio
from app.tasks.celery_app import celery_app
from app.tasks.base import DatabaseTask, update_task_status
from app.models.journal import Journal
from app.services.cnki_detail_parser import CNKIDetailParser
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@celery_app.task(
    base=DatabaseTask,
    bind=True,
    max_retries=3,
    autoretry_for=(ConnectionError, asyncio.TimeoutError),
    retry_backoff=True
)
def fetch_journal_columns_task(
    self,
    journal_id: int,
    user_id: int,
    task_name: str = None
):
    """
    获取期刊栏目数据

    Args:
        journal_id: 期刊ID
        user_id: 用户ID
        task_name: 任务名称（可选）
    """
    task_id = self.request.id

    # 更新任务状态
    update_task_status(
        task_id,
        status='STARTED',
        progress={'current': 0, 'total': 1, 'message': '正在获取期刊栏目...'}
    )

    try:
        # 获取期刊信息
        journal = self.db.query(Journal).filter(Journal.id == journal_id).first()
        if not journal:
            raise ValueError(f"期刊 {journal_id} 不存在")

        update_task_status(
            task_id,
            progress={'current': 0, 'total': 1, 'message': f'正在获取 {journal.name} 的栏目...'}
        )

        # 执行爬取
        parser = CNKIDetailParser()
        result = asyncio.run(parser.fetch_journal_columns(journal.detail_url))

        # 更新期刊数据
        if result.get('journal_code'):
            journal.journal_code = result['journal_code']
        if result.get('columns'):
            journal.journal_columns = result['columns']
        if result.get('columns_detail'):
            journal.journal_columns_detail = result['columns_detail']

        journal.cnki_detail_last_updated = datetime.utcnow()
        self.db.commit()

        # 更新任务状态
        update_task_status(
            task_id,
            status='SUCCESS',
            progress={'current': 1, 'total': 1, 'message': '完成'},
            result={
                'journal_id': journal_id,
                'journal_name': journal.name,
                'journal_code': result.get('journal_code'),
                'columns_count': len(result.get('columns', []))
            }
        )

        return result

    except Exception as e:
        logger.error(f"获取期刊栏目失败: {e}", exc_info=True)
        update_task_status(
            task_id,
            status='FAILURE',
            error=str(e),
            progress={'current': 0, 'total': 1, 'message': f'失败: {str(e)}'}
        )
        raise


@celery_app.task(
    base=DatabaseTask,
    bind=True,
    max_retries=2
)
def batch_fetch_columns_task(
    self,
    limit: int = 100,
    user_id: int = None
):
    """
    批量获取期刊栏目数据

    Args:
        limit: 每批处理数量
        user_id: 用户ID
    """
    task_id = self.request.id

    # 获取需要更新的期刊
    journals = self.db.query(Journal).filter(
        Journal.detail_url.isnot(None),
        Journal.journal_columns_detail.is_(None)
    ).limit(limit).all()

    total = len(journals)

    update_task_status(
        task_id,
        progress={'current': 0, 'total': total, 'message': f'开始批量更新 {total} 个期刊...'}
    )

    results = {'success': 0, 'failed': 0, 'errors': []}

    for idx, journal in enumerate(journals):
        try:
            parser = CNKIDetailParser()
            result = asyncio.run(parser.fetch_journal_columns(journal.detail_url))

            if result.get('journal_code'):
                journal.journal_code = result['journal_code']
            if result.get('columns'):
                journal.journal_columns = result['columns']
            if result.get('columns_detail'):
                journal.journal_columns_detail = result['columns_detail']

            journal.cnki_detail_last_updated = datetime.utcnow()
            self.db.commit()

            results['success'] += 1

            # 每处理10个更新一次进度
            if (idx + 1) % 10 == 0:
                update_task_status(
                    task_id,
                    progress={
                        'current': idx + 1,
                        'total': total,
                        'message': f'已处理 {idx + 1}/{total}',
                        'last_journal': journal.name
                    }
                )

            # 延迟避免封禁
            asyncio.run(asyncio.sleep(2))

        except Exception as e:
            results['failed'] += 1
            results['errors'].append({'journal': journal.name, 'error': str(e)})
            logger.error(f"处理期刊 {journal.name} 失败: {e}")

    update_task_status(
        task_id,
        status='SUCCESS',
        progress={'current': total, 'total': total, 'message': '全部完成'},
        result=results
    )

    return results


@celery_app.task(
    base=DatabaseTask,
    bind=True,
    max_retries=2
)
def batch_update_journal_details_task(
    self,
    limit: int = None,
    force: bool = False,
    user_id: int = None
):
    """
    批量更新期刊详情数据（field、subfield 等基本信息，不含栏目）

    支持断点续传：自动跳过已有 field 数据的期刊

    Args:
        limit: 限制更新数量（None=全部更新）
        force: 是否强制更新所有期刊
        user_id: 用户ID
    """
    task_id = self.request.id
    from datetime import timedelta

    # 构建查询：只处理有 detail_url 的期刊
    query = self.db.query(Journal).filter(Journal.detail_url.isnot(None))

    # 非强制模式：跳过已有 field 的期刊，且跳过 10 分钟内更新的（安全窗口）
    if not force:
        safe_window = datetime.now() - timedelta(minutes=10)
        query = query.filter(
            (Journal.field.is_(None)) &
            ((Journal.cnki_detail_last_updated.is_(None)) |
             (Journal.cnki_detail_last_updated < safe_window))
        )

    if limit:
        query = query.limit(limit)

    journals = query.all()
    total = len(journals)

    if total == 0:
        update_task_status(
            task_id,
            status='SUCCESS',
            progress={'current': 0, 'total': 0, 'message': '没有需要更新的期刊'}
        )
        return {'total': 0, 'success': 0, 'failed': 0}

    update_task_status(
        task_id,
        status='STARTED',
        progress={'current': 0, 'total': total, 'message': f'开始批量更新 {total} 个期刊详情...'}
    )

    logger.info(f"开始批量更新期刊详情，共 {total} 个期刊")

    # 使用 CNKIDetailParser 更新
    parser = CNKIDetailParser(self.db, min_delay=1.0, max_delay=2.0)
    results = {'total': total, 'success': 0, 'failed': 0, 'skipped': 0}

    for idx, journal in enumerate(journals):
        try:
            # 检查是否已被其他进程更新（断点续传）
            if not force and journal.field:
                results['skipped'] += 1
                continue

            # 更新单个期刊
            success = parser.update_journal(journal.id, delay=True)

            if success:
                results['success'] += 1
            else:
                results['failed'] += 1

            # 每处理 10 个更新一次进度
            if (idx + 1) % 10 == 0 or (idx + 1) == total:
                update_task_status(
                    task_id,
                    progress={
                        'current': idx + 1,
                        'total': total,
                        'message': f'已处理 {idx + 1}/{total}，成功 {results["success"]}，失败 {results["failed"]}',
                        'success': results['success'],
                        'failed': results['failed']
                    }
                )
            logger.info(f"[{idx + 1}/{total}] 更新: {journal.name}")

        except Exception as e:
            results['failed'] += 1
            logger.error(f"处理期刊 {journal.name} 失败: {e}", exc_info=True)

    # 最终状态更新
    update_task_status(
        task_id,
        status='SUCCESS',
        progress={
            'current': total,
            'total': total,
            'message': f'完成！成功 {results["success"]}，失败 {results["failed"]}，跳过 {results["skipped"]}',
            'success': results['success'],
            'failed': results['failed'],
            'skipped': results['skipped']
        },
        result=results
    )

    logger.info(f"批量更新完成: {results}")
    return results
