from fastapi import APIRouter, Response

from app.src.schemas.pcb import PCBRequest
from app.src.services.pcb_generator import generate_project_zip

router = APIRouter(prefix="/api/v1/pcb", tags=["pcb"])


@router.post("/generate")
async def generate(req: PCBRequest):
    data, filename = generate_project_zip(req)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=data, media_type="application/zip", headers=headers)
