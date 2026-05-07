# Scripts 目录说明

本目录包含 PaperTracker 项目的数据管理脚本。

## 📁 目录结构

```
scripts/
├── manage.py                 # 统一管理工具（推荐使用）
├── fetch_all_cssci_with_anti_detection.py  # 获取CSSCI列表
├── fetch_all_journals.py     # 获取CNKI期刊列表
├── query_journals.py         # 查询工具
├── update_journal_cores.py   # 更新期刊核心信息
├── update_journal_details.py # 更新期刊详情
└── archive/                  # 归档的旧脚本
    ├── migrations/           # 数据库迁移脚本（已完成）
    └── one_time_tasks/       # 一次性任务脚本
```

## 🚀 使用方法

### 推荐方式：使用统一管理工具

```bash
# 更新期刊详情（获取field、subfield等）
python scripts/manage.py update-details

# 只更新100条（测试）
python scripts/manage.py update-details --limit 100

# 强制更新所有期刊（忽略已有数据）
python scripts/manage.py update-details --force

# 获取CSSCI期刊列表
python scripts/manage.py fetch-cssci

# 获取CNKI期刊列表
python scripts/manage.py fetch-journals

# 更新期刊核心信息
python scripts/manage.py update-cores

# 查询期刊数据
python scripts/manage.py query
```

### 直接使用单个脚本

```bash
# 更新期刊详情
python scripts/update_journal_details.py --limit 100 --verbose

# 获取CSSCI列表
python scripts/fetch_all_cssci_with_anti_detection.py

# 查询期刊
python scripts/query_journals.py
```

## 📋 常用命令说明

| 命令 | 说明 | 参数 |
|------|------|------|
| `update-details` | 更新期刊详情（field、subfield） | `--limit N` 限制数量, `--force` 强制更新 |
| `fetch-cssci` | 获取CSSCI期刊列表 | 无 |
| `fetch-journals` | 获取CNKI期刊列表 | 无 |
| `update-cores` | 更新期刊核心信息 | 无 |
| `query` | 查询期刊数据 | 无 |

## 📦 归档说明

`archive/` 目录包含已完成任务的脚本，仅供参考：

- **migrations/**: 数据库迁移脚本（已完成）
- **one_time_tasks/**: 一次性任务脚本（CSSCI扩展版、数据清理等）

这些脚本保留用于参考，不建议重复运行。

## ⚠️ 注意事项

1. **断点续传**: `update-details` 命令支持断点续传，中断后重新运行会自动跳过已完成的期刊
2. **延迟设置**: 默认2-5秒延迟，避免触发反爬虫
3. **日志输出**: 使用 `--verbose` 参数查看详细日志

## 🔧 维护

添加新命令时，在 `manage.py` 中：
1. 定义新的命令函数 `cmd_xxx(args)`
2. 在 `subparsers` 中添加命令解析器
3. 在 `commands` 字典中注册命令
