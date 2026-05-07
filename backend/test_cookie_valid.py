import requests
import json
import re

cookies = {
    'Ecp_ClientId': '_vqrnqik__caByTET4758758s8HvEM9n0VHXDg7Gd7',
    'SID_navi': '018110',
    'cnkiUserKey': 'e152802a-81bb-45ea-1563-56419bc6c85d',
    'Ecp_IpLoginFail': '26050739.144.210.22'
}

url = 'https://navi.cnki.net/knavi/journals/searchbaseinfo'
data = {
    'searchStateJson': json.dumps({'StateID':'','Platfrom':'','QueryTime':'','Account':'knavi','ClientToken':'','Language':'','CNode':{'PCode':'OYXNO5VW','SMode':'','OperateT':''},'QNode':{'SelectT':'','Select_Fields':'','S_DBCodes':'','Subscribed':'','QGroup':[],'OrderBy':'OTA|DESC','GroupBy':'','Additon':''}}, separators=(',', ':')),
    'displaymode': '1', 'pageindex': '1', 'pagecount': '21',
    'index': 'JSTMWT6S', 'searchType': '刊名(曾用刊名)',
    'parentcode': 'SQN63324', 'switchdata': 'clickTabSearch'
}
headers = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

resp = requests.post(url, data=data, headers=headers, cookies=cookies, timeout=20)
print('Status:', resp.status_code)
print('Len:', len(resp.text))

# Try multiple patterns
items = re.findall(r'<h1>\s*([^<]+)</h1>', resp.text)
print('Pattern 1 (h1):', len(items))
if items:
    for i in items[:5]:
        print(' -', i.strip())

items2 = re.findall(r'title="([^"]+)"[^>]*>\s*<span class="mask"></span>\s*<div class="img-thumb">', resp.text)
print('Pattern 2 (title):', len(items2))

# Check total pages
m = re.search(r'pageCount[\s\:\=]+(\d+)', resp.text)
if m:
    print('Total pages:', m.group(1))

# Save for inspection
with open('data/test_page1.html', 'w', encoding='utf-8') as f:
    f.write(resp.text)
print('Saved to data/test_page1.html')
