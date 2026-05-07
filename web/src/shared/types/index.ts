/**
 * 共享TypeScript类型定义
 *
 * 与后端API模型保持一致
 */

// ============= 期刊相关类型 =============

/**
 * 期刊基础信息
 */
export interface Journal {
  id: number;
  name: string;
  name_en?: string;
  issn?: string;
  cn?: string;

  // 期刊级别
  is_cssci: boolean;
  is_cssci_expansion: boolean;
  is_beida_core: boolean;
  cssci_year?: number;

  // 学科分类
  field?: string;
  subfield?: string;

  // CNKI映射
  cnki_source_id?: string;
  cnki_url?: string;
  journal_code?: string;  // CNKI期刊代码

  // 联系方式
  official_url?: string;
  email?: string;

  // 框架分析状态
  framework_analyzed: boolean;
  total_papers: number;
  last_paper_date?: string;

  // 影响因子
  impact_factor?: number;  // 兼容旧数据
  composite_impact_factor?: number;  // 复合影响因子
  comprehensive_impact_factor?: number;  // 综合影响因子
  publisher?: string;

  // 出版模式标识
  is_network_first: boolean;  // 网络首发
  is_enhanced_publishing: boolean;  // 增强出版

  // 来源信息
  source?: string;
  detail_url?: string;

  // 时间戳
  created_at: string;
  updated_at: string;

  // CNKI 详情扩展字段
  publishing_cycle?: string;           // 出版周期
  publishing_location?: string;        // 出版地
  language?: string;                   // 语种
  format?: string;                     // 开本
  postal_code?: string;                // 邮发代号
  founded_year?: number;               // 创刊时间
  total_documents?: number;            // 出版文献量
  total_downloads?: number;            // 总下载次数
  total_citations?: number;            // 总被引次数
  journal_tags?: string[];             // 期刊标签
  journal_columns?: string[];          // 期刊固定栏目名称
  journal_columns_detail?: Array<{ param: string; title: string; value: string }>;  // 期刊栏目完整数据
  cnki_detail_last_updated?: string;   // CNKI详情最后更新时间
}

/**
 * 期刊列表响应
 */
export interface JournalListResponse {
  total: number;
  journals: Journal[];
}

/**
 * 期刊列表查询参数
 */
export interface JournalListParams {
  field?: string;
  is_cssci?: boolean;
  search?: string;
  skip?: number;
  limit?: number;
}

/**
 * 期刊统计信息
 */
export interface JournalStats {
  total_journals: number;
  cssci_journals: number;
  cssci_expansion_journals: number;
  beida_core_journals: number;
  journals_with_frameworks: number;
  by_field: Record<string, number>;
}

// ============= 论文框架相关类型 =============

/**
 * 论文框架结构
 */
export interface FrameworkStructure {
  level: number;
  title: string;
  children?: FrameworkStructure[];
}

/**
 * 期刊框架模式
 */
export interface JournalFramework {
  id: number;
  journal_id: number;
  pattern_name?: string;
  framework_structure: FrameworkStructure[];
  frequency: number;
  percentage: number;
  avg_chapters?: number;
  sample_paper_ids?: number[];
  last_updated: string;
  created_at: string;
}

/**
 * 论文实际结构
 */
export interface PaperStructure {
  id: number;
  literature_id?: number;
  journal_id: number;
  framework_id?: number;
  structure: FrameworkStructure[];
  chapter_count: number;
  word_counts?: Record<string, number>;
  extracted_at: string;
}

// ============= 文献相关类型 =============

/**
 * 文献/论文
 */
export interface Literature {
  id: number;
  title: string;
  authors?: string;
  journal_id?: number;
  journal_name?: string;
  year?: number;
  source?: string;
  abstract?: string;
  keywords?: string;
  citation_count?: number;
  is_cssci?: boolean;
  pdf_path?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

// ============= API响应类型 =============

/**
 * API错误响应
 */
export interface ApiError {
  detail: string;
  status_code?: number;
}

/**
 * 分页参数
 */
export interface PaginationParams {
  skip: number;
  limit: number;
}

/**
 * 分页响应
 */
export interface PaginationResponse<T> {
  total: number;
  items: T[];
  skip: number;
  limit: number;
}

// ============= 管理界面类型 =============

/**
 * 侧边栏菜单项
 */
export interface MenuItem {
  key: string;
  icon?: React.ReactNode;
  label: string;
  path?: string;
  children?: MenuItem[];
  disabled?: boolean;
}

/**
 * 统计卡片数据
 */
export interface StatCard {
  title: string;
  value: number | string;
  suffix?: string;
  prefix?: React.ReactNode;
  color?: string;
  trend?: {
    value: number;
    isUp: boolean;
  };
}

/**
 * 图表数据点
 */
export interface ChartDataPoint {
  name: string;
  value: number;
  [key: string]: any;
}

// ============= 用户界面类型 =============

/**
 * 步骤进度
 */
export interface StepProgress {
  current: number;
  total: number;
  title: string;
  completed: boolean;
}

/**
 * 框架推荐
 */
export interface FrameworkRecommend {
  framework: JournalFramework;
  journal: Journal;
  match_score: number;
  reason: string;
}


// ============= 栏目相关类型 =============

/**
 * 期刊栏目详情
 */
export interface JournalColumnDetail {
  param: string;
  title: string;
  value: string;
}

/**
 * 栏目搜索结果
 */
export interface ColumnSearchResult {
  title: string;
  journal_count: number;
  journals: Array<{
    journal_id: number;
    journal_name: string;
    param: string;
    value: string;
  }>;
}


// ============= 论文相关类型 =============

/**
 * 论文基本信息
 */
export interface PaperBasic {
  title: string;
  detail_url: string;
  authors?: string;
  year_issue?: string;
  citation_count: number;
  download_count: number;
}


// ============= 任务相关类型 =============

/**
 * 任务状态
 */
export type TaskStatus = 'PENDING' | 'STARTED' | 'SUCCESS' | 'FAILURE' | 'REVOKED';

/**
 * 任务类型
 */
export type TaskType = 'fetch_columns' | 'batch_fetch_columns' | 'fetch_papers';

/**
 * 任务进度
 */
export interface TaskProgress {
  current: number;
  total: number | string;
  message: string;
  current_item?: string;
  last_paper?: string;
}

/**
 * 任务
 */
export interface Task {
  id: string;
  type: TaskType;
  name: string;
  status: TaskStatus;
  priority: number;
  progress: TaskProgress | null;
  result: any;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/**
 * 创建任务请求
 */
export interface CreateTaskRequest {
  type: TaskType;
  params: {
    journal_id?: number;
    column_name?: string;
    limit?: number;
    fetch_details?: boolean;
    max_papers?: number;
  };
  priority?: number;
  name?: string;
}

/**
 * WebSocket 消息类型
 */
export interface TaskWebSocketMessage {
  task_id: string;
  status: TaskStatus;
  progress?: TaskProgress;
  result?: any;
  error?: string;
  completed_at?: string;
}
