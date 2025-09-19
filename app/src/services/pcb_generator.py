from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path

from app.src.schemas.pcb import PCBRequest

KICAD_PY = (
    "/Applications/KiCad/"
    "KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
)


def _write_driver_script(work_project_dir: Path, req: PCBRequest) -> Path:
    """Create a small Python driver that uses pcbnew to build a .kicad_pcb."""
    script = f"""
import pcbnew
import wx
from pathlib import Path

# Initialize minimal wxApp for plugin-dependent APIs
_app = wx.App(False)

board = pcbnew.BOARD()

# Units helper
mm = pcbnew.FromMM

# Set a simple rectangular outline on Edge.Cuts
edge = board.GetLayerID('Edge.Cuts')
x0, y0 = 0, 0
x1, y1 = {req.board.width_mm}, {req.board.height_mm}

def add_line(xa, ya, xb, yb):
    seg = pcbnew.PCB_SHAPE(board)
    seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
    seg.SetLayer(edge)
    seg.SetStart(pcbnew.VECTOR2I(mm(xa), mm(ya)))
    seg.SetEnd(pcbnew.VECTOR2I(mm(xb), mm(yb)))
    board.Add(seg)

add_line(x0, y0, x1, y0)
add_line(x1, y0, x1, y1)
add_line(x1, y1, x0, y1)
add_line(x0, y1, x0, y0)

# Load footprints from project-local libs (fp-lib-table lives in project dir)
proj = Path('{work_project_dir.as_posix()}')

def load_and_place(lib, fp, x, y, rot):
    # pcbnew.FootprintLoad accepts a .pretty dir path and footprint name (file stem).
    pretty = proj / 'footprints' / lib
    stems = [p.stem for p in pretty.glob('*.kicad_mod')]
    name = fp
    if name not in stems:
        lower_map = {{s.lower(): s for s in stems}}
        if fp.lower() in lower_map:
            name = lower_map[fp.lower()]
    mod = pcbnew.FootprintLoad(str(pretty), name)
    if not mod:
        msg = (
            f"Failed to load footprint: {{lib}}/{{fp}}; "
            f"available={{stems}}"
        )
        raise RuntimeError(msg)
    mod.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    mod.SetOrientationDegrees(rot)
    board.Add(mod)

# Place Pico
load_and_place(
    'raspberry-pi-pico.pretty',
    'RPi_Pico_SMD_TH',
    {req.pico.x_mm},
    {req.pico.y_mm},
    {req.pico.rotation_deg},
)

# Place switches
switches = {[(s.ref, s.x_mm, s.y_mm, s.rotation_deg) for s in req.switches]}
for _ref, x, y, rot in switches:
    load_and_place('kailh-choc-hotswap.pretty', 'switch_24', x, y, rot)

out_path = proj / 'StickLess.kicad_pcb'
pcbnew.SaveBoard(str(out_path), board)
print('WROTE', out_path)
"""
    driver = work_project_dir / "_build_pcb.py"
    driver.write_text(script)
    return driver


def generate_project_zip(req: PCBRequest) -> tuple[bytes, str]:
    """Copy template, call pcbnew to generate .kicad_pcb, zip, and return bytes."""
    template = Path("app/output").resolve()
    work_root = Path(tempfile.mkdtemp(prefix="pcb_"))
    work_project = work_root / "project"
    shutil.copytree(template, work_project, dirs_exist_ok=True)

    # Ensure fp-lib-table exists in project root for local libs
    # It is already placed in the template earlier.

    # Write driver and run via KiCad-bundled Python
    driver = _write_driver_script(work_project, req)
    env = os.environ.copy()
    # Make KiCad binaries available if needed
    env.setdefault("KIPRJMOD", str(work_project))

    proc = subprocess.run(
        [KICAD_PY, str(driver)],
        cwd=str(work_project),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pcbnew generation failed: {proc.stderr}\n{proc.stdout}")

    # Zip project dir
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in work_project.rglob("*"):
            zf.write(p, arcname=p.relative_to(work_project))

    return buf.getvalue(), f"pcb_{uuid.uuid4().hex}.zip"
