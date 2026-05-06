.PHONY: help setup install install-dev clean clean-cache test test-all test-unit test-integration test-e2e test-coverage test-coverage-all test-watch lint format format-check type-check check dev dev-debug shell docs docs-serve info deps-outdated lock ci ci-coverage

# Variables
PYTHON := python3
UV := uv
FLOX := flox activate --
SRC_DIR := src
TEST_DIR := tests
STUB_DIR := docker/auth_stub
VENV := .venv

# Colors for help output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
NC := \033[0m # No Color

# Default target
help: ## Show this help message
	@echo "$(BLUE)RAG File Uploader - Available Make Targets$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Notes:$(NC)"
	@echo "  • All commands run within flox environment"
	@echo "  • Default 'make test' excludes integration tests (no external services needed)"
	@echo "  • Use 'make test-all' or 'make test-integration' to run tests requiring NATS, MinIO, etc."

##@ Setup & Installation

setup: ## Initialize project: create venv, install dependencies
	@echo "$(BLUE)Setting up project environment...$(NC)"
	@echo "$(GREEN)→ Creating Python virtual environment with uv...$(NC)"
	$(FLOX) $(UV) sync
	@echo "$(GREEN)✓ Virtual environment created and dependencies installed$(NC)"
	@echo ""
	@echo "$(YELLOW)Next steps:$(NC)"
	@echo "  1. Activate flox environment: eval \"\$$(flox activate)\""
	@echo "  2. Run tests (without integration): make test"
	@echo "  3. Run all tests (with integration): make test-all"
	@echo "  4. Start dev server: make dev"

install: ## Install/sync dependencies (after pyproject.toml changes)
	@echo "$(GREEN)→ Syncing dependencies...$(NC)"
	$(FLOX) $(UV) sync

install-dev: ## Install with dev dependencies
	@echo "$(GREEN)→ Installing all dependencies including dev tools...$(NC)"
	$(FLOX) $(UV) sync --all-groups

##@ Code Quality

lint: ## Run ruff linter
	@echo "$(GREEN)→ Running ruff linter...$(NC)"
	$(FLOX) $(UV) run ruff check $(SRC_DIR) $(TEST_DIR) $(STUB_DIR)

format: ## Format code with ruff
	@echo "$(GREEN)→ Formatting code with ruff...$(NC)"
	$(FLOX) $(UV) run ruff format $(SRC_DIR) $(TEST_DIR) $(STUB_DIR)
	$(FLOX) $(UV) run ruff check --fix $(SRC_DIR) $(TEST_DIR) $(STUB_DIR)

format-check: ## Check code formatting without modifying files
	@echo "$(GREEN)→ Checking code formatting...$(NC)"
	$(FLOX) $(UV) run ruff format --check $(SRC_DIR) $(TEST_DIR) $(STUB_DIR)

type-check: ## Run mypy type checker
	@echo "$(GREEN)→ Running mypy type checker...$(NC)"
	$(FLOX) $(UV) run mypy $(SRC_DIR) $(STUB_DIR)

check: format-check lint type-check ## Run all code quality checks (format, lint, type)

##@ Testing

test: ## Run all tests (excluding integration tests requiring external services)
	@echo "$(GREEN)→ Running tests (excluding integration)...$(NC)"
	$(FLOX) $(UV) run pytest $(TEST_DIR) -v -m "not integration"

test-all: ## Run all tests including integration tests
	@echo "$(GREEN)→ Running all tests (including integration)...$(NC)"
	$(FLOX) $(UV) run pytest $(TEST_DIR) -v

test-unit: ## Run unit tests only
	@echo "$(GREEN)→ Running unit tests...$(NC)"
	$(FLOX) $(UV) run pytest $(TEST_DIR)/unit -v

test-integration: ## Run integration tests only (requires external services like NATS)
	@echo "$(GREEN)→ Running integration tests...$(NC)"
	$(FLOX) $(UV) run pytest $(TEST_DIR) -v -m "integration"

test-e2e: ## Run end-to-end tests
	@echo "$(GREEN)→ Running E2E tests...$(NC)"
	$(FLOX) $(UV) run pytest $(TEST_DIR)/e2e -v

test-coverage: ## Run tests with coverage report (excludes integration tests)
	@echo "$(GREEN)→ Running tests with coverage...$(NC)"
	$(FLOX) $(UV) run pytest $(TEST_DIR) -m "not integration" --cov=$(SRC_DIR) --cov-config=pytest.ini --cov-report=html --cov-report=term-missing

test-coverage-all: ## Run all tests including integration with coverage report
	@echo "$(GREEN)→ Running all tests with coverage...$(NC)"
	$(FLOX) $(UV) run pytest $(TEST_DIR) --cov=$(SRC_DIR) --cov-config=pytest.ini --cov-report=html --cov-report=term-missing

test-watch: ## Run tests in watch mode (excludes integration tests)
	@echo "$(GREEN)→ Running tests in watch mode...$(NC)"
	$(FLOX) $(UV) run ptw $(TEST_DIR) -- -v -m "not integration"

##@ Development

dev: ## Start development server with auto-reload
	@echo "$(GREEN)→ Starting development server...$(NC)"
	$(FLOX) $(UV) run uvicorn $(SRC_DIR).presentation.main:app --reload --host 0.0.0.0 --port 8000

dev-debug: ## Start development server with debug logging
	@echo "$(GREEN)→ Starting development server (debug mode)...$(NC)"
	$(FLOX) $(UV) run uvicorn $(SRC_DIR).presentation.main:app --reload --host 0.0.0.0 --port 8000 --log-level debug

shell: ## Start Python shell with project context
	@echo "$(GREEN)→ Starting Python shell...$(NC)"
	$(FLOX) $(UV) run python

##@ Documentation

docs: ## Build documentation with MkDocs
	@echo "$(GREEN)→ Building documentation...$(NC)"
	$(FLOX) $(UV) run mkdocs build

docs-serve: ## Serve documentation locally at http://127.0.0.1:8000
	@echo "$(GREEN)→ Serving documentation at http://127.0.0.1:8000...$(NC)"
	$(FLOX) $(UV) run mkdocs serve

##@ Cleanup

clean: ## Remove build artifacts, cache files, and venv
	@echo "$(GREEN)→ Cleaning build artifacts...$(NC)"
	rm -rf $(VENV)
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.egg" -delete
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

clean-cache: ## Remove only cache files (keep venv)
	@echo "$(GREEN)→ Cleaning cache files...$(NC)"
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "$(GREEN)✓ Cache cleanup complete$(NC)"

##@ Utilities

info: ## Display project information
	@echo "$(BLUE)Project Information$(NC)"
	@echo "  Name: rag-file-uploader"
	@echo "  Python: $(shell $(FLOX) python --version 2>/dev/null || echo 'Not in flox env')"
	@echo "  UV: $(shell $(FLOX) uv --version 2>/dev/null || echo 'Not in flox env')"
	@echo "  Virtual Environment: $(VENV)"
	@echo ""
	@echo "$(BLUE)Installed Packages$(NC)"
	@$(FLOX) $(UV) pip list 2>/dev/null || echo "  Run 'make setup' first"

deps-outdated: ## Check for outdated dependencies
	@echo "$(GREEN)→ Checking for outdated dependencies...$(NC)"
	$(FLOX) $(UV) pip list --outdated

lock: ## Regenerate uv.lock file
	@echo "$(GREEN)→ Regenerating lock file...$(NC)"
	$(FLOX) $(UV) lock

##@ CI/CD Pipeline

ci: clean-cache check test ## Run full CI pipeline (clean, check, test)
	@echo "$(GREEN)✓ CI pipeline completed successfully$(NC)"

ci-coverage: clean-cache check test-coverage ## Run CI with coverage report
	@echo "$(GREEN)✓ CI pipeline with coverage completed$(NC)"
