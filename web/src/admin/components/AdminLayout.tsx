/**
 * 管理界面布局组件
 *
 * 包含侧边栏和头部导航
 */

import React, { useState } from 'react';
import { Layout, theme } from 'antd';
import { Outlet } from 'react-router-dom';
import AdminSidebar from './AdminSidebar';

const { Header, Content } = Layout;

/**
 * 管理界面布局
 */
export const AdminLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const {
    token: { colorBgContainer },
  } = theme.useToken();

  return (
    <Layout style={{ height: '100vh', overflow: 'hidden' }}>
      <AdminSidebar collapsed={collapsed} onCollapse={setCollapsed} />
      <Layout style={{ marginLeft: collapsed ? 80 : 200, transition: 'margin-left 0.2s', display: 'flex', flexDirection: 'column' }}>
        <Header
          style={{
            padding: '0 24px',
            background: colorBgContainer,
            borderBottom: '1px solid #f0f0f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            height: 56,
            flexShrink: 0,
          }}
        >
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
            期刊数据管理系统
          </h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span style={{ color: '#666' }}>管理员</span>
          </div>
        </Header>
        <Content
          style={{
            flex: 1,
            overflow: 'auto',
            padding: '16px 16px 16px 16px',
            background: '#f5f5f5',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
};

export default AdminLayout;
