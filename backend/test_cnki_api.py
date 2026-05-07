import requests

url = 'https://navi.cnki.net/knavi/journals/searchbaseinfo'
params = {
    'searchStateJson': '{"StateID":"","Platfrom":"","QueryTime":"","Account":"knavi","ClientToken":"","Language":"","CNode":{"PCode":"OYXNO5VW","SMode":"","OperateT":""},"QNode":{"SelectT":"","Select_Fields":"","S_DBCodes":"","Subscribed":"","QGroup":[],"OrderBy":"OTA|DESC","GroupBy":"","Additon":""}}',
    'displaymode': '1',
    'pageindex': '1',
    'pagecount': '21',
    'index': 'JSTMWT6S',
    'searchType': '刊名(曾用刊名)',
    'parentcode': 'SQN63324',
    'switchdata': 'clickTabSearch',
    'clickName': 'CSSCI 中文社会科学引文索引'
}
headers = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://navi.cnki.net/knavi/journals/index'
}
try:
    r = requests.post(url, data=params, headers=headers, timeout=15)
    print('Status:', r.status_code)
    print('Len:', len(r.text))
    print(r.text[:500])
except Exception as e:
    print('Error:', e)
