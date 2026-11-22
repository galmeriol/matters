# Common commands. `make check` is what every change must pass.
.PHONY: help sync check test lint format-check typecheck format fix serve stop restart

help:  ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-13s %s\n", $$1, $$2}'

sync:  ## Install dependencies into the venv
	uv sync

check: test lint format-check typecheck  ## Everything a change must pass

test:  ## Run the tests
	uv run pytest -q

lint:  ## Lint
	uv run ruff check

format-check:  ## Fail if anything needs formatting
	uv run ruff format --check

typecheck:  ## Strict mypy
	uv run mypy

format:  ## Format the code
	uv run ruff format

fix:  ## Apply safe lint fixes, then format
	uv run ruff check --fix
	uv run ruff format

serve:  ## Start the viewer
	uv run matters serve --no-open

start:  ## Run the viewer in the background
	uv run matters start

stop:  ## Stop the viewer
	uv run matters stop

status:  ## Show the running viewer
	uv run matters status

restart:  ## Restart the background viewer with the current code
	uv run matters restart
