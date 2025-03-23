.PHONY: help install dev test lint format clean docker-build docker-run

PYTHON := python
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
BLACK := $(PYTHON) -m black
ISORT := $(PYTHON) -m isort
FLAKE8 := $(PYTHON) -m flake8
MYPY := $(PYTHON) -m mypy

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package and dependencies
	$(PIP) install -e ".[all]"

dev:  ## Install development dependencies
	$(PIP) install -e ".[all,dev]"

test:  ## Run tests
	$(PYTEST) tests/

test-cov:  ## Run tests with coverage
	$(PYTEST) --cov=webhook_relay tests/

lint:  ## Run linters
	$(BLACK) --check src tests
	$(ISORT) --check-only --profile black src tests
	$(FLAKE8) src tests
	$(MYPY) src

format:  ## Format code
	$(BLACK) src tests
	$(ISORT) --profile black src tests

clean:  ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .coverage
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

docker-build:  ## Build Docker image
	docker build -t webhook-relay .

docker-run-collector:  ## Run collector service in Docker
	docker run -p 8000:8000 -p 9090:9090 -v $(PWD)/examples:/config webhook-relay webhook_relay.collector.app serve --config /config/collector_config.yaml

docker-run-forwarder:  ## Run forwarder service in Docker
	docker run -p 9091:9091 -v $(PWD)/examples:/config webhook-relay webhook_relay.forwarder.app serve --config /config/forwarder_config.yaml

docker-compose-up:  ## Run all services with docker-compose
	docker-compose up -d

docker-compose-down:  ## Stop all services with docker-compose
	docker-compose down