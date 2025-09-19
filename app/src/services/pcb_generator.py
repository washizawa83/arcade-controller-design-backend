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

# Set a simple rectangular outline on Edge.Cuts (fixed board size)
edge = board.GetLayerID('Edge.Cuts')
x0, y0 = 0, 0
x1, y1 = 300.0, 200.0

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

#! Load footprints from project-local libs (fp-lib-table lives in project dir)
proj = Path('{work_project_dir.as_posix()}')

def move_if_exists(ref_name, x, y, rot=None):
    for m in board.GetFootprints():
        if m.GetReference() == ref_name:
            m.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            if rot is not None:
                m.SetOrientationDegrees(rot)
            return True
    return False

def load_and_place(lib, fp, ref_name, x, y, rot):
    # If footprint with this reference already exists, just move it
    if move_if_exists(ref_name, x, y, rot):
        return

    # Otherwise, add new footprint
    pretty = proj / 'footprints' / lib
    stems = [p.stem for p in pretty.glob('*.kicad_mod')]
    name = fp
    if name not in stems:
        for cand in stems:
            if cand.lower() == fp.lower():
                name = cand
                break
    mod = pcbnew.FootprintLoad(str(pretty), name)
    if not mod:
        msg = (
            "Failed to load footprint: "
            + lib + "/" + fp + "; available=" + str(stems)
        )
        raise RuntimeError(msg)
    mod.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    mod.SetOrientationDegrees(rot)
    mod.SetReference(ref_name)
    board.Add(mod)

# Place/move Pico (U1) to a fixed position
load_and_place('raspberry-pi-pico.pretty', 'RPi_Pico_SMD_TH', 'U1', 150.0, 26.0, 0.0)

# Move/add mounting holes to fixed positions
HOLE_POS = [
    ('H1', 125.0, 10.0),
    ('H2', 175.0, 10.0),
    ('H3', 10.0, 10.0),
    ('H4', 10.0, 100.0),
    ('H5', 10.0, 190.0),
    ('H6', 125.0, 190.0),
    ('H7', 175.0, 190.0),
    ('H8', 290.0, 190.0),
    ('H9', 290.0, 100.0),
    ('H10', 290.0, 10.0),
]
for _r, _hx, _hy in HOLE_POS:
    # Move if exists; otherwise add from local mount library
    if not move_if_exists(_r, _hx, _hy):
        pretty = proj / 'footprints' / 'mount.pretty'
        target = pretty / 'MountingHole_3.2mm_M3.kicad_mod'
        if pretty.exists() and target.exists():
            # use directory path (.pretty) for FootprintLoad in headless mode
            load_and_place('mount.pretty', 'MountingHole_3.2mm_M3', _r, _hx, _hy, 0.0)

# Place switches
switches = {[(s.ref, s.x_mm, s.y_mm, s.rotation_deg) for s in req.switches]}
for ref_name, x, y, rot in switches:
    load_and_place('kailh-choc-hotswap.pretty', 'switch_24', ref_name, x, y, rot)

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

    # Normalize project-local libs: write fp-lib-table with local_* nicknames
    fp_table = work_project / "fp-lib-table"
    lines = [
        "(fp_lib_table\n",
        "  (lib (name \"local_rpi_pico\")(type \"KiCad\")\n",
        "       (uri \"${KIPRJMOD}/footprints/raspberry-pi-pico.pretty\")\n",
        "       (options \"\")(descr \"Proj local RPi Pico footprints\"))\n",
        "  (lib (name \"local_kailh_choc\")(type \"KiCad\")\n",
        "       (uri \"${KIPRJMOD}/footprints/kailh-choc-hotswap.pretty\")\n",
        "       (options \"\")(descr \"Proj local Kailh choc hotswap\"))\n",
        ")\n",
    ]
    fp_table.write_text("".join(lines))

    # Normalize schematic footprint references to local_* nicknames
    sch = work_project / "StickLess.kicad_sch"
    if sch.exists():
        import re

        sch_text = sch.read_text()
        # Map any RPi Pico footprint nickname to local one
        sch_text = re.sub(
            r'(property\s+"Footprint"\s+"\s*)(?:raspberry-pi-pico|RPi_Pico)(:RPi_Pico_SMD_TH)',
            r'\1local_rpi_pico\2',
            sch_text,
        )
        # Map any kailh choc nickname to local one
        sch_text = re.sub(
            r'(property\s+"Footprint"\s+"\s*)(?:kailh-choc-hotswap)(:switch_24)',
            r'\1local_kailh_choc\2',
            sch_text,
        )
        sch.write_text(sch_text)

    # NOTE: Avoid deleting KiCad project cache files to preserve existing
    # resolution context in the user's environment.

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
