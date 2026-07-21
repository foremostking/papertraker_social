"""ScholarPilot 标准化测试脚本.

每次开发后运行，包含：
1. 单元测试（pytest）
2. 冒烟测试（Web UI 核心功能）

用法：
    python run_tests.py              # 仅单元测试
    python run_tests.py --smoke      # 单元测试 + 冒烟测试
    python run_tests.py --smoke-only # 仅冒烟测试
"""
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
PYTHON = sys.executable


def run_unit_tests() -> bool:
    """运行单元测试."""
    print("\n" + "=" * 60)
    print("  单元测试（pytest）")
    print("=" * 60)

    test_files = [
        "tests/test_citation_extraction.py",
        "tests/test_reproducibility.py",
        "tests/test_submission_helper.py",
        "tests/test_dashboard.py",
        "tests/test_literature_matrix.py",
        "tests/test_result_parser.py",
    ]

    cmd = [PYTHON, "-m", "pytest"] + test_files + ["-v", "--tb=short"]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env={**__import__("os").environ, "PYTHONPATH": "src"})

    if result.returncode == 0:
        print("\n✅ 单元测试全部通过")
    else:
        print("\n❌ 单元测试失败")
    return result.returncode == 0


def run_smoke_test() -> bool:
    """运行冒烟测试——验证 Web UI 核心功能."""
    print("\n" + "=" * 60)
    print("  冒烟测试（Web UI 核心功能）")
    print("=" * 60)

    sys.path.insert(0, str(PROJECT_ROOT / "src"))

    results = []
    try:
        # Test 1: 配置加载
        print("\n[Test 1] 配置加载...")
        from scholarpilot.config import get_settings
        settings = get_settings()
        assert settings is not None
        print(f"  ✅ 配置加载成功，projects_dir={settings.projects_dir}")
        results.append(True)

        # Test 2: 文件管理器
        print("[Test 2] 文件管理器...")
        from scholarpilot.cli import _get_file_manager
        fm = _get_file_manager()
        projects = fm.list_projects()
        print(f"  ✅ 文件管理器正常，现有 {len(projects)} 个项目")
        results.append(True)

        # Test 3: 模板列表
        print("[Test 3] 示例模板...")
        from scholarpilot.cli import _get_example_templates
        templates = _get_example_templates()
        assert len(templates) == 8, f"期望8个模板，实际{len(templates)}"
        disciplines = set(t["discipline"] for t in templates)
        assert len(disciplines) == 6, f"期望6个学科，实际{len(disciplines)}"
        print(f"  ✅ {len(templates)}个模板，{len(disciplines)}个学科")
        results.append(True)

        # Test 4: 引用提取
        print("[Test 4] 引用提取...")
        from scholarpilot.tools.citation_manager import extract_citations_from_text
        text = "毛捷和徐军伟（2019）研究发现地方债务对经济有显著影响。"
        cites = extract_citations_from_text(text)
        assert len(cites) == 1
        assert cites[0].year == "2019"
        assert "毛捷" in cites[0].authors
        print(f"  ✅ 引用提取正常，提取到 {len(cites)} 条引用")
        results.append(True)

        # Test 5: 引用提取无误匹配
        print("[Test 5] 引用提取无误匹配...")
        text2 = "相关系数为0.324，在1%的水平上显著，这与刘苗和韩毅（2026）的研究发现一致。"
        cites2 = extract_citations_from_text(text2)
        assert len(cites2) == 1
        for a in cites2[0].authors:
            assert "显著" not in a
            assert a != "这"
        print(f"  ✅ 无误匹配，作者名: {cites2[0].authors}")
        results.append(True)

        # Test 6: Web 应用导入
        print("[Test 6] Web 应用导入...")
        from scholarpilot.web.app import main, show_project_list, show_create_project, show_settings
        print("  ✅ Web 应用模块导入正常")
        results.append(True)

        # Test 7: ScholarAgent 导入
        print("[Test 7] ScholarAgent 导入...")
        from scholarpilot.agent.scholar import ScholarAgent
        print("  ✅ ScholarAgent 导入正常")
        results.append(True)

        # Test 8: 导出函数
        print("[Test 8] 导出函数...")
        from scholarpilot.tools.exporter import export_project
        print("  ✅ export_project 导入正常")
        results.append(True)

        # Test 9: Web 服务 HTTP 健康检查
        print("[Test 9] Web 服务 HTTP 健康检查...")
        import urllib.request
        import urllib.error
        try:
            req = urllib.request.Request("http://localhost:8501/_stcore/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode()
                if resp.status == 200 and body.strip() == "ok":
                    print(f"  ✅ Streamlit 服务正常响应 (HTTP {resp.status})")
                    results.append(True)
                else:
                    print(f"  ❌ 健康检查异常: status={resp.status}, body={body}")
                    results.append(False)
        except urllib.error.URLError as e:
            print(f"  ⚠️  Streamlit 服务未运行: {e.reason}")
            print(f"     请先启动: start_web.bat 或 streamlit run src/scholarpilot/web/app.py")
            results.append(False)
        except Exception as e:
            print(f"  ⚠️  健康检查失败: {e}")
            results.append(False)

    except Exception as e:
        print(f"  ❌ 冒烟测试失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)

    passed = sum(results)
    total = len(results)
    print(f"\n冒烟测试结果: {passed}/{total} 通过")
    return all(results)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ScholarPilot 测试脚本")
    parser.add_argument("--smoke", action="store_true", help="运行单元测试 + 冒烟测试")
    parser.add_argument("--smoke-only", action="store_true", help="仅运行冒烟测试")
    args = parser.parse_args()

    success = True

    if not args.smoke_only:
        success = run_unit_tests() and success

    if args.smoke or args.smoke_only:
        success = run_smoke_test() and success

    print("\n" + "=" * 60)
    if success:
        print("  ✅ 所有测试通过")
    else:
        print("  ❌ 测试失败")
    print("=" * 60)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
