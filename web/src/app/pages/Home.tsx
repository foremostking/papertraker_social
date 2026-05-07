/**
 * 用户界面首页
 *
 * 论文生成引导系统首页
 */

import React from 'react';
import { Card, Row, Col, Button, Typography, Space } from 'antd';
import { ArrowRightOutlined, BookOutlined, EditOutlined, BulbOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

const { Title, Paragraph } = Typography;

/**
 * 首页页面
 */
export const Home: React.FC = () => {
  const navigate = useNavigate();

  const steps = [
    {
      number: '1',
      title: '选题确定',
      description: '确定研究方向和论文选题',
      icon: <BulbOutlined />,
      status: 'completed',
    },
    {
      number: '2',
      title: '文献调研',
      description: '收集和整理相关文献资料',
      icon: <BookOutlined />,
      status: 'completed',
    },
    {
      number: '3',
      title: '框架构建',
      description: '学习目标期刊的论文框架',
      icon: <EditOutlined />,
      status: 'active',
    },
    {
      number: '3.5',
      title: '期刊框架学习',
      description: '浏览目标期刊的已发表论文框架，学习论文结构',
      icon: <BookOutlined />,
      status: 'pending',
      path: '/step3.5',
    },
    {
      number: '4',
      title: '内容撰写',
      description: '按照框架进行论文内容撰写',
      icon: <EditOutlined />,
      status: 'locked',
    },
    {
      number: '5',
      title: '修改完善',
      description: '反复修改和完善论文',
      icon: <EditOutlined />,
      status: 'locked',
    },
    {
      number: '6',
      title: '投稿发表',
      description: '选择合适的期刊进行投稿',
      icon: <BookOutlined />,
      status: 'locked',
    },
    {
      number: '7',
      title: '发表成功',
      description: '论文成功发表',
      icon: <BulbOutlined />,
      status: 'locked',
    },
  ];

  const getStepStatus = (status: string) => {
    switch (status) {
      case 'completed':
        return 'success';
      case 'active':
        return 'processing';
      case 'pending':
        return 'warning';
      default:
        return 'default';
    }
  };

  return (
    <div>
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <Title level={2} style={{ color: '#1890ff' }}>
          论文生成助手
        </Title>
        <Paragraph style={{ fontSize: 16, color: '#666', maxWidth: 600, margin: '0 auto' }}>
          从选题到发表，我们为您提供全流程的论文写作指导。
          了解目标期刊的论文框架，让您的写作事半功倍。
        </Paragraph>
      </div>

      <Row gutter={[24, 24]}>
        {steps.map((step) => (
          <Col xs={24} sm={12} md={8} lg={6} key={step.number}>
            <Card
              hoverable={step.status === 'pending' || step.status === 'active'}
              style={{
                height: '100%',
                borderColor:
                  step.status === 'completed'
                    ? '#52c41a'
                    : step.status === 'active'
                    ? '#1890ff'
                    : step.status === 'pending'
                    ? '#faad14'
                    : '#d9d9d9',
              }}
              onClick={() => step.path && navigate(step.path)}
            >
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: '50%',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      backgroundColor:
                        step.status === 'completed'
                          ? '#52c41a'
                          : step.status === 'active'
                          ? '#1890ff'
                          : step.status === 'pending'
                          ? '#faad14'
                          : '#f0f0f0',
                      color: step.status === 'locked' ? '#999' : '#fff',
                      fontSize: 18,
                      fontWeight: 'bold',
                    }}
                  >
                    {step.number}
                  </div>
                  <div style={{ flex: 1 }}>
                    <Title level={5} style={{ margin: 0 }}>
                      {step.title}
                    </Title>
                  </div>
                </div>
                <Paragraph style={{ margin: 0, color: '#666', minHeight: 44 }}>
                  {step.description}
                </Paragraph>
                {(step.status === 'pending' || step.status === 'active') && (
                  <Button
                    type={step.status === 'pending' ? 'primary' : 'default'}
                    size="small"
                    icon={<ArrowRightOutlined />}
                    style={{ marginTop: 8 }}
                  >
                    {step.status === 'pending' ? '开始' : '继续'}
                  </Button>
                )}
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      <Card style={{ marginTop: 32, backgroundColor: '#f0f5ff', borderColor: '#adc6ff' }}>
        <Row gutter={24} align="middle">
          <Col flex="1">
            <Title level={4} style={{ margin: 0, color: '#1890ff' }}>
              为什么需要学习期刊框架？
            </Title>
            <Paragraph style={{ margin: '12px 0 0 0', color: '#666' }}>
              每个期刊都有自己偏好的论文结构和写作风格。了解目标期刊的已发表论文框架，
              可以帮助您：
              <br />
              1. 掌握期刊的论文结构和章节安排
              <br />
              2. 学习该期刊的写作风格和表达方式
              <br />3. 提高投稿成功率，减少退稿风险
            </Paragraph>
          </Col>
          <Col>
            <Button type="primary" size="large" onClick={() => navigate('/step3.5')}>
              开始学习期刊框架
            </Button>
          </Col>
        </Row>
      </Card>
    </div>
  );
};

export default Home;
