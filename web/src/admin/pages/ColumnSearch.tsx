/**
 * 栏目搜索页面
 *
 * 功能：
 * - 按栏目名称搜索所有期刊
 * - 展示栏目使用统计
 * - 支持跳转到期刊详情
 */

import React, { useState } from 'react';
import {
  Card,
  Input,
  Button,
  Table,
  Tag,
  Space,
  Typography,
  Empty,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ColumnSearchResult } from '@/shared/types';
import { getAllColumns } from '@/shared/services/api';

const { Title, Text } = Typography;

export const ColumnSearch = () => {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ColumnSearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [hasSearched, setHasSearched] = useState(false);

  const handleSearch = async () => {
    if (!search.trim()) {
      message.warning('请输入搜索关键词');
      return;
    }

    setLoading(true);
    setHasSearched(true);
    try {
      const data = await getAllColumns(search, 100);
      setResults(data.columns);
      setTotal(data.total);
    } catch (error: any) {
      message.error(error.detail || '搜索失败');
    } finally {
      setLoading(false);
    }
  };

  const expandedRowRender = (record: ColumnSearchResult) => (
    <Table
      dataSource={record.journals}
      columns={[
        {
          title: '期刊名称',
          dataIndex: 'journal_name',
          key: 'journal_name',
          render: (text: string) => <strong>{text}</strong>,
        },
        {
          title: '参数',
          dataIndex: 'param',
          key: 'param',
          render: (text: string) => <Tag color="blue">{text}</Tag>,
        },
        {
          title: '值',
          dataIndex: 'value',
          key: 'value',
          ellipsis: true,
        },
        {
          title: '操作',
          key: 'action',
          render: (_: any, journal: any) => (
            <Button
              type="link"
              size="small"
              onClick={() => navigate(`/admin/journals/${journal.journal_id}`)}
            >
              查看期刊
            </Button>
          ),
        },
      ]}
      pagination={false}
      rowKey="journal_id"
      size="small"
    />
  );

  const columns = [
    {
      title: '栏目名称',
      dataIndex: 'title',
      key: 'title',
      render: (text: string) => <strong>{text}</strong>,
    },
    {
      title: '期刊数量',
      dataIndex: 'journal_count',
      key: 'journal_count',
      render: (count: number) => <Tag color="blue">{count} 个期刊</Tag>,
    },
  ];

  return (
    <div>
      <Title level={4}>栏目搜索</Title>
      <Text type="secondary">
        搜索期刊栏目，查找包含特定栏目的所有期刊
      </Text>

      <Card style={{ marginTop: 16, marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="输入栏目名称搜索，如：理论研究、实证研究、案例分析..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onPressEnter={handleSearch}
            size="large"
            allowClear
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleSearch}
            loading={loading}
            size="large"
          >
            搜索
          </Button>
        </Space.Compact>
      </Card>

      {hasSearched && (
        <Card>
          {total > 0 ? (
            <>
              <p style={{ marginBottom: 16 }}>
                找到 <strong>{total}</strong> 个栏目，涉及{' '}
                <strong>
                  {results.reduce((sum, r) => sum + r.journal_count, 0)}
                </strong>{' '}
                个期刊
              </p>

              <Table
                dataSource={results}
                rowKey="title"
                expandable={{
                  expandedRowRender,
                  defaultExpandedRowKeys: [],
                }}
                columns={columns}
                pagination={{ pageSize: 20 }}
              />
            </>
          ) : (
            <Empty description="未找到匹配的栏目" />
          )}
        </Card>
      )}
    </div>
  );
};
