"""ScholarPilot Web UI — Streamlit 应用主入口.

让研究者通过浏览器使用 ScholarPilot 的全部能力，
无需安装 CLI、无需配置环境，打开即用。

启动方式：
    streamlit run src/scholarpilot/web/app.py
"""
import sys
from pathlib import Path

# 确保能导入 scholarpilot 包
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from scholarpilot.config import get_settings
from scholarpilot.web.styles import (
    inject_global_styles, brand_header, page_header,
    project_card_html, badge, empty_state,
)


def main():
    st.set_page_config(
        page_title="ScholarPilot — AI学术研究助手",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ===== 全局样式 =====
    inject_global_styles()

    # ===== 侧边栏 =====
    settings = get_settings()
    has_api_key = bool(
        settings.zhipu_api_key or settings.ark_api_key
        or settings.claude_api_key or settings.openai_api_key
    )

    with st.sidebar:
        st.markdown("## 🎓 ScholarPilot")
        st.caption("AI 辅助学术研究全流程工具")
        st.divider()

        # 配置状态
        if has_api_key:
            st.success("✓ API Key 已配置")
            model = settings.default_writing_model or "未设置"
            st.caption(f"写作模型：`{model}`")
        else:
            st.warning("⚠️ 尚未配置 API Key")
            st.caption("请先前往「设置」页面配置")

        st.divider()

        page = st.radio(
            "导航",
            ["📋 项目列表", "➕ 创建项目", "⚙️ 设置"],
            index=0,
            label_visibility="collapsed",
        )

        st.divider()
        st.caption("ScholarPilot v0.1.0")

    # ===== 路由 =====
    if page == "📋 项目列表":
        show_project_list()
    elif page == "➕ 创建项目":
        show_create_project()
    elif page == "⚙️ 设置":
        show_settings()


def show_project_list():
    """项目列表页."""
    page_header("我的论文项目", "管理你的所有研究项目")

    from scholarpilot.cli import _get_file_manager
    fm = _get_file_manager()
    project_names = fm.list_projects()

    if not project_names:
        st.markdown(empty_state("📝", "还没有项目，点击左侧「创建项目」开始你的第一篇论文！"), unsafe_allow_html=True)
        return

    # 项目卡片网格
    cols = st.columns(3)
    for idx, name in enumerate(project_names):
        project_dir = fm.get_project_dir(name)
        if project_dir:
            with cols[idx % 3]:
                _render_project_card(name, project_dir)


def _render_project_card(name, project_dir):
    """渲染单个项目卡片."""
    from scholarpilot.cli import _get_file_manager
    from scholarpilot.web.styles import badge
    fm = _get_file_manager()
    project_dir = Path(project_dir)

    meta = fm.get_project_meta(project_dir) or {}
    state = _load_state(project_dir)

    title = meta.get("title", name)
    status = state.get("current_phase", "unknown")
    completed_phases = state.get("completed_phases", [])
    total_sections = state.get("total_sections", 0)
    done_sections = len(state.get("completed_sections", []))
    is_completed = status == "completed"

    # 状态徽章
    if is_completed:
        status_badge = badge("✅ 已完成", "success")
    elif status == "unknown":
        status_badge = badge("📌 未开始", "muted")
    else:
        status_badge = badge("🔄 生成中", "warning")

    # 进度信息
    if total_sections > 0:
        progress = done_sections / total_sections
        progress_html = f'<div style="font-size:0.8rem;color:#64748B;margin-top:0.5rem;">章节进度 {done_sections}/{total_sections}</div>'
    else:
        progress_html = ""

    # 渲染卡片
    st.markdown(
        project_card_html(title, name, status_badge, progress_html),
        unsafe_allow_html=True
    )

    # 进度条
    if total_sections > 0:
        st.progress(progress)

    # 操作按钮——已完成项目只显示"查看结果"，未完成显示"查看详情"+"继续生成"
    if is_completed:
        if st.button("📄 查看结果", key=f"result_{name}", use_container_width=True,
                     type="primary"):
            st.session_state["selected_project"] = name
            st.session_state["action"] = "results"
            st.switch_page("pages/project_detail.py")
    else:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("查看详情", key=f"detail_{name}", use_container_width=True):
                st.session_state["selected_project"] = name
                st.session_state["action"] = "view"
                st.switch_page("pages/project_detail.py")
        with col2:
            if st.button("继续生成", key=f"continue_{name}", use_container_width=True,
                         type="primary"):
                st.session_state["selected_project"] = name
                st.session_state["action"] = "continue"
                st.switch_page("pages/project_detail.py")


def show_create_project():
    """创建项目页."""
    page_header("创建新项目", "选择模板或自定义研究主题")

    tab1, tab2 = st.tabs(["📝 从模板创建", "✏️ 自定义创建"])

    # ===== Tab1: 模板创建 =====
    with tab1:
        from scholarpilot.cli import _get_example_templates
        templates = _get_example_templates()

        # 按学科分组
        disciplines = {}
        for t in templates:
            disciplines.setdefault(t["discipline"], []).append(t)

        selected_template = None
        for disc, items in disciplines.items():
            st.markdown(f'<span class="sp-discipline-label">{disc}</span>', unsafe_allow_html=True)

            for t in items:
                # 模板卡片
                st.markdown(f"""
                <div class="sp-template-card">
                    <div class="sp-template-title">{t['title']}</div>
                    <div class="sp-template-meta">
                        研究类型：{t.get('research_type', '—')} |
                        期刊级别：{t.get('journal_level', '—')} |
                        数据来源：{t.get('data_source', '—')}
                    </div>
                    <div class="sp-template-desc">{t['description'][:120]}...</div>
                </div>
                """, unsafe_allow_html=True)

                if st.button("选择此模板", key=f"tpl_{t['id']}", use_container_width=True):
                    st.session_state["selected_template"] = t
                    st.rerun()

            st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

        if "selected_template" in st.session_state:
            t = st.session_state["selected_template"]
            st.success(f"已选择模板：{t['title']}")

            project_name = st.text_input(
                "项目名称",
                value=f"paper_{t['id'].split('-')[0]}",
                help="英文+数字+下划线，如 debt_paper"
            )

            if st.button("🚀 创建项目并开始", type="primary", use_container_width=True):
                _create_project_from_template(project_name, t)

    # ===== Tab2: 自定义创建 =====
    with tab2:
        st.markdown("<div class='sp-page-desc'>手动输入研究主题，自由创建项目</div>", unsafe_allow_html=True)

        project_name = st.text_input("项目名称", value="", help="英文+数字+下划线")
        research_topic = st.text_area(
            "研究主题描述",
            value="",
            height=120,
            help="详细描述你的研究想法，包括：研究问题、研究对象、研究方法、数据来源等。描述越详细，生成质量越高。"
        )

        col1, col2 = st.columns(2)
        with col1:
            journal = st.text_input("目标期刊（可选）", value="")
        with col2:
            research_type = st.selectbox("研究类型", ["", "实证研究", "理论研究", "综述研究", "案例研究"])

        if st.button("🚀 创建项目", type="primary", use_container_width=True):
            if not project_name.strip():
                st.error("请输入项目名称")
            elif not research_topic.strip():
                st.error("请输入研究主题描述")
            else:
                _create_project_custom(project_name, research_topic, journal, research_type)


def _create_project_from_template(project_name, template):
    """从模板创建项目."""
    from scholarpilot.cli import _get_file_manager
    fm = _get_file_manager()

    if fm.get_project_dir(project_name):
        st.error(f"项目已存在：{project_name}")
        return

    project_dir = fm.create_project(project_name)
    fm.update_project_meta(project_dir, {
        "title": template["title"],
        "research_type": template.get("research_type", ""),
    })

    # 写入模板描述到 SPEC.md
    spec_path = project_dir / "SPEC.md"
    if spec_path.exists():
        content = spec_path.read_text(encoding="utf-8")
        content += f"\n\n<!-- 模板: {template['id']} -->\n"
        content += f"<!-- 研究主题: {template['description']} -->\n"
        spec_path.write_text(content, encoding="utf-8")

    st.success(f"✅ 项目创建成功：{project_name}")
    st.session_state["selected_project"] = project_name
    st.session_state["action"] = "start"
    st.balloons()
    st.info("即将跳转到项目详情页，点击「开始生成」即可启动论文写作流程。")
    st.switch_page("pages/project_detail.py")


def _create_project_custom(project_name, research_topic, journal, research_type):
    """自定义创建项目."""
    from scholarpilot.cli import _get_file_manager
    fm = _get_file_manager()

    if fm.get_project_dir(project_name):
        st.error(f"项目已存在：{project_name}")
        return

    project_dir = fm.create_project(project_name)
    meta = {}
    if journal:
        meta["target_journal"] = journal
    if research_type:
        meta["research_type"] = research_type
    if meta:
        fm.update_project_meta(project_dir, meta)

    # 写入研究主题到 SPEC.md
    spec_path = project_dir / "SPEC.md"
    if spec_path.exists():
        content = spec_path.read_text(encoding="utf-8")
        content += f"\n\n<!-- 研究主题: {research_topic} -->\n"
        spec_path.write_text(content, encoding="utf-8")

    st.success(f"✅ 项目创建成功：{project_name}")
    st.session_state["selected_project"] = project_name
    st.session_state["action"] = "start"
    st.balloons()
    st.switch_page("pages/project_detail.py")


def show_settings():
    """设置页."""
    page_header("设置", "配置 LLM API Key 和模型参数")

    settings = get_settings()

    # ===== API Key 配置 =====
    st.markdown("### 🔑 LLM API Key 配置")

    providers = [
        ("智谱 GLM-4（推荐）", "zhipu", settings.zhipu_api_key, "SCHOLAR_ZHIPU_API_KEY",
         "https://open.bigmodel.cn"),
        ("火山方舟", "ark", settings.ark_api_key, "SCHOLAR_ARK_API_KEY",
         "https://www.volcengine.com/product/ark"),
        ("Claude", "claude", settings.claude_api_key, "SCHOLAR_CLAUDE_API_KEY",
         "https://console.anthropic.com"),
        ("OpenAI", "openai", settings.openai_api_key, "SCHOLAR_OPENAI_API_KEY",
         "https://platform.openai.com"),
        ("DeepSeek", "deepseek", settings.deepseek_api_key, "SCHOLAR_DEEPSEEK_API_KEY",
         "https://platform.deepseek.com"),
    ]

    for name, key, current_val, env_key, url in providers:
        status_class = "sp-setting-status-ok" if current_val else "sp-setting-status-missing"
        status_text = "✓ 已配置" if current_val else "✗ 未配置"

        st.markdown(f"""
        <div class="sp-setting-group">
            <div class="sp-setting-title">{name}</div>
            <div class="sp-setting-status {status_class}">{status_text}</div>
            <div style="font-size:0.78rem;color:#64748B;margin-top:0.3rem;">
                获取 API Key：<a href="{url}" target="_blank">{url}</a>
            </div>
        </div>
        """, unsafe_allow_html=True)

        input_val = st.text_input(
            "API Key",
            value=current_val if current_val else "",
            type="password",
            key=f"input_{key}",
            label_visibility="collapsed",
        )
        if st.button("保存", key=f"save_{key}"):
            if input_val.strip():
                _update_env_var(env_key, input_val.strip())
                st.success(f"{name} API Key 已保存")
                st.rerun()
            else:
                st.error("API Key 不能为空")

    st.markdown("<div class='sp-divider'></div>", unsafe_allow_html=True)

    # ===== 模型配置 =====
    st.markdown("### 🤖 默认模型配置")

    col1, col2, col3 = st.columns(3)
    with col1:
        writing = st.text_input("写作模型", value=settings.default_writing_model or "glm-4")
    with col2:
        analysis = st.text_input("分析模型", value=settings.default_analysis_model or "glm-4")
    with col3:
        casual = st.text_input("轻量模型", value=settings.default_casual_model or "glm-4")

    if st.button("保存模型配置"):
        _update_env_var("SCHOLAR_DEFAULT_WRITING_MODEL", writing)
        _update_env_var("SCHOLAR_DEFAULT_ANALYSIS_MODEL", analysis)
        _update_env_var("SCHOLAR_DEFAULT_CASUAL_MODEL", casual)
        st.success("模型配置已保存，重启应用后生效")
        st.rerun()

    st.markdown("<div class='sp-divider'></div>", unsafe_allow_html=True)

    # ===== Semantic Scholar =====
    st.markdown("### 📚 文献检索配置")
    ss_key = st.text_input(
        "Semantic Scholar API Key（可选，避免限流）",
        value=settings.ss_api_key or "",
        type="password",
    )
    if st.button("保存文献检索配置"):
        _update_env_var("SCHOLAR_SS_API_KEY", ss_key.strip())
        st.success("配置已保存")
        st.rerun()


def _load_state(project_dir):
    """加载项目状态."""
    import json
    state_path = Path(project_dir) / ".scholar" / "state.json"
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _update_env_var(key, value):
    """更新 .env 文件."""
    from scholarpilot.config import _find_env_file
    env_path = _find_env_file()

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
