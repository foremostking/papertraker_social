/**
 * 期刊栏目列表组件
 *
 * 功能：
 * - 展示期刊的所有栏目
 * - 支持编辑栏目信息
 * - 支持刷新栏目数据
 */

import React, { useState } from 'react';
import { Button, Space, Table, Modal, Form, Input, message, Tag } from 'antd';
import { ReloadOutlined, EditOutlined } from '@ant-design/icons';
import type { JournalColumnDetail } from '@/shared/types';
import { updateJournalColumns } from '@/shared/services/api';

interface ColumnListProps {
  journalId: number;
  journalName: string;
  columns: string[];
  columnsDetail: JournalColumnDetail[];
  onRefresh: () => void;
  loading?: boolean;
}

export const ColumnList: React.FC<ColumnListProps> = ({
  journalId,
  journalName,
  columns,
  columnsDetail,
  onRefresh,
  loading,
}) => {
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [selectedColumn, setSelectedColumn] = useState<JournalColumnDetail | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      // 更新 columns_detail
      const updatedDetails = columnsDetail.map(col =>
        col.param === selectedColumn?.param
          ? { ...col, ...values }
          : col
      );

      // 同时更新 columns 数组
      const updatedColumns = updatedDetails.map(c => c.title);

      await updateJournalColumns(journalId, {
        columns: updatedColumns,
        columns_detail: updatedDetails,
      });

      message.success('栏目已更新');
      setEditModalVisible(false);
      onRefresh();
    } catch (error: any) {
      message.error(error.detail || '更新失败');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (record: JournalColumnDetail) => {
    setSelectedColumn(record);
    form.setFieldsValue(record);
    setEditModalVisible(true);
  };

  const tableColumns = [
    {
      title: '参数',
      dataIndex: 'param',
      key: 'param',
      width: 120,
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: '栏目名称',
      dataIndex: 'title',
      key: 'title',
      render: (text: string) => <strong>{text}</strong>,
    },
    {
      title: '值',
      dataIndex: 'value',
      key: 'value',
      ellipsis: true,
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: any, record: JournalColumnDetail) => (
        <Button
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => handleEdit(record)}
        >
          编辑
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button
          icon={<ReloadOutlined />}
          onClick={onRefresh}
          loading={loading}
        >
          刷新栏目
        </Button>
        <span style={{ color: '#999' }}>
          共 {columnsDetail.length} 个栏目
        </span>
      </Space>

      <Table
        dataSource={columnsDetail}
        rowKey="param"
        columns={tableColumns}
        pagination={false}
        size="small"
      />

      <Modal
        title="编辑栏目"
        open={editModalVisible}
        onOk={handleSave}
        onCancel={() => setEditModalVisible(false)}
        confirmLoading={saving}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="栏目名称"
            name="title"
            rules={[{ required: true, message: '请输入栏目名称' }]}
          >
            <Input placeholder="请输入栏目名称" />
          </Form.Item>
          <Form.Item label="参数" name="param">
            <Input disabled />
          </Form.Item>
          <Form.Item label="值" name="value">
            <Input.TextArea rows={3} placeholder="请输入值" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
