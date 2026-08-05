.PHONY: dev web check lint types test provision

dev: ## BFF con recarga; sirve web/ en el mismo origen
	uv run uvicorn ordo_desk.main:create_app --factory --reload --port 8100

web: ## Solo los estáticos, sin BFF
	uv run python tools/serve_dev.py

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy

test:
	uv run pytest

check: lint types test ## lint + types + tests

provision: ## Identidades IAM de la demo: make provision TENANT=ropa
	@test -n "$(TENANT)" || (echo "Uso: make provision TENANT=ropa" && exit 1)
	uv run python sim/provision.py $(TENANT)
