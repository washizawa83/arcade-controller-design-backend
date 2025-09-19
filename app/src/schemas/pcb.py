from pydantic import BaseModel, Field


class Point(BaseModel):
    x_mm: float = Field(..., description="X coordinate in millimeters")
    y_mm: float = Field(..., description="Y coordinate in millimeters")
    rotation_deg: float = Field(0.0, description="Rotation in degrees")


class BoardSpec(BaseModel):
    width_mm: float = Field(..., gt=0)
    height_mm: float = Field(..., gt=0)


class SwitchSpec(Point):
    ref: str = Field(..., description="Reference designator, e.g., SW1")


class PCBRequest(BaseModel):
    board: BoardSpec
    pico: Point
    switches: list[SwitchSpec]
    units: str = Field("mm", pattern="^(mm)$")
