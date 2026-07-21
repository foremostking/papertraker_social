"""ScholarPilot Web UI 统一样式系统.

提供品牌色彩体系、卡片样式、布局组件，
让所有页面保持一致的视觉风格。
"""


def inject_global_styles():
    """注入全局 CSS 样式.

    在每个页面的 main() 开头调用一次。
    """
    import streamlit as st

    st.markdown("""
    <style>
    /* ===== 全局变量 ===== */
    :root {
        --sp-primary: #4F46E5;
        --sp-primary-light: #818CF8;
        --sp-primary-dark: #3730A3;
        --sp-secondary: #0EA5E9;
        --sp-success: #10B981;
        --sp-warning: #F59E0B;
        --sp-danger: #EF4444;
        --sp-bg: #F8FAFC;
        --sp-card-bg: #FFFFFF;
        --sp-border: #E2E8F0;
        --sp-text: #1E293B;
        --sp-text-muted: #64748B;
        --sp-radius: 12px;
        --sp-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
        --sp-shadow-hover: 0 4px 12px rgba(79,70,229,0.15);
    }

    /* ===== 页面背景 ===== */
    .stApp {
        background: var(--sp-bg);
    }

    /* ===== 主内容区 ===== */
    .stMainBlockContainer {
        padding-top: 2rem;
        max-width: 1200px;
    }

    /* ===== 品牌标题 ===== */
    .sp-brand-title {
        font-size: 2rem;
        font-weight: 800;
        background: linear-gradient(135deg, var(--sp-primary) 0%, var(--sp-secondary) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .sp-brand-subtitle {
        font-size: 0.95rem;
        color: var(--sp-text-muted);
        margin-bottom: 1.5rem;
    }

    /* ===== 页面标题 ===== */
    .sp-page-title {
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--sp-text);
        margin-bottom: 0.25rem;
    }
    .sp-page-desc {
        font-size: 0.9rem;
        color: var(--sp-text-muted);
        margin-bottom: 1.5rem;
    }

    /* ===== 卡片 ===== */
    .sp-card {
        background: var(--sp-card-bg);
        border-radius: var(--sp-radius);
        padding: 1.25rem;
        box-shadow: var(--sp-shadow);
        border: 1px solid var(--sp-border);
        transition: box-shadow 0.2s ease, transform 0.2s ease;
        margin-bottom: 1rem;
    }

    /* ===== 项目卡片 ===== */
    .sp-project-card {
        background: var(--sp-card-bg);
        border-radius: var(--sp-radius);
        padding: 1.5rem;
        box-shadow: var(--sp-shadow);
        border: 1px solid var(--sp-border);
        transition: all 0.25s ease;
        height: 100%;
        display: flex;
        flex-direction: column;
        min-height: 200px;
    }
    .sp-project-card:hover {
        box-shadow: var(--sp-shadow-hover);
        transform: translateY(-2px);
        border-color: var(--sp-primary-light);
    }
    .sp-project-card-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: var(--sp-text);
        margin-bottom: 0.5rem;
        line-height: 1.5;
        min-height: 3.3rem;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .sp-project-card-meta {
        font-size: 0.8rem;
        color: var(--sp-text-muted);
        margin-bottom: 0.75rem;
    }
    .sp-project-card-footer {
        margin-top: auto;
    }

    /* ===== 状态徽章 ===== */
    .sp-badge {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .sp-badge-success {
        background: #D1FAE5;
        color: #065F46;
    }
    .sp-badge-warning {
        background: #FEF3C7;
        color: #92400E;
    }
    .sp-badge-info {
        background: #DBEAFE;
        color: #1E40AF;
    }
    .sp-badge-muted {
        background: #F1F5F9;
        color: #475569;
    }

    /* ===== 模板卡片 ===== */
    .sp-template-card {
        background: var(--sp-card-bg);
        border-radius: var(--sp-radius);
        padding: 1.25rem;
        box-shadow: var(--sp-shadow);
        border: 1px solid var(--sp-border);
        border-left: 4px solid var(--sp-primary);
        transition: all 0.2s ease;
        margin-bottom: 0.75rem;
    }
    .sp-template-card:hover {
        border-left-color: var(--sp-secondary);
        box-shadow: var(--sp-shadow-hover);
    }
    .sp-template-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: var(--sp-text);
        margin-bottom: 0.3rem;
    }
    .sp-template-meta {
        font-size: 0.8rem;
        color: var(--sp-text-muted);
        margin-bottom: 0.4rem;
    }
    .sp-template-desc {
        font-size: 0.85rem;
        color: var(--sp-text-muted);
        line-height: 1.5;
    }
    .sp-discipline-label {
        display: inline-block;
        padding: 0.15rem 0.6rem;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        background: linear-gradient(135deg, var(--sp-primary) 0%, var(--sp-secondary) 100%);
        color: white;
        margin-bottom: 0.75rem;
    }

    /* ===== 质量指标 ===== */
    .sp-metric {
        background: var(--sp-card-bg);
        border-radius: var(--sp-radius);
        padding: 1rem;
        box-shadow: var(--sp-shadow);
        border: 1px solid var(--sp-border);
        text-align: center;
    }
    .sp-metric-value {
        font-size: 1.5rem;
        font-weight: 800;
        color: var(--sp-primary);
    }
    .sp-metric-label {
        font-size: 0.78rem;
        color: var(--sp-text-muted);
        margin-top: 0.2rem;
    }

    /* ===== 进度条 ===== */
    .stProgress > div > div {
        background: linear-gradient(90deg, var(--sp-primary) 0%, var(--sp-secondary) 100%);
    }

    /* ===== 侧边栏 ===== */
    section[data-testid="stSidebar"] {
        background: white;
        border-right: 1px solid var(--sp-border);
    }
    section[data-testid="stSidebar"] .stMarkdown h2 {
        font-size: 1.3rem;
        font-weight: 800;
        background: linear-gradient(135deg, var(--sp-primary) 0%, var(--sp-secondary) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    /* ===== 按钮样式 ===== */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(79,70,229,0.2);
    }

    /* ===== Tab 样式 ===== */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 1rem;
    }

    /* ===== 分割线 ===== */
    .sp-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent, var(--sp-border), transparent);
        margin: 1.5rem 0;
    }

    /* ===== 空状态 ===== */
    .sp-empty-state {
        text-align: center;
        padding: 3rem 1rem;
        color: var(--sp-text-muted);
    }
    .sp-empty-state-icon {
        font-size: 3rem;
        margin-bottom: 1rem;
        opacity: 0.5;
    }

    /* ===== 设置项 ===== */
    .sp-setting-group {
        background: var(--sp-card-bg);
        border-radius: var(--sp-radius);
        padding: 1rem 1.25rem;
        box-shadow: var(--sp-shadow);
        border: 1px solid var(--sp-border);
        margin-bottom: 0.75rem;
    }
    .sp-setting-title {
        font-size: 1rem;
        font-weight: 700;
        color: var(--sp-text);
        margin-bottom: 0.5rem;
    }
    .sp-setting-status {
        font-size: 0.8rem;
        font-weight: 600;
    }
    .sp-setting-status-ok {
        color: var(--sp-success);
    }
    .sp-setting-status-missing {
        color: var(--sp-text-muted);
    }
    </style>
    """, unsafe_allow_html=True)


def brand_header(subtitle: str = ""):
    """渲染品牌头部."""
    import streamlit as st
    st.markdown(f"""
    <div class="sp-brand-title">ScholarPilot</div>
    <div class="sp-brand-subtitle">{subtitle or "AI 辅助学术研究全流程工具"}</div>
    """, unsafe_allow_html=True)


def page_header(title: str, desc: str = ""):
    """渲染页面标题."""
    import streamlit as st
    st.markdown(f"""
    <div class="sp-page-title">{title}</div>
    {f'<div class="sp-page-desc">{desc}</div>' if desc else ''}
    """, unsafe_allow_html=True)


def project_card_html(title: str, name: str, status_html: str, progress_html: str) -> str:
    """生成项目卡片的 HTML."""
    return f"""
    <div class="sp-project-card">
        <div class="sp-project-card-title">{title}</div>
        <div class="sp-project-card-meta">项目名：{name}</div>
        {status_html}
        {progress_html}
    </div>
    """


def badge(text: str, kind: str = "info") -> str:
    """生成状态徽章 HTML."""
    return f'<span class="sp-badge sp-badge-{kind}">{text}</span>'


def empty_state(icon: str, message: str) -> str:
    """生成空状态 HTML."""
    return f"""
    <div class="sp-empty-state">
        <div class="sp-empty-state-icon">{icon}</div>
        <div>{message}</div>
    </div>
    """


def metric_card(value: str, label: str) -> str:
    """生成质量指标卡片 HTML."""
    return f"""
    <div class="sp-metric">
        <div class="sp-metric-value">{value}</div>
        <div class="sp-metric-label">{label}</div>
    </div>
    """
