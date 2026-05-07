/**
 * 管理界面仪表盘页面
 *
 * 显示系统概览统计和图表
 */

import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Statistic, Spin, Alert, Typography } from 'antd';
import {
  BookOutlined,
  TrophyOutlined,
  FileTextOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { Column } from '@ant-design/charts';
import { getJournalStats } from '../../shared/services/api';
import type { JournalStats } from '../../shared/types';

const { Title } = Typography;

/**
 * 仪表盘页面
 */
export const Dashboard: React.FC = () => {
  const [stats, setStats] = useState<JournalStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getJournalStats();
      setStats(data);
    } catch (err) {
      console.error('Failed to fetch stats:', err);
      setError('加载统计数据失败');
    } finally {
      setLoading(false);
    }
  };

  // 准备学科分布图表数据
  const getFieldChartData = () => {
    if (!stats?.by_field) return [];
    return Object.entries(stats.by_field)
      .map(([field, count]) => ({ name: field, value: count }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 10);
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '100px 0' }}>
        <Spin size="large">
          <div style={{ padding: 24, fontSize: 14 }}>加载统计数据...</div>
        </Spin>
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        message="加载失败"
        description={error}
        type="error"
        showIcon
        action={
          <button onClick={fetchStats} style={{ border: 'none', background: 'none', color: '#1890ff', cursor: 'pointer' }}>
            重试
          </button>
        }
      />
    );
  }

  const fieldChartData = getFieldChartData();

  return (
    <div style={{ padding: '0 0 16px' }}>
      <Title level={3} style={{ marginBottom: 16 }}>数据概览</Title>

      {/* 统计卡片 - 第一行 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={12} md={6} lg={6}>
          <Card styles={{ body: { padding: 20 } }} style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
            <Statistic
              title={<span style={{ color: 'rgba(255,255,255,0.85)' }}>总期刊数</span>}
              value={stats?.total_journals || 0}
              prefix={<BookOutlined style={{ color: '#fff' }} />}
              valueStyle={{ color: '#fff', fontSize: 28 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6} lg={6}>
          <Card styles={{ body: { padding: 20 } }} style={{ background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' }}>
            <Statistic
              title={<span style={{ color: 'rgba(255,255,255,0.85)' }}>CSSCI期刊</span>}
              value={stats?.cssci_journals || 0}
              prefix={<TrophyOutlined style={{ color: '#fff' }} />}
              valueStyle={{ color: '#fff', fontSize: 28 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6} lg={6}>
          <Card styles={{ body: { padding: 20 } }} style={{ background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' }}>
            <Statistic
              title={<span style={{ color: 'rgba(255,255,255,0.85)' }}>CSSCI扩展版</span>}
              value={stats?.cssci_expansion_journals || 0}
              valueStyle={{ color: '#fff', fontSize: 28 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={12} md={6} lg={6}>
          <Card styles={{ body: { padding: 20 } }} style={{ background: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)' }}>
            <Statistic
              title={<span style={{ color: 'rgba(255,255,255,0.85)' }}>北大核心</span>}
              value={stats?.beida_core_journals || 0}
              valueStyle={{ color: '#fff', fontSize: 28 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 统计卡片 - 第二行 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={12} md={12}>
          <Card>
            <Statistic
              title="有框架分析"
              value={stats?.journals_with_frameworks || 0}
              prefix={<FileTextOutlined />}
              suffix={`/ ${stats?.total_journals || 0}`}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={12}>
          <Card>
            <Statistic
              title="本月新增"
              value={0}
              prefix={<PlusOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 学科分布图表 */}
      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Card title="按学科分布（TOP 10）" styles={{ body: { padding: '16px 24px' } }}>
            {fieldChartData.length > 0 ? (
              <Column
                data={fieldChartData}
                xField="name"
                yField="value"
                label={{
                  position: 'top',
                  style: {
                    fill: '#000',
                    fontSize: 12,
                  },
                }}
                height={300}
                columnStyle={{
                  fill: '#1890ff',
                  fillOpacity: 0.8,
                }}
                xAxis={{
                  label: {
                    autoRotate: true,
                    autoHide: true,
                    autoRotateAngle: -45,
                  },
                }}
              />
            ) : (
              <div style={{ textAlign: 'center', padding: '50px', color: '#999' }}>
                暂无数据
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Dashboard;
