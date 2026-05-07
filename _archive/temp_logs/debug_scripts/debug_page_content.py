"""
检查页面实际内容
"""
import requests
from bs4 import BeautifulSoup

url = "https://navi.cnki.net/knavi/detail?p=mK1ZVKSnEbTJirnKZrFtnthzhs7g5V3OefYbWFdceOtOZO7p5To5UwKtE7o3jXk3Yxj_eJ9_JsZdxcg_y7RYQNnhV&uniplatform=NZKPT&language=CHS"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

response = requests.get(url, headers=headers, timeout=30)
soup = BeautifulSoup(response.text, 'html.parser')

print("=== 查找 journalInfo 容器 ===")
dd = soup.find('dl', class_='journalInfo')
if dd:
    text = dd.get_text(separator='|', strip=True)
    print(f"找到容器，内容长度: {len(text)}")
    print(f"内容预览: {text[:300]}")
else:
    print("未找到 journalInfo")

print("\n=== 查找所有 dl 标签 ===")
all_dl = soup.find_all('dl', limit=3)
for i, dl in enumerate(all_dl):
    print(f"\ndl[{i}] class={dl.get('class')}")
    text = dl.get_text(strip=True)[:200]
    print(f"  内容: {text}")

print("\n=== 检查是否有专辑/专题信息 ===")
page_text = soup.get_text()
if '专辑' in page_text:
    print("包含'专辑'")
if '专题' in page_text:
    print("包含'专题'")

# 检查 span#jiName 和 span#tiName
ji_name = soup.find('span', id='jiName')
ti_name = soup.find('span', id='tiName')
print(f"\njiName: {ji_name.get_text(strip=True) if ji_name else '未找到'}")
print(f"tiName: {ti_name.get_text(strip=True) if ti_name else '未找到'}")
