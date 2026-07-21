"""项目详情页 — 查看进度、启动生成、查看结果."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
import json
import threading
import time
import streamlit as st
from datetime import datetime

from scholarpilot.config import get_settings
from scholarpilot.web.styles import inject_global_styles, page_header, metric_card


def main():
    st.set_page_config(
        page_title="项目详情 — ScholarPilot",
        page_icon="🎓",
        layout="wide",
    )

    inject_global_styles()

    # 检查是否选中了项目
    if "selected_project" not in st.session_state:
        st.error("未选择项目，请先从项目列表选择")
        if st.button("← 返回列表"):
            st.switch_page("app.py")
        return

    project_name = st.session_state["selected_project"]
    action = st.session_state.get("action", "")

    from scholarpilot.cli import _get_file_manager
    fm = _get_file_manager()
    project_dir = fm.get_project_dir(project_name)

    if not project_dir:
        st.error(f"项目不存在：{project_name}")
        return

    # 加载项目信息
    meta = fm.get_project_meta(project_dir) or {}
    state = _load_state(project_dir)

    # ===== 页头 =====
    title = meta.get("title", project_name)
    created = meta.get("created_at", "—")
    if isinstance(created, str) and "T" in created:
        created = created.split("T")[0]

    # 返回按钮——用 Streamlit 按钮而非 HTML 链接，避免新开页面
    if st.button("← 返回列表", key="back_to_list"):
        st.switch_page("app.py")

    st.markdown(f"""
    <div class="sp-page-title">{title}</div>
    <div class="sp-page-desc">项目名：{project_name} | 创建时间：{created}</div>
    """, unsafe_allow_html=True)

    # ===== 检查 API Key =====
    settings = get_settings()
    has_api_key = bool(
        settings.zhipu_api_key or settings.ark_api_key
        or settings.claude_api_key or settings.openai_api_key
    )
    if not has_api_key:
        st.error("⚠️ 尚未配置 API Key，请先前往设置页面配置")
        if st.button("前往设置"):
            st.switch_page("app.py")
        return

    # ===== 生成控制 =====
    current_phase = state.get("current_phase", "")
    completed_phases = state.get("completed_phases", [])
    is_completed = current_phase == "completed" or "completed" in completed_phases

    if action == "start" or (not completed_phases and not current_phase):
        show_start_panel(project_name, project_dir)
    elif action == "results" or is_completed:
        show_results_panel(project_name, project_dir)
    elif action == "continue" or current_phase:
        show_progress_panel(project_name, project_dir)
    else:
        show_results_panel(project_name, project_dir)

    # ===== 实时刷新 =====
    if "generating" in st.session_state and st.session_state["generating"]:
        time.sleep(3)
        st.rerun()


def show_start_panel(project_name, project_dir):
    """开始生成面板."""
    st.markdown("### 🚀 开始生成论文")

    # 检查是否有预填研究主题
    spec_path = project_dir / "SPEC.md"
    prefill_topic = ""
    if spec_path.exists():
        import re
        content = spec_path.read_text(encoding="utf-8")
        match = re.search(r'<!--\s*研究主题:\s*(.+?)\s*-->', content)
        if match:
            prefill_topic = match.group(1).strip()

    if prefill_topic:
        st.info("📝 检测到预填的研究主题：")
        st.text_area("研究主题", value=prefill_topic, height=100, key="research_topic_input")
    else:
        st.text_area(
            "输入您的研究想法",
            value="",
            height=120,
            key="research_topic_input",
            help="详细描述研究问题、对象、方法、数据来源等"
        )

    col1, col2 = st.columns([1, 3])
    with col1:
        non_interactive = st.checkbox("非交互模式", value=True)
    with col2:
        st.caption("💡 非交互模式全程自动，约 10-12 分钟完成")

    if st.button("🚀 开始生成", type="primary", use_container_width=True):
        topic = st.session_state.get("research_topic_input", prefill_topic)
        if not topic.strip():
            st.error("请输入研究主题")
            return

        _start_generation(project_name, project_dir, topic, non_interactive)
        st.session_state["generating"] = True
        st.rerun()


def show_progress_panel(project_name, project_dir):
    """进度展示面板."""
    st.markdown("### 🔄 生成进度")

    state = _load_state(project_dir)
    current_phase = state.get("current_phase", "")
    completed_phases = state.get("completed_phases", [])
    completed_sections = state.get("completed_sections", [])
    total_sections = state.get("total_sections", 0)

    phase_labels = {
        "topic_analysis": "选题分析",
        "literature_search": "文献检索",
        "spec_generation": "规格生成",
        "outline": "大纲生成",
        "data_collection": "数据采集",
        "section_writing": "逐章撰写",
        "citation_verification": "引用验证",
        "deai_polish": "去AI味+润色",
        "post_processing": "后处理",
        "completed": "已完成",
    }

    all_phases = list(phase_labels.keys())

    # 阶段进度
    st.markdown("#### 阶段进度")
    all_done = current_phase == "completed"
    phase_cols = st.columns(len(all_phases))
    for i, phase in enumerate(all_phases):
        label = phase_labels.get(phase, phase)
        with phase_cols[i]:
            if phase in completed_phases or all_done:
                st.success(label, icon="✅")
            elif phase == current_phase:
                st.warning(label, icon="🔄")
            else:
                st.caption(f"⏳ {label}")

    # 章节进度
    if total_sections > 0:
        st.markdown("#### 章节进度")
        progress = len(completed_sections) / total_sections
        st.progress(progress, text=f"{len(completed_sections)}/{total_sections} 章已完成")

        for sec in completed_sections:
            st.caption(f"  ✅ {sec}")

    # 文献检索统计
    from scholarpilot.cli import _get_file_manager
    fm = _get_file_manager()
    memory = fm.load_memory(project_dir) or {}
    lit_sources = memory.get("entries", {}).get("literature_sources", {}).get("value", {})
    if lit_sources:
        st.markdown("#### 文献检索统计")
        cnki = lit_sources.get("cnki_count", 0)
        ncpssd = lit_sources.get("ncpssd_count", 0)
        openalex = lit_sources.get("openalex_count", 0)
        ss = lit_sources.get("ss_count", 0)
        total = cnki + ncpssd + openalex + ss

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("CNKI", cnki)
        with col2:
            st.metric("NCPSSD", ncpssd)
        with col3:
            st.metric("OpenAlex", openalex)
        with col4:
            st.metric("总计", total)

    # 生成日志
    log_path = project_dir / ".scholar" / "generation.log"
    if log_path.exists():
        with st.expander("📝 生成日志"):
            log_content = log_path.read_text(encoding="utf-8")
            st.code(log_content[-3000:], language="text")

    # 完成判断
    if current_phase == "completed" or "completed" in completed_phases:
        st.session_state["generating"] = False
        st.balloons()
        st.success("🎉 论文生成完成！")
        if st.button("📋 查看结果", type="primary", use_container_width=True):
            st.session_state["action"] = "results"
            st.rerun()


def show_results_panel(project_name, project_dir):
    """结果展示面板."""
    st.markdown("### 📋 论文结果")

    draft_dir = project_dir / "draft"
    state = _load_state(project_dir)

    # ===== 质量指标卡片 =====
    full_draft = draft_dir / "full_draft.md"
    polished = draft_dir / "full_draft_polished.md"

    from scholarpilot.cli import _get_file_manager
    fm = _get_file_manager()
    memory = fm.load_memory(project_dir) or {}
    cit_mgmt = memory.get("entries", {}).get("citation_management", {}).get("value", {})

    # 获取指标值
    draft_chars = len(full_draft.read_text(encoding="utf-8")) if full_draft.exists() else 0
    polished_chars = len(polished.read_text(encoding="utf-8")) if polished.exists() else 0
    cit_total = cit_mgmt.get("total", 0) if cit_mgmt else 0
    cit_verified = cit_mgmt.get("verified", 0) if cit_mgmt else 0
    deai_risk = state.get("deai_risk_after", 0)
    if isinstance(deai_risk, dict):
        deai_risk = deai_risk.get("score", 0)

    # 渲染指标卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(metric_card(f"{draft_chars:,}", "论文字数"), unsafe_allow_html=True)
    with col2:
        st.markdown(metric_card(f"{polished_chars:,}", "润色后字数"), unsafe_allow_html=True)
    with col3:
        cit_text = f"{cit_verified}/{cit_total}" if cit_total > 0 else "—"
        st.markdown(metric_card(cit_text, "引用验证"), unsafe_allow_html=True)
    with col4:
        risk_text = f"{deai_risk:.0f}%" if deai_risk else "—"
        st.markdown(metric_card(risk_text, "去AI味风险"), unsafe_allow_html=True)

    st.markdown("<div class='sp-divider'></div>", unsafe_allow_html=True)

    # ===== 内容标签页 =====
    tab1, tab2, tab3, tab4 = st.tabs(["📄 论文正文", "📚 参考文献", "📊 质量报告", "📥 导出"])

    with tab1:
        show_file = polished if polished.exists() else full_draft
        if show_file.exists():
            content = show_file.read_text(encoding="utf-8")
            st.markdown(_clean_markdown(content))
        else:
            st.info("论文正文尚未生成")

    with tab2:
        ref_path = draft_dir / "references.md"
        if ref_path.exists():
            content = ref_path.read_text(encoding="utf-8")
            st.markdown(_clean_markdown(content))
        else:
            st.info("参考文献尚未生成")

    with tab3:
        deai_report = draft_dir / "deai_report.md"
        if deai_report.exists():
            content = deai_report.read_text(encoding="utf-8")
            st.markdown(content)
        else:
            st.info("质量报告尚未生成")

    with tab4:
        st.markdown("#### 导出论文")

        export_formats = [
            ("Word (.docx)", "docx"),
            ("PDF", "pdf"),
            ("LaTeX", "latex"),
            ("Markdown", "md"),
        ]

        col1, col2 = st.columns(2)
        for label, fmt in export_formats:
            with col1 if fmt in ("docx", "pdf") else col2:
                if st.button(f"导出 {label}", key=f"export_{fmt}", use_container_width=True):
                    _export_project(project_name, project_dir, fmt)

        # 已导出的文件
        final_dir = project_dir / "final"
        if final_dir.exists():
            st.markdown("##### 已导出的文件")
            for f in final_dir.iterdir():
                if f.is_file():
                    size_kb = f.stat().st_size / 1024
                    st.write(f"📄 {f.name} ({size_kb:.1f} KB)")
                    with open(f, "rb") as fp:
                        st.download_button(
                            f"下载 {f.name}",
                            fp,
                            file_name=f.name,
                            key=f"download_{f.name}",
                            use_container_width=True,
                        )


def _start_generation(project_name, project_dir, topic, non_interactive):
    """在后台线程启动论文生成."""
    def run_agent():
        import os
        os.environ["SCHOLAR_NON_INTERACTIVE"] = "true" if non_interactive else "false"

        from scholarpilot.agent.scholar import ScholarAgent
        agent = ScholarAgent(project_dir=project_dir)
        if non_interactive:
            agent.non_interactive = True

        try:
            asyncio.run(agent.run(topic))
        except Exception as e:
            state_path = project_dir / ".scholar" / "state.json"
            if state_path.exists():
                state = json.loads(state_path.read_text(encoding="utf-8"))
            else:
                state = {}
            state["error"] = str(e)
            state["error_time"] = datetime.now().isoformat()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()
    st.session_state["generation_thread"] = thread


def _export_project(project_name, project_dir, fmt):
    """导出项目."""
    try:
        from scholarpilot.tools.exporter import export_project
        output_path = export_project(project_dir, fmt=fmt)
        st.success(f"导出成功：{output_path}")
    except Exception as e:
        st.error(f"导出失败：{e}")


def _load_state(project_dir):
    """加载项目状态."""
    state_path = Path(project_dir) / ".scholar" / "state.json"
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _clean_markdown(content: str) -> str:
    """预处理 Markdown 内容，修复格式问题.

    1. 替换 AI 腔词为学术规范词（拆解→分析、波及→影响等）
    2. 去除模型思考痕迹（——在笔者看来等）
    3. 修复双句号 。。 和分号句号 ；。
    4. 在 ### 子标题前换行
    5. 在句号后换行使段落更清晰
    6. 分离摘要区域的元数据标签
    """
    import re

    # ===== 0. 替换 AI 腔词为学术规范词 =====
    ai_word_map = {
        # 标题级替换
        "拆解来龙去脉": "文献综述与研究背景",
        "审视困境": "研究问题",
        "拆解渊源": "研究背景",
        "考察难题": "研究问题",
        # 组合词替换（先替换长词，避免被短词覆盖）
        "框架意义": "理论意义",
        "手段意义": "方法意义",
        "模式机制": "理论机制",
        "文献综述与模式机制": "文献综述与理论机制",
        "波及规律": "影响规律",
        "波及方向": "影响方向",
        "辐射运作方式": "影响机制",
        "辐射机理": "影响机制",
        "冲击机制": "影响机制",
        "冲击要素": "影响因素",
        "运作方式": "机制",
        "传导路径": "机制",
        "根基设施": "基础设施",
        "开辟水平": "发展水平",
        # 单词替换（放在组合词之后）
        "来龙去脉": "背景",
        "波及": "影响",
        "辐射": "影响",
        "商榷": "探讨",
        "拆解": "分析",
        "审视": "研究",
        "剖析": "分析",
        "解读": "分析",
        "考察": "研究",
        "素材": "数据",
        "材料": "数据",
        "开辟": "发展",
        "延伸": "发展",
        "演化": "发展",
        "架构": "理论",
        "架构意义": "理论意义",
        "枢纽": "核心",
        "界域": "领域",
        "范型": "模式",
        "范式": "模式",
        "须要": "需要",
        "有赖于": "需要",
        "仰赖": "依赖",
        "断言": "认为",
        "主张": "认为",
        "申明": "指出",
        "疆域": "领域",
        "脉络": "路径",
        "溯源": "追溯",
        "肇因": "原因",
        "动因": "因素",
        "驱动力": "动力",
        "催化": "促进",
        "嬗变": "转变",
        "蜕变": "转变",
        "孕育": "培养",
        "孵化": "培育",
        "涵养": "培养",
        "削减": "减少",
        "压缩": "降低",
        "斩获": "获得",
        "收获": "获得",
        "察觉": "发现",
        "发觉": "发现",
        "探寻": "探索",
        "求索": "探索",
        "明证": "证明",
        "确证": "证实",
        "校验": "验证",
        "比照": "比较",
        "较量": "比较",
        "更动": "改变",
        "瞩目": "关注",
        "关切": "关注",
        "凸显": "突出",
        "捍卫": "保障",
        "守护": "保障",
        "唤起": "激发",
        "点燃": "激发",
        "催生": "推动",
        "聚合": "整合",
        "汇编": "整合",
        "因应": "应对",
        "周旋": "应对",
        "培植": "培育",
        "拓宽": "拓展",
        "描摹": "描述",
        "勾勒": "刻画",
        "提炼": "总结",
        "趋向": "趋势",
        "态势": "趋势",
        "特质": "特征",
        "表征": "特征",
        "运作方式": "机制",
        "传导路径": "机制",
        "机理": "机制",
        "长处": "优势",
        "优越性": "优势",
        "利好": "优势",
        "强项": "优势",
        "短板": "劣势",
        "弱项": "劣势",
        "骨架": "框架",
        "脉络": "框架",
        "语境": "背景",
        "情境": "背景",
        "渊源": "背景",
        "要件": "条件",
        "凭借": "条件",
        "历程": "过程",
        "轨迹": "过程",
        "范畴": "领域",
        "侧面": "层面",
        "层级": "层次",
        "中枢": "核心",
        "要旨": "核心",
        "底座": "基础",
        "基石": "基础",
        "标尺": "标准",
        "尺度": "标准",
        "功用": "功能",
        "职能": "功能",
        "构造": "结构",
        "格局": "结构",
        "样式": "模式",
        "形态": "模式",
        "效用": "效果",
        "产出": "效果",
        "成果": "结果",
        "判断": "结论",
        "判定": "结论",
        "推断": "结论",
        "走向": "趋势",
        "动向": "趋势",
        "见解": "观点",
        "论点": "观点",
        "学说": "理论",
        "信息": "数据",
        "论断": "结论",
        "论析": "分析",
        "探究": "研究",
        "研讨": "研究",
    }
    for ai_word, academic_word in ai_word_map.items():
        content = content.replace(ai_word, academic_word)

    # ===== 1. 去除模型思考痕迹 =====
    content = re.sub(r'——在笔者看来[，,]?这一点值得进一步讨论。*', '', content)
    content = re.sub(r'——笔者主张[，,]?这一点值得进一步讨论。*', '', content)
    content = re.sub(r'——笔者认为[，,]?这一点值得进一步讨论。*', '', content)
    content = re.sub(r'——从\w*实践来看[，,]?这一点值得进一步讨论。*', '', content)
    # 通用模式：——XX，这一点值得进一步讨论
    content = re.sub(r'——[^。\n]{2,10}[，,]?这一点值得进一步讨论。*', '', content)
    # 去除括号注释
    content = re.sub(r'（此处[须需]要[^）]*）', '', content)
    content = re.sub(r'（当然这只是[^）]*）', '', content)
    content = re.sub(r'（这一点在后续[^）]*）', '', content)
    # 去除残留的破折号开头空句
    content = re.sub(r'\n——。\n', '\n', content)
    content = re.sub(r'——。\s*', '', content)

    # ===== 2. 修复双句号 。。→。 =====
    content = re.sub(r'。{2,}', '。', content)

    # ===== 3. 修复 ；。→； =====
    content = re.sub(r'；。', '；', content)
    content = re.sub(r'：。', '：', content)

    # ===== 4. 在行内的 ### 子标题前插入换行 =====
    content = re.sub(r'(?<!\n)(#{1,4}\s)', r'\n\n\1', content)

    # ===== 5. 在引用块 > 前换行 =====
    content = re.sub(r'(?<!\n)(>\s)', r'\n\1', content)

    # ===== 6. 在 - 列表项前换行（行内的） =====
    content = re.sub(r'(?<=。)(-\s)', r'\n\1', content)

    # ===== 7. 分离摘要区域的元数据标签 =====
    # "【英文关键词】" "【中图分类号】" "【JEL分类号】" 等标签前换行
    content = re.sub(r'(?<!\n)(\*\*【)', r'\n\n\1', content)

    # ===== 8. 在句号后换行 =====
    lines = content.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # 保留空行、代码块、公式行、表格行不变
        if (stripped == '' or stripped.startswith('```') or
            stripped.startswith('$$') or stripped.startswith('|')):
            cleaned_lines.append(line)
            continue

        # 在句号后换行（中文句号。后跟非标点字符时）
        parts = re.split(r'。(?=[^\s。，；：、）\]\}】》\d\-])', line)
        if len(parts) > 1:
            new_parts = []
            for i, p in enumerate(parts):
                p = p.strip()
                if p:
                    if i < len(parts) - 1:
                        new_parts.append(p + '。')
                    else:
                        new_parts.append(p)
            cleaned_lines.append('\n'.join(new_parts))
        else:
            cleaned_lines.append(line)

    result = '\n'.join(cleaned_lines)

    # ===== 9. 修复空行过多 =====
    result = re.sub(r'\n{4,}', '\n\n\n', result)

    # ===== 10. 修复标题末尾的句号 =====
    result = re.sub(r'^(#{1,4}\s.+?)。+$', r'\1', result, flags=re.MULTILINE)

    return result


if __name__ == "__main__":
    main()
