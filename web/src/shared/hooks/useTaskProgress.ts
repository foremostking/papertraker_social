/**
 * 任务进度管理 Hook
 *
 * 提供任务状态跟踪、WebSocket 实时进度更新、任务取消等功能
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { Task, TaskWebSocketMessage } from '../types';
import { connectTaskProgress, getTaskStatus, cancelTask as cancelTaskAPI } from '../services/api';
import { message } from 'antd';

interface UseTaskProgressOptions {
  onCompleted?: (task: Task) => void;
  onError?: (task: Task) => void;
  autoReconnect?: boolean;
}

export const useTaskProgress = (taskId: string, options: UseTaskProgressOptions = {}) => {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();

  const { onCompleted, onError, autoReconnect = true } = options;

  // 初始加载任务状态
  const fetchTask = useCallback(async () => {
    try {
      const data = await getTaskStatus(taskId);
      setTask(data);
      setLoading(false);
      return data;
    } catch (error: any) {
      message.error(error.detail || '加载任务状态失败');
      setLoading(false);
      return null;
    }
  }, [taskId]);

  // 连接 WebSocket
  const connect = useCallback(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      message.error('未登录');
      return;
    }

    socketRef.current = connectTaskProgress(taskId, token, {
      onMessage: (wsMessage: TaskWebSocketMessage) => {
        setTask(prev => ({
          ...prev,
          ...wsMessage,
        } as Task));

        // 任务完成或失败时的回调
        if (wsMessage.status === 'SUCCESS' && onCompleted) {
          setTask(prev => {
            if (prev) onCompleted(prev);
            return prev;
          });
        } else if (wsMessage.status === 'FAILURE' && onError) {
          setTask(prev => {
            if (prev) onError(prev);
            return prev;
          });
        }
      },
      onError: () => {
        if (autoReconnect && task?.status === 'STARTED') {
          // 3秒后重连
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('Reconnecting WebSocket...');
            connect();
          }, 3000);
        }
      },
      onClose: () => {
        // 清除重连定时器
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
      },
    });
  }, [taskId, task, autoReconnect, onCompleted, onError]);

  // 取消任务
  const cancelTaskFn = useCallback(async () => {
    try {
      await cancelTaskAPI(taskId);
      setTask(prev => prev ? { ...prev, status: 'REVOKED' } : null);
      message.success('任务已取消');
    } catch (error: any) {
      message.error(error.detail || '取消任务失败');
    }
  }, [taskId]);

  // 初始化
  useEffect(() => {
    let mounted = true;

    const initialize = async () => {
      const data = await fetchTask();
      if (!mounted) return;

      // 如果任务还在运行，连接 WebSocket
      if (data && ['PENDING', 'STARTED'].includes(data.status)) {
        connect();
      }
    };

    initialize();

    return () => {
      mounted = false;
      // 清理
      if (socketRef.current) {
        socketRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [fetchTask, connect]);

  return {
    task,
    loading,
    cancel: cancelTaskFn,
    refetch: fetchTask,
  };
};
