"""
期刊详情更新任务
使用 Celery 异步处理
"""
from celery import shared_task
from datetime import datetime, timedelta
from app.tasks.base import DatabaseTask
from app.services.cnki_detail_parser import CNKIDetailParser
from app.models.journal import Journal
import logging

logger = logging.getLogger(__name__)


@shared_task(base=DatabaseTask, bind=True, max_retries=3)
def update_single_journal(self, journal_id: int):
    """
    更新单个期刊的 CNKI 详情

    Args:
        journal_id: 期刊 ID

    Returns:
        dict: 更新结果
    """
    db = self.db

    journal = db.query(Journal).filter(Journal.id == journal_id).first()
    if not journal:
        return {'status': 'error', 'message': f'期刊 {journal_id} 不存在'}

    if not journal.detail_url:
        return {'status': 'skipped', 'message': f'期刊 {journal.name} 没有 detail_url'}

    parser = CNKIDetailParser(db, min_delay=2.0, max_delay=4.0)

    try:
        info = parser.parse_detail_page(journal.detail_url)
        if 'error' in info:
            # 即使失败也更新时间戳
            journal.cnki_detail_last_updated = datetime.now()
            db.commit()
            return {'status': 'failed', 'message': info['error']}

        # 更新期刊信息
        for key, value in info.items():
            if key != 'error' and hasattr(journal, key):
                setattr(journal, key, value)

        db.commit()
        logger.info(f"成功更新期刊: {journal.name}")
        return {
            'status': 'success',
            'journal_id': journal_id,
            'journal_name': journal.name,
            'field': info.get('field'),
            'subfield': info.get('subfield')
        }
    except Exception as e:
        db.rollback()
        logger.error(f"更新期刊 {journal.name} 失败: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(base=DatabaseTask, bind=True)
def batch_update_journals_dispatcher(self, limit: int = None):
    """
    批量更新期刊 - 分发任务

    将待更新的期刊ID分发给 Celery Worker 处理
    """
    db = self.db

    # 获取待更新的期刊
    safe_window = datetime.now() - timedelta(minutes=10)
    query = db.query(Journal).filter(
        Journal.detail_url.isnot(None),
        Journal.field.is_(None),
        (Journal.cnki_detail_last_updated.is_(None)) |
        (Journal.cnki_detail_last_updated < safe_window)
    )

    if limit:
        query = query.limit(limit)

    journals = query.all()
    count = len(journals)

    logger.info(f"准备分发 {count} 个期刊更新任务")

    # 分发任务
    for journal in journals:
        update_single_journal.delay(journal.id)

    return {'status': 'dispatched', 'total': count}
