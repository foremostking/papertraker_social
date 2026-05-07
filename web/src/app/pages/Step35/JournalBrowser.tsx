/**
 * 步骤3.5：期刊框架学习 - 期刊浏览器
 *
 * 用户可以浏览和搜索期刊，查看期刊的论文框架
 */

import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Input, Select, Tag, Spin, Empty, Pagination } from 'antd';
import { SearchOutlined, BookOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getJournals, getJournalStats } from '../../../shared/services/api';
import type { Journal } from '../../../shared/types';
import { formatImpactFactor } from '../../../shared/services/api';

const { Search } = Input;
const { Option } = Select;

/**
 * 期刊浏览器页面
 */
export const JournalBrowser: React.FC = () => {
  const navigate = useNavigate();
  const [journals, setJournals] = useState<Journal[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [fields, setFields] = useState<string[]>([]);

  // 查询参数
  const [params, setParams] = useState<{
    skip: number;
    limit: number;
    search?: string;
    field?: string;
    is_cssci?: boolean;
  }>({
    skip: 0,
    limit: 12,
  });

  useEffect(() => {
    fetchJournals();
    fetchFields();
  }, [params]);

  const fetchJournals = async () => {
    try {
      setLoading(true);
      const data = await getJournals(params);
      setJournals(data.journals);
      setTotal(data.total);
    } catch (error) {
      console.error('Failed to fetch journals:', error);
    } finally {
      setLoading(false);
    }
  };

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

  const handlePageChange = (page: number, pageSize: number) => {
    setParams({
      ...params,
      skip: (page - 1) * pageSize,
      limit: pageSize,
    });
  };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>步骤3.5：期刊框架学习</h2>
        <p style={{ color: '#666', marginTop: 8 }}>
          浏览目标期刊的已发表论文框架，学习该期刊的论文结构和写作风格
        </p>
      </div>

      {/* 进度指示 */}
      <Card style={{ marginBottom: 24, backgroundColor: '#f0f5ff', borderColor: '#adc6ff' }}>
        <Row align="middle">
          <Col>
            <BookOutlined style={{ fontSize: 24, color: '#1890ff', marginRight: 12 }} />
          </Col>
          <Col flex="1">
            <div style={{ fontSize: 16, fontWeight: 500, color: '#1890ff' }}>
              论文写作进度：3/7
            </div>
            <div style={{ fontSize: 14, color: '#666', marginTop: 4 }}>
              当前阶段：期刊框架学习
            </div>
          </Col>
        </Row>
      </Card>

      {/* 筛选工具栏 */}
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={16}>
          <Col xs={24} md={8}>
            <Search
              placeholder="搜索期刊名称"
              allowClear
              onSearch={handleSearch}
              enterButton={<SearchOutlined />}
            />
          </Col>
          <Col xs={24} md={6}>
            <Select
              placeholder="选择学科"
              allowClear
              style={{ width: '100%' }}
              onChange={handleFieldChange}
              value={params.field}
            >
              {fields.map((field) => (
                <Option key={field} value={field}>
                  {field}
                </Option>
              ))}
            </Select>
          </Col>
          <Col xs={24} md={6}>
            <Select
              placeholder="期刊级别"
              allowClear
              style={{ width: '100%' }}
              onChange={(value) =>
                setParams({
                  ...params,
                  is_cssci: value === 'cssci' ? true : undefined,
                })
              }
            >
              <Option value="cssci">CSSCI来源期刊</Option>
            </Select>
          </Col>
        </Row>
      </Card>

      {/* 期刊列表 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '50px' }}>
          <Spin size="large" />
        </div>
      ) : journals.length === 0 ? (
        <Empty description="暂无期刊数据" />
      ) : (
        <>
          <Row gutter={[16, 16]}>
            {journals.map((journal) => (
              <Col xs={24} sm={12} md={8} lg={6} key={journal.id}>
                <Card
                  hoverable
                  onClick={() => navigate(`/step3.5/frameworks/${journal.id}`)}
                  style={{ height: '100%' }}
                  bodyStyle={{ padding: 16 }}
                >
                  <div style={{ marginBottom: 12 }}>
                    <div
                      style={{
                        fontSize: 15,
                        fontWeight: 600,
                        color: '#1890ff',
                        marginBottom: 8,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {journal.name}
                    </div>
                    {journal.field && (
                      <Tag color="blue" style={{ marginBottom: 4 }}>
                        {journal.field}
                      </Tag>
                    )}
                    {journal.is_cssci && <Tag color="green">CSSCI</Tag>}
                  </div>
                  <div style={{ fontSize: 12, color: '#666' }}>
                    {journal.composite_impact_factor && (
                      <div style={{ marginBottom: 4 }}>
                        复合IF: {formatImpactFactor(journal.composite_impact_factor)}
                      </div>
                    )}
                    {journal.publisher && (
                      <div
                        style={{
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {journal.publisher}
                      </div>
                    )}
                  </div>
                  {journal.framework_analyzed && (
                    <Tag color="success" style={{ marginTop: 8 }}>
                      已分析框架
                    </Tag>
                  )}
                </Card>
              </Col>
            ))}
          </Row>

          <div style={{ textAlign: 'center', marginTop: 24 }}>
            <Pagination
              current={Math.floor(params.skip / params.limit) + 1}
              pageSize={params.limit}
              total={total}
              onChange={handlePageChange}
              showSizeChanger
              showTotal={(t) => `共 ${t} 本期刊`}
              pageSizeOptions={[12, 24, 48]}
            />
          </div>
        </>
      )}
    </div>
  );
};

export default JournalBrowser;
