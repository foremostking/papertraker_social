/**
 * 用户界面布局组件
 *
 * 用于外部用户/作者的论文生成引导界面
 */

import React from 'react';
import { Layout, theme, Menu, Button } from 'antd';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  HomeOutlined,
  BookOutlined,
  FileTextOutlined,
  UserOutlined,
} from '@ant-design/icons';

const { Header, Content, Footer } = Layout;

/**
 * 用户界面菜单项
 */
const userMenuItems = [
  { key: 'home', icon: <HomeOutlined />, label: '首页', path: '/' },
  { key: 'step3.5', icon: <BookOutlined />, label: '步骤3.5', path: '/step3.5' },
  { key: 'frameworks', icon: <FileTextOutlined />, label: '框架学习', path: '/frameworks' },
];

/**
 * 用户界面布局
 */
export const AppLayout: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    token: { colorBgContainer },
  } = theme.useToken();

  const handleMenuClick = ({ key }: { key: string }) => {
    const item = userMenuItems.find((item) => item.key === key);
    if (item) {
      navigate(item.path);
    }
  };

  const getSelectedKey = () => {
    const path = location.pathname;
    if (path.startsWith('/step3.5')) return 'step3.5';
    if (path.startsWith('/frameworks')) return 'frameworks';
    return 'home';
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#fff',
          borderBottom: '1px solid #f0f0f0',
          padding: '0 48px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <div
            style={{
              fontSize: 20,
              fontWeight: 'bold',
              color: '#1890ff',
              marginRight: 48,
            }}
          >
            PaperTracker Social
          </div>
          <Menu
            mode="horizontal"
            selectedKeys={[getSelectedKey()]}
            items={userMenuItems.map((item) => ({
              key: item.key,
              icon: item.icon,
              label: item.label,
            }))}
            onClick={handleMenuClick}
            style={{ flex: 1, border: 'none' }}
          />
        </div>
        <div>
          <Button type="text" icon={<UserOutlined />}>
            登录
          </Button>
        </div>
      </Header>
      <Content style={{ padding: '24px 48px', background: '#f5f5f5' }}>
        <div
          style={{
            padding: 24,
            minHeight: 'calc(100vh - 134px - 70px)',
            background: colorBgContainer,
            borderRadius: 8,
          }}
        >
          <Outlet />
        </div>
      </Content>
      <Footer style={{ textAlign: 'center', background: '#fff' }}>
        PaperTracker Social ©{new Date().getFullYear()} 论文生成助手
      </Footer>
    </Layout>
  );
};

export default AppLayout;
