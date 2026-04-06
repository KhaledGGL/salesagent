.PHONY: help up down dev logs build restart shell worker-shell ps clean test test-fast install-dev

help:
	@echo "Targets:"
	@echo "  make up           — start all services (production config)"
	@echo "  make dev          — start with hot-reload (dev overlay)"
	@echo "  make down         — stop all services"
	@echo "  make build        — rebuild images"
	@echo "  make logs         — tail logs from all services"
	@echo "  make shell        — exec into the api container"
	@echo "  make worker-shell — exec into the worker container"
	@echo "  make ps           — list running services"
	@echo "  make clean        — stop and remove volumes"

up:
	docker compose up -d

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f --tail=100

shell:
	docker compose exec api /bin/bash

worker-shell:
	docker compose exec worker /bin/bash

ps:
	docker compose ps

clean:
	docker compose down -v

install-dev:
	pip install -r requirements-dev.txt

test:
	pytest

test-fast:
	pytest -x --ff
