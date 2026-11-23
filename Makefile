# =============================================================================
# MSP Triage Infrastructure - Makefile
# =============================================================================
# Common development commands for the MSP Triage platform.
#
# Usage:
#   make help          # Show all available commands
#   make setup         # Initial project setup
#   make test          # Run all tests
#   make deploy-dev    # Deploy to dev environment
# =============================================================================

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help setup install test lint format security validate plan apply deploy clean

# Environment (default: dev)
ENV ?= dev
TF_VARS_FILE := terraform.tfvars.$(ENV)

# Python
PYTHON := python3
PIP := pip
VENV := .venv
VENV_BIN := $(VENV)/bin

# Terraform
TF := terraform
TF_PLAN_FILE := tfplan-$(ENV)

# Docker
DOCKER := docker
DOCKER_COMPOSE := docker-compose
LAYER_BUILDER_IMAGE := lambda-layer-builder
LOCALSTACK_CONTAINER := localstack

# Directories
SRC_DIRS := $(wildcard src_*/)
BUILD_DIR := .build
TESTS_DIR := tests

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m  # No Color

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------
help:  ## Show this help message
	@echo ""
	@echo "$(BLUE)MSP Triage Infrastructure - Available Commands$(NC)"
	@echo "=================================================="
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Current environment: $(ENV)$(NC)"
	@echo ""

# -----------------------------------------------------------------------------
# Setup & Installation
# -----------------------------------------------------------------------------
setup: install init-terraform  ## Initial project setup (venv + terraform init)
	@echo "$(GREEN)✓ Setup complete$(NC)"

install:  ## Create virtual environment and install dependencies
	@echo "$(BLUE)→ Creating virtual environment...$(NC)"
	@$(PYTHON) -m venv $(VENV)
	@echo "$(BLUE)→ Upgrading pip...$(NC)"
	@$(VENV_BIN)/pip install --upgrade pip
	@echo "$(BLUE)→ Installing development dependencies...$(NC)"
	@$(VENV_BIN)/pip install -r requirements-dev.txt
	@echo "$(GREEN)✓ Dependencies installed$(NC)"

init-terraform:  ## Initialize Terraform
	@echo "$(BLUE)→ Initializing Terraform for $(ENV)...$(NC)"
	@$(TF) init
	@echo "$(GREEN)✓ Terraform initialized$(NC)"

env-load:  ## Load environment variables from .env
	@echo "$(BLUE)→ Loading environment from .env...$(NC)"
	@if [ ! -f .env ]; then \
		echo "$(RED)✗ .env file not found. Copy from .env.example$(NC)"; \
		exit 1; \
	fi
	@set -a && source .env && set +a
	@echo "$(GREEN)✓ Environment loaded$(NC)"

env-check:  ## Check if required environment variables are set
	@echo "$(BLUE)→ Checking environment variables...$(NC)"
	@test -n "$$AWS_PROFILE" || (echo "Missing AWS_PROFILE" && exit 1)
	@test -n "$$TF_VAR_project" || (echo "Missing TF_VAR_project" && exit 1)
	@test -n "$$TF_VAR_environment" || (echo "Missing TF_VAR_environment" && exit 1)
	@echo "$(GREEN)✓ All required variables are set$(NC)"

# -----------------------------------------------------------------------------
# Development
# -----------------------------------------------------------------------------
test:  ## Run all tests with coverage
	@echo "$(BLUE)→ Running tests...$(NC)"
	@$(VENV_BIN)/pytest $(TESTS_DIR) -v --cov=src_* --cov-report=term-missing --cov-report=html
	@echo "$(GREEN)✓ Tests complete. Coverage report: htmlcov/index.html$(NC)"

test-quick:  ## Run tests without coverage (faster)
	@echo "$(BLUE)→ Running tests (quick mode)...$(NC)"
	@$(VENV_BIN)/pytest $(TESTS_DIR) -v -x
	@echo "$(GREEN)✓ Tests complete$(NC)"

test-unit:  ## Run only unit tests
	@echo "$(BLUE)→ Running unit tests...$(NC)"
	@$(VENV_BIN)/pytest $(TESTS_DIR) -v -m "not integration"
	@echo "$(GREEN)✓ Unit tests complete$(NC)"

test-local: localstack-up  ## Run tests against LocalStack
	@echo "$(BLUE)→ Running tests against LocalStack...$(NC)"
	@AWS_ENDPOINT_URL=http://localhost:4566 $(VENV_BIN)/pytest $(TESTS_DIR) -v -m local
	@echo "$(GREEN)✓ Local tests complete$(NC)"

lint:  ## Run all linters (ruff, black --check, mypy)
	@echo "$(BLUE)→ Running linters...$(NC)"
	@$(VENV_BIN)/ruff check $(SRC_DIRS) $(TESTS_DIR)
	@$(VENV_BIN)/black --check $(SRC_DIRS) $(TESTS_DIR)
	@$(VENV_BIN)/mypy $(SRC_DIRS) --ignore-missing-imports
	@echo "$(GREEN)✓ All linters passed$(NC)"

format:  ## Auto-format code with black and ruff
	@echo "$(BLUE)→ Formatting code...$(NC)"
	@$(VENV_BIN)/ruff check --fix $(SRC_DIRS) $(TESTS_DIR)
	@$(VENV_BIN)/isort $(SRC_DIRS) $(TESTS_DIR)
	@$(VENV_BIN)/black $(SRC_DIRS) $(TESTS_DIR)
	@echo "$(GREEN)✓ Code formatted$(NC)"

# -----------------------------------------------------------------------------
# Security
# -----------------------------------------------------------------------------
security: security-python security-terraform  ## Run all security scans
	@echo "$(GREEN)✓ All security scans complete$(NC)"

security-python:  ## Run Python security scans (bandit, pip-audit)
	@echo "$(BLUE)→ Running bandit (Python security linter)...$(NC)"
	@$(VENV_BIN)/bandit -r $(SRC_DIRS) -ll -ii
	@echo "$(BLUE)→ Running pip-audit (dependency vulnerabilities)...$(NC)"
	@$(VENV_BIN)/pip-audit -r requirements.txt
	@$(VENV_BIN)/pip-audit -r requirements-dev.txt
	@echo "$(GREEN)✓ Python security scans passed$(NC)"

security-terraform:  ## Run Terraform security scans (requires tfsec/trivy)
	@echo "$(BLUE)→ Running tfsec (Terraform security scanner)...$(NC)"
	@command -v tfsec >/dev/null 2>&1 && tfsec . || echo "$(YELLOW)⚠ tfsec not installed, skipping$(NC)"
	@echo "$(BLUE)→ Running checkov (IaC security scanner)...$(NC)"
	@command -v checkov >/dev/null 2>&1 && checkov -d . --quiet || echo "$(YELLOW)⚠ checkov not installed, skipping$(NC)"
	@echo "$(GREEN)✓ Terraform security scans complete$(NC)"

# -----------------------------------------------------------------------------
# Terraform
# -----------------------------------------------------------------------------
validate:  ## Validate Terraform configuration
	@echo "$(BLUE)→ Validating Terraform for $(ENV)...$(NC)"
	@$(TF) validate
	@echo "$(GREEN)✓ Terraform configuration is valid$(NC)"

fmt:  ## Format Terraform files
	@echo "$(BLUE)→ Formatting Terraform files...$(NC)"
	@$(TF) fmt -recursive
	@echo "$(GREEN)✓ Terraform files formatted$(NC)"

fmt-check:  ## Check Terraform formatting (CI mode)
	@echo "$(BLUE)→ Checking Terraform formatting...$(NC)"
	@$(TF) fmt -check -recursive
	@echo "$(GREEN)✓ Terraform formatting is correct$(NC)"

plan: validate  ## Generate Terraform plan
	@echo "$(BLUE)→ Generating Terraform plan for $(ENV)...$(NC)"
	@$(TF) plan -var-file=$(TF_VARS_FILE) -out=$(TF_PLAN_FILE)
	@echo "$(GREEN)✓ Plan saved to $(TF_PLAN_FILE)$(NC)"

apply:  ## Apply Terraform changes (requires plan)
	@echo "$(YELLOW)⚠ Applying Terraform changes to $(ENV)...$(NC)"
	@if [ ! -f $(TF_PLAN_FILE) ]; then \
		echo "$(RED)✗ No plan file found. Run 'make plan' first.$(NC)"; \
		exit 1; \
	fi
	@read -p "Are you sure you want to apply to $(ENV)? [y/N] " confirm && \
		[ $$confirm = "y" ] || (echo "Aborted." && exit 1)
	@$(TF) apply $(TF_PLAN_FILE)
	@echo "$(GREEN)✓ Apply complete$(NC)"

apply-auto: validate  ## Apply Terraform changes without confirmation (CI mode)
	@echo "$(YELLOW)⚠ Auto-applying Terraform changes to $(ENV)...$(NC)"
	@$(TF) apply -auto-approve -var-file=$(TF_VARS_FILE)
	@echo "$(GREEN)✓ Auto-apply complete$(NC)"

destroy:  ## Destroy Terraform-managed infrastructure
	@echo "$(RED)⚠ DESTROYING infrastructure in $(ENV)...$(NC)"
	@read -p "Are you SURE? This cannot be undone. Type 'destroy' to confirm: " confirm && \
		[ $$confirm = "destroy" ] || (echo "Aborted." && exit 1)
	@$(TF) destroy -var-file=$(TF_VARS_FILE)
	@echo "$(GREEN)✓ Destroy complete$(NC)"

output:  ## Show Terraform outputs
	@$(TF) output

state-list:  ## List resources in Terraform state
	@$(TF) state list

state-backup:  ## Backup Terraform state to S3
	@echo "$(BLUE)→ Backing up Terraform state...$(NC)"
	@./scripts/backup-state.sh
	@echo "$(GREEN)✓ State backed up$(NC)"

# -----------------------------------------------------------------------------
# Deployment
# -----------------------------------------------------------------------------
deploy-dev:  ## Deploy to dev environment
	@$(MAKE) deploy ENV=dev

deploy-staging:  ## Deploy to staging environment
	@$(MAKE) deploy ENV=staging

deploy-prod:  ## Deploy to production environment
	@echo "$(RED)⚠ PRODUCTION DEPLOYMENT$(NC)"
	@read -p "Are you sure? [y/N] " confirm && \
		[ $$confirm = "y" ] || (echo "Aborted." && exit 1)
	@$(MAKE) deploy ENV=prod

deploy: validate plan apply  ## Full deployment workflow (validate → plan → apply)
	@echo "$(GREEN)✓ Deployment to $(ENV) complete$(NC)"

deploy-lambda:  ## Deploy only Lambda functions (faster iteration)
	@echo "$(BLUE)→ Deploying Lambda functions to $(ENV)...$(NC)"
	@$(TF) apply -auto-approve -var-file=$(TF_VARS_FILE) \
		-target=aws_lambda_function.orchestrator \
		-target=aws_lambda_function.worker \
		-target=aws_lambda_function.teams_bot \
		-target=aws_lambda_function.identity_tools \
		-target=aws_lambda_function.tenant_onboarding
	@echo "$(GREEN)✓ Lambda functions deployed$(NC)"

# -----------------------------------------------------------------------------
# Build
# -----------------------------------------------------------------------------
build:  ## Build all Lambda deployment packages
	@echo "$(BLUE)→ Building Lambda packages...$(NC)"
	@mkdir -p $(BUILD_DIR)
	@for dir in $(SRC_DIRS); do \
		name=$$(basename $$dir); \
		echo "  Building $$name..."; \
		cd $$dir && zip -r ../$(BUILD_DIR)/$$name.zip . -x "*.pyc" -x "__pycache__/*" && cd ..; \
	done
	@echo "$(GREEN)✓ Build complete. Packages in $(BUILD_DIR)/$(NC)"

build-layers:  ## Build Lambda layers (local build)
	@echo "$(BLUE)→ Building Lambda layers...$(NC)"
	@for dir in layers/*/; do \
		if [ -f "$$dir/build.sh" ]; then \
			echo "  Building layer: $$dir"; \
			(cd $$dir && bash build.sh); \
		fi \
	done
	@echo "$(GREEN)✓ Layers built$(NC)"

build-layers-docker:  ## Build Lambda layers using Docker (for native dependencies)
	@echo "$(BLUE)→ Building Lambda layers with Docker...$(NC)"
	@$(DOCKER) build -t $(LAYER_BUILDER_IMAGE) -f Dockerfile.lambda-layer .
	@$(DOCKER) create --name layer-builder $(LAYER_BUILDER_IMAGE)
	@$(DOCKER) cp layer-builder:/build/layer.zip layers/bot-framework-jwt/layer.zip
	@$(DOCKER) rm layer-builder
	@$(DOCKER) rmi $(LAYER_BUILDER_IMAGE)
	@echo "$(GREEN)✓ Layer built: layers/bot-framework-jwt/layer.zip$(NC)"

# -----------------------------------------------------------------------------
# Docker - LocalStack
# -----------------------------------------------------------------------------
localstack-up:  ## Start LocalStack for local testing
	@echo "$(BLUE)→ Starting LocalStack...$(NC)"
	@$(DOCKER_COMPOSE) up -d
	@echo "$(GREEN)✓ LocalStack running at http://localhost:4566$(NC)"
	@echo "  Web UI: http://localhost:8080"
	@echo "  Wait ~30 seconds for services to initialize"

localstack-down:  ## Stop LocalStack
	@echo "$(BLUE)→ Stopping LocalStack...$(NC)"
	@$(DOCKER_COMPOSE) down
	@echo "$(GREEN)✓ LocalStack stopped$(NC)"

localstack-logs:  ## View LocalStack logs
	@$(DOCKER_COMPOSE) logs -f

localstack-status:  ## Check LocalStack service status
	@echo "$(BLUE)→ LocalStack service status:$(NC)"
	@curl -s http://localhost:4566/_localstack/health | jq

localstack-init:  ## Initialize LocalStack with required resources
	@echo "$(BLUE)→ Initializing LocalStack resources...$(NC)"
	@./scripts/init-localstack.sh
	@echo "$(GREEN)✓ LocalStack initialized$(NC)"

localstack-clean:  ## Clean LocalStack data
	@echo "$(BLUE)→ Cleaning LocalStack data...$(NC)"
	@$(DOCKER_COMPOSE) down -v
	@rm -rf /tmp/localstack
	@echo "$(GREEN)✓ LocalStack cleaned$(NC)"

# -----------------------------------------------------------------------------
# Docker - Development Environment
# -----------------------------------------------------------------------------
dev-build:  ## Build development environment container
	@echo "$(BLUE)→ Building development container...$(NC)"
	@$(DOCKER) build -t msp-dev -f Dockerfile.dev .
	@echo "$(GREEN)✓ Development container built$(NC)"

dev-shell:  ## Start interactive shell in development container
	@echo "$(BLUE)→ Starting development shell...$(NC)"
	@$(DOCKER) run -it --rm \
		-v $(PWD):/app \
		-v ~/.aws:/root/.aws:ro \
		-e AWS_PROFILE=$(AWS_PROFILE) \
		msp-dev bash

dev-test:  ## Run tests in development container
	@echo "$(BLUE)→ Running tests in container...$(NC)"
	@$(DOCKER) run --rm \
		-v $(PWD):/app \
		msp-dev make test

dev-lint:  ## Run linters in development container
	@echo "$(BLUE)→ Running linters in container...$(NC)"
	@$(DOCKER) run --rm \
		-v $(PWD):/app \
		msp-dev make lint

# -----------------------------------------------------------------------------
# Portal
# -----------------------------------------------------------------------------
portal-deploy:  ## Deploy tenant portal to S3
	@echo "$(BLUE)→ Deploying tenant portal...$(NC)"
	@./scripts/deploy-portal.sh
	@echo "$(GREEN)✓ Portal deployed$(NC)"

portal-local:  ## Start local portal server for development
	@echo "$(BLUE)→ Starting local portal server on http://localhost:3000$(NC)"
	@cd portal-site && $(PYTHON) -m http.server 3000

portal-docker:  ## Run portal in Docker container
	@echo "$(BLUE)→ Starting portal in Docker on http://localhost:3000$(NC)"
	@$(DOCKER) run -d --rm \
		--name msp-portal \
		-p 3000:80 \
		-v $(PWD)/portal-site:/usr/share/nginx/html:ro \
		nginx:alpine
	@echo "$(GREEN)✓ Portal running$(NC)"
	@echo "  Stop with: docker stop msp-portal"

# -----------------------------------------------------------------------------
# Tenant Management
# -----------------------------------------------------------------------------
tenant-list:  ## List all tenants
	@echo "$(BLUE)→ Listing tenants...$(NC)"
	@aws dynamodb scan \
		--table-name msp-triage-$(ENV)-tenant-registry \
		--projection-expression "tenant_id, display_name, status, management_mode" \
		--output table

tenant-status:  ## Show status of all tenants (requires API)
	@echo "$(BLUE)→ Fetching tenant statuses...$(NC)"
	@curl -s "$$(terraform output -raw tenant_onboarding_api_url)/status/tenants" \
		-H "x-api-key: $$(aws apigatewayv2 get-api-key --api-key $$(terraform output -raw onboarding_api_key_id) --include-value --query 'value' --output text)" | jq

tenant-onboard:  ## Onboard a new tenant (interactive)
	@echo "$(BLUE)→ Onboarding new tenant...$(NC)"
	@read -p "Tenant ID: " tid; \
	read -p "Display Name: " name; \
	read -p "Entra Tenant ID: " entra; \
	read -p "Admin Group ID: " admin; \
	read -p "Contact Email: " email; \
	curl -X POST "$$(terraform output -raw tenant_onboarding_api_url)/tenants" \
		-H "x-api-key: $$(aws apigatewayv2 get-api-key --api-key $$(terraform output -raw onboarding_api_key_id) --include-value --query 'value' --output text)" \
		-H "Content-Type: application/json" \
		-d "{\"tenant_id\": \"$$tid\", \"display_name\": \"$$name\", \"entra_tenant_id\": \"$$entra\", \"admin_group_id\": \"$$admin\", \"contact_email\": \"$$email\"}" | jq

# -----------------------------------------------------------------------------
# Logs & Monitoring
# -----------------------------------------------------------------------------
logs:  ## Tail CloudWatch logs for all critical Lambdas
	@echo "$(BLUE)→ Tailing logs for critical Lambdas...$(NC)"
	@aws logs tail \
		/aws/lambda/msp-triage-$(ENV)-teams-bot \
		/aws/lambda/msp-triage-$(ENV)-identity-tools \
		/aws/lambda/msp-triage-$(ENV)-tenant-onboarding \
		--since 5m --follow

logs-lambda:  ## Tail logs for a specific Lambda (usage: make logs-lambda NAME=teams_bot)
	@echo "$(BLUE)→ Tailing logs for $(NAME)...$(NC)"
	@aws logs tail /aws/lambda/msp-triage-$(ENV)-$(NAME) --since 5m --follow

alarms:  ## Show active CloudWatch alarms
	@echo "$(BLUE)→ Fetching active alarms...$(NC)"
	@aws cloudwatch describe-alarms \
		--alarm-name-prefix msp-triage-$(ENV) \
		--state-value ALARM \
		--output table

# -----------------------------------------------------------------------------
# Analytics
# -----------------------------------------------------------------------------
analytics-run:  ## Manually trigger analytics aggregation
	@echo "$(BLUE)→ Triggering analytics aggregation...$(NC)"
	@aws lambda invoke \
		--function-name msp-triage-$(ENV)-analytics-aggregation \
		--payload '{"days": 30}' \
		/dev/stdout | jq

analytics-summary:  ## Show executive summary
	@echo "$(BLUE)→ Fetching executive summary...$(NC)"
	@curl -s "$$(terraform output -raw tenant_onboarding_api_url)/analytics/executive-summary" \
		-H "x-api-key: $$(aws apigatewayv2 get-api-key --api-key $$(terraform output -raw onboarding_api_key_id) --include-value --query 'value' --output text)" | jq

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------
clean:  ## Remove build artifacts and temporary files
	@echo "$(BLUE)→ Cleaning build artifacts...$(NC)"
	@rm -rf $(BUILD_DIR)
	@rm -rf .terraform
	@rm -rf .pytest_cache
	@rm -rf htmlcov
	@rm -rf .coverage
	@rm -rf *.tfplan
	@rm -rf __pycache__
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@echo "$(GREEN)✓ Clean complete$(NC)"

clean-docker:  ## Remove Docker images and containers
	@echo "$(BLUE)→ Cleaning Docker resources...$(NC)"
	@$(DOCKER) system prune -f
	@$(DOCKER) image prune -f
	@echo "$(GREEN)✓ Docker cleaned$(NC)"

clean-all: clean clean-docker  ## Clean everything including venv and Docker
	@rm -rf $(VENV)
	@$(DOCKER_COMPOSE) down -v 2>/dev/null || true
	@echo "$(GREEN)✓ Full clean complete$(NC)"

# -----------------------------------------------------------------------------
# Documentation
# -----------------------------------------------------------------------------
docs-build:  ## Build documentation site
	@echo "$(BLUE)→ Building documentation...$(NC)"
	@$(VENV_BIN)/mkdocs build
	@echo "$(GREEN)✓ Documentation built in site/$(NC)"

docs-serve:  ## Serve documentation locally
	@echo "$(BLUE)→ Serving documentation at http://localhost:8000$(NC)"
	@$(VENV_BIN)/mkdocs serve

# -----------------------------------------------------------------------------
# Pre-commit
# -----------------------------------------------------------------------------
precommit-install:  ## Install pre-commit hooks
	@echo "$(BLUE)→ Installing pre-commit hooks...$(NC)"
	@$(VENV_BIN)/pre-commit install
	@$(VENV_BIN)/pre-commit install --hook-type commit-msg
	@echo "$(GREEN)✓ Pre-commit hooks installed$(NC)"

precommit-run:  ## Run pre-commit on all files
	@echo "$(BLUE)→ Running pre-commit on all files...$(NC)"
	@$(VENV_BIN)/pre-commit run --all-files
	@echo "$(GREEN)✓ Pre-commit complete$(NC)"

# -----------------------------------------------------------------------------
# Release
# -----------------------------------------------------------------------------
release-check: lint test security validate  ## Run all checks before release
	@echo "$(GREEN)✓ All release checks passed$(NC)"