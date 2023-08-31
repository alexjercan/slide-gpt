.PHONY: help fmt

help:
	@cat Makefile | grep -E "^\w+$:"

lint: # Lint code
	poetry run pylint slide_gpt/ tests/
	poetry run mypy slide_gpt/ tests/ --ignore-missing-imports

fmt: # Format code
	poetry run isort slide_gpt/ tests/
	poetry run black slide_gpt/ tests/
