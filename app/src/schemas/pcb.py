from pydantic import BaseModel, Field
from typing import Literal


class Point(BaseModel):
    x_mm: float = Field(..., description="X coordinate in millimeters")
    y_mm: float = Field(..., description="Y coordinate in millimeters")
    rotation_deg: float = Field(0.0, description="Rotation in degrees")


class SwitchSpec(Point):
    ref: str = Field(..., description="Reference designator, e.g., SW1")
    size: Literal[18, 24, 30] = Field(24, description="Switch size in mm: 18, 24, or 30")


class PCBRequest(BaseModel):
    switches: list[SwitchSpec]
    units: str = Field("mm", pattern="^(mm)$")
