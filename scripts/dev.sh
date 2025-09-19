#!/bin/bash
# Development server startup script

echo "Starting development server..."
uv run uvicorn app.src.main:app --reload --host 0.0.0.0 --port 8000
