"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.src.config import get_settings
from app.src.routers import health

# Get application settings
settings = get_settings()

# Create FastAPI app instance
app = FastAPI(
    title=settings.app_name,
    description="Arcade Controller Design Project Backend API",
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Welcome to Arcade Controller Design Project API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
