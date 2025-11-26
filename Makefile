.PHONY: help install sync dev start stop restart logs shell clean test lint format check

help:
	@echo "HAAnim Development Commands"
	@echo ""
	@echo "Package Management:"
	@echo "  make install   - Install UV (if not installed) and sync dependencies"
	@echo "  make sync      - Sync dependencies with uv.lock"
	@echo "  make dev       - Install dev dependencies"
	@echo ""
	@echo "Development Environment:"
	@echo "  make start     - Start the development environment"
	@echo "  make stop      - Stop the development environment"
	@echo "  make restart   - Restart the development environment"
	@echo "  make logs      - View logs (Ctrl+C to exit)"
	@echo "  make shell     - Open a shell in the container"
	@echo "  make clean     - Remove development data and containers"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint      - Run linting checks"
	@echo "  make format    - Format code with black"
	@echo "  make check     - Run all checks (lint + format check)"
	@echo "  make test      - Run tests with pytest"
	@echo ""

install:
	@echo "Installing UV and dependencies..."
	@command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
	@uv sync
	@echo "✓ Dependencies installed"

sync:
	@echo "Syncing dependencies..."
	@uv sync
	@echo "✓ Dependencies synced"

dev:
	@echo "Installing dev dependencies..."
	@uv sync --all-extras
	@echo "✓ Dev dependencies installed"

start:
	@./podman/start.sh

stop:
	@./podman/stop.sh

restart:
	@./podman/restart.sh

logs:
	@./podman/logs.sh

shell:
	@./podman/shell.sh

clean:
	@echo "Cleaning development environment..."
	@podman-compose down -v
	@rm -rf podman/config/.storage podman/config/*.db* podman/config/*.log
	@echo "✓ Development environment cleaned"

test:
	@echo "Running tests..."
	@uv run pytest
	@echo "✓ Tests completed"

lint:
	@echo "Running linting checks..."
	@uv run pylint custom_components/haanim/ || true
	@uv run flake8 custom_components/haanim/ || true
	@uv run mypy custom_components/haanim/ || true
	@echo "✓ Linting completed"

format:
	@echo "Formatting code with black..."
	@uv run black --line-length 110 custom_components/haanim/
	@echo "✓ Code formatted"

check:
	@echo "Running all checks..."
	@uv run black --check --line-length 110 custom_components/haanim/
	@uv run pylint custom_components/haanim/
	@uv run flake8 custom_components/haanim/
	@uv run mypy custom_components/haanim/
	@echo "✓ All checks passed"
