#!/bin/bash
# Formatting script using ruff

echo "Running ruff format..."
uv run ruff format app/

echo "Running ruff check with auto-fix..."
uv run ruff check --fix app/
