/**
 * 期刊详情页面
 *
 * 显示期刊完整信息和编辑功能
 */

import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import {
  Card,
  Descriptions,
  Button,
  Tag,
  Spin,
  message,
  Space,
  Row,
  Col,
  Statistic,
  Typography,
  Collapse,
  Drawer,
  Tabs,
} from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  SyncOutlined,
  LinkOutlined,
  FileTextOutlined,
  DownloadOutlined,
  HeartOutlined,
} from '@ant-design/icons';
import { getJournalById, updateJournalCNKIDetails } from '../../../shared/services/api';
import type { Journal } from '../../../shared/types';
import type { JournalListParams } from '../../../shared/types';
import { ColumnList } from './components/ColumnList';
import { PaperFetcher } from './components/PaperFetcher';

const { Title, Text } = Typography;

/**
 * 导航状态类型
 */
interface NavigationState {
  params?: JournalListParams;
  searchKeyword?: string;
}

/**
 * 期刊详情页面
 */
export const JournalDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [journal, setJournal] = useState<Journal | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [columnsDetailVisible, setColumnsDetailVisible] = useState(false);

  // 获取导航时保存的状态
  const navigationState = location.state as NavigationState | undefined;

  useEffect(() => {
    if (id) {
      fetchJournal();
    }
  }, [id]);

  const fetchJournal = async () => {
    try {
      setLoading(true);
      const data = await getJournalById(Number(id));
      setJournal(data);
    } catch (error: any) {
      message.error(error.detail || '加载期刊详情失败');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateCNKI = async () => {
    if (!id) return;

    try {
      setUpdating(true);
      const updated = await updateJournalCNKIDetails(Number(id));
      setJournal(updated);
      message.success('CNKI 详情更新成功');
    } catch (error: any) {
      message.error(error.detail || '更新失败');
    } finally {
      setUpdating(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '100px 0' }}>
        <Spin size="large">
          <div style={{ padding: 24, fontSize: 14 }}>加载期刊详情...</div>
        </Spin>
      </div>
    );
  }

  if (!journal) {
    return (
      <Card>
        <div style={{ textAlign: 'center', padding: '50px' }}>
          <p style={{ color: '#999' }}>期刊不存在</p>
          <Button
            type="primary"
            onClick={() => navigate('/admin/journals', { state: navigationState })}
          >
            返回列表
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 顶部操作栏 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 16
      }}>
        <Space>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/admin/journals', { state: navigationState })}
          >
            返回列表
          </Button>
          <Button
            type="primary"
            icon={<SyncOutlined spin={updating} />}
            onClick={handleUpdateCNKI}
            loading={updating}
          >
            更新 CNKI 详情
          </Button>
        </Space>
        <Button type="primary" icon={<EditOutlined />}>
          编辑
        </Button>
      </div>

      {/* 期刊标题和级别标签 */}
      <Card style={{ marginBottom: 16 }}>
        <Row align="middle" gutter={16}>
          <Col flex="auto">
            <Title level={3} style={{ margin: 0 }}>{journal.name}</Title>
            {journal.name_en && (
              <Text type="secondary" style={{ fontSize: 14 }}>
                {journal.name_en}
              </Text>
            )}
          </Col>
          <Col>
            <Space size={8}>
              {journal.is_cssci && <Tag color="green">CSSCI来源期刊</Tag>}
              {journal.is_cssci_expansion && <Tag color="lime">CSSCI扩展版</Tag>}
              {journal.is_beida_core && <Tag color="purple">北大核心</Tag>}
              {journal.is_network_first && <Tag color="blue">网络首发</Tag>}
              {journal.is_enhanced_publishing && <Tag color="cyan">增强出版</Tag>}
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 主内容区 - 标签页 */}
      <Tabs
        defaultActiveKey="basic"
        items={[
          {
            key: 'basic',
            label: '基本信息',
            children: (
              <Row gutter={16}>
                {/* 左侧 - 基本信息 */}
                <Col span={14}>
                  <Card title="基本信息" size="small" style={{ marginBottom: 16 }}>
                    <Descriptions column={2} size="small">
                      <Descriptions.Item label="ISSN">{journal.issn || '-'}</Descriptions.Item>
                      <Descriptions.Item label="CN">{journal.cn || '-'}</Descriptions.Item>
                      <Descriptions.Item label="主办单位" span={2}>{journal.publisher || '-'}</Descriptions.Item>
                      <Descriptions.Item label="一级学科">{journal.field || '-'}</Descriptions.Item>
                      <Descriptions.Item label="二级学科">{journal.subfield || '-'}</Descriptions.Item>
                      <Descriptions.Item label="出版周期">{journal.publishing_cycle || '-'}</Descriptions.Item>
                      <Descriptions.Item label="创刊时间">{journal.founded_year || '-'}</Descriptions.Item>
                      <Descriptions.Item label="出版地">{journal.publishing_location || '-'}</Descriptions.Item>
                      <Descriptions.Item label="语种">{journal.language || '-'}</Descriptions.Item>
                      <Descriptions.Item label="开本">{journal.format || '-'}</Descriptions.Item>
                      <Descriptions.Item label="邮发代号">{journal.postal_code || '-'}</Descriptions.Item>
                      <Descriptions.Item label="专辑名称">{journal.album_name || '-'}</Descriptions.Item>
                    </Descriptions>
                  </Card>

                  {/* 影响因子 */}
                  <Card title="影响因子" size="small">
                    <Row gutter={16}>
                      <Col span={8}>
                        <Statistic
                          title="复合影响因子"
                          value={journal.composite_impact_factor || 0}
                          precision={3}
                          styles={{ content: { color: '#1890ff' } }}
                        />
                      </Col>
                      <Col span={8}>
                        <Statistic
                          title="综合影响因子"
                          value={journal.comprehensive_impact_factor || 0}
                          precision={3}
                          styles={{ content: { color: '#52c41a' } }}
                        />
                      </Col>
                      <Col span={8}>
                        <Statistic
                          title="CSSCI年份"
                          value={journal.cssci_year || '-'}
                          styles={{ content: { color: '#722ed1' } }}
                        />
                      </Col>
                    </Row>
                  </Card>
                </Col>

                {/* 右侧 - 统计和链接 */}
                <Col span={10}>
                  {/* 数据统计 */}
                  <Card title="数据统计" size="small" style={{ marginBottom: 16 }}>
                    <Row gutter={[8, 8]}>
                      <Col span={12}>
                        <Statistic
                          title="论文总数"
                          value={journal.total_papers || 0}
                          prefix={<FileTextOutlined />}
                          styles={{ content: { fontSize: 18 } }}
                        />
                      </Col>
                      <Col span={12}>
                        <Statistic
                          title="出版文献"
                          value={journal.total_documents || 0}
                          prefix={<FileTextOutlined />}
                          styles={{ content: { fontSize: 18 } }}
                        />
                      </Col>
                      <Col span={12}>
                        <Statistic
                          title="总下载"
                          value={journal.total_downloads || 0}
                          prefix={<DownloadOutlined />}
                          styles={{ content: { fontSize: 18 } }}
                          formatter={(value) => (Number(value) >= 10000 ? `${(Number(value) / 10000).toFixed(1)}万` : value)}
                        />
                      </Col>
                      <Col span={12}>
                        <Statistic
                          title="总被引"
                          value={journal.total_citations || 0}
                          prefix={<HeartOutlined />}
                          styles={{ content: { fontSize: 18 } }}
                          formatter={(value) => (Number(value) >= 10000 ? `${(Number(value) / 10000).toFixed(1)}万` : value)}
                        />
                      </Col>
                    </Row>
                  </Card>

                  {/* 快捷链接 */}
                  <Card title="快捷链接" size="small" style={{ marginBottom: 16 }}>
                    <Space style={{ width: '100%', display: 'flex', flexDirection: 'column' }} size={8}>
                      {journal.official_url && (
                        <Button
                          block
                          icon={<LinkOutlined />}
                          href={journal.official_url}
                          target="_blank"
                        >
                          官方网站
                        </Button>
                      )}
                      {journal.cnki_url && (
                        <Button
                          block
                          icon={<LinkOutlined />}
                          href={journal.cnki_url}
                          target="_blank"
                        >
                          CNKI链接
                        </Button>
                      )}
                      {journal.detail_url && (
                        <Button
                          block
                          icon={<LinkOutlined />}
                          href={journal.detail_url}
                          target="_blank"
                        >
                          CNKI详情页
                        </Button>
                      )}
                      {journal.email && (
                        <Button
                          block
                          type="link"
                          href={`mailto:${journal.email}`}
                        >
                          {journal.email}
                        </Button>
                      )}
                    </Space>
                  </Card>

                  {/* 期刊标签 */}
                  {journal.journal_tags && journal.journal_tags.length > 0 && (
                    <Card title="期刊标签" size="small" style={{ marginBottom: 16 }}>
                      <Space size={8} wrap>
                        {journal.journal_tags.map((tag, index) => (
                          <Tag key={index} color="blue">{tag}</Tag>
                        ))}
                      </Space>
                    </Card>
                  )}

                  {/* 期刊固定栏目 */}
                  {journal.journal_columns && journal.journal_columns.length > 0 && (
                    <Card
                      title="期刊栏目"
                      size="small"
                      style={{ marginBottom: 16 }}
                      extra={
                        journal.journal_columns_detail && journal.journal_columns_detail.length > 0 && (
                          <Button
                            type="link"
                            size="small"
                            onClick={() => setColumnsDetailVisible(true)}
                          >
                            查看详情
                          </Button>
                        )
                      }
                    >
                      <Space size={8} wrap>
                        {journal.journal_columns.map((column, index) => (
                          <Tag key={index} color="geekblue">{column}</Tag>
                        ))}
                      </Space>
                    </Card>
                  )}

                  {/* 时间信息 */}
                  <Card title="时间信息" size="small">
                    <Descriptions column={1} size="small">
                      <Descriptions.Item label="最后论文日期">
                        {journal.last_paper_date
                          ? new Date(journal.last_paper_date).toLocaleDateString('zh-CN')
                          : '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label="详情更新">
                        {journal.cnki_detail_last_updated
                          ? new Date(journal.cnki_detail_last_updated).toLocaleDateString('zh-CN')
                          : '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label="数据更新">
                        {new Date(journal.updated_at).toLocaleDateString('zh-CN')}
                      </Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'columns',
            label: '栏目管理',
            children: (
              <ColumnList
                journalId={journal.id}
                journalName={journal.name}
                columns={journal.journal_columns || []}
                columnsDetail={journal.journal_columns_detail || []}
                onRefresh={fetchJournal}
                loading={updating}
              />
            ),
          },
          ...(journal.journal_code ? [{
            key: 'papers',
            label: '获取论文',
            children: <PaperFetcher journal={journal} />,
          }] : []),
        ]}
      />

      {/* 期刊栏目详情抽屉 */}
      <Drawer
        title="期刊栏目完整数据"
        open={columnsDetailVisible}
        onClose={() => setColumnsDetailVisible(false)}
        styles={{ body: { minWidth: 500 } }}
      >
        {journal?.journal_columns_detail && journal.journal_columns_detail.length > 0 ? (
          <Collapse
            items={journal.journal_columns_detail.map((column, index) => ({
              key: index,
              label: column.title,
              children: (
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="栏目名称">{column.title}</Descriptions.Item>
                  <Descriptions.Item label="参数 (param)">
                    <Text copyable style={{ wordBreak: 'break-all' }}>
                      {column.param}
                    </Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="值 (value)">
                    <Text copyable style={{ wordBreak: 'break-all' }}>
                      {column.value}
                    </Text>
                  </Descriptions.Item>
                </Descriptions>
              ),
            }))}
          />
        ) : (
          <p>暂无栏目详情数据</p>
        )}
      </Drawer>
    </div>
  );
};

export default JournalDetail;
