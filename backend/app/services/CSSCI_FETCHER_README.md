# CNKI CSSCI期刊抓取器 - 使用说明

## 文件说明

| 文件 | 说明 |
|------|------|
| `cnki_cssci_fetcher_anti_detection.py` | 反爬虫增强版抓取器（推荐使用） |
| `cnki_cssci_fetcher_fixed.py` | 基础版抓取器 |
| `fetch_all_cssci_with_anti_detection.py` | 完整抓取脚本 |

## 反爬虫策略

| 策略 | 配置 | 说明 |
|------|------|------|
| **随机延迟** | 1.5-4秒/页 | 避免固定频率请求 |
| **User-Agent轮换** | 8个 | 每20页更换一次 |
| **重试机制** | 最多3次 | 指数退避：2秒 → 4秒 → 8秒 |
| **检查点恢复** | 每5页 | 支持中断后继续 |
| **人类行为模拟** | 随机滚动 | 每7页模拟滚动 |
| **隐藏自动化特征** | JavaScript注入 | 修改navigator.webdriver等 |

## 使用方法

### 完整抓取（51页，1062本期刊）

```bash
cd backend
python scripts/fetch_all_cssci_with_anti_detection.py
```

### 自定义抓取

```python
from app.services.cnki_cssci_fetcher_anti_detection import CNKICSSCIFetcherAntiDetection

# 创建抓取器
fetcher = CNKICSSCIFetcherAntiDetection(headless=True)  # False=观察模式

# 抓取指定页数
journals = await fetcher.fetch_cssci_journals(max_pages=10)  # None=全部

# 保存数据
fetcher.save_to_json("data/journals/my_journals.json")
```

### 配置参数

```python
fetcher = CNKICSSCIFetcherAntiDetection(headless=True)

# 延迟配置
fetcher.min_delay = 1.0  # 最小延迟（秒）
fetcher.max_delay = 3.0  # 最大延迟（秒）

# 重试配置
fetcher.max_retries = 5  # 最大重试次数
fetcher.retry_base_delay = 3  # 重试基础延迟

# 检查点配置
fetcher.checkpoint_interval = 10  # 每10页保存
```

## 检查点恢复

如果抓取被中断（Ctrl+C或网络错误），重新运行会自动从上次位置继续：

```
[恢复] 发现检查点文件
  已抓取: 420 本期刊
  上次完成到: 第 20 页
  总页数: 51
[恢复] 从第21页继续抓取...
```

成功完成后检查点文件会自动删除。

## 输出数据格式

```json
{
  "total": 1062,
  "fetch_time": "2026-03-23 13:12:58",
  "stats": {
    "total_pages": 51,
    "total_journals": 1062,
    "retry_count": 0,
    "failed_pages": []
  },
  "journals": [
    {
      "name": "期刊名称",
      "issn": "0577-9154",
      "cn": "11-1081/F",
      "publisher": "主办单位",
      "impact_factor": "28.117",
      "detail_url": "https://navi.cnki.net/...",
      "is_cssci": true,
      "source": "CNKI",
      "cssci_year": 2023
    }
  ]
}
```

## 实际抓取结果

- **总页数**：51页
- **总期刊数**：1062本
- **抓取时间**：约3-5分钟
- **重试次数**：0次（稳定）
- **字段完整度**：
  - ISSN: 81.2%
  - CN: 81.3%
  - 主办单位: 100%

## 学科分布

根据主办单位分类：
- 高校系统：759本 (71.5%)
- 其他：127本
- 研究机构：93本
- 学会系统：60本
- 科学院系统：23本

## 注意事项

1. **首次运行建议使用观察模式** (`headless=False`) 以确保正常工作
2. **不要降低延迟** 过快请求可能被限制
3. **检查点自动管理** 成功完成后会自动删除
4. **失败页面记录** 查看stats.failed_pages了解哪些页面需要重新抓取
