"""Base schemas for the application."""

from pydantic import BaseModel


class BaseResponse(BaseModel):
    """Base response model."""

    success: bool
    message: str
