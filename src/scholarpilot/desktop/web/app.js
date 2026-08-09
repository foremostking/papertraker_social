/* ══════════════════════════════════════════════════════════════════
   ScholarPilot 桌面应用 — 前端主逻辑
   ══════════════════════════════════════════════════════════════════
   架构：
     - State       全局状态
     - API         pywebview API 封装（返回 JSON 字符串 → JSON.parse）
     - Utils       工具函数（Toast / Modal / 格式化）
     - Markdown    marked.js 学术风格配置
     - Router      hash 路由
     - Pages       三个页面渲染器
     - Events      Python → JS 回调入口 onEvent()
     - Selection   划词工具栏
     - Comments    评论侧边栏
     - Logs        实时日志流
   ══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ════════════════════════════════════════════════════════════════
     Phase 定义 — 9 个步骤的元数据
     ════════════════════════════════════════════════════════════════ */
  const PHASES = [
    { id: 'topic_analysis',    name: '选题分析',   icon: 'target',   desc: '分析研究主题，确定论文方向' },
    { id: 'literature_search', name: '文献检索',   icon: 'book',     desc: '搜索和整理相关文献' },
    { id: 'evidence_matrix',   name: '证据矩阵',   icon: 'search',   desc: '构建文献证据矩阵' },
    { id: 'spec_generation',   name: '规格生成',   icon: 'clipboard',desc: '生成论文规格说明书' },
    { id: 'outline',           name: '大纲生成',   icon: 'edit',     desc: '构建论文章节大纲' },
    { id: 'data_collection',   name: '数据采集',   icon: 'chart',    desc: '采集实证研究数据' },
    { id: 'section_writing',   name: '逐章撰写',   icon: 'pen',      desc: '逐章生成论文内容' },
    { id: 'post_processing',   name: '后处理',     icon: 'tool',     desc: '润色、去AI痕迹、校准' },
    { id: 'completed',         name: '完成',       icon: 'check',    desc: '论文生成完毕' },
  ];

  const PHASE_MAP = {};
  PHASES.forEach((p, i) => { p.index = i; PHASE_MAP[p.id] = p; });

  /* ════════════════════════════════════════════════════════════════
     SVG 图标库
     ════════════════════════════════════════════════════════════════ */
  const ICONS = {
    target:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>',
    book:      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
    search:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    clipboard: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/></svg>',
    edit:      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    chart:     '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    pen:       '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19l7-7 3 3-7 7-3-3z"/><path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"/><path d="M2 2l7.586 7.586"/><circle cx="11" cy="11" r="2"/></svg>',
    tool:      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    check:     '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
    clock:     '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    trash:     '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    play:      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
    cancel:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    eye:       '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
    plus:      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    close:     '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    chevronR:  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>',
    comment:   '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    file:      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    calendar:  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
    doc:       '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
    folder:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  };

  /* ════════════════════════════════════════════════════════════════
     全局状态
     ════════════════════════════════════════════════════════════════ */
  const State = {
    api: null,
    ready: false,
    route: '',
    currentProject: '',
    projects: [],
    steps: [],
    chapters: [],
    comments: [],
    logs: [],
    currentPhase: '',
    generating: false,
    progressData: null,
    bottomPanelCollapsed: false,
    commentSidebarOpen: false,
    _timelineRenderTimer: null,  // debounce 时间线渲染
  };

  /* ════════════════════════════════════════════════════════════════
     API 封装 — 所有调用返回 Promise，自动 JSON.parse
     ════════════════════════════════════════════════════════════════ */
  const API = {
    _call(method, ...args) {
      if (!State.api) {
        return Promise.reject(new Error('pywebview API 尚未就绪'));
      }
      return State.api[method](...args).then(function (jsonStr) {
        try {
          return JSON.parse(jsonStr);
        } catch (e) {
          console.error('JSON 解析失败:', e, jsonStr);
          throw new Error('返回数据格式错误');
        }
      });
    },

    getProjectList()        { return this._call('get_project_list'); },
    createProject(name, topic) { return this._call('create_project', name, topic); },
    deleteProject(name)     { return this._call('delete_project', name); },
    renameProject(oldName, newName) { return this._call('rename_project', oldName, newName); },
    startGeneration(name, topic) { return this._call('start_generation', name, topic); },
    cancelGeneration()      { return this._call('cancel_generation'); },
    getGenerationStatus()   { return this._call('get_generation_status'); },
    getStepList(name)       { return this._call('get_step_list', name); },
    getStepOutput(name, phase) { return this._call('get_step_output', name, phase); },
    getChapterList(name)    { return this._call('get_chapter_list', name); },
    rewriteSection(name, sectionTitle, original, feedback, selected) {
      return this._call('rewrite_section', name, sectionTitle, original, feedback, selected);
    },
    applyRewrite(name, sectionName, newContent, feedback) {
      return this._call('apply_rewrite', name, sectionName, newContent, feedback);
    },
    getComments(name)       { return this._call('get_comments', name); },
    addComment(name, quote, text, section, position) {
      return this._call('add_comment', name, quote, text, section, position);
    },
    resolveComment(name, id) { return this._call('resolve_comment', name, id); },
    getConfig()             { return this._call('get_config'); },
    setApiKey(provider, key) { return this._call('set_api_key', provider, key); },
    setModelConfig(writingModel) { return this._call('set_model_config', writingModel); },
    exportProject(name, fmt) { return this._call('export_project', name, fmt); },
  };

  /* ════════════════════════════════════════════════════════════════
     工具函数
     ════════════════════════════════════════════════════════════════ */

  /** 转义 HTML */
  function escapeHtml(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }

  /** 格式化时间 */
  function formatTime(timestamp) {
    if (!timestamp) return '--';
    try {
      var d = new Date(timestamp);
      if (isNaN(d.getTime())) return timestamp;
      var now = new Date();
      var diff = (now - d) / 1000;
      if (diff < 60) return '刚刚';
      if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
      if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
      if (diff < 604800) return Math.floor(diff / 86400) + ' 天前';
      var m = (d.getMonth() + 1).toString().padStart(2, '0');
      var day = d.getDate().toString().padStart(2, '0');
      var h = d.getHours().toString().padStart(2, '0');
      var min = d.getMinutes().toString().padStart(2, '0');
      return m + '-' + day + ' ' + h + ':' + min;
    } catch (e) {
      return timestamp;
    }
  }

  /** 格式化字符数 */
  function formatCharCount(count) {
    if (!count || count === 0) return '0 字';
    if (count < 10000) return count + ' 字';
    return (count / 10000).toFixed(1) + ' 万字';
  }

  /** 获取状态文本 */
  function statusText(status) {
    switch (status) {
      case 'not_started':  return '未开始';
      case 'in_progress':  return '生成中';
      case 'completed':    return '已完成';
      default:             return '未知';
    }
  }

  /** Toast 通知 */
  function showToast(type, message, duration) {
    duration = duration || 3000;
    var root = document.getElementById('toast-root');
    var toast = document.createElement('div');
    toast.className = 'toast ' + type;
    var iconMap = {
      success: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
      error:   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
      warning: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      info:    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };
    toast.innerHTML =
      '<span class="toast-icon">' + (iconMap[type] || iconMap.info) + '</span>' +
      '<span>' + escapeHtml(message) + '</span>';
    root.appendChild(toast);
    setTimeout(function () {
      toast.classList.add('removing');
      setTimeout(function () { toast.remove(); }, 300);
    }, duration);
  }

  /** 模态框 */
  function showModal(options) {
    var root = document.getElementById('modal-root');
    var overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    var modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML =
      '<div class="modal-header">' +
        '<div class="modal-title">' + escapeHtml(options.title || '') + '</div>' +
        '<button class="modal-close">' + ICONS.close + '</button>' +
      '</div>' +
      '<div class="modal-body"></div>' +
      (options.footer !== false ? '<div class="modal-footer"></div>' : '');

    overlay.appendChild(modal);
    root.appendChild(overlay);

    var bodyEl = modal.querySelector('.modal-body');
    if (typeof options.body === 'string') {
      bodyEl.innerHTML = options.body;
    } else if (options.body instanceof HTMLElement) {
      bodyEl.appendChild(options.body);
    }

    var footerEl = modal.querySelector('.modal-footer');
    if (footerEl && options.buttons) {
      options.buttons.forEach(function (btn) {
        var button = document.createElement('button');
        button.className = 'btn ' + (btn.type || 'btn-secondary');
        button.textContent = btn.text;
        button.addEventListener('click', function () {
          if (btn.onClick) {
            btn.onClick(modal, overlay);
          }
          if (btn.closeOnClick !== false) {
            root.removeChild(overlay);
          }
        });
        footerEl.appendChild(button);
      });
    }

    modal.querySelector('.modal-close').addEventListener('click', function () {
      root.removeChild(overlay);
    });

    overlay.addEventListener('click', function (e) {
      if (e.target === overlay && options.closeOnOverlay !== false) {
        root.removeChild(overlay);
      }
    });

    return { modal: modal, overlay: overlay, bodyEl: bodyEl };
  }

  /** 确认对话框 */
  function confirmDialog(title, message, onConfirm) {
    showModal({
      title: title,
      body: '<p style="color:var(--text-secondary);font-size:14px;">' + escapeHtml(message) + '</p>',
      buttons: [
        { text: '取消', type: 'btn-secondary' },
        {
          text: '确认', type: 'btn-danger',
          onClick: function () { if (onConfirm) onConfirm(); },
        },
      ],
    });
  }

  /* ════════════════════════════════════════════════════════════════
     Markdown 配置 — 学术风格
     ════════════════════════════════════════════════════════════════ */
  function initMarkdown() {
    if (typeof marked === 'undefined') {
      console.warn('marked.js 未加载');
      return;
    }
    // marked v12 配置：breaks 换行 + gfm 表格
    // 代码高亮在 renderMarkdown 中通过 hljs 后处理实现
    marked.setOptions({
      breaks: true,
      gfm: true,
    });
  }

  /** 渲染 Markdown 并对代码块进行高亮 */
  function renderMarkdown(text) {
    if (!text) return '<p style="color:var(--text-tertiary);">暂无内容</p>';
    if (typeof marked === 'undefined') {
      return '<pre>' + escapeHtml(text) + '</pre>';
    }
    try {
      var html = marked.parse(text);
      // 后处理：对 <pre><code> 块应用 highlight.js
      if (typeof hljs !== 'undefined') {
        var temp = document.createElement('div');
        temp.innerHTML = html;
        temp.querySelectorAll('pre code').forEach(function (block) {
          try { hljs.highlightElement(block); } catch (e) { /* ignore */ }
        });
        return temp.innerHTML;
      }
      return html;
    } catch (e) {
      console.error('Markdown 渲染失败:', e);
      return '<pre>' + escapeHtml(text) + '</pre>';
    }
  }

  /* ════════════════════════════════════════════════════════════════
     路由系统
     ════════════════════════════════════════════════════════════════ */
  function handleRoute() {
    var hash = window.location.hash || '#/projects';
    State.route = hash;

    // 解析路由
    var parts = hash.replace(/^#\/?/, '').split('/');

    // 隐藏底部面板和评论侧边栏（非预览页面）
    if (parts[0] !== 'preview') {
      closeCommentSidebar();
    }

    if (parts[0] === 'projects' || parts.length === 0 || !parts[0]) {
      renderProjectsPage();
    } else if (parts[0] === 'settings') {
      renderSettingsPage();
    } else if (parts[0] === 'progress' && parts[1]) {
      State.currentProject = decodeURIComponent(parts[1]);
      renderProgressPage(State.currentProject);
    } else if (parts[0] === 'preview' && parts[1]) {
      State.currentProject = decodeURIComponent(parts[1]);
      State.currentPhase = parts[2] ? decodeURIComponent(parts[2]) : '';
      renderPreviewPage(State.currentProject, State.currentPhase);
    } else {
      window.location.hash = '#/projects';
    }
  }

  function navigate(route) {
    window.location.hash = route;
  }

  /* ════════════════════════════════════════════════════════════════
     侧边栏渲染
     ════════════════════════════════════════════════════════════════ */
  function updateNavActive(route) {
    var items = document.querySelectorAll('.nav-item');
    items.forEach(function (item) {
      item.classList.remove('active');
      var dataRoute = item.getAttribute('data-route');
      if (dataRoute && route.startsWith(dataRoute)) {
        item.classList.add('active');
      }
    });

    // 显示/隐藏导航项
    var navProgress = document.getElementById('nav-progress');
    var navPreview = document.getElementById('nav-preview');
    if (State.currentProject) {
      navProgress.style.display = '';
      navPreview.style.display = '';
      navProgress.setAttribute('data-route', '#/progress/' + encodeURIComponent(State.currentProject));
      navPreview.setAttribute('data-route', '#/preview/' + encodeURIComponent(State.currentProject));
    } else {
      navProgress.style.display = 'none';
      navPreview.style.display = 'none';
    }
  }

  function renderSidebarProjects() {
    var container = document.getElementById('sidebar-project-list');
    if (!State.projects.length) {
      container.innerHTML = '<div style="padding:8px 12px;font-size:12px;color:var(--text-tertiary);">暂无项目</div>';
      return;
    }
    container.innerHTML = State.projects.slice(0, 15).map(function (p) {
      return '<div class="sidebar-project-item" data-project="' + escapeHtml(p.name) + '">' +
        '<span class="dot dot-' + p.status + '"></span>' +
        '<span>' + escapeHtml(p.title || p.name) + '</span>' +
      '</div>';
    }).join('');

    container.querySelectorAll('.sidebar-project-item').forEach(function (el) {
      el.addEventListener('click', function () {
        var name = el.getAttribute('data-project');
        navigate('#/preview/' + encodeURIComponent(name));
      });
    });
  }

  function updateBreadcrumb(items) {
    var bc = document.getElementById('breadcrumb');
    bc.innerHTML = items.map(function (item, i) {
      var isLast = i === items.length - 1;
      var html = '<span class="breadcrumb-item' + (isLast ? ' current' : '') + '"' +
        (item.route ? ' data-route="' + item.route + '"' : '') + '>' +
        escapeHtml(item.label) + '</span>';
      if (!isLast) html += '<span class="breadcrumb-sep">/</span>';
      return html;
    }).join('');

    bc.querySelectorAll('[data-route]').forEach(function (el) {
      el.addEventListener('click', function () {
        navigate(el.getAttribute('data-route'));
      });
    });
  }

  function updateHeaderActions(actions) {
    var container = document.getElementById('header-actions');
    if (!actions || !actions.length) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = actions.map(function (a, i) {
      return '<button class="btn ' + (a.type || 'btn-secondary') + ' btn-sm" data-action="' + i + '">' +
        (a.icon || '') +
        '<span>' + escapeHtml(a.text) + '</span>' +
      '</button>';
    }).join('');

    container.querySelectorAll('[data-action]').forEach(function (el) {
      el.addEventListener('click', function () {
        var idx = parseInt(el.getAttribute('data-action'), 10);
        if (actions[idx].onClick) actions[idx].onClick();
      });
    });
  }

  /* ════════════════════════════════════════════════════════════════
     页面 1 — 项目列表
     ════════════════════════════════════════════════════════════════ */
  function renderProjectsPage() {
    State.currentProject = '';
    updateNavActive('#/projects');
    updateBreadcrumb([{ label: '我的项目' }]);
    updateHeaderActions([
      { text: '新建项目', type: 'btn-primary', icon: ICONS.plus, onClick: showCreateProjectDialog },
    ]);

    var main = document.getElementById('main-content');
    main.innerHTML =
      '<div class="projects-page">' +
        '<div class="projects-page-header">' +
          '<h1>我的论文项目</h1>' +
        '</div>' +
        '<div class="projects-toolbar">' +
          '<div class="search-box">' + ICONS.search +
            '<input type="text" id="project-search" placeholder="搜索项目名称或主题..." />' +
          '</div>' +
          '<select class="sort-dropdown" id="project-sort">' +
            '<option value="updated">最近更新</option>' +
            '<option value="created">创建时间</option>' +
            '<option value="name">名称</option>' +
            '<option value="progress">进度</option>' +
          '</select>' +
        '</div>' +
        '<div id="project-list-container">' +
          '<div class="loading-inline"><div class="loading-spinner"></div>正在加载项目列表...</div>' +
        '</div>' +
      '</div>';

    // 搜索
    var searchInput = document.getElementById('project-search');
    searchInput.addEventListener('input', function () {
      renderProjectList(searchInput.value);
    });

    // 排序
    var sortSelect = document.getElementById('project-sort');
    sortSelect.addEventListener('change', function () {
      renderProjectList(searchInput.value, sortSelect.value);
    });

    loadProjects();
  }

  async function loadProjects() {
    try {
      var result = await API.getProjectList();
      if (result.error) throw new Error(result.error);
      State.projects = Array.isArray(result) ? result : [];
      renderSidebarProjects();
      var searchInput = document.getElementById('project-search');
      var sortSelect = document.getElementById('project-sort');
      renderProjectList(
        searchInput ? searchInput.value : '',
        sortSelect ? sortSelect.value : 'updated'
      );
    } catch (e) {
      var container = document.getElementById('project-list-container');
      if (container) {
        container.innerHTML =
          '<div class="empty-state">' +
            '<h3>加载失败</h3><p>' + escapeHtml(e.message) + '</p>' +
            '<button class="btn btn-secondary" onclick="window.app.retryLoadProjects()">重试</button>' +
          '</div>';
      }
      showToast('error', '加载项目列表失败: ' + e.message);
    }
  }

  function renderProjectList(searchQuery, sortBy) {
    searchQuery = (searchQuery || '').toLowerCase().trim();
    sortBy = sortBy || 'updated';

    var projects = State.projects.slice();

    // 搜索过滤
    if (searchQuery) {
      projects = projects.filter(function (p) {
        return (p.name || '').toLowerCase().includes(searchQuery) ||
               (p.title || '').toLowerCase().includes(searchQuery) ||
               (p.topic || '').toLowerCase().includes(searchQuery);
      });
    }

    // 排序
    switch (sortBy) {
      case 'created':
        projects.sort(function (a, b) { return (b.created_at || '').localeCompare(a.created_at || ''); });
        break;
      case 'name':
        projects.sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });
        break;
      case 'progress':
        projects.sort(function (a, b) { return (b.progress_pct || 0) - (a.progress_pct || 0); });
        break;
      default: // updated
        projects.sort(function (a, b) { return (b.updated_at || '').localeCompare(a.updated_at || ''); });
    }

    var container = document.getElementById('project-list-container');
    if (!container) return;

    if (!projects.length) {
      container.innerHTML =
        '<div class="empty-state">' +
          ICONS.folder +
          '<h3>' + (searchQuery ? '未找到匹配的项目' : '还没有论文项目') + '</h3>' +
          '<p>' + (searchQuery ? '试试其他关键词' : '创建你的第一个项目，开始 AI 辅助论文写作') + '</p>' +
          (searchQuery ? '' : '<button class="btn btn-primary" id="empty-create-btn">' + ICONS.plus + '<span>新建项目</span></button>') +
        '</div>';
      var emptyBtn = document.getElementById('empty-create-btn');
      if (emptyBtn) emptyBtn.addEventListener('click', showCreateProjectDialog);
      return;
    }

    container.innerHTML =
      '<div class="project-grid">' +
        projects.map(renderProjectCard).join('') +
      '</div>';

    // 绑定事件
    container.querySelectorAll('.project-card').forEach(function (card) {
      var name = card.getAttribute('data-project');
      card.addEventListener('click', function (e) {
        if (e.target.closest('.project-card-action')) return;
        navigate('#/preview/' + encodeURIComponent(name));
      });

      // 操作按钮
      card.querySelectorAll('.project-card-action').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          e.stopPropagation();
          var action = btn.getAttribute('data-action');
          handleProjectAction(action, name);
        });
      });
    });
  }

  function renderProjectCard(p) {
    var statusBadge = '<span class="status-badge status-' + p.status + '">' +
      '<span class="badge-dot"></span>' + statusText(p.status) + '</span>';

    var actionBtn = '';
    if (p.status === 'not_started') {
      actionBtn = '<button class="btn btn-primary btn-sm project-card-action" data-action="start">' +
        ICONS.play + '<span>开始生成</span></button>';
    } else if (p.status === 'in_progress') {
      actionBtn = '<button class="btn btn-primary btn-sm project-card-action" data-action="continue">' +
        ICONS.play + '<span>继续生成</span></button>';
    } else if (p.status === 'completed') {
      actionBtn = '<button class="btn btn-secondary btn-sm project-card-action" data-action="view">' +
        ICONS.eye + '<span>查看结果</span></button>';
    }

    var deleteBtn = '<button class="btn btn-ghost btn-sm project-card-action" data-action="delete" title="删除">' +
      ICONS.trash + '</button>';
    var renameBtn = '<button class="btn btn-ghost btn-sm project-card-action" data-action="rename" title="重命名">' +
      ICONS.edit + '</button>';

    return '<div class="project-card" data-project="' + escapeHtml(p.name) + '">' +
      '<div class="project-card-header">' +
        '<div style="overflow:hidden;">' +
          '<div class="project-card-title">' + escapeHtml(p.title || p.name) + '</div>' +
          '<div class="project-card-topic">' + escapeHtml(p.topic || '未设置主题') + '</div>' +
        '</div>' +
        statusBadge +
      '</div>' +
      '<div class="project-card-meta">' +
        '<span>' + ICONS.calendar + formatTime(p.updated_at || p.created_at) + '</span>' +
        '<span>' + ICONS.doc + formatCharCount(p.char_count) + '</span>' +
      '</div>' +
      '<div class="progress-bar">' +
        '<div class="progress-bar-fill" style="width:' + (p.progress_pct || 0) + '%"></div>' +
      '</div>' +
      '<div class="project-card-footer">' +
        '<span style="font-size:12px;color:var(--text-tertiary);">进度 ' + (p.progress_pct || 0) + '%</span>' +
        '<div class="project-card-actions">' + renameBtn + deleteBtn + actionBtn + '</div>' +
      '</div>' +
    '</div>';
  }

  function handleProjectAction(action, name) {
    var project = State.projects.find(function (p) { return p.name === name; });
    switch (action) {
      case 'start':
      case 'continue':
        if (action === 'start') {
          showStartGenerationDialog(name, project);
        } else {
          startGeneration(name, project ? project.topic : '');
        }
        break;
      case 'view':
        navigate('#/preview/' + encodeURIComponent(name));
        break;
      case 'delete':
        confirmDialog('删除项目', '确定要删除项目 "' + (project ? project.title || name : name) + '" 吗？此操作不可撤销。', function () {
          deleteProject(name);
        });
        break;
      case 'rename':
        showRenameDialog(name, project);
        break;
    }
  }

  /** 新建项目对话框 */
  function showCreateProjectDialog() {
    var body =
      '<div class="form-field">' +
        '<label class="form-label">项目名称</label>' +
        '<input type="text" class="form-input" id="new-project-name" placeholder="例如：数字经济发展研究" />' +
        '<div class="form-hint">项目名称用于标识，建议用简洁的英文或中文</div>' +
      '</div>' +
      '<div class="form-field">' +
        '<label class="form-label">研究主题</label>' +
        '<textarea class="form-textarea" id="new-project-topic" placeholder="请描述你的研究主题或初步想法..."></textarea>' +
        '<div class="form-hint">可以是一句话想法，也可以是详细的研究方向描述</div>' +
      '</div>';

    showModal({
      title: '新建论文项目',
      body: body,
      buttons: [
        { text: '取消', type: 'btn-secondary' },
        {
          text: '创建', type: 'btn-primary',
          closeOnClick: false,
          onClick: function (modal, overlay) {
            var name = modal.querySelector('#new-project-name').value.trim();
            var topic = modal.querySelector('#new-project-topic').value.trim();
            if (!name) {
              showToast('warning', '请输入项目名称');
              return;
            }
            createProject(name, topic, overlay);
          },
        },
      ],
    });
  }

  async function createProject(name, topic, overlay) {
    try {
      var result = await API.createProject(name, topic);
      if (result.error) throw new Error(result.error);
      showToast('success', '项目创建成功');
      if (overlay) document.getElementById('modal-root').removeChild(overlay);
      await loadProjects();
      // 创建后自动进入进度面板
      navigate('#/progress/' + encodeURIComponent(name));
    } catch (e) {
      showToast('error', '创建失败: ' + e.message);
    }
  }

  function showRenameDialog(oldName, project) {
    var body =
      '<div class="form-field">' +
        '<label class="form-label">当前名称：' + escapeHtml(oldName) + '</label>' +
      '</div>' +
      '<div class="form-field">' +
        '<label class="form-label">新名称</label>' +
        '<input type="text" class="form-input" id="rename-project-name" value="' + escapeHtml(oldName) + '" />' +
      '</div>';

    showModal({
      title: '重命名项目',
      body: body,
      buttons: [
        { text: '取消', type: 'btn-secondary' },
        {
          text: '确认', type: 'btn-primary',
          closeOnClick: false,
          onClick: function (modal, overlay) {
            var newName = modal.querySelector('#rename-project-name').value.trim();
            if (!newName) {
              showToast('warning', '请输入新名称');
              return;
            }
            if (newName === oldName) {
              showToast('info', '名称未改变');
              document.getElementById('modal-root').removeChild(overlay);
              return;
            }
            renameProject(oldName, newName, overlay);
          },
        },
      ],
    });
  }

  async function renameProject(oldName, newName, overlay) {
    try {
      var result = await API.renameProject(oldName, newName);
      if (result.error) throw new Error(result.error);
      showToast('success', '重命名成功: ' + newName);
      if (overlay) document.getElementById('modal-root').removeChild(overlay);
      await loadProjects();
    } catch (e) {
      showToast('error', '重命名失败: ' + e.message);
    }
  }

  /** 开始生成对话框 */
  function showStartGenerationDialog(name, project) {
    var topic = project ? (project.topic || '') : '';
    var body =
      '<div class="form-field">' +
        '<label class="form-label">项目：' + escapeHtml(name) + '</label>' +
      '</div>' +
      '<div class="form-field">' +
        '<label class="form-label">研究主题 / 想法</label>' +
        '<textarea class="form-textarea" id="gen-topic" placeholder="请描述你的研究主题或想法...">' + escapeHtml(topic) + '</textarea>' +
        '<div class="form-hint">AI 将根据此主题自动完成选题分析、文献检索、大纲生成和论文撰写</div>' +
      '</div>';

    showModal({
      title: '开始生成论文',
      body: body,
      buttons: [
        { text: '取消', type: 'btn-secondary' },
        {
          text: '开始生成', type: 'btn-primary',
          closeOnClick: false,
          onClick: function (modal, overlay) {
            var t = modal.querySelector('#gen-topic').value.trim();
            if (!t) {
              showToast('warning', '请输入研究主题');
              return;
            }
            document.getElementById('modal-root').removeChild(overlay);
            startGeneration(name, t);
          },
        },
      ],
    });
  }

  async function startGeneration(name, topic) {
    try {
      addLog('info', '正在启动生成任务: ' + name);
      var result = await API.startGeneration(name, topic);
      if (result.error) throw new Error(result.error);
      State.generating = true;
      showToast('success', '论文生成已启动');
      navigate('#/progress/' + encodeURIComponent(name));
    } catch (e) {
      showToast('error', '启动失败: ' + e.message);
      addLog('error', '启动失败: ' + e.message);
    }
  }

  async function deleteProject(name) {
    try {
      var result = await API.deleteProject(name);
      if (result.error) throw new Error(result.error);
      showToast('success', '项目已删除');
      await loadProjects();
    } catch (e) {
      showToast('error', '删除失败: ' + e.message);
    }
  }

  function showExportDialog(projectName) {
    var formats = [
      { id: 'docx', label: 'Word (.docx)', icon: ICONS.doc, desc: '适合进一步编辑和排版' },
      { id: 'pdf', label: 'PDF', icon: ICONS.file, desc: '适合提交和打印，需要 Word 或 LibreOffice' },
      { id: 'latex', label: 'LaTeX (.tex)', icon: ICONS.edit, desc: '适合学术投稿和公式排版' },
      { id: 'md', label: 'Markdown', icon: ICONS.doc, desc: '纯文本格式，方便版本管理' },
    ];

    var bodyHtml =
      '<div class="export-dialog">' +
        '<p style="color:var(--text-secondary);font-size:13px;margin-bottom:var(--space-lg);">选择导出格式：</p>' +
        formats.map(function (f) {
          return '<div class="export-option" data-fmt="' + f.id + '">' +
            '<div class="export-option-icon">' + f.icon + '</div>' +
            '<div class="export-option-info">' +
              '<div class="export-option-label">' + escapeHtml(f.label) + '</div>' +
              '<div class="export-option-desc">' + escapeHtml(f.desc) + '</div>' +
            '</div>' +
          '</div>';
        }).join('') +
        '<div class="export-status" id="export-status" style="display:none;"></div>' +
      '</div>';

    var modalResult = showModal({
      title: '导出论文 — ' + escapeHtml(projectName),
      body: bodyHtml,
      footer: false,
    });

    // 绑定导出选项点击
    modalResult.bodyEl.querySelectorAll('.export-option').forEach(function (opt) {
      opt.addEventListener('click', function () {
        var fmt = opt.getAttribute('data-fmt');
        doExport(projectName, fmt, modalResult);
      });
    });
  }

  async function doExport(projectName, fmt, modalResult) {
    var statusEl = modalResult.bodyEl.querySelector('#export-status');
    statusEl.style.display = 'block';
    statusEl.className = 'export-status loading';
    statusEl.textContent = '正在导出 ' + fmt.toUpperCase() + ' 格式...';

    // 禁用所有选项
    modalResult.bodyEl.querySelectorAll('.export-option').forEach(function (opt) {
      opt.style.pointerEvents = 'none';
      opt.style.opacity = '0.5';
    });

    try {
      var result = await API.exportProject(projectName, fmt);
      if (result.error) throw new Error(result.error);
      statusEl.className = 'export-status success';
      statusEl.innerHTML =
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>' +
        '导出成功！文件路径：<br/><code>' + escapeHtml(result.output_path) + '</code>';
      showToast('success', '导出成功: ' + result.output_path);
    } catch (e) {
      statusEl.className = 'export-status error';
      statusEl.textContent = '导出失败: ' + e.message;
      // 恢复选项
      modalResult.bodyEl.querySelectorAll('.export-option').forEach(function (opt) {
        opt.style.pointerEvents = '';
        opt.style.opacity = '';
      });
    }
  }

  /* ════════════════════════════════════════════════════════════════
     页面 1.5 — 设置页面
     ════════════════════════════════════════════════════════════════ */
  function renderSettingsPage() {
    State.currentProject = '';
    updateNavActive('#/settings');
    updateBreadcrumb([{ label: '首页', route: '#/projects' }, { label: '设置' }]);
    updateHeaderActions([]);

    var main = document.getElementById('main-content');
    main.innerHTML =
      '<div class="settings-page">' +
        '<h2 class="settings-title">API Key 配置</h2>' +
        '<p class="settings-desc">配置大模型 API Key，用于论文生成和学术分析。密钥保存在本地 <code>.env</code> 文件中，不会上传到任何服务器。</p>' +
        '<div class="settings-form" id="settings-form">' +
          Object.keys(API_PROVIDERS).map(function (provider) {
            return '<div class="form-field">' +
              '<label class="form-label">' + escapeHtml(API_PROVIDERS[provider]) + '</label>' +
              '<div class="form-input-row">' +
                '<input type="password" class="form-input" id="api-key-' + provider + '" ' +
                  'placeholder="输入 ' + escapeHtml(API_PROVIDERS[provider]) + ' 的 API Key" autocomplete="off">' +
                '<button class="btn btn-secondary btn-sm" data-action="toggle" data-target="api-key-' + provider + '">' +
                  ICONS.eye +
                '</button>' +
              '</div>' +
            '</div>';
          }).join('') +
          '<div class="form-field">' +
            '<label class="form-label">默认写作模型</label>' +
            '<select class="form-input" id="default-writing-model">' +
              MODEL_OPTIONS.map(function (m) {
                return '<option value="' + escapeHtml(m.value) + '">' + escapeHtml(m.label) + '</option>';
              }).join('') +
            '</select>' +
          '</div>' +
          '<div class="form-actions">' +
            '<button class="btn btn-primary" id="save-settings-btn">' +
              '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>' +
              '<span>保存配置</span>' +
            '</button>' +
            '<span class="form-status" id="form-status"></span>' +
          '</div>' +
        '</div>' +
      '</div>';

    // 加载当前配置
    API.getConfig().then(function (config) {
      if (config.error) return;
      // 标记哪些提供商已配置
      Object.keys(API_PROVIDERS).forEach(function (provider) {
        var input = document.getElementById('api-key-' + provider);
        if (input && config[provider + '_configured']) {
          input.placeholder = '已配置（输入新 Key 覆盖，留空则保持不变）';
          input.parentElement.parentElement.classList.add('configured');
        }
      });
      // 设置默认写作模型
      var modelSelect = document.getElementById('default-writing-model');
      if (modelSelect && config.writing_model) {
        modelSelect.value = config.writing_model;
      }
    }).catch(function () { /* 加载失败，静默处理 */ });

    // 绑定事件
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);

    // 密码可见性切换
    main.querySelectorAll('[data-action="toggle"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var targetId = btn.getAttribute('data-target');
        var input = document.getElementById(targetId);
        if (input) {
          input.type = input.type === 'password' ? 'text' : 'password';
        }
      });
    });
  }

  async function saveSettings() {
    var statusEl = document.getElementById('form-status');
    statusEl.className = 'form-status saving';
    statusEl.textContent = '正在保存...';

    var savedCount = 0;
    var errors = [];

    // 保存各个 API Key
    for (var provider in API_PROVIDERS) {
      var input = document.getElementById('api-key-' + provider);
      if (input && input.value.trim()) {
        try {
          var result = await API.setApiKey(provider, input.value.trim());
          if (result.error) throw new Error(result.error);
          savedCount++;
          input.value = '';
          input.placeholder = '已配置（输入新 Key 覆盖，留空则保持不变）';
          input.parentElement.parentElement.classList.add('configured');
        } catch (e) {
          errors.push(API_PROVIDERS[provider] + ': ' + e.message);
        }
      }
    }

    // 保存默认写作模型
    var modelSelect = document.getElementById('default-writing-model');
    if (modelSelect && modelSelect.value) {
      try {
        var modelResult = await API.setModelConfig(modelSelect.value);
        if (modelResult.error) throw new Error(modelResult.error);
      } catch (e) {
        errors.push('模型配置: ' + e.message);
      }
    }

    if (errors.length) {
      statusEl.className = 'form-status error';
      statusEl.textContent = '部分保存失败: ' + errors.join('; ');
    } else if (savedCount > 0 || modelSelect.value) {
      statusEl.className = 'form-status success';
      statusEl.textContent = '配置已保存' + (savedCount > 0 ? '（' + savedCount + ' 个 API Key）' : '');
      // 刷新配置状态
      setTimeout(function () { updateConfigBadge(); }, 500);
    } else {
      statusEl.className = 'form-status';
      statusEl.textContent = '未输入任何 API Key';
    }
  }

  /* ════════════════════════════════════════════════════════════════
     API 提供商映射
     ════════════════════════════════════════════════════════════════ */
  const API_PROVIDERS = {
    zhipu:   '智谱 AI (GLM)',
    ark:     '火山方舟 (豆包)',
    claude:  'Claude (Anthropic)',
    openai:  'OpenAI',
    deepseek:'DeepSeek',
  };

  const MODEL_OPTIONS = [
    { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
    { value: 'glm-4', label: '智谱 GLM-4' },
    { value: 'gpt-4o', label: 'GPT-4o' },
    { value: 'deepseek/deepseek-chat', label: 'DeepSeek Chat' },
  ];

  /* ════════════════════════════════════════════════════════════════
     页面 2 — 进度面板
     ════════════════════════════════════════════════════════════════ */
  async function renderProgressPage(projectName) {
    updateNavActive('#/progress/' + encodeURIComponent(projectName));
    updateBreadcrumb([
      { label: '我的项目', route: '#/projects' },
      { label: projectName, route: '#/preview/' + encodeURIComponent(projectName) },
      { label: '生成进度' },
    ]);
    updateHeaderActions([
      { text: '查看预览', type: 'btn-secondary', icon: ICONS.eye, onClick: function () {
        navigate('#/preview/' + encodeURIComponent(projectName));
      }},
    ]);

    var main = document.getElementById('main-content');
    main.innerHTML =
      '<div class="progress-page">' +
        '<div class="progress-status-bar" id="progress-status-bar">' +
          '<div class="loading-inline"><div class="loading-spinner"></div>正在获取生成状态...</div>' +
        '</div>' +
        '<div class="step-timeline" id="step-timeline">' +
          '<div class="loading-inline"><div class="loading-spinner"></div>正在加载步骤...</div>' +
        '</div>' +
      '</div>';

    // 加载步骤列表
    try {
      var steps = await API.getStepList(projectName);
      if (steps.error) throw new Error(steps.error);
      State.steps = Array.isArray(steps) ? steps : [];
      renderTimeline(projectName);
    } catch (e) {
      document.getElementById('step-timeline').innerHTML =
        '<div class="empty-state"><h3>加载失败</h3><p>' + escapeHtml(e.message) + '</p></div>';
    }

    // 加载章节列表（逐章撰写阶段）
    try {
      var chapters = await API.getChapterList(projectName);
      if (!chapters.error) {
        State.chapters = Array.isArray(chapters) ? chapters : [];
      }
    } catch (e) { /* ignore */ }

    // 检查生成状态
    try {
      var status = await API.getGenerationStatus();
      State.generating = status.is_running || false;
    } catch (e) { /* ignore */ }

    renderStatusBar(projectName);
    renderTimeline(projectName);
  }

  function renderStatusBar(projectName) {
    var bar = document.getElementById('progress-status-bar');
    if (!bar) return;

    var data = State.progressData;
    var isRunning = State.generating;
    var currentPhase = data ? data.phase : '';
    var message = data ? (data.message || '') : '';
    var progressPct = data ? (data.progress_pct || 0) : 0;

    // 如果没有实时数据，从步骤列表计算
    if (!data && State.steps.length) {
      var completedCount = State.steps.filter(function (s) { return s.completed; }).length;
      progressPct = Math.round((completedCount / State.steps.length) * 100);
      var currentStep = State.steps.find(function (s) { return !s.completed; });
      currentPhase = currentStep ? currentStep.id : '';
      message = currentStep ? '当前步骤: ' + currentStep.name : '所有步骤已完成';
    }

    var currentPhaseName = currentPhase && PHASE_MAP[currentPhase] ? PHASE_MAP[currentPhase].name : '';

    bar.innerHTML =
      '<div class="progress-status-top">' +
        '<div class="progress-status-label">' +
          (isRunning ? '<div class="spinner"></div>' : (progressPct >= 100 ? ICONS.check : ICONS.clock)) +
          '<span>' + (isRunning ? '正在生成' : (progressPct >= 100 ? '已完成' : '等待中')) + '</span>' +
          (currentPhaseName ? ' — ' + escapeHtml(currentPhaseName) : '') +
        '</div>' +
        '<div class="progress-pct">' + progressPct + '%</div>' +
      '</div>' +
      '<div class="progress-status-message">' + escapeHtml(message || '准备开始...') + '</div>' +
      '<div class="progress-bar-large">' +
        '<div class="progress-bar-fill" style="width:' + progressPct + '%"></div>' +
      '</div>' +
      (isRunning ?
        '<div style="margin-top:12px;display:flex;gap:8px;">' +
          '<button class="btn btn-danger btn-sm" id="cancel-gen-btn">' + ICONS.cancel + '<span>取消生成</span></button>' +
        '</div>' : '');

    var cancelBtn = document.getElementById('cancel-gen-btn');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        confirmDialog('取消生成', '确定要取消当前的生成任务吗？已完成的步骤不会丢失。', function () {
          cancelGeneration();
        });
      });
    }
  }

  function renderTimeline(projectName) {
    var container = document.getElementById('step-timeline');
    if (!container) return;
    if (!State.steps.length) {
      container.innerHTML = '<div class="empty-state"><p>暂无步骤数据</p></div>';
      return;
    }

    // 确定当前进行中的步骤
    var currentPhase = State.progressData ? State.progressData.phase : '';
    var inProgressIndex = -1;
    if (currentPhase && PHASE_MAP[currentPhase]) {
      inProgressIndex = PHASE_MAP[currentPhase].index;
    }

    container.innerHTML = State.steps.map(function (step, i) {
      var phase = PHASE_MAP[step.id];
      var status = 'pending';
      if (step.completed) {
        status = 'completed';
      } else if (i === inProgressIndex || (inProgressIndex === -1 && !step.completed && State.steps.slice(0, i).every(function (s) { return s.completed; }))) {
        status = 'in_progress';
      }

      var iconHtml = '';
      if (status === 'completed') {
        iconHtml = ICONS.check;
      } else if (status === 'in_progress') {
        iconHtml = '<div class="spinner"></div>';
      } else {
        iconHtml = ICONS[phase.icon] || ICONS.clock;
      }

      // 章节子进度（仅 section_writing）
      var childrenHtml = '';
      if (step.id === 'section_writing' && State.chapters.length) {
        childrenHtml = '<div class="timeline-children">' +
          State.chapters.map(function (ch) {
            var chStatus = ch.completed ? 'completed' : 'pending';
            return '<div class="chapter-progress-item ' + chStatus + '">' +
              '<span class="chapter-dot"></span>' +
              '<span>' + escapeHtml(ch.title) + '</span>' +
              (ch.char_count ? '<span style="margin-left:auto;color:var(--text-tertiary);">' + formatCharCount(ch.char_count) + '</span>' : '') +
            '</div>';
          }).join('') +
        '</div>';
      }

      return '<div class="timeline-item ' + status + '" data-phase="' + step.id + '">' +
        (i < State.steps.length - 1 ? '<div class="timeline-connector"></div>' : '') +
        '<div class="timeline-icon">' + iconHtml + '</div>' +
        '<div class="timeline-content">' +
          '<div class="timeline-title">' + escapeHtml(step.name) + '</div>' +
          '<div class="timeline-desc">' + escapeHtml(phase ? phase.desc : '') + '</div>' +
          childrenHtml +
        '</div>' +
      '</div>';
    }).join('');

    // 点击步骤 → 跳转预览
    container.querySelectorAll('.timeline-item').forEach(function (item) {
      item.addEventListener('click', function () {
        var phase = item.getAttribute('data-phase');
        navigate('#/preview/' + encodeURIComponent(projectName) + '/' + encodeURIComponent(phase));
      });
    });
  }

  async function cancelGeneration() {
    try {
      var result = await API.cancelGeneration();
      if (result.error) throw new Error(result.error);
      State.generating = false;
      showToast('success', '已取消生成任务');
      addLog('warning', '用户取消了生成任务');
      renderStatusBar(State.currentProject);
    } catch (e) {
      showToast('error', '取消失败: ' + e.message);
    }
  }

  /* ════════════════════════════════════════════════════════════════
     页面 3 — 预览面板
     ════════════════════════════════════════════════════════════════ */
  async function renderPreviewPage(projectName, phase) {
    updateNavActive('#/preview/' + encodeURIComponent(projectName));
    updateBreadcrumb([
      { label: '我的项目', route: '#/projects' },
      { label: projectName },
    ]);
    updateHeaderActions([
      { text: '生成进度', type: 'btn-secondary', icon: ICONS.clock, onClick: function () {
        navigate('#/progress/' + encodeURIComponent(projectName));
      }},
      { text: '导出', type: 'btn-secondary', icon: ICONS.file, onClick: function () {
        showExportDialog(projectName);
      }},
      { text: '评论', type: 'btn-secondary', icon: ICONS.comment, onClick: function () {
        toggleCommentSidebar();
      }},
    ]);

    var main = document.getElementById('main-content');
    main.innerHTML =
      '<div class="preview-page">' +
        '<div class="step-tree" id="step-tree">' +
          '<div class="loading-inline"><div class="loading-spinner"></div>加载中...</div>' +
        '</div>' +
        '<div class="markdown-area" id="markdown-area">' +
          '<div class="loading-inline"><div class="loading-spinner"></div>加载中...</div>' +
        '</div>' +
        '<div class="comment-sidebar" id="comment-sidebar">' +
          '<div class="comment-sidebar-header">' +
            '<h3>' + ICONS.comment + '<span>评论</span>' +
              '<span class="comment-count-badge" id="comment-count">0</span>' +
            '</h3>' +
            '<button class="btn btn-ghost btn-sm" id="close-comment-sidebar">' + ICONS.close + '</button>' +
          '</div>' +
          '<div class="comment-list" id="comment-list">' +
            '<div class="comment-empty">暂无评论</div>' +
          '</div>' +
        '</div>' +
      '</div>';

    // 关闭评论侧边栏
    document.getElementById('close-comment-sidebar').addEventListener('click', closeCommentSidebar);

    // 加载步骤列表
    try {
      var steps = await API.getStepList(projectName);
      if (steps.error) throw new Error(steps.error);
      State.steps = Array.isArray(steps) ? steps : [];
      renderStepTree(projectName, phase);
    } catch (e) {
      document.getElementById('step-tree').innerHTML =
        '<div style="padding:16px;color:var(--text-tertiary);font-size:12px;">加载失败</div>';
    }

    // 加载章节列表
    try {
      var chapters = await API.getChapterList(projectName);
      if (!chapters.error) {
        State.chapters = Array.isArray(chapters) ? chapters : [];
        renderStepTree(projectName, phase);
      }
    } catch (e) { /* ignore */ }

    // 加载评论
    await loadComments(projectName);

    // 加载内容
    var targetPhase = phase || (State.steps.length ? (State.steps.find(function (s) { return s.completed; }) || State.steps[0]) : {}).id || '';
    if (targetPhase) {
      await loadStepOutput(projectName, targetPhase);
    } else {
      document.getElementById('markdown-area').innerHTML =
        '<div class="empty-state">' + ICONS.file +
        '<h3>暂无可预览的内容</h3><p>请先开始生成论文</p>' +
        '<button class="btn btn-primary" id="goto-progress">' + ICONS.play + '<span>前往进度面板</span></button>' +
        '</div>';
      var gotoBtn = document.getElementById('goto-progress');
      if (gotoBtn) gotoBtn.addEventListener('click', function () {
        navigate('#/progress/' + encodeURIComponent(projectName));
      });
    }
  }

  function renderStepTree(projectName, activePhase) {
    var container = document.getElementById('step-tree');
    if (!container) return;
    if (!State.steps.length) {
      container.innerHTML = '<div style="padding:16px;color:var(--text-tertiary);font-size:12px;">暂无步骤</div>';
      return;
    }

    var html = '<div class="step-tree-title">步骤导航</div>';
    html += State.steps.map(function (step) {
      var phase = PHASE_MAP[step.id];
      var isActive = activePhase === step.id;
      var statusClass = step.completed ? 'completed' : 'pending';

      var childrenHtml = '';
      if (step.id === 'section_writing' && State.chapters.length) {
        childrenHtml = '<div class="step-tree-children">' +
          State.chapters.map(function (ch) {
            var chActive = activePhase === ch.id;
            return '<div class="step-tree-child ' + (chActive ? 'active' : '') + '" data-phase="' + ch.id + '">' +
              '<span style="font-size:10px;">' + (ch.completed ? ICONS.check : '&#9675;') + '</span>' +
              '<span>' + escapeHtml(ch.title) + '</span>' +
            '</div>';
          }).join('') +
        '</div>';
      }

      return '<div class="step-tree-item ' + statusClass + (isActive ? ' active' : '') + '" data-phase="' + step.id + '">' +
        '<span class="step-icon">' + (ICONS[phase ? phase.icon : 'clock'] || '') + '</span>' +
        '<span>' + escapeHtml(step.name) + '</span>' +
      '</div>' + childrenHtml;
    }).join('');

    container.innerHTML = html;

    // 绑定点击
    container.querySelectorAll('.step-tree-item, .step-tree-child').forEach(function (el) {
      el.addEventListener('click', function () {
        var p = el.getAttribute('data-phase');
        if (p) {
          navigate('#/preview/' + encodeURIComponent(projectName) + '/' + encodeURIComponent(p));
        }
      });
    });
  }

  async function loadStepOutput(projectName, phase) {
    var area = document.getElementById('markdown-area');
    if (!area) return;

    var phaseInfo = PHASE_MAP[phase];
    var title = phaseInfo ? phaseInfo.name : phase;

    area.innerHTML = '<div class="loading-inline"><div class="loading-spinner"></div>正在加载 ' + escapeHtml(title) + '...</div>';

    try {
      var result = await API.getStepOutput(projectName, phase);
      if (result.error) throw new Error(result.error);

      var content = result.content || '';
      var contentType = result.content_type || 'markdown';
      var metadata = result.metadata || {};
      var savedAt = result.saved_at || '';

      // 更新 step tree active
      renderStepTree(projectName, phase);

      var contentHtml = '';
      if (contentType === 'markdown' || contentType === 'text') {
        contentHtml = renderMarkdown(content);
      } else if (contentType === 'json') {
        contentHtml = '<pre><code>' + escapeHtml(JSON.stringify(content, null, 2)) + '</code></pre>';
      } else {
        contentHtml = renderMarkdown(content);
      }

      // 更新面包屑
      updateBreadcrumb([
        { label: '我的项目', route: '#/projects' },
        { label: projectName, route: '#/preview/' + encodeURIComponent(projectName) },
        { label: title },
      ]);

      area.innerHTML =
        '<div class="markdown-header">' +
          '<h2>' + (ICONS[phaseInfo ? phaseInfo.icon : 'file'] || ICONS.file) + '<span>' + escapeHtml(title) + '</span></h2>' +
          '<div class="markdown-meta">' +
            (savedAt ? '<span>' + ICONS.calendar + formatTime(savedAt) + '</span>' : '') +
            (content ? '<span>' + formatCharCount(content.length) + '</span>' : '') +
          '</div>' +
        '</div>' +
        '<div class="markdown-body" id="markdown-body">' + contentHtml + '</div>';

      // 如果是 section_writing 的章节，启用划词工具栏
      initSelectionToolbarForArea();

    } catch (e) {
      area.innerHTML =
        '<div class="empty-state">' +
          '<h3>加载失败</h3>' +
          '<p>' + escapeHtml(e.message) + '</p>' +
        '</div>';
    }
  }

  /* ════════════════════════════════════════════════════════════════
     评论侧边栏
     ════════════════════════════════════════════════════════════════ */
  async function loadComments(projectName) {
    try {
      var result = await API.getComments(projectName);
      if (result.error) throw new Error(result.error);
      State.comments = Array.isArray(result) ? result : [];
      renderComments();
    } catch (e) {
      console.error('加载评论失败:', e);
    }
  }

  function renderComments() {
    var list = document.getElementById('comment-list');
    var count = document.getElementById('comment-count');
    if (!list) return;

    if (count) count.textContent = State.comments.length;

    if (!State.comments.length) {
      list.innerHTML = '<div class="comment-empty">暂无评论<br><span style="font-size:11px;">选中文字后点击评论按钮添加</span></div>';
      return;
    }

    list.innerHTML = State.comments.map(function (c) {
      return '<div class="comment-item' + (c.resolved ? ' resolved' : '') + '" data-id="' + escapeHtml(c.id) + '">' +
        '<div class="comment-quote">' + escapeHtml(c.quote || '(无选中文字)') + '</div>' +
        '<div class="comment-text">' + escapeHtml(c.text || '') + '</div>' +
        '<div class="comment-meta">' +
          '<span>' + (c.section ? escapeHtml(c.section) : '') + ' ' + formatTime(c.created_at) + '</span>' +
          '<div class="comment-actions">' +
            (c.resolved ? '' : '<button class="comment-action-btn resolve" data-action="resolve">解决</button>') +
          '</div>' +
        '</div>' +
      '</div>';
    }).join('');

    list.querySelectorAll('[data-action="resolve"]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var item = btn.closest('.comment-item');
        var id = item.getAttribute('data-id');
        resolveComment(State.currentProject, id);
      });
    });
  }

  async function resolveComment(projectName, id) {
    try {
      var result = await API.resolveComment(projectName, id);
      if (result.error) throw new Error(result.error);
      showToast('success', '评论已标记为已解决');
      await loadComments(projectName);
    } catch (e) {
      showToast('error', '操作失败: ' + e.message);
    }
  }

  function toggleCommentSidebar() {
    var sidebar = document.getElementById('comment-sidebar');
    if (!sidebar) return;
    State.commentSidebarOpen = !State.commentSidebarOpen;
    if (State.commentSidebarOpen) {
      sidebar.classList.add('open');
    } else {
      sidebar.classList.remove('open');
    }
  }

  function closeCommentSidebar() {
    var sidebar = document.getElementById('comment-sidebar');
    if (sidebar) sidebar.classList.remove('open');
    State.commentSidebarOpen = false;
  }

  /* ════════════════════════════════════════════════════════════════
     划词工具栏
     ════════════════════════════════════════════════════════════════ */
  var selectionToolbar = null;
  var currentSelection = null;
  var selectionTimer = null;  // 竞态保护：取消上一次待处理的选区

  function initSelectionToolbarForArea() {
    var area = document.getElementById('markdown-area');
    if (!area) return;

    // 移除旧监听器（通过克隆节点）
    selectionToolbar = document.getElementById('selection-toolbar');

    // 监听 mouseup 检测文字选择
    area.addEventListener('mouseup', handleSelection);
    area.addEventListener('keyup', handleSelection);
  }

  function handleSelection(e) {
    // 竞态保护：取消上一次待处理的选区判断
    if (selectionTimer) {
      clearTimeout(selectionTimer);
      selectionTimer = null;
    }
    // 延迟检查，确保 selection 已更新
    selectionTimer = setTimeout(function () {
      selectionTimer = null;
      var sel = window.getSelection();
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
        hideSelectionToolbar();
        return;
      }

      var text = sel.toString().trim();
      if (!text || text.length < 2) {
        hideSelectionToolbar();
        return;
      }

      // 确保选区在 markdown-body 内
      var range = sel.getRangeAt(0);
      var markdownBody = document.getElementById('markdown-body');
      if (!markdownBody || !markdownBody.contains(range.commonAncestorContainer)) {
        hideSelectionToolbar();
        return;
      }

      currentSelection = {
        text: text,
        range: range.cloneRange(),
      };

      showSelectionToolbar(range);
    }, 10);
  }

  function showSelectionToolbar(range) {
    var toolbar = document.getElementById('selection-toolbar');
    if (!toolbar) return;

    var rect = range.getBoundingClientRect();
    var toolbarWidth = 200;
    var toolbarHeight = 36;

    var left = rect.left + (rect.width / 2) - (toolbarWidth / 2);
    var top = rect.top - toolbarHeight - 8;

    // 边界检查
    if (left < 8) left = 8;
    if (left + toolbarWidth > window.innerWidth - 8) left = window.innerWidth - toolbarWidth - 8;
    if (top < 8) top = rect.bottom + 8;

    toolbar.style.left = left + 'px';
    toolbar.style.top = top + 'px';
    toolbar.style.display = 'flex';
  }

  function hideSelectionToolbar() {
    var toolbar = document.getElementById('selection-toolbar');
    if (toolbar) toolbar.style.display = 'none';
    currentSelection = null;
  }

  function initToolbarButtons() {
    var toolbar = document.getElementById('selection-toolbar');
    if (!toolbar) return;

    toolbar.querySelectorAll('.toolbar-btn').forEach(function (btn) {
      btn.addEventListener('mousedown', function (e) {
        // 防止点击按钮时丢失选区
        e.preventDefault();
      });
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        var action = btn.getAttribute('data-action');
        handleToolbarAction(action);
      });
    });

    // 点击其他区域隐藏工具栏
    document.addEventListener('mousedown', function (e) {
      if (!e.target.closest('#selection-toolbar') && !e.target.closest('.markdown-body')) {
        hideSelectionToolbar();
      }
    });

    // 滚动时隐藏
    var mainContent = document.getElementById('main-content');
    if (mainContent) {
      mainContent.addEventListener('scroll', hideSelectionToolbar);
    }
  }

  function handleToolbarAction(action) {
    if (!currentSelection || !currentSelection.text) {
      showToast('warning', '请先选择文字');
      return;
    }

    var selectedText = currentSelection.text;

    switch (action) {
      case 'comment':
        showCommentDialog(selectedText);
        break;
      case 'rewrite':
        showRewriteDialog(selectedText);
        break;
      case 'explain':
        showExplainDialog(selectedText);
        break;
    }

    hideSelectionToolbar();
  }

  /** 评论对话框 */
  function showCommentDialog(quote) {
    var body =
      '<div class="form-field">' +
        '<label class="form-label">选中文字</label>' +
        '<div class="comment-quote">' + escapeHtml(quote) + '</div>' +
      '</div>' +
      '<div class="form-field">' +
        '<label class="form-label">评论内容</label>' +
        '<textarea class="form-textarea" id="comment-text" placeholder="写下你的评论或修改建议..." autofocus></textarea>' +
      '</div>';

    showModal({
      title: '添加评论',
      body: body,
      buttons: [
        { text: '取消', type: 'btn-secondary' },
        {
          text: '添加', type: 'btn-primary',
          closeOnClick: false,
          onClick: function (modal, overlay) {
            var text = modal.querySelector('#comment-text').value.trim();
            if (!text) {
              showToast('warning', '请输入评论内容');
              return;
            }
            addCommentApi(quote, text, State.currentPhase);
            document.getElementById('modal-root').removeChild(overlay);
          },
        },
      ],
    });
  }

  async function addCommentApi(quote, text, section) {
    try {
      var result = await API.addComment(State.currentProject, quote, text, section || '', 0);
      if (result.error) throw new Error(result.error);
      showToast('success', '评论已添加');
      // 打开评论侧边栏
      if (!State.commentSidebarOpen) toggleCommentSidebar();
      await loadComments(State.currentProject);
    } catch (e) {
      showToast('error', '添加评论失败: ' + e.message);
    }
  }

  /** 重写对话框 */
  function showRewriteDialog(selectedText) {
    var body =
      '<div class="form-field">' +
        '<label class="form-label">选中文字</label>' +
        '<div class="comment-quote">' + escapeHtml(selectedText) + '</div>' +
      '</div>' +
      '<div class="form-field">' +
        '<label class="form-label">修改意见</label>' +
        '<textarea class="form-textarea" id="rewrite-feedback" placeholder="请描述你希望如何修改这段文字..." autofocus></textarea>' +
        '<div class="form-hint">例如：语言更学术化、增加数据支撑、调整逻辑结构等</div>' +
      '</div>';

    showModal({
      title: 'AI 重写',
      body: body,
      buttons: [
        { text: '取消', type: 'btn-secondary' },
        {
          text: '开始重写', type: 'btn-primary',
          closeOnClick: false,
          onClick: function (modal, overlay) {
            var feedback = modal.querySelector('#rewrite-feedback').value.trim();
            if (!feedback) {
              showToast('warning', '请输入修改意见');
              return;
            }
            performRewrite(selectedText, feedback, modal, overlay);
          },
        },
      ],
    });
  }

  async function performRewrite(selectedText, feedback, modal, overlay) {
    // 获取原始内容
    var markdownBody = document.getElementById('markdown-body');
    var originalContent = markdownBody ? markdownBody.innerText : '';

    // 显示加载状态
    var bodyEl = modal.querySelector('.modal-body');
    bodyEl.innerHTML =
      '<div class="loading-inline" style="justify-content:center;padding:32px;">' +
        '<div class="loading-spinner"></div>' +
        '<span>AI 正在重写，请稍候...</span>' +
      '</div>';

    // 隐藏 footer
    var footer = modal.querySelector('.modal-footer');
    if (footer) footer.style.display = 'none';

    try {
      var sectionTitle = PHASE_MAP[State.currentPhase] ? PHASE_MAP[State.currentPhase].name : State.currentPhase;
      var result = await API.rewriteSection(
        State.currentProject,
        sectionTitle,
        originalContent,
        feedback,
        selectedText
      );

      if (result.error) throw new Error(result.error);

      var newContent = result.new_content || '';

      // 显示重写结果
      bodyEl.innerHTML =
        '<div class="form-field">' +
          '<label class="form-label">原始内容</label>' +
          '<div class="rewrite-result"><div class="rewrite-diff-original">' + escapeHtml(selectedText) + '</div></div>' +
        '</div>' +
        '<div class="form-field">' +
          '<label class="form-label">AI 重写结果</label>' +
          '<div class="rewrite-result">' + renderMarkdown(newContent) + '</div>' +
        '</div>';

      if (footer) {
        footer.style.display = '';
        footer.innerHTML = '';
        var applyBtn = document.createElement('button');
        applyBtn.className = 'btn btn-primary';
        applyBtn.innerHTML = ICONS.check + '<span>应用修改</span>';
        applyBtn.addEventListener('click', function () {
          applyRewriteApi(State.currentPhase, newContent, feedback);
          document.getElementById('modal-root').removeChild(overlay);
        });

        var discardBtn = document.createElement('button');
        discardBtn.className = 'btn btn-secondary';
        discardBtn.textContent = '放弃';
        discardBtn.addEventListener('click', function () {
          document.getElementById('modal-root').removeChild(overlay);
        });

        footer.appendChild(discardBtn);
        footer.appendChild(applyBtn);
      }
    } catch (e) {
      bodyEl.innerHTML =
        '<div class="empty-state"><h3>重写失败</h3><p>' + escapeHtml(e.message) + '</p></div>';
      if (footer) footer.style.display = '';
    }
  }

  async function applyRewriteApi(sectionName, newContent, feedback) {
    try {
      var result = await API.applyRewrite(State.currentProject, sectionName, newContent, feedback);
      if (result.error) throw new Error(result.error);
      showToast('success', '修改已应用');
      // 重新加载内容
      await loadStepOutput(State.currentProject, State.currentPhase);
    } catch (e) {
      showToast('error', '应用失败: ' + e.message);
    }
  }

  /** 解释对话框 */
  function showExplainDialog(selectedText) {
    var body =
      '<div class="form-field">' +
        '<label class="form-label">选中文字</label>' +
        '<div class="comment-quote">' + escapeHtml(selectedText) + '</div>' +
      '</div>' +
      '<div class="form-field">' +
        '<label class="form-label">AI 解释</label>' +
        '<div class="rewrite-result" id="explain-result" style="min-height:60px;">' +
          '<div class="loading-inline"><div class="loading-spinner"></div>正在生成解释...</div>' +
        '</div>' +
      '</div>';

    showModal({
      title: 'AI 解释',
      body: body,
      buttons: [
        { text: '关闭', type: 'btn-secondary' },
      ],
    });

    // 调用重写 API 以"解释"模式（复用接口）
    // 实际项目中可添加专门的 explain API
    var markdownBody = document.getElementById('markdown-body');
    var originalContent = markdownBody ? markdownBody.innerText : '';
    var sectionTitle = PHASE_MAP[State.currentPhase] ? PHASE_MAP[State.currentPhase].name : State.currentPhase;
    var feedback = '请解释以下这段文字的含义、逻辑和学术背景：\n\n' + selectedText;

    API.rewriteSection(State.currentProject, sectionTitle, originalContent, feedback, selectedText)
      .then(function (result) {
        var explainEl = document.getElementById('explain-result');
        if (explainEl) {
          if (result.error) {
            explainEl.innerHTML = '<p style="color:var(--error);">解释失败: ' + escapeHtml(result.error) + '</p>';
          } else {
            explainEl.innerHTML = renderMarkdown(result.new_content || '无法生成解释');
          }
        }
      })
      .catch(function (e) {
        var explainEl = document.getElementById('explain-result');
        if (explainEl) {
          explainEl.innerHTML = '<p style="color:var(--error);">解释失败: ' + escapeHtml(e.message) + '</p>';
        }
      });
  }

  /* ════════════════════════════════════════════════════════════════
     实时日志流
     ════════════════════════════════════════════════════════════════ */
  function addLog(level, message) {
    var now = new Date();
    var time = now.getHours().toString().padStart(2, '0') + ':' +
               now.getMinutes().toString().padStart(2, '0') + ':' +
               now.getSeconds().toString().padStart(2, '0');
    State.logs.push({ time: time, level: level, message: message });
    if (State.logs.length > 500) State.logs.shift();
    renderLogs();
  }

  function renderLogs() {
    var stream = document.getElementById('log-stream');
    var count = document.getElementById('log-count');
    if (!stream) return;
    if (count) count.textContent = State.logs.length;

    stream.innerHTML = State.logs.map(function (log) {
      return '<div class="log-entry">' +
        '<span class="log-time">' + log.time + '</span>' +
        '<span class="log-level ' + log.level + '">[' + log.level.toUpperCase() + ']</span>' +
        '<span class="log-msg">' + escapeHtml(log.message) + '</span>' +
      '</div>';
    }).join('');

    stream.scrollTop = stream.scrollHeight;
  }

  function initBottomPanel() {
    var toggle = document.getElementById('bottom-panel-toggle');
    var panel = document.getElementById('bottom-panel');
    if (!toggle || !panel) return;

    toggle.addEventListener('click', function () {
      panel.classList.toggle('collapsed');
      State.bottomPanelCollapsed = panel.classList.contains('collapsed');
    });
  }

  /* ════════════════════════════════════════════════════════════════
     Python → JS 回调入口
     ════════════════════════════════════════════════════════════════ */
  function onEvent(eventType, data) {
    console.log('[ScholarPilot] Event:', eventType, data);

    switch (eventType) {
      case 'progress':
        handleProgressEvent(data);
        break;
      case 'step_complete':
        handleStepCompleteEvent(data);
        break;
      case 'error':
        handleErrorEvent(data);
        break;
    }
  }

  function handleProgressEvent(data) {
    State.progressData = data;
    State.generating = data.status !== 'complete' && data.status !== 'error';

    var phase = data.phase || '';
    var phaseInfo = PHASE_MAP[phase];
    var phaseName = phaseInfo ? phaseInfo.name : phase;
    var message = data.message || '';
    var status = data.status || 'progress';

    // 日志
    var logLevel = 'progress';
    if (status === 'error') logLevel = 'error';
    else if (status === 'complete') logLevel = 'success';
    else if (status === 'start') logLevel = 'info';

    addLog(logLevel, '[' + phaseName + '] ' + message);

    // 如果当前在进度页面，更新 UI（debounce 时间线渲染，避免高频重绘）
    if (State.route && State.route.startsWith('#/progress')) {
      renderStatusBar(State.currentProject);
      if (State._timelineRenderTimer) {
        clearTimeout(State._timelineRenderTimer);
      }
      State._timelineRenderTimer = setTimeout(function () {
        State._timelineRenderTimer = null;
        renderTimeline(State.currentProject);
      }, 200);
    }

    // 步骤完成时刷新步骤列表
    if (status === 'complete') {
      refreshSteps(State.currentProject);
    }
  }

  function handleStepCompleteEvent(data) {
    var phase = data.phase || '';
    var phaseInfo = PHASE_MAP[phase];
    var phaseName = phaseInfo ? phaseInfo.name : phase;
    addLog('success', '步骤完成: ' + phaseName);

    // 更新步骤状态
    if (State.steps.length) {
      var step = State.steps.find(function (s) { return s.id === phase; });
      if (step) step.completed = true;
    }

    // 如果当前在进度页面，重新渲染
    if (State.route && State.route.startsWith('#/progress')) {
      renderStatusBar(State.currentProject);
      renderTimeline(State.currentProject);
    }

    // 如果在预览页面且正在查看该步骤，刷新内容
    if (State.route && State.route.startsWith('#/preview') && State.currentPhase === phase) {
      loadStepOutput(State.currentProject, phase);
    }

    // 完成时刷新侧边栏项目列表
    if (phase === 'completed') {
      loadProjects();
      showToast('success', '论文生成完成！');
    }
  }

  function handleErrorEvent(data) {
    var phase = data.phase || '';
    var phaseInfo = PHASE_MAP[phase];
    var phaseName = phaseInfo ? phaseInfo.name : phase;
    var errorMsg = data.error || '未知错误';
    addLog('error', '[' + phaseName + '] 错误: ' + errorMsg);
    showToast('error', '生成错误: ' + errorMsg, 5000);
    State.generating = false;

    if (State.route && State.route.startsWith('#/progress')) {
      renderStatusBar(State.currentProject);
    }
  }

  async function refreshSteps(projectName) {
    if (!projectName) return;
    try {
      var steps = await API.getStepList(projectName);
      if (!steps.error) {
        State.steps = Array.isArray(steps) ? steps : [];
        if (State.route && State.route.startsWith('#/progress')) {
          renderTimeline(projectName);
        }
        if (State.route && State.route.startsWith('#/preview')) {
          renderStepTree(projectName, State.currentPhase);
        }
      }
    } catch (e) { /* ignore */ }
  }

  /* ════════════════════════════════════════════════════════════════
     配置检查
     ════════════════════════════════════════════════════════════════ */
  async function checkConfig() {
    try {
      var config = await API.getConfig();
      if (config.error) throw new Error(config.error);

      var badge = document.getElementById('config-badge');
      var text = document.getElementById('config-text');

      if (config.has_api_key) {
        badge.classList.add('ok');
        badge.classList.remove('warn');
        text.textContent = config.writing_model || '已配置';
      } else {
        badge.classList.add('warn');
        badge.classList.remove('ok');
        text.textContent = '未配置 API Key';
      }
    } catch (e) {
      var text2 = document.getElementById('config-text');
      if (text2) text2.textContent = '配置检查失败';
    }
  }

  /* ════════════════════════════════════════════════════════════════
     导航项点击
     ════════════════════════════════════════════════════════════════ */
  function initSidebarNav() {
    document.querySelectorAll('.nav-item').forEach(function (item) {
      item.addEventListener('click', function () {
        var route = item.getAttribute('data-route');
        if (route) navigate(route);
      });
    });
  }

  /* ════════════════════════════════════════════════════════════════
     初始化
     ════════════════════════════════════════════════════════════════ */
  function init() {
    // 暴露给 Python 调用
    window.app = {
      onEvent: onEvent,
      retryLoadProjects: loadProjects,
    };

    // 初始化 Markdown
    initMarkdown();

    // 初始化 UI 组件
    initSidebarNav();
    initBottomPanel();
    initToolbarButtons();

    // 路由
    window.addEventListener('hashchange', handleRoute);

    // 等待 pywebview API 就绪
    function startApp() {
      State.api = window.pywebview ? window.pywebview.api : null;
      State.ready = true;

      // 初始路由
      if (!window.location.hash) {
        window.location.hash = '#/projects';
      } else {
        handleRoute();
      }

      // 加载项目列表（侧边栏）
      loadProjects();

      // 检查配置
      checkConfig();

      addLog('info', 'ScholarPilot 已就绪');
    }

    if (window.pywebview && window.pywebview.api) {
      // pywebview 已就绪
      startApp();
    } else {
      // 等待 pywebview ready 事件
      window.addEventListener('pywebviewready', function () {
        State.api = window.pywebview.api;
        startApp();
      });

      // 兜底：1.5 秒后如果还没就绪，也尝试启动（开发调试模式）
      setTimeout(function () {
        if (!State.ready) {
          console.warn('pywebview 未就绪，以降级模式启动');
          startApp();
        }
      }, 1500);
    }
  }

  // DOM 就绪后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
