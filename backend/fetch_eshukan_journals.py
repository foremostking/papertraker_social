import requests
from bs4 import BeautifulSoup
import json
import time
import re

BASE_URL = "https://eshukan.com/SuperSearchList.aspx"
PARAMS = {
    "keyword": "",
    "classify": "0",
    "wenZhong": "-1",
    "kanQi": "0",
    "area": "0",
    "level": "1",
    "heXin": "201",  # CSSCI来源期刊 2025-2026
    "puKan": "0",
    "first": "0",
    "countrySupport": "0",
    "college": "0",
    "yxyz": "0",
    "hornor": "0",
    "contentIncluded": "0",
    "doubleAnonymous": "0",
    "comment": "0",
    "gaoFei": "0",
    "banMianFei": "0",
    "banMianFeiArea": "0",
    "shenGaoTime": "-1",
    "hot": "-1",
    "method": "0",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def parse_journal(card):
    """解析单本期刊信息"""
    journal = {}
    
    # 名称
    title_link = card.find("a", class_="title")
    if title_link:
        journal["name"] = title_link.get_text(strip=True)
    else:
        title_div = card.find("div", class_="title")
        if title_div:
            journal["name"] = title_div.get_text(strip=True)
    
    if not journal.get("name"):
        return None
    
    # 核心类型标签
    tags_div = card.find("div", class_="tags")
    if tags_div:
        tags = [t.strip() for t in tags_div.get_text().split(",") if t.strip()]
        journal["journal_tags"] = tags
        journal["is_cssci"] = any("CSSCI来源" in t for t in tags)
        journal["is_cssci_expansion"] = any("CSSCI扩展" in t for t in tags)
        journal["is_beida_core"] = any("中文核心" in t for t in tags)
    else:
        journal["is_cssci"] = True
    
    # 复合影响因子
    info_div = card.find("div", class_="info")
    if info_div:
        text = info_div.get_text()
        match = re.search(r"复合影响因子：([\d.]+)", text)
        if match:
            journal["composite_impact_factor"] = float(match.group(1))
    
    # 简介/主办单位
    intro_div = card.find("div", class_="intro")
    if intro_div:
        journal["publisher"] = intro_div.get_text(strip=True)[:200]
    
    return journal


def fetch_page(page_num):
    """获取单页数据"""
    params = PARAMS.copy()
    params["page"] = str(page_num)
    
    try:
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        
        cards = soup.find_all("div", class_="list-item")
        if not cards:
            cards = soup.select(".list-item, .search-item, .journal-item")
        
        journals = []
        for card in cards:
            j = parse_journal(card)
            if j:
                journals.append(j)
        
        return journals
    except Exception as e:
        print(f"Page {page_num} error: {e}")
        return []


# 测试获取第一页
print("Fetching page 1...")
journals = fetch_page(1)
print(f"Got {len(journals)} journals")
for j in journals[:5]:
    print(" -", j.get("name"), j.get("journal_tags"))

# 保存测试数据
with open("data/test_eshukan.json", "w", encoding="utf-8") as f:
    json.dump(journals, f, ensure_ascii=False, indent=2)
