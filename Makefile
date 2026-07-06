.PHONY: install dev test lint format clean run

# ── 安装 ──────────────────────────────────────────────
install:
	pip install -e ".[dev]"

dev: install
	pip install -e .

# ── 测试 ──────────────────────────────────────────────
test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=src/scholarpilot --cov-report=html

# ── 代码质量 ──────────────────────────────────────────
lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/

# ── 清理 ──────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name *.egg-info -exec rm -rf {} + 2>/dev/null || true

# ── 运行 ──────────────────────────────────────────────
run:
	scholarpilot chat

new:
	scholarpilot new $(NAME)
