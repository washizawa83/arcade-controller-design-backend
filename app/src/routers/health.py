"""Health check endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    message: str


@router.get("/", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy", message="Arcade Controller Design Backend is running"
    )
