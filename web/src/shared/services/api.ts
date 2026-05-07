/**
 * API服务层
 *
 * 封装所有后端API调用
 */

import axios from 'axios';
import type { AxiosInstance, AxiosError } from 'axios';
import type {
  Journal,
  JournalListResponse,
  JournalListParams,
  JournalStats,
  JournalFramework,
  ApiError,
  JournalColumnDetail,
  ColumnSearchResult,
  Task,
  TaskStatus,
  TaskType,
  CreateTaskRequest,
  TaskProgress,
  TaskWebSocketMessage,
} from '../types';

// ============= API配置 =============

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// 创建axios实例
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    // 可以在这里添加认证token
    // const token = localStorage.getItem('token');
    // if (token) {
    //   config.headers.Authorization = `Bearer ${token}`;
    // }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiError>) => {
    // 统一错误处理
    if (error.response) {
      console.error('API Error:', error.response.data);
      return Promise.reject(error.response.data);
    } else if (error.request) {
      console.error('Network Error:', error.message);
      return Promise.reject({ detail: '网络错误，请检查连接' });
    }
    return Promise.reject({ detail: error.message });
  }
);

// ============= 期刊API =============

/**
 * 获取期刊列表
 */
export async function getJournals(params?: JournalListParams): Promise<JournalListResponse> {
  const response = await apiClient.get<JournalListResponse>('/api/journals/', { params });
  return response.data;
}

/**
 * 获取期刊详情
 */
export async function getJournalById(id: number): Promise<Journal> {
  const response = await apiClient.get<Journal>(`/api/journals/${id}`);
  return response.data;
}

/**
 * 搜索期刊
 */
export async function searchJournals(keyword: string, limit: number = 20): Promise<Journal[]> {
  const response = await apiClient.get<Journal[]>('/api/journals/search', {
    params: { keyword, limit },
  });
  return response.data;
}

/**
 * 获取期刊统计信息
 */
export async function getJournalStats(): Promise<JournalStats> {
  const response = await apiClient.get<JournalStats>('/api/journals/stats');
  return response.data;
}

/**
 * 获取按学科分组的期刊
 */
export async function getJournalsByField(field: string): Promise<Journal[]> {
  const response = await apiClient.get<Journal[]>(`/api/journals/field/${field}`);
  return response.data;
}

/**
 * 获取期刊框架
 */
export async function getJournalFrameworks(journalId: number): Promise<JournalFramework[]> {
  const response = await apiClient.get<JournalFramework[]>(`/api/journals/${journalId}/frameworks`);
  return response.data;
}

/**
 * 创建期刊
 */
export async function createJournal(data: Partial<Journal>): Promise<Journal> {
  const response = await apiClient.post<Journal>('/api/journals/', data);
  return response.data;
}

/**
 * 更新期刊
 */
export async function updateJournal(id: number, data: Partial<Journal>): Promise<Journal> {
  const response = await apiClient.put<Journal>(`/api/journals/${id}`, data);
  return response.data;
}

/**
 * 删除期刊
 */
export async function deleteJournal(id: number): Promise<void> {
  await apiClient.delete(`/api/journals/${id}`);
}

/**
 * 更新单个期刊的 CNKI 详情
 */
export async function updateJournalCNKIDetails(id: number): Promise<Journal> {
  const response = await apiClient.post<Journal>(`/api/journals/${id}/update-cnki-details`);
  return response.data;
}

/**
 * 批量更新期刊 CNKI 详情
 */
export async function batchUpdateJournalCNKIDetails(params?: {
  limit?: number;
  force?: boolean;
  skip_days?: number;
}): Promise<{ message: string; stats: { total: number; success: number; failed: number; skipped?: number } }> {
  const response = await apiClient.post('/api/journals/update-cnki-batch', null, { params });
  return response.data;
}

// ============= 框架API（预留） =============

/**
 * 获取框架列表
 */
export async function getFrameworks(params?: {
  journal_id?: number;
  skip?: number;
  limit?: number;
}): Promise<{ total: number; frameworks: JournalFramework[] }> {
  const response = await apiClient.get('/api/frameworks/', { params });
  return response.data;
}

/**
 * 获取框架详情
 */
export async function getFrameworkById(id: number): Promise<JournalFramework> {
  const response = await apiClient.get<JournalFramework>(`/api/frameworks/${id}`);
  return response.data;
}

// ============= 统计API =============

/**
 * 获取概览统计
 */
export async function getOverviewStats(): Promise<{
  total_journals: number;
  cssci_journals: number;
  journals_with_frameworks: number;
  new_this_month: number;
}> {
  const response = await apiClient.get('/api/statistics/overview');
  return response.data;
}

/**
 * 获取学科分布统计
 */
export async function getFieldDistribution(): Promise<Array<{ field: string; count: number }>> {
  const response = await apiClient.get('/api/statistics/fields');
  return response.data;
}

/**
 * 获取影响因子分布
 */
export async function getImpactFactorDistribution(): Promise<Array<{
  range: string;
  count: number;
}>> {
  const response = await apiClient.get('/api/statistics/impact-factors');
  return response.data;
}

// ============= 栏目管理API =============

/**
 * 获取所有栏目列表（支持搜索）
 */
export async function getAllColumns(
  search?: string,
  limit: number = 100
): Promise<{ total: number; columns: ColumnSearchResult[] }> {
  const response = await apiClient.get('/api/journals/columns/all', {
    params: { search, limit },
  });
  return response.data;
}

/**
 * 更新期刊栏目数据
 */
export async function updateJournalColumns(
  journalId: number,
  data: {
    columns?: string[];
    columns_detail?: JournalColumnDetail[];
  }
): Promise<{ message: string }> {
  const response = await apiClient.put(`/api/journals/${journalId}/columns`, data);
  return response.data;
}

/**
 * 刷新期刊栏目（创建任务）
 */
export async function refreshJournalColumns(
  journalId: number
): Promise<{ task_id: string; message: string; journal_name: string }> {
  const response = await apiClient.post(`/api/journals/${journalId}/columns/refresh`);
  return response.data;
}

// ============= 任务管理API =============

/**
 * 创建新任务
 */
export async function createTask(
  request: CreateTaskRequest
): Promise<{ task_id: string; status: string; message: string }> {
  const response = await apiClient.post('/api/tasks/', request);
  return response.data;
}

/**
 * 获取任务状态
 */
export async function getTaskStatus(taskId: string): Promise<Task> {
  const response = await apiClient.get<Task>(`/api/tasks/${taskId}`);
  return response.data;
}

/**
 * 获取任务列表
 */
export async function listTasks(
  status?: string,
  limit: number = 20,
  offset: number = 0
): Promise<Task[]> {
  const response = await apiClient.get<Task[]>('/api/tasks/', {
    params: { status, limit, offset },
  });
  return response.data;
}

/**
 * 取消任务
 */
export async function cancelTask(
  taskId: string
): Promise<{ message: string; task_id: string }> {
  const response = await apiClient.post(`/api/tasks/${taskId}/cancel`);
  return response.data;
}

/**
 * 删除任务记录
 */
export async function deleteTask(taskId: string): Promise<{ message: string }> {
  const response = await apiClient.delete(`/api/tasks/${taskId}`);
  return response.data;
}

// ============= WebSocket 连接 =============

/**
 * 连接任务进度 WebSocket
 *
 * @param taskId 任务ID
 * @param token JWT认证token
 * @param callbacks 回调函数
 * @returns WebSocket实例
 */
export function connectTaskProgress(
  taskId: string,
  token: string,
  callbacks: {
    onMessage: (message: TaskWebSocketMessage) => void;
    onError?: (event: Event) => void;
    onClose?: () => void;
  }
): WebSocket {
  const wsUrl = `ws://localhost:8000/ws/tasks/${taskId}?token=${token}`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log(`WebSocket connected for task ${taskId}`);
  };

  ws.onmessage = (event) => {
    try {
      const message: TaskWebSocketMessage = JSON.parse(event.data);
      callbacks.onMessage(message);
    } catch (error) {
      console.error('Failed to parse WebSocket message:', error);
    }
  };

  ws.onerror = (event) => {
    console.error('WebSocket error:', event);
    callbacks.onError?.(event);
  };

  ws.onclose = () => {
    console.log(`WebSocket closed for task ${taskId}`);
    callbacks.onClose?.();
  };

  return ws;
}

// ============= 工具函数 =============

/**
 * 格式化日期
 */
export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('zh-CN');
}

/**
 * 格式化影响因子
 */
export function formatImpactFactor(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  return value.toFixed(3);
}

/**
 * 导出API客户端
 */
export { apiClient };
