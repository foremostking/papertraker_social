"""
获取CNKI页面内容调试
"""
import requests
from bs4 import BeautifulSoup
import re

url = "https://navi.cnki.net/knavi/detail?p=mK1ZVKSnEbTx_IcbkGmFOvRRTBBKOKLXNaCGNosnDzKpzpKzwpjxmR_IIRjvzvKhyfja4joS4npLA_fiU7_tsfjZIVEjAqbOS4K2sXZAoFHx_KBIPG_Tyg==&uniplatform=NZKPT&language=CHS"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

response = requests.get(url, headers=headers, timeout=30)
response.encoding = 'utf-8'

# 查找期刊信息
soup = BeautifulSoup(response.text, 'html.parser')

print("=== 查找 jiName (专辑名称/一级学科) ===")
ji_name = soup.find('span', id='jiName')
if ji_name:
    print(f"找到: {ji_name.get_text(strip=True)}")
else:
    print("未找到 jiName 元素")

print("\n=== 查找 tiName (专题名称/二级学科) ===")
ti_name = soup.find('span', id='tiName')
if ti_name:
    print(f"找到: {ti_name.get_text(strip=True)}")
else:
    print("未找到 tiName 元素")

print("\n=== 期刊信息区域 ===")
dd = soup.find('dl', class_='journalInfo')
if dd:
    text = dd.get_text(separator='|', strip=True)
    print(text[:500])
    # 查找专辑/专题
    if '专辑' in text:
        print("\n包含'专辑'关键词")
    if '专题' in text:
        print("包含'专题'关键词")
else:
    print("未找到 journalInfo 元素")

# 检查页面中是否有专辑和专题的文字
page_text = soup.get_text()
print("\n=== 检查页面中是否包含专辑/专题 ===")
album_matches = re.findall(r'专辑名[称][:：]\s*([^；;\n]{2,20})', page_text)
if album_matches:
    print(f"找到专辑名称: {album_matches}")
else:
    print("未找到专辑名称")

subject_matches = re.findall(r'专题名[称][:：]\s*([^；;\n]{2,20})', page_text)
if subject_matches:
    print(f"找到专题名称: {subject_matches}")
else:
    print("未找到专题名称")
