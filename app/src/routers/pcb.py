from fastapi import APIRouter, File as FastAPIFile, HTTPException, Response, UploadFile
import io
import json
import zipfile

from app.src.schemas.pcb import PCBRequest
from app.src.services.pcb_generator import (
    autoroute_dsn_to_ses,
    generate_project_zip,
    apply_ses_to_pcb,
    build_routed_project_zip,
)

router = APIRouter(prefix="/api/v1/pcb", tags=["pcb"])

# Module-level default to satisfy linter rule about call in defaults
FILE_UPLOAD_DSN = FastAPIFile(..., description="Upload DSN file")
FILE_UPLOAD_PCB = FastAPIFile(..., description="Upload KiCad PCB file")
FILE_UPLOAD_SES = FastAPIFile(..., description="Upload Specctra Session (.ses)")


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


@router.post("/apply-ses")
async def apply_ses(pcb: UploadFile = FILE_UPLOAD_PCB, ses: UploadFile = FILE_UPLOAD_SES):
    if not pcb.filename.lower().endswith(".kicad_pcb"):
        raise HTTPException(status_code=400, detail="pcb must be a .kicad_pcb file")
    if not ses.filename.lower().endswith(".ses"):
        raise HTTPException(status_code=400, detail="ses must be a .ses file")
    pcb_bytes = await pcb.read()
    ses_bytes = await ses.read()
    try:
        out_bytes = apply_ses_to_pcb(pcb_bytes, ses_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from None
    # Always include a .kicad_prl that hides the drawing sheet for better UX
    base = pcb.filename.rsplit(".", 1)[0] + "-routed"
    prl = {
        "board": {
            "visible_items": [
                "vias","footprint_text","footprint_anchors","ratsnest","grid",
                "footprints_front","footprints_back","footprint_values","footprint_references",
                "tracks","drc_errors","bitmaps","pads","zones","drc_warnings","drc_exclusions",
                "locked_item_shadows","conflict_shadows","shapes"
            ]
        },
        "meta": {"filename": f"{base}.kicad_prl", "version": 5},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base}.kicad_pcb", out_bytes)
        zf.writestr(f"{base}.kicad_prl", json.dumps(prl, indent=2))
    headers = {"Content-Disposition": f'attachment; filename="{base}.zip"'}
    return Response(content=buf.getvalue(), media_type="application/zip", headers=headers)


@router.post("/generate-design-data")
async def generate_design_data(req: PCBRequest):
    data, filename = build_routed_project_zip(req)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=data, media_type="application/zip", headers=headers)
