/**
 * 期刊列表页面
 *
 * 支持筛选、分页、搜索
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  Table,
  Card,
  Input,
  Select,
  Button,
  Space,
  Tag,
  Spin,
  message,
  Modal,
  Progress,
  Popconfirm,
} from 'antd';
import { SearchOutlined, ReloadOutlined, CloudDownloadOutlined, SyncOutlined, DeleteOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import { getJournals, getJournalStats, updateJournalCNKIDetails, batchUpdateJournalCNKIDetails, deleteJournal } from '../../../shared/services/api';
import type { Journal, JournalListParams } from '../../../shared/types';
import { formatImpactFactor } from '../../../shared/services/api';

const { Search } = Input;
const { Option } = Select;

/**
 * 导航状态类型
 */
interface NavigationState {
  params?: JournalListParams;
  searchKeyword?: string;
}

/**
 * 期刊列表页面
 */
export const JournalList: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [journals, setJournals] = useState<Journal[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [fields, setFields] = useState<string[]>([]);

  // 查询参数 - 初始化时检查是否有保存的状态
  const getInitialParams = (): JournalListParams => {
    const state = location.state as NavigationState;
    const savedParams = state?.params;
    return {
      skip: savedParams?.skip ?? 0,
      limit: savedParams?.limit ?? 20,
      search: savedParams?.search,
      field: savedParams?.field,
      is_cssci: savedParams?.is_cssci,
    };
  };

  const [params, setParams] = useState<JournalListParams>(getInitialParams());

  // 搜索关键词
  const [searchKeyword, setSearchKeyword] = useState(() => {
    const state = location.state as NavigationState;
    return state?.searchKeyword || '';
  });

  // CNKI 更新状态
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [batchUpdating, setBatchUpdating] = useState(false);
  const [batchUpdateModalVisible, setBatchUpdateModalVisible] = useState(false);
  const [batchUpdateProgress, setBatchUpdateProgress] = useState({ current: 0, total: 0 });
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // 初始化
  useEffect(() => {
    fetchFields();
  }, []);

  // 当params变化时获取期刊列表
  useEffect(() => {
    fetchJournals();
  }, [params]);

  const fetchJournals = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getJournals(params);
      setJournals(data.journals);
      setTotal(data.total);
    } catch (error: any) {
      message.error(error.detail || '加载期刊列表失败');
    } finally {
      setLoading(false);
    }
  }, [params]); // 依赖 params，确保使用最新值

  const fetchFields = async () => {
    try {
      const stats = await getJournalStats();
      setFields(Object.keys(stats.by_field || {}).sort());
    } catch (error) {
      console.error('Failed to fetch fields:', error);
    }
  };

  const handleSearch = (value: string) => {
    setParams({
      ...params,
      search: value || undefined,
      skip: 0,
    });
  };

  const handleFieldChange = (value: string | null) => {
    setParams({
      ...params,
      field: value || undefined,
      skip: 0,
    });
  };

  const handleCssciChange = (value: string | null) => {
    setParams({
      ...params,
      is_cssci: value === 'true' ? true : value === 'false' ? false : undefined,
      skip: 0,
    });
  };

  const handleTableChange = (pagination: any) => {
    setParams({
      ...params,
      skip: (pagination.current - 1) * pagination.pageSize,
      limit: pagination.pageSize,
    });
  };

  // 单个期刊更新 CNKI 详情
  const handleUpdateSingle = async (id: number) => {
    try {
      setUpdatingId(id);
      await updateJournalCNKIDetails(id);
      message.success('CNKI 详情更新成功');
      fetchJournals(); // 刷新列表
    } catch (error: any) {
      message.error(error.detail || '更新失败');
    } finally {
      setUpdatingId(null);
    }
  };

  // 批量更新 CNKI 详情
  const handleBatchUpdate = async () => {
    setBatchUpdateModalVisible(true);
    setBatchUpdating(true);
    setBatchUpdateProgress({ current: 0, total: total });

    try {
      const result = await batchUpdateJournalCNKIDetails({ limit: 100 });
      setBatchUpdateProgress({ current: result.stats.success, total: result.stats.total });

      message.success(
        `批量更新完成！成功: ${result.stats.success}, 失败: ${result.stats.failed}`
      );
      fetchJournals(); // 刷新列表
    } catch (error: any) {
      message.error(error.detail || '批量更新失败');
    } finally {
      setBatchUpdating(false);
      // 延迟关闭弹窗
      setTimeout(() => setBatchUpdateModalVisible(false), 2000);
    }
  };

  // 删除期刊
  const handleDelete = async (id: number) => {
    try {
      setDeletingId(id);
      await deleteJournal(id);
      message.success('期刊删除成功');
      fetchJournals(); // 刷新列表
    } catch (error: any) {
      message.error(error.detail || '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  const columns: ColumnsType<Journal> = [
    {
      title: '期刊名称',
      dataIndex: 'name',
      key: 'name',
      width: 250,
      fixed: 'left',
      render: (text: string, record: Journal) => (
        <a
          onClick={() => {
            const state: NavigationState = {
              params,
              searchKeyword,
            };
            navigate(`/admin/journals/${record.id}`, { state });
          }}
          style={{ fontWeight: 500 }}
        >
          {text}
        </a>
      ),
    },
    {
      title: 'ISSN',
      dataIndex: 'issn',
      key: 'issn',
      width: 120,
      render: (text) => text || '-',
    },
    {
      title: 'CN',
      dataIndex: 'cn',
      key: 'cn',
      width: 100,
      render: (text) => text || '-',
    },
    {
      title: '学科',
      dataIndex: 'field',
      key: 'field',
      width: 120,
      render: (text) => text || '-',
    },
    {
      title: '复合影响因子',
      dataIndex: 'composite_impact_factor',
      key: 'composite_impact_factor',
      width: 130,
      sorter: (a: Journal, b: Journal) =>
        (a.composite_impact_factor || 0) - (b.composite_impact_factor || 0),
      render: (value) => formatImpactFactor(value),
    },
    {
      title: '综合影响因子',
      dataIndex: 'comprehensive_impact_factor',
      key: 'comprehensive_impact_factor',
      width: 130,
      sorter: (a: Journal, b: Journal) =>
        (a.comprehensive_impact_factor || 0) - (b.comprehensive_impact_factor || 0),
      render: (value) => formatImpactFactor(value),
    },
    {
      title: '主办单位',
      dataIndex: 'publisher',
      key: 'publisher',
      width: 200,
      ellipsis: true,
      render: (text) => text || '-',
    },
    {
      title: '级别',
      key: 'level',
      width: 150,
      render: (_, record: Journal) => (
        <Space size={4}>
          {record.is_cssci && <Tag color="green">CSSCI</Tag>}
          {record.is_cssci_expansion && <Tag color="lime">CSSCI扩展</Tag>}
          {record.is_beida_core && <Tag color="purple">北大核心</Tag>}
          {!record.is_cssci && !record.is_cssci_expansion && !record.is_beida_core && '-'}
        </Space>
      ),
    },
    {
      title: '出版模式',
      key: 'publishing',
      width: 120,
      render: (_, record: Journal) => (
        <Space size={4}>
          {record.is_network_first && <Tag color="blue">网络首发</Tag>}
          {record.is_enhanced_publishing && <Tag color="cyan">增强出版</Tag>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right',
      render: (_, record: Journal) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<SyncOutlined spin={updatingId === record.id} />}
            onClick={() => handleUpdateSingle(record.id)}
            disabled={updatingId !== null}
          >
            更新
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => {
              const state: NavigationState = {
                params,
                searchKeyword,
              };
              navigate(`/admin/journals/${record.id}`, { state });
            }}
          >
            查看
          </Button>
          <Popconfirm
            title="确认删除"
            description={`确定要删除期刊《${record.name}》吗？此操作不可恢复。`}
            onConfirm={() => handleDelete(record.id)}
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deletingId === record.id}
              disabled={deletingId !== null}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space size="middle" wrap>
          <Search
            placeholder="搜索期刊名称"
            allowClear
            style={{ width: 250 }}
            onSearch={handleSearch}
            enterButton={<SearchOutlined />}
          />
          <Select
            placeholder="选择学科"
            allowClear
            style={{ width: 150 }}
            onChange={handleFieldChange}
            value={params.field}
          >
            {fields.map((field) => (
              <Option key={field} value={field}>
                {field}
              </Option>
            ))}
          </Select>
          <Select
            placeholder="期刊级别"
            allowClear
            style={{ width: 150 }}
            onChange={handleCssciChange}
          >
            <Option value="true">CSSCI来源期刊</Option>
            <Option value="false">非CSSCI</Option>
          </Select>
          <Button icon={<ReloadOutlined />} onClick={fetchJournals}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<CloudDownloadOutlined />}
            onClick={handleBatchUpdate}
            loading={batchUpdating}
          >
            批量更新 CNKI 详情
          </Button>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={journals}
        rowKey="id"
        loading={loading}
        scroll={{ x: 1500 }}
        pagination={{
          current: Math.floor(params.skip / (params.limit || 20)) + 1,
          pageSize: params.limit || 20,
          total,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (t) => `共 ${t} 条`,
          pageSizeOptions: [10, 20, 50, 100],
        }}
        onChange={handleTableChange}
      />

      {/* 批量更新进度弹窗 */}
      <Modal
        title="批量更新 CNKI 详情"
        open={batchUpdateModalVisible}
        onCancel={() => setBatchUpdateModalVisible(false)}
        footer={null}
        closable={!batchUpdating}
        mask={{ closable: !batchUpdating }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          {batchUpdating ? (
            <>
              <Spin tip="正在更新中，请稍候..." />
              <Progress
                percent={Math.round((batchUpdateProgress.current / batchUpdateProgress.total) * 100)}
                status="active"
              />
              <p style={{ textAlign: 'center', color: '#666' }}>
                已完成 {batchUpdateProgress.current} / {batchUpdateProgress.total}
              </p>
            </>
          ) : (
            <p style={{ textAlign: 'center' }}>
              更新完成！
            </p>
          )}
        </Space>
      </Modal>
    </div>
  );
};

export default JournalList;
