import re

with open('data/test_page1.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Original pattern from script
pattern = r'<a[^>]*href="https://navi\.cnki\.net/knavi/detail\?p=([^"]+)"[^>]*title="([^"]+)"[^>]*>.*?<div class="detials">\s*<h1>\s*([^<]+)</h1>(.*?)</div>\s*</a>'
items = re.findall(pattern, html, re.DOTALL)
print('Original pattern:', len(items))

# Simpler pattern
pattern2 = r'href="https://navi\.cnki\.net/knavi/detail\?p=([^"]+)"[^>]*title="([^"]+)"[^>]*>.*?<h1>\s*([^<]+)</h1>'
items2 = re.findall(pattern2, html, re.DOTALL)
print('Simpler pattern:', len(items2))

# Even simpler - just get name and url
pattern3 = r'href="https://navi\.cnki\.net/knavi/detail\?p=([^"]+)"[^>]*title="([^"]+)"'
items3 = re.findall(pattern3, html)
print('Simplest pattern:', len(items3))
if items3:
    for i in items3[:3]:
        print(' -', i[1])
