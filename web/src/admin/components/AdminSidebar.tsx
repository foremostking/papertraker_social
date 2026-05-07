/**
 * 管理界面侧边栏导航组件
 *
 * 包含所有功能模块菜单（含预留模块）
 */

import React from 'react';
import { Layout, Menu } from 'antd';
import { useNavigate, useLocation } from 'react-router-dom';
import type { MenuItem } from '../../shared/types';

const { Sider } = Layout;

// 引入图标
import {
  DashboardOutlined,
  BookOutlined,
  FileTextOutlined,
  UserOutlined,
  FileOutlined,
  CloudDownloadOutlined,
  BarChartOutlined,
  SettingOutlined,
  CopyOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SearchOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';

/**
 * 侧边栏菜单配置
 */
export const adminMenuItems: MenuItem[] = [
  { key: 'dashboard', icon: <DashboardOutlined />, label: '仪表盘', path: '/admin' },

  {
    key: 'journals',
    icon: <BookOutlined />,
    label: '期刊管理',
    children: [
      { key: 'journal-list', label: '期刊列表', path: '/admin/journals' },
      { key: 'column-search', label: '栏目搜索', path: '/admin/columns/search', icon: <SearchOutlined /> },
      { key: 'journal-categories', label: '学科分类', path: '/admin/journals/categories', disabled: true },
      { key: 'journal-import', label: '数据导入', path: '/admin/journals/import', disabled: true },
    ],
  },

  // 任务管理
  {
    key: 'tasks',
    icon: <ClockCircleOutlined />,
    label: '任务管理',
    path: '/admin/tasks',
  },

  // ⭐ 预留模块 - 逐步实现
  {
    key: 'frameworks',
    icon: <FileTextOutlined />,
    label: '论文框架',
    disabled: true,
    children: [
      { key: 'framework-list', label: '框架模板', path: '/admin/frameworks' },
      { key: 'framework-review', label: '待审核', path: '/admin/frameworks/review' },
      { key: 'framework-categories', label: '框架分类', path: '/admin/frameworks/categories' },
    ],
  },

  {
    key: 'users',
    icon: <UserOutlined />,
    label: '用户管理',
    disabled: true,
    children: [
      { key: 'internal-users', label: '内部用户', path: '/admin/users/internal' },
      { key: 'external-users', label: '外部用户', path: '/admin/users/external' },
      { key: 'permissions', label: '权限管理', path: '/admin/users/permissions' },
    ],
  },

  {
    key: 'papers',
    icon: <FileOutlined />,
    label: '论文管理',
    disabled: true,
    children: [
      { key: 'paper-list', label: '论文列表', path: '/admin/papers' },
      { key: 'comments', label: '评论管理', path: '/admin/papers/comments' },
      { key: 'tags', label: '标签管理', path: '/admin/papers/tags' },
    ],
  },

  {
    key: 'crawler',
    icon: <CloudDownloadOutlined />,
    label: '爬虫任务',
    disabled: true,
    children: [
      { key: 'crawler-tasks', label: '采集任务', path: '/admin/crawler/tasks' },
      { key: 'crawler-logs', label: '采集日志', path: '/admin/crawler/logs' },
      { key: 'crawler-schedule', label: '定时任务', path: '/admin/crawler/schedule' },
    ],
  },

  {
    key: 'statistics',
    icon: <BarChartOutlined />,
    label: '数据统计',
    children: [
      { key: 'stats-overview', label: '概览统计', path: '/admin/statistics' },
      { key: 'stats-journals', label: '期刊统计', path: '/admin/statistics/journals' },
      { key: 'stats-users', label: '用户统计', path: '/admin/statistics/users', disabled: true },
      { key: 'stats-frameworks', label: '框架统计', path: '/admin/statistics/frameworks', disabled: true },
    ],
  },

  {
    key: 'system',
    icon: <SettingOutlined />,
    label: '系统配置',
    disabled: true,
    children: [
      { key: 'system-settings', label: '参数配置', path: '/admin/system/settings' },
      { key: 'system-logs', label: '操作日志', path: '/admin/system/logs' },
      { key: 'system-backup', label: '数据备份', path: '/admin/system/backup' },
    ],
  },

  {
    key: 'content',
    icon: <CopyOutlined />,
    label: '内容管理',
    disabled: true,
    children: [
      { key: 'content-articles', label: '文章管理', path: '/admin/content/articles' },
      { key: 'content-announcements', label: '公告管理', path: '/admin/content/announcements' },
      { key: 'content-feedback', label: '用户反馈', path: '/admin/content/feedback' },
    ],
  },
];

interface AdminSidebarProps {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

/**
 * 管理界面侧边栏组件
 */
export const AdminSidebar: React.FC<AdminSidebarProps> = ({ collapsed, onCollapse }) => {
  const navigate = useNavigate();
  const location = useLocation();

  // 将菜单项转换为Ant Design Menu格式
  const menuItems = adminMenuItems.map((item) => {
    if (item.children) {
      return {
        key: item.key,
        icon: item.icon,
        label: item.label,
        disabled: item.disabled,
        children: item.children.map((child) => ({
          key: child.key,
          label: child.label,
          disabled: child.disabled,
        })),
      };
    }
    return {
      key: item.key,
      icon: item.icon,
      label: item.label,
      disabled: item.disabled,
    };
  });

  // 处理菜单点击
  const handleMenuClick = ({ key }: { key: string }) => {
    const findPath = (items: MenuItem[], targetKey: string): string | null => {
      for (const item of items) {
        if (item.key === targetKey && item.path) {
          return item.path;
        }
        if (item.children) {
          const childPath = findPath(item.children, targetKey);
          if (childPath) return childPath;
        }
      }
      return null;
    };

    const path = findPath(adminMenuItems, key);
    if (path) {
      navigate(path);
    }
  };

  // 根据当前路径计算选中的菜单项
  const getSelectedKeys = (): string[] => {
    const path = location.pathname;
    const findKey = (items: MenuItem[], targetPath: string): string | null => {
      for (const item of items) {
        if (item.path === targetPath) {
          return item.key;
        }
        if (item.children) {
          const childKey = findKey(item.children, targetPath);
          if (childKey) return childKey;
        }
      }
      return null;
    };
    const key = findKey(adminMenuItems, path);
    return key ? [key] : [];
  };

  // 根据当前路径计算展开的菜单
  const getOpenKeys = (): string[] => {
    const path = location.pathname;
    const openKeys: string[] = [];
    for (const item of adminMenuItems) {
      if (item.children) {
        const hasMatchingChild = item.children.some(
          (child) => child.path && path.startsWith(child.path)
        );
        if (hasMatchingChild) {
          openKeys.push(item.key);
        }
      }
    }
    return openKeys;
  };

  return (
    <Sider
      collapsible
      collapsed={collapsed}
      onCollapse={onCollapse}
      theme="dark"
      width={200}
      collapsedWidth={80}
      style={{
        overflow: 'auto',
        height: '100vh',
        flexShrink: 0,
      }}
      trigger={
        <div style={{ textAlign: 'center', padding: '8px 0' }}>
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </div>
      }
    >
      <div
        style={{
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontSize: collapsed ? 16 : 18,
          fontWeight: 'bold',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
        }}
      >
        {collapsed ? 'PT' : 'PaperTracker'}
      </div>
      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={getSelectedKeys()}
        defaultOpenKeys={getOpenKeys()}
        items={menuItems}
        onClick={handleMenuClick}
      />
    </Sider>
  );
};

export default AdminSidebar;
