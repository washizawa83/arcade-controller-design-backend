from fastapi import APIRouter, File as FastAPIFile, HTTPException, Response, UploadFile

from app.src.schemas.pcb import PCBRequest
from app.src.services.pcb_generator import generate_project_zip, autoroute_dsn_to_ses

router = APIRouter(prefix="/api/v1/pcb", tags=["pcb"])

# Module-level default to satisfy linter rule about call in defaults
FILE_UPLOAD_DSN = FastAPIFile(..., description="Upload DSN file")


@router.post("/generate")
async def generate(req: PCBRequest):
    data, filename = generate_project_zip(req)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=data, media_type="application/zip", headers=headers)


@router.post("/autoroute")
async def autoroute_dsn(file: UploadFile = FILE_UPLOAD_DSN):
    if not file.filename.lower().endswith(".dsn"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a .dsn")
    dsn = await file.read()
    try:
        ses_bytes = autoroute_dsn_to_ses(dsn)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from None
    base = file.filename.rsplit(".", 1)[0]
    headers = {
        "Content-Disposition": f'attachment; filename="{base}.ses"'
    }
    return Response(content=ses_bytes, media_type="application/octet-stream", headers=headers)
