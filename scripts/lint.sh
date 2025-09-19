#!/bin/bash
# Linting script using ruff

echo "Running ruff check..."
uv run ruff check app/

echo "Running ruff format check..."
uv run ruff format --check app/
