.PHONY: install install-dev run test lint fmt clean

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

run:
	python -m bhoomi

test:
	python -m pytest

lint:
	ruff check src tests

fmt:
	ruff check --fix src tests

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
