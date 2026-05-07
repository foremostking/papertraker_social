# 期刊管理界面实现方案

## Context

项目已完成数据层和API层：
- **1062本CSSCI期刊** 数据已导入PostgreSQL
- **期刊API** 已实现（`backend/app/api/v1/journals.py`）
- **Docker环境**（PostgreSQL + Redis）已就绪

用户需求：构建双端界面
- **管理界面（内部用户）** - 期刊管理、数据统计
- **用户界面（外部用户）** - 论文生成引导、框架学习

## 目标

构建统一的前端项目，包含管理界面和用户界面：

| 界面 | 用户 | 路由前缀 | 主要功能 |
|------|------|---------|---------|
| **管理界面** | 内部用户/管理员 | `/admin/*` | 详见下方功能模块 |
| **用户界面** | 外部用户/作者 | `/app/*` | 论文生成引导、期刊框架学习 |

### 管理界面功能模块规划

```
/admin
├── /dashboard              # 仪表盘（首页）
├── /journals               # 期刊管理模块
│   ├── /list              # 期刊列表
│   ├── /:id               # 期刊详情
│   ├── /categories        # 学科分类管理
│   └── /import            # 数据导入
├── /frameworks            # 论文框架管理模块 ⭐预留
│   ├── /templates         # 框架模板列表
│   ├── /:id               # 框架详情/编辑
│   ├── /categories        # 框架分类
│   └── /review            # 待审核框架
├── /users                 # 用户管理模块 ⭐预留
│   ├── /internal          # 内部用户（管理员、编辑）
│   ├── /external          # 外部用户（作者、研究者）
│   └── /permissions       # 权限管理
├── /papers                # 论文/内容管理模块 ⭐预留
│   ├── /list              # 论文列表
│   ├── /:id               # 论文详情
│   ├── /comments          # 评论管理
│   └── /tags              # 标签/关键词管理
├── /crawler               # 爬虫任务管理模块 ⭐预留
│   ├── /tasks             # 采集任务列表
│   ├── /logs              # 采集日志
│   └── /schedule          # 定时任务配置
├── /statistics            # 数据统计模块
│   ├── /overview          # 概览统计
│   ├── /journals          # 期刊数据统计
│   ├── /users             # 用户行为统计
│   └── /frameworks        # 框架使用统计 ⭐预留
├── /system                # 系统配置模块 ⭐预留
│   ├── /settings          # 系统参数配置
│   ├── /logs              # 操作日志
│   └── /backup            # 数据备份
└── /content               # 内容管理模块 ⭐预留
    ├── /articles          # 文章管理
    ├── /announcements     # 公告管理
    └── /feedback          # 用户反馈
```

## 目录结构优化

### 推荐结构：web/ 统一管理

```
papertracker_social/
├── backend/                   # 后端API服务
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── journals.py    # 期刊API（✅ 完成）
│   │   │   └── admin.py      # 管理员API（需新增）
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   └── services/
│   ├── scripts/
│   ├── tests/
│   └── alembic/
│
├── web/                       # 前端（统一管理）
│   ├── src/
│   │   ├── admin/            # 管理界面
│   │   │   ├── pages/
│   │   │   │   ├── Dashboard.tsx           # 仪表盘
│   │   │   │   ├── Journals/               # 期刊管理模块
│   │   │   │   │   ├── JournalList.tsx
│   │   │   │   │   ├── JournalDetail.tsx
│   │   │   │   │   ├── JournalCategories.tsx
│   │   │   │   │   └── components/
│   │   │   │   ├── Frameworks/             # 论文框架管理 ⭐预留
│   │   │   │   │   ├── FrameworkList.tsx
│   │   │   │   │   ├── FrameworkDetail.tsx
│   │   │   │   │   ├── FrameworkReview.tsx
│   │   │   │   │   └── components/
│   │   │   │   ├── Users/                  # 用户管理 ⭐预留
│   │   │   │   │   ├── InternalUsers.tsx
│   │   │   │   │   ├── ExternalUsers.tsx
│   │   │   │   │   └── components/
│   │   │   │   ├── Papers/                 # 论文/内容管理 ⭐预留
│   │   │   │   │   ├── PaperList.tsx
│   │   │   │   │   ├── PaperDetail.tsx
│   │   │   │   │   ├── Comments.tsx
│   │   │   │   │   └── components/
│   │   │   │   ├── Crawler/                # 爬虫任务管理 ⭐预留
│   │   │   │   │   ├── TaskList.tsx
│   │   │   │   │   ├── TaskLogs.tsx
│   │   │   │   │   └── components/
│   │   │   │   ├── Statistics/             # 数据统计
│   │   │   │   │   ├── Overview.tsx
│   │   │   │   │   ├── JournalStats.tsx
│   │   │   │   │   ├── UserStats.tsx      # ⭐预留
│   │   │   │   │   └── FrameworkStats.tsx # ⭐预留
│   │   │   │   ├── System/                 # 系统配置 ⭐预留
│   │   │   │   │   ├── Settings.tsx
│   │   │   │   │   ├── Logs.tsx
│   │   │   │   │   └── Backup.tsx
│   │   │   │   └── Content/                # 内容管理 ⭐预留
│   │   │   │       ├── Articles.tsx
│   │   │   │       ├── Announcements.tsx
│   │   │   │       └── Feedback.tsx
│   │   │   └── components/                 # 管理界面通用组件
│   │   ├── app/             # 用户界面
│   │   │   ├── pages/
│   │   │   │   ├── Home.tsx
│   │   │   │   ├── Step35/       # 期刊框架学习
│   │   │   │   │   ├── JournalBrowser.tsx
│   │   │   │   │   ├── FrameworkViewer.tsx
│   │   │   │   │   └── FrameworkRecommend.tsx
│   │   │   │   └── ...
│   │   │   └── components/
│   │   ├── shared/           # 共享模块
│   │   │   ├── components/    # 通用组件
│   │   │   ├── services/      # API服务
│   │   │   ├── types/         # TypeScript类型
│   │   │   ├── hooks/         # React Hooks
│   │   │   └── utils/         # 工具函数
│   │   ├── styles/           # 全局样式
│   │   ├── App.tsx           # 根组件
│   │   └── main.tsx
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
│
├── docs/                      # 项目文档
├── docker-compose.yml         # Docker配置
└── README.md
```

### 路由设计

```typescript
// web/src/App.tsx
<Routes>
  {/* 用户界面 - 默认路由 */}
  <Route path="/" element={<AppLayout />}>
    <Route index element={<Home />} />
    <Route path="step3.5" element={<Step35Layout />}>
      <Route index element={<JournalBrowser />} />
      <Route path="frameworks/:id" element={<FrameworkViewer />} />
    </Route>
  </Route>

  {/* 管理界面 - /admin前缀 */}
  <Route path="/admin" element={<AdminLayout />}>
    <Route index element={<Dashboard />} />

    {/* 期刊管理 */}
    <Route path="journals" element={<JournalList />} />
    <Route path="journals/:id" element={<JournalDetail />} />
    <Route path="journals/categories" element={<JournalCategories />} />

    {/* 论文框架管理 ⭐预留 */}
    <Route path="frameworks" element={<FrameworkList />} />
    <Route path="frameworks/:id" element={<FrameworkDetail />} />
    <Route path="frameworks/review" element={<FrameworkReview />} />

    {/* 用户管理 ⭐预留 */}
    <Route path="users/internal" element={<InternalUsers />} />
    <Route path="users/external" element={<ExternalUsers />} />
    <Route path="users/permissions" element={<Permissions />} />

    {/* 论文/内容管理 ⭐预留 */}
    <Route path="papers" element={<PaperList />} />
    <Route path="papers/:id" element={<PaperDetail />} />
    <Route path="papers/comments" element={<Comments />} />
    <Route path="papers/tags" element={<Tags />} />

    {/* 爬虫任务管理 ⭐预留 */}
    <Route path="crawler/tasks" element={<TaskList />} />
    <Route path="crawler/logs" element={<TaskLogs />} />
    <Route path="crawler/schedule" element={<ScheduleConfig />} />

    {/* 数据统计 */}
    <Route path="statistics" element={<StatisticsOverview />} />
    <Route path="statistics/journals" element={<JournalStats />} />
    <Route path="statistics/users" element={<UserStats />} />        {/* ⭐预留 */}
    <Route path="statistics/frameworks" element={<FrameworkStats />} /> {/* ⭐预留 */}

    {/* 系统配置 ⭐预留 */}
    <Route path="system/settings" element={<SystemSettings />} />
    <Route path="system/logs" element={<SystemLogs />} />
    <Route path="system/backup" element={<DataBackup />} />

    {/* 内容管理 ⭐预留 */}
    <Route path="content/articles" element={<Articles />} />
    <Route path="content/announcements" element={<Announcements />} />
    <Route path="content/feedback" element={<Feedback />} />
  </Route>
</Routes>
```

### 侧边栏导航配置（预留）

```typescript
// web/src/admin/components/AdminSidebar.tsx
const adminMenuItems = [
  { key: 'dashboard', icon: <DashboardOutlined />, label: '仪表盘', path: '/admin' },

  {
    key: 'journals',
    icon: <BookOutlined />,
    label: '期刊管理',
    children: [
      { key: 'journal-list', label: '期刊列表', path: '/admin/journals' },
      { key: 'journal-categories', label: '学科分类', path: '/admin/journals/categories' },
      { key: 'journal-import', label: '数据导入', path: '/admin/journals/import' },
    ]
  },

  // ⭐ 预留模块 - 逐步实现
  {
    key: 'frameworks',
    icon: <FileTextOutlined />,
    label: '论文框架',
    children: [
      { key: 'framework-list', label: '框架模板', path: '/admin/frameworks' },
      { key: 'framework-review', label: '待审核', path: '/admin/frameworks/review' },
      { key: 'framework-categories', label: '框架分类', path: '/admin/frameworks/categories' },
    ],
    disabled: true, // 预留，暂未实现
  },

  {
    key: 'users',
    icon: <UserOutlined />,
    label: '用户管理',
    children: [
      { key: 'internal-users', label: '内部用户', path: '/admin/users/internal' },
      { key: 'external-users', label: '外部用户', path: '/admin/users/external' },
      { key: 'permissions', label: '权限管理', path: '/admin/users/permissions' },
    ],
    disabled: true,
  },

  {
    key: 'papers',
    icon: <FileOutlined />,
    label: '论文管理',
    children: [
      { key: 'paper-list', label: '论文列表', path: '/admin/papers' },
      { key: 'comments', label: '评论管理', path: '/admin/papers/comments' },
      { key: 'tags', label: '标签管理', path: '/admin/papers/tags' },
    ],
    disabled: true,
  },

  {
    key: 'crawler',
    icon: <CloudDownloadOutlined />,
    label: '爬虫任务',
    children: [
      { key: 'crawler-tasks', label: '采集任务', path: '/admin/crawler/tasks' },
      { key: 'crawler-logs', label: '采集日志', path: '/admin/crawler/logs' },
      { key: 'crawler-schedule', label: '定时任务', path: '/admin/crawler/schedule' },
    ],
    disabled: true,
  },

  {
    key: 'statistics',
    icon: <BarChartOutlined />,
    label: '数据统计',
    children: [
      { key: 'stats-overview', label: '概览统计', path: '/admin/statistics' },
      { key: 'stats-journals', label: '期刊统计', path: '/admin/statistics/journals' },
      { key: 'stats-users', label: '用户统计', path: '/admin/statistics/users' },
      { key: 'stats-frameworks', label: '框架统计', path: '/admin/statistics/frameworks' },
    ],
  },

  {
    key: 'system',
    icon: <SettingOutlined />,
    label: '系统配置',
    children: [
      { key: 'system-settings', label: '参数配置', path: '/admin/system/settings' },
      { key: 'system-logs', label: '操作日志', path: '/admin/system/logs' },
      { key: 'system-backup', label: '数据备份', path: '/admin/system/backup' },
    ],
    disabled: true,
  },

  {
    key: 'content',
    icon: <CopyOutlined />,
    label: '内容管理',
    children: [
      { key: 'content-articles', label: '文章管理', path: '/admin/content/articles' },
      { key: 'content-announcements', label: '公告管理', path: '/admin/content/announcements' },
      { key: 'content-feedback', label: '用户反馈', path: '/admin/content/feedback' },
    ],
    disabled: true,
  },
];
```

## 技术栈

**Web前端**：
- React 18 + TypeScript + Vite 5
- Ant Design 5（UI组件）
- React Router v6（路由）
- TanStack Query（数据获取）
- ECharts（图表）
- Axios（HTTP客户端）

**后端API**：
- FastAPI（已有）
- PostgreSQL（已配置）
- 已实现期刊API：`/api/journals/*`

## 核心页面设计

### 管理界面：Dashboard

```
+----------------------------------------------------------+
| 期刊数据管理系统                                  |
+----------------------------------------------------------+
|  总期刊      | CSSCI    | 有框架    | 本月新增    |
|  1062       | 1062     | 0         | 0           |
+----------------------------------------------------------+
|  按学科分布 [柱状图]                                |
|  影响因子分布 [箱线图]                                |
|  出版模式统计 [饼图]                                  |
+----------------------------------------------------------+
```

### 管理界面：期刊列表

```
+----------------------------------------------------------+
| 期刊管理                                           |
+----------------------------------------------------------+
| [学科▼] [级别▼] [搜索...]                              |
+----------------------------------------------------------+
| 期刊名称      | 影响因子 | 主办单位      | 操作      |
| 中国工业经济  | 48.895  | 中国科学院...  | 查看 详情  |
| 管理世界      | 37.304  | 国务院发展...  | 查看 详情  |
| ...                                                      |
+----------------------------------------------------------+
| 共1062条        < 1 2 3 21 51 >                      |
+----------------------------------------------------------+
```

### 用户界面：步骤3.5 期刊框架学习

```
+----------------------------------------------------------+
| 步骤3.5：期刊框架学习                              |
+----------------------------------------------------------+
|  进度: ████░░░░░░░░░░░░░░░░░░░ 3/7                 |
+----------------------------------------------------------+
|  在这个步骤，你将：                                  |
|  1. 浏览目标期刊的已发表论文框架                   |
|  2. 学习该期刊的论文结构和写作风格                   |
|  3. 选择适合的框架模板进行创作                       |
|                                                      |
|  [开始浏览期刊]                                       |
|                                                      |
|  或直接选择：                                          |
|  [按学科浏览]  [按影响因子浏览]                       |
+----------------------------------------------------------+
```

## 实施步骤

### 第1步：重构前端目录

```bash
# 将frontend重命名为web
mv frontend web

# 初始化Vite项目
cd web
npm create vite@latest . --template react-ts
npm install antd @ant-design/charts @ant-design/icons
npm install @tanstack/react-query react-router-dom axios
```

### 第2步：创建目录结构

```bash
cd web/src
# 创建完整的预留目录结构
mkdir -p admin/{pages/{Journals,Frameworks,Users,Papers,Crawler,Statistics,System,Content},components}
mkdir -p app/{pages/Step35,components}
mkdir -p shared/{components,services,types,hooks,utils}
mkdir -p styles
```

### 第3步：实现核心功能（优先级排序）

| 优先级 | 功能模块 | 说明 | 工作量 |
|--------|---------|------|-------|
| P0 | 共享API服务层 | api.ts, types.ts | 0.5天 |
| P0 | Layout组件 | AdminLayout, AppLayout, Sidebar | 1天 |
| P0 | 管理界面：Dashboard | 仪表盘统计卡片 | 1天 |
| P0 | 管理界面：期刊列表 | 列表、筛选、分页、搜索 | 1.5天 |
| P1 | 管理界面：期刊详情 | 详情页、编辑功能 | 1天 |
| P1 | 管理界面：期刊分类 | 学科分类管理 | 0.5天 |
| P1 | 管理界面：数据统计 | 图表组件 | 1天 |
| P2 | 用户界面：Step3.5 | 期刊浏览器 | 2天 |
| **预留** | 论文框架管理 | 标记disabled，逐步实现 | - |
| **预留** | 用户管理 | 标记disabled，逐步实现 | - |
| **预留** | 论文管理 | 标记disabled，逐步实现 | - |
| **预留** | 爬虫任务 | 标记disabled，逐步实现 | - |
| **预留** | 系统配置 | 标记disabled，逐步实现 | - |
| **预留** | 内容管理 | 标记disabled，逐步实现 | - |

### 第一阶段（MVP）实施范围

**Phase 1 - 管理界面基础**：
- ✅ Dashboard（仪表盘）
- ✅ 期刊列表（含筛选、分页、搜索）
- ✅ 期刊详情
- ✅ 期刊分类管理
- ✅ 基础数据统计

**Phase 2 - 用户界面**：
- ✅ Step3.5 期刊浏览器
- ✅ 框架查看器

**Phase 3+ - 预留模块扩展**：
- 论文框架管理
- 用户管理
- 论文管理
- 爬虫任务管理
- 系统配置
- 内容管理

## Critical Files

### 后端API（需新增/扩展）

| 文件路径 | 说明 | 状态 |
|---------|------|------|
| `backend/app/api/v1/journals.py` | 期刊API（✅ 已完成） | ✅ |
| `backend/app/api/v1/frameworks.py` | 论文框架API ⭐预留 | 待创建 |
| `backend/app/api/v1/users.py` | 用户管理API ⭐预留 | 待创建 |
| `backend/app/api/v1/papers.py` | 论文管理API ⭐预留 | 待创建 |
| `backend/app/api/v1/crawler.py` | 爬虫任务API ⭐预留 | 待创建 |
| `backend/app/api/v1/statistics.py` | 统计数据API | 待创建 |
| `backend/app/api/v1/system.py` | 系统配置API ⭐预留 | 待创建 |

### 前端核心文件

| 文件路径 | 说明 | 阶段 |
|---------|------|------|
| `web/src/shared/services/api.ts` | 共享API服务层 | P0 |
| `web/src/shared/types/index.ts` | TypeScript类型定义 | P0 |
| `web/src/shared/components/` | 通用组件 | P0 |
| `web/src/admin/components/AdminLayout.tsx` | 管理界面布局 | P0 |
| `web/src/admin/components/AdminSidebar.tsx` | 侧边栏导航（含预留） | P0 |
| `web/src/admin/pages/Dashboard.tsx` | 仪表盘 | P0 |
| `web/src/admin/pages/Journals/JournalList.tsx` | 期刊列表 | P0 |
| `web/src/admin/pages/Journals/JournalDetail.tsx` | 期刊详情 | P1 |
| `web/src/admin/pages/Journals/JournalCategories.tsx` | 期刊分类 | P1 |
| `web/src/admin/pages/Statistics/Overview.tsx` | 数据统计概览 | P1 |
| `web/src/app/App.tsx` | 根组件/路由配置 | P0 |
| `web/src/app/pages/Step35/JournalBrowser.tsx` | 期刊浏览器 | P2 |

### 预留文件（逐步实现）

| 文件路径 | 说明 |
|---------|------|
| `web/src/admin/pages/Frameworks/` | 论文框架管理 ⭐ |
| `web/src/admin/pages/Users/` | 用户管理 ⭐ |
| `web/src/admin/pages/Papers/` | 论文管理 ⭐ |
| `web/src/admin/pages/Crawler/` | 爬虫任务管理 ⭐ |
| `web/src/admin/pages/System/` | 系统配置 ⭐ |
| `web/src/admin/pages/Content/` | 内容管理 ⭐ |

## 验收标准

- [x] web项目可正常启动（Vite开发服务器）
- [x] 管理界面路由 `/admin` 可访问
- [x] 用户界面路由 `/app` 可访问
- [x] Dashboard显示正确的统计卡片
- [x] 期刊列表支持筛选、分页、搜索
- [x] API调用正常、错误处理完善
- [x] 后端API服务器正常运行（http://localhost:8000）
- [x] 前后端联调成功

## 更新日志

### 2026-03-23
- ✅ 创建web目录并初始化Vite项目
- ✅ 安装依赖（antd、@ant-design/charts、@tanstack/react-query、react-router-dom、axios）
- ✅ 创建完整目录结构（含预留模块）
- ✅ 创建TypeScript类型定义
- ✅ 创建共享API服务层
- ✅ 创建Layout组件（AdminLayout、AppLayout）
- ✅ 创建侧边栏导航（含预留模块，标记disabled）
- ✅ 创建Dashboard仪表盘页面
- ✅ 创建期刊列表页面
- ✅ 创建期刊详情页面
- ✅ 创建用户界面Home页面
- ✅ 创建Step3.5期刊浏览器页面
- ✅ 配置路由和App.tsx
- ✅ 前端开发服务器启动成功（http://localhost:5173/）
- ✅ 修复后端pydantic-settings依赖
- ✅ 修复数据库依赖注入问题
- ✅ 修复Pydantic schema验证问题
- ✅ 后端API服务器启动成功（http://localhost:8000）
- ✅ 前后端联调成功，API正常响应
- ✅ 1062本期刊数据可正常访问

### 2026-03-24
- 📋 项目状态确认，Phase 1 管理界面基础已完成
- 📝 更新项目进展报告
- 📋 待完成：期刊分类管理页面、数据统计概览页面

### 运行状态

**前端服务**：http://localhost:5173/
- 用户界面：http://localhost:5173/
- 管理界面：http://localhost:5173/admin

**后端API**：http://localhost:8000
- API文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health
- 期刊列表：http://localhost:8000/api/journals/
- 统计信息：http://localhost:8000/api/journals/stats
- [ ] 添加更多统计图表
