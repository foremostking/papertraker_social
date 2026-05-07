# CNKI期刊爬虫使用指南

## 两步抓取策略

### 第一步：获取期刊列表
- API端点：`https://navi.cnki.net/knavi/journals/searchbaseinfo`
- 返回：期刊名称、详情页链接等基本信息

### 第二步：获取详细信息
- 访问每个期刊的详情页
- 从`class="infobox"`元素中解析：
  - ISSN
  - CN刊号
  - 主办单位
  - 投稿邮箱
  - 官网地址
  - 英文名称
  - 学科分类

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 测试爬虫

```bash
python scripts/test_fetcher.py
```

测试脚本只会抓取2页数据，用于验证爬虫是否正常工作。

### 3. 完整抓取

```bash
python -m app.services.cnki_journal_fetcher
```

这将抓取全部1062条CSSCI期刊记录（包含详细信息）。

### 4. 快速模式（仅基本信息）

如果只需要基本信息，可以禁用第二步：

```python
from app.services.cnki_journal_fetcher import CNKIJournalFetcher

fetcher = CNKIJournalFetcher(fetch_details=False)
journals = fetcher.fetch_cssci_journals()
```

## 数据导入

### 1. 配置数据库

编辑 `.env` 文件，配置PostgreSQL连接：

```
DATABASE_URL=postgresql://user:password@localhost:5432/papertracker
```

### 2. 创建数据库

```bash
createdb papertracker
```

### 3. 导入数据

```bash
python -m app.services.journal_importer
```

## 启动API服务

```bash
uvicorn app.main:app --reload --port 8000
```

API文档: http://localhost:8000/docs

## API示例

### 获取期刊列表

```bash
curl "http://localhost:8000/api/journals?limit=10"
```

### 获取CSSCI期刊

```bash
curl "http://localhost:8000/api/journals?is_cssci=true"
```

### 按学科筛选

```bash
curl "http://localhost:8000/api/journals?field=经济学"
```

### 获取统计信息

```bash
curl "http://localhost:8000/api/journals/stats"
```

## 数据结构

### 期刊数据格式（完整版）

```json
{
  "name": "经济研究",
  "name_en": "Economic Research Journal",
  "issn": "0577-9154",
  "cn": "11-1081/F",
  "publisher": "中国社会科学院经济研究所",
  "field": "经济学",
  "email": "erj@cass.org.cn",
  "official_url": "http://www.erj.cn",
  "is_cssci": true,
  "cssci_year": 2023,
  "journal_url": "https://navi.cnki.net/knavi/journals/..."
}
```

## 常见问题

### Q1: 完整模式抓取速度慢

**原因**: 需要访问每个期刊的详情页

**解决方案**:
1. 使用快速模式（`fetch_details=False`）
2. 分批抓取（使用`max_pages`参数）
3. 调整请求间隔时间

### Q2: 爬虫无法获取数据

**原因**: CNKI API可能需要签名验证

**解决方案**:
1. 检查网络连接
2. 使用Selenium方案（在代码中已实现）
3. 检查CNKI网站是否更新

### Q3: 数据库连接失败

**原因**: PostgreSQL未启动或配置错误

**解决方案**:
1. 检查PostgreSQL服务是否运行
2. 验证 `.env` 文件中的数据库配置
3. 确保数据库已创建

### Q4: 如何更新期刊数据

定期运行爬虫即可：

```bash
# 完整模式
python -m app.services.cnki_journal_fetcher
python -m app.services.journal_importer
```

## 数据更新机制

系统支持自动检测CSSCI目录更新：

- 每月自动检测一次
- 通过对比总页数判断是否有更新
- 检测到更新后自动触发完整同步

## 项目结构

```
backend/
├── app/
│   ├── services/
│   │   ├── cnki_journal_fetcher.py    # CNKI爬虫（两步抓取）
│   │   └── journal_importer.py        # 数据导入
│   ├── models/
│   │   └── journal.py                 # 数据模型
│   ├── api/v1/
│   │   └── journals.py                # API端点
│   └── schemas/
│       └── journal.py                 # Pydantic模式
├── scripts/
│   └── test_fetcher.py                # 测试脚本
└── data/
    └── journals/
        ├── cssci_journals.json        # 完整数据
        └── test_journals.json         # 测试数据
```

## 下一步

1. ✅ 完成期刊数据抓取
2. 🔄 验证数据准确性
3. 📋 实现论文PDF下载功能
4. 📋 实现框架提取和聚类分析
5. 📋 开发前端界面

## 参考资料

- [CNKI期刊导航](https://navi.cnki.net/knavi/journals/index?uniplatform=NZKPT)
- [CSSCI来源期刊目录](https://keyanchu.yeu.edu.cn/)
- [项目实施计划](C:/Users/xuxiaobing/.claude/plans/stateful-humming-octopus.md)
