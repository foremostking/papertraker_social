import re

with open('data/test_page1.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 提取前3个完整的期刊条目
items = re.findall(r'<li>.*?</li>', html, re.DOTALL)
print(f"Total items found: {len(items)}")

for i, item in enumerate(items[:3]):
    print(f"\n=== Item {i+1} ===")
    # 名称
    name = re.search(r'<h1>\s*([^<]+)</h1>', item)
    if name:
        print('Name:', name.group(1).strip())
    # 标签
    tags = re.findall(r'<span>([^<]+)</span>', item)
    print('Tags:', tags)
    # 影响因子
    cf = re.search(r'复合影响因子[：:]([\d.]+)', item)
    if cf:
        print('Composite IF:', cf.group(1))
    ci = re.search(r'综合影响因子[：:]([\d.]+)', item)
    if ci:
        print('Comprehensive IF:', ci.group(1))
    # ISSN
    issn = re.search(r'ISSN[：:]([\dA-Z\-]+)', item)
    if issn:
        print('ISSN:', issn.group(1).strip())
    # CN
    cn = re.search(r'CN[：:]([\dA-Z\-/]+)', item)
    if cn:
        print('CN:', cn.group(1).strip())
    # 主办单位
    pub = re.search(r'主办单位[：:]([^<]+)', item)
    if pub:
        print('Publisher:', pub.group(1).strip())
    # detail URL
    url = re.search(r'href="(https://navi\.cnki\.net/knavi/detail\?p=[^"]+)"', item)
    if url:
        print('Detail URL:', url.group(1))
