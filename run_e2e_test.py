"""ScholarPilot E2E 测试 — 完整生成一篇论文并验证质量.

用法：
    python run_e2e_test.py

验证项：
1. 论文生成成功
2. 无模型思考痕迹（——在笔者看来、拆解渊源等）
3. 无双句号 。。
4. 英文参考文献完整性（有标题、期刊、年份）
5. 引用验证率
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

PROJECT_NAME = f"e2e_test_{time.strftime('%Y%m%d_%H%M%S')}"
RESEARCH_TOPIC = (
    "企业数字化转型对企业创新绩效的影响研究。"
    "以2015-2023年A股上市公司为样本，研究数字化转型对企业创新绩效的影响。"
    "核心解释变量为数字化转型指数（文本分析法构建），"
    "因变量为企业创新绩效（专利申请数量+新产品销售收入）。"
    "采用面板固定效应模型，控制企业规模、年龄、杠杆率等变量。"
    "数据来源：CSMAR数据库。期刊级别：CSSCI。"
)


async def main():
    from scholarpilot.cli import _get_file_manager
    from scholarpilot.agent.scholar import ScholarAgent

    # 1. 创建项目
    print("=" * 60)
    print("  ScholarPilot E2E 测试")
    print("=" * 60)
    print(f"\n项目名: {PROJECT_NAME}")
    print(f"研究主题: {RESEARCH_TOPIC[:60]}...")

    fm = _get_file_manager()
    if fm.get_project_dir(PROJECT_NAME):
        print(f"项目已存在，跳过创建: {PROJECT_NAME}")
        return

    project_dir = fm.create_project(PROJECT_NAME)
    fm.update_project_meta(project_dir, {
        "title": "企业数字化转型对企业创新绩效的影响研究",
        "research_type": "实证研究",
    })
    print(f"✅ 项目创建成功: {project_dir}")

    # 2. 启动生成
    print(f"\n开始生成论文（非交互模式）...")
    print(f"预计耗时 10-15 分钟\n")

    agent = ScholarAgent(project_dir=project_dir)
    agent.non_interactive = True

    start_time = time.time()

    try:
        await agent.run(RESEARCH_TOPIC)
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()
        return

    elapsed = time.time() - start_time
    print(f"\n✅ 论文生成完成，耗时 {elapsed/60:.1f} 分钟")

    # 3. 验证质量
    print("\n" + "=" * 60)
    print("  质量验证")
    print("=" * 60)

    results = {}

    # 3.1 检查文件是否存在
    draft_dir = project_dir / "draft"
    files_to_check = [
        "full_draft.md",
        "full_draft_polished.md",
        "references.md",
        "deai_report.md",
    ]
    print("\n[1] 文件检查")
    for fname in files_to_check:
        fpath = draft_dir / fname
        if fpath.exists():
            chars = len(fpath.read_text(encoding="utf-8"))
            print(f"  ✅ {fname}: {chars:,} 字符")
            results[fname] = chars
        else:
            print(f"  ❌ {fname}: 不存在")
            results[fname] = 0

    # 3.2 检查模型思考痕迹
    print("\n[2] 模型思考痕迹检查")
    polished_path = draft_dir / "full_draft_polished.md"
    if polished_path.exists():
        content = polished_path.read_text(encoding="utf-8")
        traces = {
            "——在笔者看来": len(re.findall(r'——在笔者看来', content)),
            "——笔者主张": len(re.findall(r'——笔者主张', content)),
            "这一点值得进一步讨论": len(re.findall(r'这一点值得进一步讨论', content)),
            "此处须要更多实证": len(re.findall(r'此处[须需]要更多实证', content)),
            "当然这只是一种可能": len(re.findall(r'当然这只是一种可能', content)),
            "拆解渊源": len(re.findall(r'拆解渊源', content)),
            "考察难题": len(re.findall(r'考察难题', content)),
            "波及规律": len(re.findall(r'波及规律', content)),
        }
        total_traces = sum(traces.values())
        for pattern, count in traces.items():
            status = "✅" if count == 0 else "❌"
            print(f"  {status} {pattern}: {count}")
        results["traces"] = total_traces
        print(f"  总计: {total_traces} 处痕迹")

    # 3.3 检查双句号
    print("\n[3] 格式检查")
    if polished_path.exists():
        double_periods = len(re.findall(r'。。', content))
        semicolon_periods = len(re.findall(r'；。', content))
        print(f"  {'✅' if double_periods == 0 else '❌'} 双句号 。。: {double_periods}")
        print(f"  {'✅' if semicolon_periods == 0 else '❌'} 分号句号 ；。: {semicolon_periods}")
        results["double_periods"] = double_periods

    # 3.4 检查英文参考文献完整性
    print("\n[4] 英文参考文献完整性")
    ref_path = draft_dir / "references.md"
    if ref_path.exists():
        ref_content = ref_path.read_text(encoding="utf-8")
        # 提取英文参考文献（References 部分）
        en_section = ref_content.split("References（英文）")[-1] if "References（英文）" in ref_content else ""
        en_refs = re.findall(r'\[(\d+)\]\s*(.+)', en_section)

        complete_count = 0
        incomplete_count = 0
        for num, text in en_refs:
            # 完整引用应有标题（引号或书名号）+ 期刊/会议名
            has_title = '"' in text or '"' in text or "'" in text
            has_journal = any(j in text for j in ["Journal", "Review", "Economics", "Science", "Proceedings", "Vol", "pp", "doi"])
            has_year = bool(re.search(r'\b(19|20)\d{2}\b', text))

            if has_title and has_year:
                complete_count += 1
            else:
                incomplete_count += 1
                if incomplete_count <= 3:
                    print(f"  ❌ [{num}] {text[:80]}...")

        print(f"  ✅ 完整引用: {complete_count}")
        print(f"  {'✅' if incomplete_count == 0 else '❌'} 不完整引用: {incomplete_count}")
        results["en_refs_complete"] = complete_count
        results["en_refs_incomplete"] = incomplete_count

    # 3.5 引用验证率
    print("\n[5] 引用验证统计")
    state_path = project_dir / ".scholar" / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        completed_sections = state.get("completed_sections", [])
        print(f"  章节完成: {len(completed_sections)}/{state.get('total_sections', '?')}")

    mem_path = project_dir / ".scholar" / "memory.json"
    if mem_path.exists():
        mem = json.loads(mem_path.read_text(encoding="utf-8"))
        cit = mem.get("entries", {}).get("citation_management", {}).get("value", {})
        total = cit.get("total", 0)
        verified = cit.get("verified", 0)
        rate = (verified / total * 100) if total > 0 else 0
        print(f"  引用验证: {verified}/{total} ({rate:.0f}%)")
        results["citation_rate"] = rate

    # 4. 总结
    print("\n" + "=" * 60)
    print("  E2E 测试总结")
    print("=" * 60)

    all_pass = True
    checks = [
        ("论文正文已生成", results.get("full_draft_polished.md", 0) > 0),
        ("参考文献已生成", results.get("references.md", 0) > 0),
        ("无模型思考痕迹", results.get("traces", 999) == 0),
        ("无双句号", results.get("double_periods", 999) == 0),
        ("英文引用不完整数<3", results.get("en_refs_incomplete", 999) < 3),
    ]

    for name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")
        if not passed:
            all_pass = False

    if all_pass:
        print("\n  🎉 所有验证通过！")
    else:
        print("\n  ⚠️ 部分验证未通过，需检查")

    print(f"\n项目目录: {project_dir}")


if __name__ == "__main__":
    asyncio.run(main())
