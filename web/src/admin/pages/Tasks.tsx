/**
 * 任务管理页面
 *
 * 功能：
 * - 查看任务列表
 * - 筛选任务状态
 * - 查看任务详情
 * - 取消/删除任务
 */

import React, { useState, useEffect } from 'react';
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Modal,
  Descriptions,
  Progress,
  message,
} from 'antd';
import {
  ReloadOutlined,
  DeleteOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import type { Task, TaskStatus } from '@/shared/types';
import { listTasks, cancelTask, deleteTask as deleteTaskAPI } from '@/shared/services/api';

const STATUS_COLORS: Record<TaskStatus, string> = {
  PENDING: 'default',
  STARTED: 'processing',
  SUCCESS: 'success',
  FAILURE: 'error',
  REVOKED: 'warning',
};

const STATUS_TEXT: Record<TaskStatus, string> = {
  PENDING: '等待中',
  STARTED: '进行中',
  SUCCESS: '已完成',
  FAILURE: '失败',
  REVOKED: '已取消',
};

const TYPE_TEXT: Record<string, string> = {
  fetch_columns: '获取栏目',
  batch_fetch_columns: '批量获取栏目',
  fetch_papers: '获取论文',
};

export const TasksPage = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<TaskStatus | ''>('');
  const [detailModal, setDetailModal] = useState(false);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const data = await listTasks(
        statusFilter || undefined,
        50,
        0
      );
      setTasks(data);
    } catch (error: any) {
      message.error(error.detail || '加载任务失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
  }, [statusFilter]);

  // 自动刷新（如果有进行中的任务）
  useEffect(() => {
    if (!autoRefresh) return;

    const hasRunning = tasks.some(
      (t) => t.status === 'STARTED' || t.status === 'PENDING'
    );

    if (hasRunning) {
      const interval = setInterval(() => {
        fetchTasks();
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [tasks, autoRefresh]);

  const handleCancel = async (taskId: string) => {
    Modal.confirm({
      title: '确认取消任务？',
      content: '取消后任务将停止执行，但已获取的数据不会丢失。',
      onOk: async () => {
        try {
          await cancelTask(taskId);
          message.success('任务已取消');
          fetchTasks();
        } catch (error: any) {
          message.error(error.detail || '取消失败');
        }
      },
    });
  };

  const handleDelete = async (taskId: string) => {
    Modal.confirm({
      title: '确认删除任务记录？',
      content: '删除后将无法恢复任务记录。',
      onOk: async () => {
        try {
          await deleteTaskAPI(taskId);
          message.success('任务已删除');
          fetchTasks();
        } catch (error: any) {
          message.error(error.detail || '删除失败');
        }
      },
    });
  };

  const handleViewDetail = (task: Task) => {
    setSelectedTask(task);
    setDetailModal(true);
  };

  const columns = [
    {
      title: '任务名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: Task) => (
        <Button
          type="link"
          style={{ padding: 0 }}
          onClick={() => handleViewDetail(record)}
        >
          {name}
        </Button>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      render: (type: string) => <Tag>{TYPE_TEXT[type] || type}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: TaskStatus) => (
        <Tag color={STATUS_COLORS[status]}>{STATUS_TEXT[status]}</Tag>
      ),
    },
    {
      title: '进度',
      key: 'progress',
      render: (_: any, record: Task) => {
        if (!record.progress) return '-';
        const percent =
          typeof record.progress.total === 'number'
            ? Math.round((record.progress.current / record.progress.total) * 100)
            : 0;
        return (
          <div style={{ width: 120 }}>
            <Progress
              percent={percent}
              size="small"
              status={record.status === 'FAILURE' ? 'exception' : undefined}
            />
          </div>
        );
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => new Date(date).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: Task) => (
        <Space size="small">
          {(record.status === 'PENDING' || record.status === 'STARTED') && (
            <Button
              size="small"
              icon={<CloseCircleOutlined />}
              onClick={() => handleCancel(record.id)}
            >
              取消
            </Button>
          )}
          {record.status !== 'PENDING' && record.status !== 'STARTED' && (
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => handleDelete(record.id)}
            >
              删除
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card
        title="任务管理"
        extra={
          <Space>
            <Button.Group>
              <Button
                type={statusFilter === '' ? 'primary' : 'default'}
                onClick={() => setStatusFilter('')}
              >
                全部
              </Button>
              <Button
                type={statusFilter === 'STARTED' ? 'primary' : 'default'}
                onClick={() => setStatusFilter('STARTED')}
              >
                进行中
              </Button>
              <Button
                type={statusFilter === 'SUCCESS' ? 'primary' : 'default'}
                onClick={() => setStatusFilter('SUCCESS')}
              >
                已完成
              </Button>
              <Button
                type={statusFilter === 'FAILURE' ? 'primary' : 'default'}
                onClick={() => setStatusFilter('FAILURE')}
              >
                失败
              </Button>
            </Button.Group>
            <Button icon={<ReloadOutlined />} onClick={fetchTasks}>
              刷新
            </Button>
          </Space>
        }
      >
        <Table
          dataSource={tasks}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {/* 任务详情弹窗 */}
      <Modal
        title="任务详情"
        open={detailModal}
        onCancel={() => setDetailModal(false)}
        footer={null}
        width={700}
      >
        {selectedTask && (
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="任务名称" span={2}>
              {selectedTask.name}
            </Descriptions.Item>
            <Descriptions.Item label="任务类型">
              {TYPE_TEXT[selectedTask.type] || selectedTask.type}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={STATUS_COLORS[selectedTask.status]}>
                {STATUS_TEXT[selectedTask.status]}
              </Tag>
            </Descriptions.Item>
            {selectedTask.progress && (
              <>
                <Descriptions.Item label="当前进度" span={2}>
                  <Progress
                    percent={
                      typeof selectedTask.progress.total === 'number'
                        ? Math.round(
                            (selectedTask.progress.current /
                              selectedTask.progress.total) *
                              100
                          )
                        : undefined
                    }
                  />
                  <p style={{ marginTop: 8 }}>
                    {selectedTask.progress.message}
                  </p>
                </Descriptions.Item>
              </>
            )}
            {selectedTask.result && (
              <Descriptions.Item label="结果" span={2}>
                <pre
                  style={{
                    maxHeight: 200,
                    overflow: 'auto',
                    background: '#f5f5f5',
                    padding: 8,
                    borderRadius: 4,
                  }}
                >
                  {JSON.stringify(selectedTask.result, null, 2)}
                </pre>
              </Descriptions.Item>
            )}
            {selectedTask.error && (
              <Descriptions.Item label="错误信息" span={2}>
                <pre
                  style={{
                    color: 'red',
                    maxHeight: 200,
                    overflow: 'auto',
                    background: '#fff2f0',
                    padding: 8,
                    borderRadius: 4,
                  }}
                >
                  {selectedTask.error}
                </pre>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="创建时间">
              {new Date(selectedTask.created_at).toLocaleString('zh-CN')}
            </Descriptions.Item>
            {selectedTask.started_at && (
              <Descriptions.Item label="开始时间">
                {new Date(selectedTask.started_at).toLocaleString('zh-CN')}
              </Descriptions.Item>
            )}
            {selectedTask.completed_at && (
              <Descriptions.Item label="完成时间">
                {new Date(selectedTask.completed_at).toLocaleString('zh-CN')}
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>
    </div>
  );
};
