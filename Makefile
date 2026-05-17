.PHONY: help up down dev logs build restart shell worker-shell ps clean test test-fast test-sales test-marketing install-dev

# Which deploy bundle to operate on. Override per invocation, e.g.:
#   make up BUNDLE=combined
#   make up BUNDLE=marketing-only
BUNDLE ?= sales-only
COMPOSE := docker compose -f deploy/compose.$(BUNDLE).yml

help:
	@echo "Targets (override BUNDLE=sales-only|marketing-only|combined; default sales-only):"
	@echo "  make up              — start all services for the current bundle"
	@echo "  make dev             — start with hot-reload (dev overlay)"
	@echo "  make down            — stop all services"
	@echo "  make build           — rebuild images"
	@echo "  make logs            — tail logs from all services"
	@echo "  make shell           — exec into the sales api container"
	@echo "  make worker-shell    — exec into the sales worker container"
	@echo "  make ps              — list running services"
	@echo "  make clean           — stop and remove volumes"
	@echo "  make test            — run all tests (sales + marketing)"
	@echo "  make test-fast       — fail-fast / failed-first"
	@echo "  make test-sales      — sales tests only"
	@echo "  make test-marketing  — marketing tests only"
	@echo "  make install-dev     — pip install requirements/dev.txt"

up:
	$(COMPOSE) up -d

dev:
	$(COMPOSE) -f deploy/compose.dev.yml up

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

logs:
	$(COMPOSE) logs -f --tail=100

shell:
	$(COMPOSE) exec sales_api /bin/bash

worker-shell:
	$(COMPOSE) exec sales_worker /bin/bash

ps:
	$(COMPOSE) ps

clean:
	$(COMPOSE) down -v

install-dev:
	pip install -r requirements/dev.txt

test:
	pytest

test-fast:
	pytest -x --ff

test-sales:
	pytest sales/tests

test-marketing:
	pytest marketing/tests
