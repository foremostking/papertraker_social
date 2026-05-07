"""
抓取CSSCI扩展版期刊名单

从南京大学中国社会科学研究评价中心官网获取CSSCI扩展版期刊列表
然后与数据库中的期刊表进行匹配
"""

import sys
import re
import time
import random
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import requests
from bs4 import BeautifulSoup
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from app.core.config import settings
from app.core.database import Database
from app.models.journal import Journal
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 复用反爬虫策略
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
]


def fetch_cssci_expansion_journals(url: str) -> list:
    """
    从指定URL获取CSSCI扩展版期刊列表
    """
    logger.info(f"正在获取CSSCI扩展版期刊列表...")
    logger.info(f"URL: {url}")

    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    try:
        # 随机延迟
        time.sleep(random.uniform(1, 3))

        # 禁用SSL验证（某些老旧证书无法验证）
        response = requests.get(
            url,
            headers=headers,
            timeout=30,
            verify=False  # 忽略SSL证书验证
        )
        response.raise_for_status()
        response.encoding = 'utf-8'

        logger.info(f"页面获取成功，长度: {len(response.text)} 字符")

        # 解析HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # 保存原始HTML用于调试
        html_file = project_root / 'scripts' / 'cssci_expansion_source.html'
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(response.text)
        logger.info(f"原始HTML已保存到: {html_file}")

        # 尝试不同的解析方式
        journals = []

        # 方法1: 查找所有可能的期刊名称容器
        # CSSCI官网通常使用表格或列表展示期刊

        # 尝试查找表格
        tables = soup.find_all('table')
        logger.info(f"找到 {len(tables)} 个表格")

        for i, table in enumerate(tables):
            rows = table.find_all('tr')
            logger.info(f"  表格{i}: {len(rows)} 行")

            for row in rows:
                cells = row.find_all(['td', 'th'])
                for cell in cells:
                    text = cell.get_text(strip=True)
                    # 期刊名称通常是中文，长度4-20字
                    if text and re.match(r'^[\u4e00-\u9fa5]{2,20}$', text):
                        journals.append(text)

        # 方法2: 查找所有段落和列表项
        if not journals:
            logger.info("尝试从段落和列表中提取...")
            for p in soup.find_all(['p', 'li', 'span']):
                text = p.get_text(strip=True)
                if text and re.match(r'^[\u4e00-\u9fa5]{2,20}$', text):
                    journals.append(text)

        # 去重
        journals = list(set(journals))
        logger.info(f"提取到 {len(journals)} 个可能的期刊名称")

        # 保存提取结果
        result_file = project_root / 'scripts' / 'cssci_expansion_journals.txt'
        with open(result_file, 'w', encoding='utf-8') as f:
            for journal in sorted(journals):
                f.write(f"{journal}\n")
        logger.info(f"期刊列表已保存到: {result_file}")

        return journals

    except requests.RequestException as e:
        logger.error(f"网络请求失败: {e}")
        return []
    except Exception as e:
        logger.error(f"解析失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def match_with_database(cssci_expansion_list: list):
    """
    将CSSCI扩展版列表与数据库中的期刊进行匹配
    """
    logger.info("\n" + "=" * 60)
    logger.info("数据库匹配")
    logger.info("=" * 60)

    db_instance = Database(settings.DATABASE_URL)
    db = db_instance.SessionLocal()

    try:
        # 获取所有期刊
        all_journals = db.query(Journal).all()
        logger.info(f"数据库中共有 {len(all_journals)} 本期刊")

        matched = []
        partial_matched = []

        for cssci_name in cssci_expansion_list:
            # 精确匹配
            exact = db.query(Journal).filter(Journal.name == cssci_name).first()
            if exact:
                matched.append(exact)
                continue

            # 模糊匹配（包含关系）
            fuzzy = db.query(Journal).filter(
                Journal.name.contains(cssci_name)
            ).first()
            if fuzzy:
                partial_matched.append((cssci_name, fuzzy))
                continue

        logger.info(f"\n精确匹配: {len(matched)} 本")
        logger.info(f"模糊匹配: {len(partial_matched)} 本")
        logger.info(f"总匹配: {len(matched) + len(partial_matched)} 本")

        # 显示匹配结果
        if matched:
            logger.info(f"\n精确匹配的期刊 (前10本):")
            for j in matched[:10]:
                logger.info(f"  - {j.name}")

        if partial_matched:
            logger.info(f"\n模糊匹配的期刊 (前10本):")
            for cssci_name, journal in partial_matched[:10]:
                logger.info(f"  - {cssci_name} → {journal.name}")

        # 更新数据库
        logger.info(f"\n开始更新数据库...")

        updated_count = 0

        # 更新精确匹配的期刊
        for journal in matched:
            if not journal.is_cssci_expansion:
                journal.is_cssci_expansion = True
                # 如果之前标记为CSSCI来源版，需要调整
                # CSSCI扩展版期刊不应该同时标记为来源版
                if journal.is_cssci:
                    logger.info(f"  [{journal.name}] 从来源版改为扩展版")
                    journal.is_cssci = False
                updated_count += 1

        # 更新模糊匹配的期刊（需要人工确认）
        for cssci_name, journal in partial_matched:
            if not journal.is_cssci_expansion:
                logger.info(f"  [{journal.name}] 模糊匹配自 '{cssci_name}'，标记为扩展版")
                journal.is_cssci_expansion = True
                if journal.is_cssci:
                    journal.is_cssci = False
                updated_count += 1

        db.commit()

        logger.info(f"\n更新完成: {updated_count} 本期刊")

        # 统计最终结果
        final_cssci = db.query(Journal).filter(Journal.is_cssci == True).count()
        final_cssci_exp = db.query(Journal).filter(Journal.is_cssci_expansion == True).count()

        logger.info(f"\n最终统计:")
        logger.info(f"  CSSCI来源版: {final_cssci} 本")
        logger.info(f"  CSSCI扩展版: {final_cssci_exp} 本")
        logger.info(f"  总计: {final_cssci + final_cssci_exp} 本")

    except Exception as e:
        logger.error(f"数据库操作失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()

    finally:
        db.close()


if __name__ == '__main__':
    # CSSCI扩展版官方来源URL
    url = "https://cssrac.nju.edu.cn/cpzx/zwshkxywsykzb/20210425/i198395.html"

    # 获取CSSCI扩展版列表
    cssci_expansion_journals = fetch_cssci_expansion_journals(url)

    if cssci_expansion_journals:
        # 与数据库匹配
        match_with_database(cssci_expansion_journals)
    else:
        logger.error("未能获取CSSCI扩展版期刊列表")
