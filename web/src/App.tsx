/**
 * App根组件
 *
 * 配置所有路由
 */

import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

// Layout组件
import { AdminLayout } from './admin/components/AdminLayout';
import { AppLayout } from './app/components/AppLayout';

// 管理界面页面
import Dashboard from './admin/pages/Dashboard';
import JournalList from './admin/pages/Journals/JournalList';
import JournalDetail from './admin/pages/Journals/JournalDetail';
import { ColumnSearch } from './admin/pages/ColumnSearch';
import { TasksPage } from './admin/pages/Tasks';

// 用户界面页面
import { Home } from './app/pages/Home';
import { JournalBrowser } from './app/pages/Step35/JournalBrowser';

// 创建TanStack Query客户端
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5分钟
    },
  },
});

/**
 * App组件
 */
function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN}>
        <BrowserRouter>
          <Routes>
            {/* 用户界面 - 默认路由 */}
            <Route path="/" element={<AppLayout />}>
              <Route index element={<Home />} />
              <Route path="step3.5" element={<JournalBrowser />} />
              {/* 预留：框架查看器 */}
              {/* <Route path="step3.5/frameworks/:id" element={<FrameworkViewer />} /> */}
            </Route>

            {/* 管理界面 - /admin前缀 */}
            <Route path="/admin" element={<AdminLayout />}>
              <Route index element={<Dashboard />} />

              {/* 期刊管理 */}
              <Route path="journals" element={<JournalList />} />
              <Route path="journals/:id" element={<JournalDetail />} />

              {/* 栏目搜索 */}
              <Route path="columns/search" element={<ColumnSearch />} />

              {/* 任务管理 */}
              <Route path="tasks" element={<TasksPage />} />

              {/* 预留：期刊分类 */}
              {/* <Route path="journals/categories" element={<JournalCategories />} /> */}

              {/* 预留模块 - 逐步实现 */}
              {/* <Route path="frameworks" element={<FrameworkList />} /> */}
              {/* <Route path="frameworks/:id" element={<FrameworkDetail />} /> */}
              {/* <Route path="frameworks/review" element={<FrameworkReview />} /> */}

              {/* <Route path="users/internal" element={<InternalUsers />} /> */}
              {/* <Route path="users/external" element={<ExternalUsers />} /> */}

              {/* <Route path="papers" element={<PaperList />} /> */}

              {/* <Route path="crawler/tasks" element={<TaskList />} /> */}

              {/* <Route path="statistics" element={<StatisticsOverview />} /> */}
              {/* <Route path="statistics/journals" element={<JournalStats />} /> */}

              {/* <Route path="system/settings" element={<SystemSettings />} /> */}

              {/* <Route path="content/articles" element={<Articles />} /> */}
            </Route>

            {/* 404重定向 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ConfigProvider>
    </QueryClientProvider>
  );
}

export default App;
