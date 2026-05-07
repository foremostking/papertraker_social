/**
 * 论文获取组件
 *
 * 功能：
 * - 选择期刊栏目
 * - 配置获取选项
 * - 创建获取任务
 * - 实时显示进度
 */

import React, { useState } from 'react';
import {
  Button,
  Card,
  Checkbox,
  Space,
  Alert,
  Modal,
  Progress,
  Tag,
  InputNumber,
  message,
} from 'antd';
import { PlayCircleOutlined, CloseOutlined } from '@ant-design/icons';
import type { Journal } from '@/shared/types';
import { createTask } from '@/shared/services/api';
import { useTaskProgress } from '@/shared/hooks/useTaskProgress';

interface PaperFetcherProps {
  journal: Journal;
}

export const PaperFetcher: React.FC<PaperFetcherProps> = ({ journal }) => {
  const [selectedColumns, setSelectedColumns] = useState<string[]>([]);
  const [fetching, setFetching] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [fetchDetails, setFetchDetails] = useState(false);
  const [maxPapers, setMaxPapers] = useState(500);

  const { task, loading } = useTaskProgress(taskId || '', {
    onCompleted: (t) => {
      setFetching(false);
      const paperCount = t.result?.papers_fetched || 0;
      const skipped = t.result?.papers_skipped || 0;
      message.success(
        `获取完成！共 ${paperCount} 篇论文` +
          (skipped > 0 ? `，跳过 ${skipped} 篇重复论文` : '')
      );
    },
    onError: (t) => {
      setFetching(false);
      message.error(`获取失败: ${t.error}`);
    },
  });

  const handleStart = async () => {
    if (!journal.journal_code) {
      message.error('该期刊没有 journal_code，无法获取论文');
      return;
    }

    if (selectedColumns.length === 0) {
      message.warning('请选择要获取论文的栏目');
      return;
    }

    setFetching(true);
    setModalVisible(true);

    try {
      // 为第一个栏目创建任务
      const firstColumn = selectedColumns[0];
      const response = await createTask({
        type: 'fetch_papers',
        params: {
          journal_id: journal.id,
          column_name: firstColumn,
          fetch_details: fetchDetails,
          max_papers: maxPapers,
        },
        priority: 5,
        name: `获取 ${journal.name} - ${firstColumn} 的论文`,
      });

      setTaskId(response.task_id);
    } catch (error: any) {
      message.error(error.detail || '创建任务失败');
      setFetching(false);
      setModalVisible(false);
    }
  };

  const handleCancel = async () => {
    if (task) {
      await task.cancel?.();
      setFetching(false);
      setModalVisible(false);
      setTaskId(null);
    }
  };

  if (!journal.journal_code) {
    return (
      <Alert
        message="无法获取论文"
        description="该期刊没有 journal_code，请先刷新期刊信息"
        type="warning"
        showIcon
      />
    );
  }

  const calculateProgress = () => {
    if (!task?.progress) return 0;
    const { current, total } = task.progress;
    if (typeof total !== 'number') return 0;
    return Math.round((current / total) * 100);
  };

  return (
    <div>
      <Card title="选择栏目" size="small" style={{ marginBottom: 16 }}>
        <Checkbox.Group
          value={selectedColumns}
          onChange={(values) => setSelectedColumns(values as string[])}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            {journal.journal_columns?.map((col) => (
              <Checkbox key={col} value={col}>
                {col}
              </Checkbox>
            ))}
          </Space>
        </Checkbox.Group>
      </Card>

      <Card title="获取选项" size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical">
          <Checkbox
            checked={fetchDetails}
            onChange={(e) => setFetchDetails(e.target.checked)}
          >
            获取论文详情（耗时较长，暂未启用）
          </Checkbox>
          <div>
            <span>最大获取数量: </span>
            <InputNumber
              value={maxPapers}
              onChange={(value) => setMaxPapers(value || 500)}
              style={{ width: 120 }}
              min={1}
              max={5000}
            />
          </div>
        </Space>
      </Card>

      <Space>
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          disabled={!selectedColumns.length}
          loading={fetching}
          onClick={handleStart}
        >
          开始获取
        </Button>
        <span style={{ color: '#999' }}>
          已选择 {selectedColumns.length} 个栏目
        </span>
      </Space>

      {/* 进度弹窗 */}
      <Modal
        title="论文获取进度"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setModalVisible(false)}>
            关闭
          </Button>,
          task?.status === 'STARTED' && (
            <Button
              key="cancel"
              danger
              icon={<CloseOutlined />}
              onClick={handleCancel}
            >
              取消任务
            </Button>
          ),
        ]}
        width={600}
      >
        {loading && <div>加载中...</div>}

        {task && (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <div>
              <Tag
                color={
                  task.status === 'SUCCESS'
                    ? 'success'
                    : task.status === 'FAILURE'
                    ? 'error'
                    : task.status === 'REVOKED'
                    ? 'warning'
                    : 'processing'
                }
              >
                {task.status === 'PENDING' && '等待中'}
                {task.status === 'STARTED' && '进行中'}
                {task.status === 'SUCCESS' && '已完成'}
                {task.status === 'FAILURE' && '失败'}
                {task.status === 'REVOKED' && '已取消'}
              </Tag>
              <span style={{ marginLeft: 8 }}>{task.name}</span>
            </div>

            {task.progress && (
              <div>
                <Progress
                  percent={calculateProgress()}
                  status={task.status === 'FAILURE' ? 'exception' : 'active'}
                />
                <p style={{ marginTop: 8, color: '#666' }}>
                  {task.progress.message}
                </p>
                {task.progress.last_paper && (
                  <p style={{ fontSize: 12, color: '#999' }}>
                    最新: {task.progress.last_paper}
                  </p>
                )}
                <p>
                  已处理: {task.progress.current} / {task.progress.total}
                </p>
              </div>
            )}

            {task.status === 'SUCCESS' && task.result && (
              <Alert
                type="success"
                message="获取完成"
                description={`共获取 ${task.result.papers_fetched} 篇论文` +
                  (task.result.papers_skipped > 0
                    ? `，跳过 ${task.result.papers_skipped} 篇重复`
                    : '')}
              />
            )}

            {task.status === 'FAILURE' && task.error && (
              <Alert type="error" message="获取失败" description={task.error} />
            )}
          </Space>
        )}
      </Modal>
    </div>
  );
};
