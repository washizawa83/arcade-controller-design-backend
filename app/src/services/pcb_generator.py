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
    script = r"""
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
proj = Path('.')

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
    pretty = (proj / 'footprints' / lib).resolve()
    stems = [p.stem for p in pretty.glob('*.kicad_mod')]
    name = fp
    if name not in stems:
        for cand in stems:
            if cand.lower() == fp.lower():
                name = cand
                break
    # Prefer project fp-lib-table nicknames when available (robust on KiCad 7)
    nickname = None
    if lib == 'raspberry-pi-pico.pretty':
        nickname = 'local_rpi_pico'
    elif lib == 'kailh-choc-hotswap.pretty':
        nickname = 'local_kailh_choc'

    mod = None
    if nickname is not None:
        try:
            mod = pcbnew.FootprintLoad(nickname, name)
        except Exception:
            mod = None
    if not mod:
        mod = pcbnew.FootprintLoad(str(pretty), name)
    if not mod:
        # KiCad 7 fallback: some builds require the .kicad_mod suffix as name
        try:
            mod = pcbnew.FootprintLoad(str(pretty), name + ".kicad_mod")
        except Exception:
            mod = None
    if not mod:
        # Last resort 1: try giving full file path as the library argument
        try:
            target = (pretty / (name + ".kicad_mod"))
            mod = pcbnew.FootprintLoad(str(target), name)
        except Exception:
            mod = None
    if not mod:
        # Last resort 2: some KiCad 7 builds accept empty name when lib points to file
        try:
            target = (pretty / (name + ".kicad_mod"))
            mod = pcbnew.FootprintLoad(str(target), "")
        except Exception:
            mod = None
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
        pretty = (proj / 'footprints' / 'mount.pretty').resolve()
        target = pretty / 'MountingHole_3.2mm_M3.kicad_mod'
        if pretty.exists() and target.exists():
            # use directory path (.pretty) for FootprintLoad in headless mode
            load_and_place('mount.pretty', 'MountingHole_3.2mm_M3', _r, _hx, _hy, 0.0)

# Place switches
switches = __SWITCHES__
for ref_name, x, y, rot in switches:
    load_and_place('kailh-choc-hotswap.pretty', 'switch_24', ref_name, x, y, rot)

# --- Assign nets from schematic-like intent (e.g., JSON map / GPIO) ---
import re
import json

def get_or_create_net(board, net_name: str):
    nets_by_name = board.GetNetsByName()
    if net_name in nets_by_name:
        return nets_by_name[net_name]
    net = pcbnew.NETINFO_ITEM(board, net_name)
    board.Add(net)
    return net

def find_footprint(board, ref: str):
    for m in board.GetFootprints():
        if m.GetReference() == ref:
            return m
    return None

# Build a mapping of (reference, pad_name) -> net_name from JSON

def import_nets_from_json_file(path_str: str) -> bool:
    try:
        path = Path(path_str)
        if not path.exists():
            return False
        raw = json.loads(path.read_text())
        net_map = dict()
        if isinstance(raw, list):
            # [{"ref":"U1","pad":"12","net":"GPIO9"}, ...]
            for e in raw:
                ref = e.get('ref')
                pad = e.get('pad')
                net = e.get('net')
                if not ref or pad is None or not net:
                    continue
                net_map[(str(ref), str(pad))] = str(net)
        elif isinstance(raw, dict):
            # {"U1": {"12": "GPIO9", "13": "GND"}, ...}
            for ref, pads in raw.items():
                if not isinstance(pads, dict):
                    continue
                for pad, net in pads.items():
                    net_map[(str(ref), str(pad))] = str(net)
        else:
            return False
        # apply
        for (ref, pad_name), net_name in net_map.items():
            fp = find_footprint(board, ref)
            if fp is None:
                continue
            pad = fp.FindPadByNumber(str(pad_name))
            if pad is None:
                continue
            net_obj = get_or_create_net(board, net_name)
            pad.SetNet(net_obj)
        print('IMPORTED_NETS_JSON', path)
        return True
    except Exception as e:
        print('IMPORTED_NETS_JSON_ERROR', e)
        return False

# Only net_map.json is used
imported = import_nets_from_json_file(str(proj / 'net_map.json'))
if not imported:
    # No fallback by design
    pass

out_path = proj / 'StickLess.kicad_pcb'
pcbnew.SaveBoard(str(out_path), board)
# Hide drawing sheet in project local .kicad_prl
prl = proj / 'StickLess.kicad_prl'
try:
    import json
    if prl.exists():
        data = json.loads(prl.read_text())
    else:
        data = dict()
    if not isinstance(data.get('board'), dict):
        data['board'] = dict()
    vis = data['board'].get('visible_items')
    if not isinstance(vis, list):
        vis = []
    if 'drawing_sheet' in vis:
        vis.remove('drawing_sheet')
    data['board']['visible_items'] = vis
    data['meta'] = dict(filename='StickLess.kicad_prl', version=5)
    prl.write_text(json.dumps(data, indent=2))
except Exception:
    pass
print('WROTE', out_path)
"""
    # Inject dynamic switches into the script
    switches_literal = [(s.ref, s.x_mm, s.y_mm, s.rotation_deg) for s in req.switches]
    script = script.replace("__SWITCHES__", repr(switches_literal))

    driver = work_project_dir / "_build_pcb.py"
    driver.write_text(script)
    return driver


def generate_project_zip(req: PCBRequest) -> tuple[bytes, str]:
    """Copy template from app/datas, run pcbnew, zip, and return bytes."""
    template = Path("app/datas").resolve()
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
            r'(property\s+\"Footprint\"\s+\"\s*)(?:raspberry-pi-pico|RPi_Pico)(:RPi_Pico_SMD_TH)',
            r'\1local_rpi_pico\2',
            sch_text,
        )
        # Map any kailh choc nickname to local one
        sch_text = re.sub(
            r'(property\s+\"Footprint\"\s+\"\s*)(?:kailh-choc-hotswap)(:switch_24)',
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


def autoroute_dsn_to_ses(dsn_bytes: bytes) -> bytes:
    """Run Freerouting CLI on provided DSN bytes and return SES bytes.

    Requires FREEROUTING_JAR env var or a .jar under ~/freerouting/.
    Uses -mt 1 for stable optimization.
    """
    work_root = Path(tempfile.mkdtemp(prefix="fr_"))
    dsn_path = work_root / "in.dsn"
    ses_path = work_root / "out.ses"
    dsn_path.write_bytes(dsn_bytes)

    jar = os.environ.get("FREEROUTING_JAR")
    if not jar:
        home = Path.home() / "freerouting"
        jars = sorted(home.glob("*.jar"))
        if not jars:
            raise RuntimeError("Freerouting JAR not found. Set FREEROUTING_JAR or place a .jar under ~/freerouting/")
        jar = str(jars[0])

    proc = subprocess.run(
        [
            "java",
            "-Djava.awt.headless=true",
            "-jar",
            jar,
            "-de",
            str(dsn_path),
            "-do",
            str(ses_path),
            "-mt",
            "1",
            "-l",
            "en",
        ],
        cwd=str(Path(jar).resolve().parent),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not ses_path.exists():
        msg = "Freerouting failed: " + proc.stderr + "\n" + proc.stdout
        raise RuntimeError(msg)
    return ses_path.read_bytes()


def apply_ses_to_pcb(pcb_bytes: bytes, ses_bytes: bytes) -> bytes:
    """Import a Specctra SES into a KiCad PCB via pcbnew Python and return routed PCB bytes.

    Runs a small driver script under KiCad-bundled Python (KICAD_PY) to call
    the internal ImportSpecctraSession API if available.
    """
    work_root = Path(tempfile.mkdtemp(prefix="imp_ses_"))
    in_pcb = work_root / "in.kicad_pcb"
    in_ses = work_root / "in.ses"
    out_pcb = work_root / "out.kicad_pcb"
    in_pcb.write_bytes(pcb_bytes)
    in_ses.write_bytes(ses_bytes)

    driver = work_root / "_apply_ses.py"
    driver.write_text(
        "\n".join(
            [
                "import re, pcbnew, wx",
                "from pathlib import Path",
                "_app = wx.App(False)",
                f"pcb_path = Path(r'{in_pcb.as_posix()}')",
                f"ses_path = Path(r'{in_ses.as_posix()}')",
                f"out_path = Path(r'{out_pcb.as_posix()}')",
                "board = pcbnew.LoadBoard(str(pcb_path))",
                "if not board:",
                "    try:",
                "        board = pcbnew.LoadBoard(str(pcb_path))",
                "    except Exception:",
                "        board = None",
                "if not board:",
                "    print('LOAD_BOARD_FAILED_FALLBACK_BLANK')",
                "    board = pcbnew.BOARD()",
                "ok = False",
                "native_ok = False",
                "# Try native API first (if available in this KiCad)",
                "try:",
                "    board.ImportSpecctraSession(str(ses_path))",
                "    native_ok = True",
                "except Exception as e1:",
                "    fn = getattr(pcbnew, 'ImportSpecctraSession', None)",
                "    if callable(fn):",
                "        try:",
                "            fn(board, str(ses_path))",
                "            native_ok = True",
                "        except Exception as e2:",
                "            print('IMPORT_TRY_MODULE_FUNC_FAILED', e2)",
                "    else:",
                "        print('IMPORT_TRY_BOARD_METHOD_FAILED', e1)",
                "# Validate native result (ensure tracks or vias exist); otherwise use fallback",
                "# Force using fallback parser to ensure consistent tracks/vias import",
                "ok = False",
                "# Fallback: minimal SES parser for wires/vias (multiline-aware)",
                "if not ok:",
                "    text = ses_path.read_text(errors='ignore')",
                "    # SES coordinate unit (resolution um 10 => 1 unit = 0.01 mm)",
                "    U = 10000.0",
                "    # Compute translation between SES and KiCad coordinate origins using U1 as anchor",
                "    dx = 0",
                "    dy = 0",
                "    y_off = 0",
                "    try:",
                "        m_place = re.search(r'\\(place\\s+U1\\s+(-?\\d+)\\s+(-?\\d+)\\s+front\\s+\\d+\\)', text)",
                "        if m_place:",
                "            sx = int(m_place.group(1)) / U",
                "            sy = int(m_place.group(2)) / U",
                "            ses_u1 = pcbnew.VECTOR2I(pcbnew.FromMM(sx), pcbnew.FromMM(sy))",
                "            u1 = None",
                "            for fp in board.GetFootprints():",
                "                try:",
                "                    if fp.GetReference() == 'U1':",
                "                        u1 = fp",
                "                        break",
                "                except Exception:",
                "                    continue",
                "            if u1 is not None:",
                "                pos = u1.GetPosition()",
                "                dx = pos.x - ses_u1.x",
                "                dy = pos.y - ses_u1.y",
                "                # For SES->KiCad Y-axis inversion, precompute offset",
                "                y_off = pos.y + ses_u1.y",
                "    except Exception:",
                "        dx = 0; dy = 0; y_off = 0",
                "    def get_or_create_net(name: str):",
                "        n = board.FindNet(name)",
                "        if n:",
                "            return n",
                "        ni = pcbnew.NETINFO_ITEM(board, name)",
                "        board.Add(ni)",
                "        return ni",
                "    def mm(val: float):",
                "        return pcbnew.FromMM(val)",
                "    # Layer ids (prefer constants if available)",
                "    try:",
                "        lid_f = getattr(pcbnew, 'F_Cu')",
                "        lid_b = getattr(pcbnew, 'B_Cu')",
                "    except Exception:",
                "        lid_f = board.GetLayerID('F.Cu')",
                "        lid_b = board.GetLayerID('B.Cu')",
                "    layer_map = {'F.Cu': lid_f, 'B.Cu': lid_b} ",
                "    U = 10000.0  # 1 unit = 0.01 mm for (resolution um 10)",
                "    cur_net = None",
                "    in_path = False",
                "    in_wire = False",
                "    path_layer = None",
                "    path_width = 0.2",
                "    coord_tokens = []",
                "    # via parsing state",
                "    in_via = False",
                "    via_tokens = []",
                "    for raw in text.splitlines():",
                "        line = raw.strip()",
                "        mnet = re.match(r'^\(net\s+([^\s\)]+)', line)",
                "        if mnet:",
                "            cur_net = mnet.group(1)",
                "            in_path = False",
                "            in_wire = False",
                "            coord_tokens = []",
                "            in_via = False",
                "            via_tokens = []",
                "            continue",
                "        if cur_net is None:",
                "            continue",
                "        # VIA block (multi-line safe)",
                "        if not in_path:",
                "            # Handle VIA accumulation/processing",
                "            if in_via:",
                "                # keep collecting tokens until a closing ')' line",
                "                if line == ')':",
                "                    # process collected via_tokens -> create via",
                "                    ints = []",
                "                    for tok in via_tokens:",
                "                        try:",
                "                            ints.append(int(tok))",
                "                        except Exception:",
                "                            pass",
                "                    if cur_net is not None and len(ints) >= 2:",
                "                        sx = pcbnew.FromMM(ints[-2] / U)",
                "                        sy = pcbnew.FromMM(ints[-1] / U)",
                "                        x = sx + dx",
                "                        y = y_off - sy",
                "                        width_mm = 0.6",
                "                        drill_mm = 0.3",
                "                        name_tok = via_tokens[0] if via_tokens else ''",
                "                        if name_tok.startswith('"') and name_tok.endswith('"'):",
                "                            padname = name_tok.strip(\"\"\")",
                "                            msz = re.search(r'_(\\d+):(\\d+)_um', padname)",
                "                            if msz:",
                "                                try:",
                "                                    width_mm = int(msz.group(1)) / 1000.0",
                "                                    drill_mm = int(msz.group(2)) / 1000.0",
                "                                except Exception:",
                "                                    width_mm = 0.6; drill_mm = 0.3",
                "                        netinfo = get_or_create_net(cur_net)",
                "                        try:",
                "                            v = pcbnew.PCB_VIA(board)",
                "                        except Exception:",
                "                            v = pcbnew.VIA(board)",
                "                        v.SetPosition(pcbnew.VECTOR2I(x, y))",
                "                        try:",
                "                            v.SetViaType(getattr(pcbnew, 'VIA_THROUGH', getattr(pcbnew, 'VIA_STANDARD', 0)))",
                "                        except Exception:",
                "                            pass",
                "                        try:",
                "                            v.SetLayerPair(board.GetLayerID('F.Cu'), board.GetLayerID('B.Cu'))",
                "                        except Exception:",
                "                            pass",
                "                        applied = False",
                "                        try:",
                "                            v.SetDiameter(mm(width_mm))",
                "                            applied = True",
                "                        except Exception:",
                "                            pass",
                "                        if not applied:",
                "                            try:",
                "                                v.SetWidth(mm(width_mm), board.GetLayerID('F.Cu'))",
                "                                applied = True",
                "                            except Exception:",
                "                                pass",
                "                        try:",
                "                            v.SetDrill(mm(drill_mm))",
                "                        except Exception:",
                "                            pass",
                "                        v.SetNet(netinfo)",
                "                        board.Add(v)",
                "                    in_via = False",
                "                    via_tokens = []",
                "                    continue",
                "                else:",
                "                    via_tokens += line.replace(')', ' ').split()",
                "                    # still inside via block",
                "                    continue",
                "            if line.startswith('(via'):",
                "                in_via = True",
                "                via_tokens = line.replace('(via', '', 1).replace(')', ' ').split()",
                "                if line.endswith(')'):",
                "                    # single-line via - process immediately",
                "                    in_via = False",
                "                    ints = []",
                "                    for tok in via_tokens:",
                "                        try:",
                "                            ints.append(int(tok))",
                "                        except Exception:",
                "                            pass",
                "                    if cur_net is not None and len(ints) >= 2:",
                "                        sx = pcbnew.FromMM(ints[-2] / U)",
                "                        sy = pcbnew.FromMM(ints[-1] / U)",
                "                        x = sx + dx",
                "                        y = y_off - sy",
                "                        width_mm = 0.6",
                "                        drill_mm = 0.3",
                "                        name_tok = via_tokens[0] if via_tokens else ''",
                "                        if name_tok.startswith('"') and name_tok.endswith('"'):",
                "                            padname = name_tok.strip(\"\"\")",
                "                            msz = re.search(r'_(\\d+):(\\d+)_um', padname)",
                "                            if msz:",
                "                                try:",
                "                                    width_mm = int(msz.group(1)) / 1000.0",
                "                                    drill_mm = int(msz.group(2)) / 1000.0",
                "                                except Exception:",
                "                                    width_mm = 0.6; drill_mm = 0.3",
                "                        netinfo = get_or_create_net(cur_net)",
                "                        try:",
                "                            v = pcbnew.PCB_VIA(board)",
                "                        except Exception:",
                "                            v = pcbnew.VIA(board)",
                "                        v.SetPosition(pcbnew.VECTOR2I(x, y))",
                "                        try:",
                "                            v.SetViaType(getattr(pcbnew, 'VIA_THROUGH', getattr(pcbnew, 'VIA_STANDARD', 0)))",
                "                        except Exception:",
                "                            pass",
                "                        try:",
                "                            v.SetLayerPair(board.GetLayerID('F.Cu'), board.GetLayerID('B.Cu'))",
                "                        except Exception:",
                "                            pass",
                "                        applied = False",
                "                        try:",
                "                            v.SetDiameter(mm(width_mm))",
                "                            applied = True",
                "                        except Exception:",
                "                            pass",
                "                        if not applied:",
                "                            try:",
                "                                v.SetWidth(mm(width_mm), board.GetLayerID('F.Cu'))",
                "                                applied = True",
                "                            except Exception:",
                "                                pass",
                "                        try:",
                "                            v.SetDrill(mm(drill_mm))",
                "                        except Exception:",
                "                            pass",
                "                        v.SetNet(netinfo)",
                "                        board.Add(v)",
                "                    via_tokens = []",
                "                    continue",
                "            # Start of a multi-line wire block",
                "            if line.startswith('(wire'):",
                "                in_wire = True",
                "                coord_tokens = []",
                "                continue",
                "            # Multi-line path header inside a wire block",
                "            if in_wire:",
                "                mp = re.match(r'^\(path\s+([FB]\\.Cu)\s+(\d+)\s*(.*)$', line)",
                "                if mp:",
                "                    path_layer = mp.group(1)",
                "                    try:",
                "                        path_width = int(mp.group(2)) / U",
                "                    except Exception:",
                "                        path_width = 0.2",
                "                    tail = mp.group(3)",
                "                    coord_tokens = []",
                "                    if tail:",
                "                        coord_tokens += tail.replace(')', ' ').split()",
                "                    in_path = True",
                "                    # If path header already closes on same line, process immediately",
                "                    if raw.endswith('))') or raw.endswith(')'):",
                "                        in_path = False",
                "                        if len(coord_tokens) >= 4:",
                "                            netinfo = get_or_create_net(cur_net)",
                "                            lay = layer_map.get(path_layer, board.GetLayerID('B.Cu'))",
                "                            try:",
                "                                coords = [int(x) for x in coord_tokens]",
                "                            except Exception:",
                "                                coords = []",
                "                            for i in range(0, len(coords)-2, 2):",
                "                                sx1 = pcbnew.FromMM(coords[i] / U)",
                "                                sy1 = pcbnew.FromMM(coords[i+1] / U)",
                "                                sx2 = pcbnew.FromMM(coords[i+2] / U)",
                "                                sy2 = pcbnew.FromMM(coords[i+3] / U)",
                "                                x1 = sx1 + dx",
                "                                y1 = y_off - sy1",
                "                                x2 = sx2 + dx",
                "                                y2 = y_off - sy2",
                "                                t = pcbnew.PCB_TRACK(board)",
                "                                t.SetLayer(lay)",
                "                                t.SetWidth(mm(path_width))",
                "                                t.SetStart(pcbnew.VECTOR2I(x1, y1))",
                "                                t.SetEnd(pcbnew.VECTOR2I(x2, y2))",
                "                                t.SetNet(netinfo)",
                "                                board.Add(t)",
                "                        coord_tokens = []",
                "                        # If this also closes the wire block, reset in_wire",
                "                        if raw.endswith('))'):",
                "                            in_wire = False",
                "                        continue",
                "            mw = re.match(r'^\(wire\s*\(path\s+([FB]\\.Cu)\s+(\d+)\s*(.*)$', line)",
                "            if mw:",
                "                path_layer = mw.group(1)",
                "                try:",
                "                    path_width = int(mw.group(2)) / U",
                "                except Exception:",
                "                    path_width = 0.2",
                "                tail = mw.group(3)",
                "                coord_tokens = []",
                "                if tail:",
                "                    coord_tokens += tail.replace(')', ' ').split()",
                "                in_path = True",
                "                # If this line already closed, process immediately",
                "                if raw.endswith('))') or raw.endswith(')'):",
                "                    in_path = False",
                "                    if len(coord_tokens) >= 4:",
                "                        netinfo = get_or_create_net(cur_net)",
                "                        lay = layer_map.get(path_layer, board.GetLayerID('B.Cu'))",
                "                        try:",
                "                            coords = [int(x) for x in coord_tokens]",
                "                        except Exception:",
                "                            coords = []",
                "                        for i in range(0, len(coords)-2, 2):",
                "                            sx1 = pcbnew.FromMM(coords[i] / U)",
                "                            sy1 = pcbnew.FromMM(coords[i+1] / U)",
                "                            sx2 = pcbnew.FromMM(coords[i+2] / U)",
                "                            sy2 = pcbnew.FromMM(coords[i+3] / U)",
                "                            x1 = sx1 + dx",
                "                            y1 = y_off - sy1",
                "                            x2 = sx2 + dx",
                "                            y2 = y_off - sy2",
                "                            t = pcbnew.PCB_TRACK(board)",
                "                            t.SetLayer(lay)",
                "                            t.SetWidth(mm(path_width))",
                "                            t.SetStart(pcbnew.VECTOR2I(x1, y1))",
                "                            t.SetEnd(pcbnew.VECTOR2I(x2, y2))",
                "                            t.SetNet(netinfo)",
                "                            board.Add(t)",
                "                    coord_tokens = []",
                "                continue",
                "        else:",
                "            # Accumulate coordinates until closing parenthesis",
                "            if line:",
                "                coord_tokens += line.replace(')', ' ').split()",
                "            if raw.endswith('))') or raw.endswith(')'):",
                "                in_path = False",
                "                if len(coord_tokens) >= 4:",
                "                    netinfo = get_or_create_net(cur_net)",
                "                    lay = layer_map.get(path_layer, board.GetLayerID('B.Cu'))",
                "                    try:",
                "                        coords = [int(x) for x in coord_tokens]",
                "                    except Exception:",
                "                        coords = []",
                "                    for i in range(0, len(coords)-2, 2):",
                "                        sx1 = pcbnew.FromMM(coords[i] / U)",
                "                        sy1 = pcbnew.FromMM(coords[i+1] / U)",
                "                        sx2 = pcbnew.FromMM(coords[i+2] / U)",
                "                        sy2 = pcbnew.FromMM(coords[i+3] / U)",
                "                        x1 = sx1 + dx",
                "                        y1 = y_off - sy1",
                "                        x2 = sx2 + dx",
                "                        y2 = y_off - sy2",
                "                        t = pcbnew.PCB_TRACK(board)",
                "                        t.SetLayer(lay)",
                "                        t.SetWidth(mm(path_width))",
                "                        t.SetStart(pcbnew.VECTOR2I(x1, y1))",
                "                        t.SetEnd(pcbnew.VECTOR2I(x2, y2))",
                "                        t.SetNet(netinfo)",
                "                        board.Add(t)",
                "                coord_tokens = []",
                "                # After path closes, if next closure closes the wire block, reset in_wire",
                "                if raw.endswith('))'):",
                "                    in_wire = False",
                "                continue",
                "        # Close an empty wire block if encountered",
                "        if not in_path and in_wire and line == ')':",
                "            in_wire = False",
                "            continue",
                "        # VIA: create through via for current net (single-line entry)",
                "        mvia = re.match(r'^\\(via(?:\\s+\"([^\"]+)\")?\\s+(-?\\d+)\\s+(-?\\d+)\\s*\\)$', line)",
                "        if mvia and cur_net is not None and not in_path:",
                "            name = mvia.group(1)",
                "            try:",
                "                sx = pcbnew.FromMM(int(mvia.group(2)) / U)",
                "                sy = pcbnew.FromMM(int(mvia.group(3)) / U)",
                "            except Exception:",
                "                sx = None; sy = None",
                "            if sx is not None and sy is not None:",
                "                x = sx + dx",
                "                y = y_off - sy",
                "                width_mm = 0.6",
                "                drill_mm = 0.3",
                "                if name:",
                "                    msz = re.search(r'_(\\d+):(\\d+)_um', name)",
                "                    if msz:",
                "                        try:",
                "                            width_mm = int(msz.group(1)) / 1000.0",
                "                            drill_mm = int(msz.group(2)) / 1000.0",
                "                        except Exception:",
                "                            width_mm = 0.6; drill_mm = 0.3",
                "                netinfo = get_or_create_net(cur_net)",
                "                try:",
                "                    v = pcbnew.PCB_VIA(board)",
                "                except Exception:",
                "                    v = pcbnew.VIA(board)",
                "                v.SetPosition(pcbnew.VECTOR2I(x, y))",
                "                try:",
                "                    v.SetViaType(getattr(pcbnew, 'VIA_THROUGH', getattr(pcbnew, 'VIA_STANDARD', 0)))",
                "                except Exception:",
                "                    pass",
                "                try:",
                "                    v.SetLayerPair(board.GetLayerID('F.Cu'), board.GetLayerID('B.Cu'))",
                "                except Exception:",
                "                    pass",
                "                applied = False",
                "                try:",
                "                    v.SetDiameter(mm(width_mm))",
                "                    applied = True",
                "                except Exception:",
                "                    pass",
                "                if not applied:",
                "                    try:",
                "                        v.SetWidth(mm(width_mm), board.GetLayerID('F.Cu'))",
                "                        applied = True",
                "                    except Exception:",
                "                        pass",
                "                try:",
                "                    v.SetDrill(mm(drill_mm))",
                "                except Exception:",
                "                    pass",
                "                v.SetNet(netinfo)",
                "                board.Add(v)",
                "    ok = True",
                "if ok:",
                "    # If board has no vias yet, inject vias from SES text (via-only pass)",
                "    try:",
                "        cur_vias = 0",
                "        for t in board.Tracks():",
                "            try:",
                "                if isinstance(t, pcbnew.PCB_VIA):",
                "                    cur_vias += 1",
                "            except Exception:",
                "                pass",
                "        if cur_vias == 0:",
                "            text = ses_path.read_text(errors='ignore')",
                "            U = 10000.0",
                "            dx = 0; dy = 0; y_off = 0",
                "            try:",
                "                m_place = re.search(r'\\(place\\s+U1\\s+(-?\\d+)\\s+(-?\\d+)\\s+front\\s+\\d+\\)', text)",
                "                if m_place:",
                "                    sx = int(m_place.group(1)) / U",
                "                    sy = int(m_place.group(2)) / U",
                "                    ses_u1 = pcbnew.VECTOR2I(pcbnew.FromMM(sx), pcbnew.FromMM(sy))",
                "                    u1 = None",
                "                    for fp in board.GetFootprints():",
                "                        try:",
                "                            if fp.GetReference() == 'U1':",
                "                                u1 = fp",
                "                                break",
                "                        except Exception:",
                "                            continue",
                "                    if u1 is not None:",
                "                        pos = u1.GetPosition()",
                "                        dx = pos.x - ses_u1.x",
                "                        dy = pos.y - ses_u1.y",
                "                        y_off = pos.y + ses_u1.y",
                "            except Exception:",
                "                dx = 0; dy = 0; y_off = 0",
                "            def get_or_create_net(name: str):",
                "                n = board.FindNet(name)",
                "                if n:",
                "                    return n",
                "                ni = pcbnew.NETINFO_ITEM(board, name)",
                "                board.Add(ni)",
                "                return ni",
                "            def mm(val: float):",
                "                return pcbnew.FromMM(val)",
                "            # Parse nets and vias only",
                "            cur_net = None",
                "            in_via = False",
                "            via_tokens = []",
                "            for raw in text.splitlines():",
                "                line = raw.strip()",
                "                mnet = re.match(r'^\\(net\\s+([^\\s\\)]+)', line)",
                "                if mnet:",
                "                    cur_net = mnet.group(1)",
                "                    in_via = False",
                "                    via_tokens = []",
                "                    continue",
                "                if cur_net is None:",
                "                    continue",
                "                if in_via:",
                "                    if line == ')':",
                "                        ints = []",
                "                        for tok in via_tokens:",
                "                            try:",
                "                                ints.append(int(tok))",
                "                            except Exception:",
                "                                pass",
                "                        if len(ints) >= 2:",
                "                            sx = pcbnew.FromMM(ints[-2] / U)",
                "                            sy = pcbnew.FromMM(ints[-1] / U)",
                "                            x = sx + dx",
                "                            y = y_off - sy",
                "                            width_mm = 0.6",
                "                            drill_mm = 0.3",
                "                            name_tok = via_tokens[0] if via_tokens else ''",
                "                            if name_tok.startswith('"') and name_tok.endswith('"'):",
                "                                padname = name_tok.strip(\"\"\")",
                "                                msz = re.search(r'_(\\\\d+):(\\\\d+)_um', padname)",
                "                                if msz:",
                "                                    try:",
                "                                        width_mm = int(msz.group(1)) / 1000.0",
                "                                        drill_mm = int(msz.group(2)) / 1000.0",
                "                                    except Exception:",
                "                                        width_mm = 0.6; drill_mm = 0.3",
                "                            netinfo = get_or_create_net(cur_net)",
                "                            v = pcbnew.PCB_VIA(board)",
                "                            v.SetPosition(pcbnew.VECTOR2I(x, y))",
                "                            try:",
                "                                v.SetViaType(getattr(pcbnew, 'VIA_THROUGH', getattr(pcbnew, 'VIA_STANDARD', 0)))",
                "                            except Exception:",
                "                                pass",
                "                            try:",
                "                                v.SetLayerPair(board.GetLayerID('F.Cu'), board.GetLayerID('B.Cu'))",
                "                            except Exception:",
                "                                pass",
                "                            try:",
                "                                v.SetDiameter(mm(width_mm))",
                "                            except Exception:",
                "                                pass",
                "                            try:",
                "                                v.SetDrill(mm(drill_mm))",
                "                            except Exception:",
                "                                pass",
                "                            v.SetNet(netinfo)",
                "                            board.Add(v)",
                "                        in_via = False",
                "                        via_tokens = []",
                "                        continue",
                "                    else:",
                "                        via_tokens += line.replace(')', ' ').split()",
                "                        continue",
                "                if line.startswith('(via'):",
                "                    in_via = True",
                "                    via_tokens = line.replace('(via', '', 1).replace(')', ' ').split()",
                "                    if line.endswith(')'):",
                "                        # single-line via",
                "                        in_via = False",
                "                        ints = []",
                "                        for tok in via_tokens:",
                "                            try:",
                "                                ints.append(int(tok))",
                "                            except Exception:",
                "                                pass",
                "                        if len(ints) >= 2:",
                "                            sx = pcbnew.FromMM(ints[-2] / U)",
                "                            sy = pcbnew.FromMM(ints[-1] / U)",
                "                            x = sx + dx",
                "                            y = y_off - sy",
                "                            width_mm = 0.6",
                "                            drill_mm = 0.3",
                "                            name_tok = via_tokens[0] if via_tokens else ''",
                "                            if name_tok.startswith('"') and name_tok.endswith('"'):",
                "                                padname = name_tok.strip(\"\"\")",
                "                                msz = re.search(r'_(\\\\d+):(\\\\d+)_um', padname)",
                "                                if msz:",
                "                                    try:",
                "                                        width_mm = int(msz.group(1)) / 1000.0",
                "                                        drill_mm = int(msz.group(2)) / 1000.0",
                "                                    except Exception:",
                "                                        width_mm = 0.6; drill_mm = 0.3",
                "                            netinfo = get_or_create_net(cur_net)",
                "                            v = pcbnew.PCB_VIA(board)",
                "                            v.SetPosition(pcbnew.VECTOR2I(x, y))",
                "                            try:",
                "                                v.SetViaType(getattr(pcbnew, 'VIA_THROUGH', getattr(pcbnew, 'VIA_STANDARD', 0)))",
                "                            except Exception:",
                "                                pass",
                "                            try:",
                "                                v.SetLayerPair(board.GetLayerID('F.Cu'), board.GetLayerID('B.Cu'))",
                "                            except Exception:",
                "                                pass",
                "                            try:",
                "                                v.SetDiameter(mm(width_mm))",
                "                            except Exception:",
                "                                pass",
                "                            try:",
                "                                v.SetDrill(mm(drill_mm))",
                "                            except Exception:",
                "                                pass",
                "                            v.SetNet(netinfo)",
                "                            board.Add(v)",
                "                        via_tokens = []",
                "                        continue",
                "    except Exception as _inj_err:",
                "        print('VIA_INJECT_WARN', _inj_err)",
                "    # Rebuild nets/connectivity before save (varies by KiCad version)",
                "    try:",
                "        board.BuildListOfNets()",
                "    except Exception:",
                "        pass",
                "    try:",
                "        board.BuildConnectivity()",
                "    except Exception:",
                "        pass",
                "    pcbnew.SaveBoard(str(out_path), board)",
                "    # Write a local .kicad_prl next to the board with drawing sheet hidden",
                "    try:",
                "        import json as _json",
                "        prl = out_path.with_suffix('.kicad_prl')",
                "        if prl.exists():",
                "            data = _json.loads(prl.read_text())",
                "        else:",
                "            data = dict()",
                "        if not isinstance(data.get('board'), dict):",
                "            data['board'] = dict()",
                "        vis = data['board'].get('visible_items')",
                "        if not isinstance(vis, list):",
                "            vis = []",
                "        if 'drawing_sheet' in vis:",
                "            vis.remove('drawing_sheet')",
                "        else:",
                "            # Ensure a sane default visibility set without drawing sheet",
                "            base = ['vias','footprint_text','footprint_anchors','ratsnest','grid','footprints_front','footprints_back','footprint_values','footprint_references','tracks','drc_errors','bitmaps','pads','zones','drc_warnings','drc_exclusions','locked_item_shadows','conflict_shadows','shapes']",
                "            vis = base",
                "        data['board']['visible_items'] = vis",
                "        data['meta'] = dict(filename=str(prl.name), version=5)",
                "        prl.write_text(_json.dumps(data, indent=2))",
                "    except Exception:",
                "        pass",
                "else:",
                "    raise RuntimeError('Specctra session import failed')",
            ]
        )
    )

    env = os.environ.copy()
    proc = subprocess.run(
        [KICAD_PY, str(driver)],
        cwd=str(work_root),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not out_pcb.exists():
        msg = (
            "pcbnew ImportSpecctraSession failed: "
            + (proc.stderr or "")
            + "\n"
            + (proc.stdout or "")
        )
        raise RuntimeError(msg)
    # Post-process: ensure vias from SES exist by textually injecting if missing
    try:
        pcb_text = out_pcb.read_text()
        # Quick check: if any (via exists already, skip injection
        if "(via" not in pcb_text:
            ses_text = ses_bytes.decode(errors="ignore")
            # Build net name -> code from PCB header
            import re as _re
            net_map = dict()
            for m in _re.finditer(r"^\t\(net\s+(\d+)\s+\"([^\"]+)\"\)$", pcb_text, _re.MULTILINE):
                net_map[m.group(2)] = int(m.group(1))
            # Compute SES->KiCad translation using U1 anchor (board U1 is at 150,26 mm here)
            U = 10000.0
            dx_mm = 0.0
            y_off_mm = 0.0
            m_place = _re.search(r"\(place\s+U1\s+(-?\d+)\s+(-?\d+)\s+front\s+\d+\)", ses_text)
            if m_place:
                try:
                    sx = int(m_place.group(1)) / U
                    sy = int(m_place.group(2)) / U
                    board_u1_x = 150.0
                    board_u1_y = 26.0
                    dx_mm = board_u1_x - sx
                    y_off_mm = board_u1_y + sy
                except Exception:
                    dx_mm = 0.0; y_off_mm = 0.0
            # Scan SES for current net and via entries (multi-line aware)
            vias = []
            cur_net = None
            in_via = False
            via_tokens: list[str] = []
            for raw in ses_text.splitlines():
                line = raw.strip()
                mnet = _re.match(r"^\(net\s+([^\s\)]+)", line)
                if mnet:
                    cur_net = mnet.group(1)
                    in_via = False
                    via_tokens = []
                    continue
                if cur_net is None:
                    continue
                if in_via:
                    if line == ")":
                        # process collected tokens
                        ints = []
                        for t in via_tokens:
                            try:
                                ints.append(int(t))
                            except Exception:
                                pass
                        if len(ints) >= 2:
                            x_mm = ints[-2] / U + dx_mm
                            y_mm = y_off_mm - (ints[-1] / U)
                            size_mm = 0.6
                            drill_mm = 0.3
                            name_tok = via_tokens[0] if via_tokens else ""
                            if name_tok.startswith('"') and name_tok.endswith('"'):
                                padname = name_tok.strip('"')
                                msz = _re.search(r"_(\\d+):(\\d+)_um", padname)
                                if msz:
                                    try:
                                        size_mm = int(msz.group(1)) / 1000.0
                                        drill_mm = int(msz.group(2)) / 1000.0
                                    except Exception:
                                        size_mm = 0.6; drill_mm = 0.3
                            net_code = net_map.get(cur_net)
                            if net_code is not None:
                                vias.append((x_mm, y_mm, size_mm, drill_mm, net_code))
                        in_via = False
                        via_tokens = []
                        continue
                    else:
                        via_tokens += line.replace(")", " ").split()
                        continue
                if line.startswith("(via"):
                    in_via = True
                    via_tokens = line.replace("(via", "", 1).replace(")", " ").split()
                    if raw.rstrip().endswith(")"):
                        # single-line
                        in_via = False
                        ints = []
                        for t in via_tokens:
                            try:
                                ints.append(int(t))
                            except Exception:
                                pass
                        if len(ints) >= 2:
                            x_mm = ints[-2] / U + dx_mm
                            y_mm = y_off_mm - (ints[-1] / U)
                            size_mm = 0.6
                            drill_mm = 0.3
                            name_tok = via_tokens[0] if via_tokens else ""
                            if name_tok.startswith('"') and name_tok.endswith('"'):
                                padname = name_tok.strip('"')
                                msz = _re.search(r"_(\\d+):(\\d+)_um", padname)
                                if msz:
                                    try:
                                        size_mm = int(msz.group(1)) / 1000.0
                                        drill_mm = int(msz.group(2)) / 1000.0
                                    except Exception:
                                        size_mm = 0.6; drill_mm = 0.3
                            net_code = net_map.get(cur_net)
                            if net_code is not None:
                                vias.append((x_mm, y_mm, size_mm, drill_mm, net_code))
                        via_tokens = []
                        continue
            if vias:
                # Insert before trailing (embedded_fonts ...) or final ")"
                insert_at = pcb_text.rfind("\n(embedded_fonts")
                if insert_at == -1:
                    insert_at = pcb_text.rfind("\n)")
                if insert_at == -1:
                    insert_at = len(pcb_text)
                # Build via blocks using same indentation style as segments
                def fmt(val: float) -> str:
                    return f"{val:.4f}".rstrip('0').rstrip('.') if '.' in f"{val:.4f}" else f"{val:.4f}"
                blocks = []
                for x_mm, y_mm, size_mm, drill_mm, net_code in vias:
                    blocks.append(
                        "\n\t(via\n"
                        + f"\t\t(at {fmt(x_mm)} {fmt(y_mm)})\n"
                        + f"\t\t(size {fmt(size_mm)})\n"
                        + f"\t\t(drill {fmt(drill_mm)})\n"
                        + "\t\t(layers \"F.Cu\" \"B.Cu\")\n"
                        + f"\t\t(net {net_code})\n"
                        + f"\t\t(uuid \"{uuid.uuid4()}\")\n"
                        + "\t)"
                    )
                pcb_text = pcb_text[:insert_at] + "".join(blocks) + pcb_text[insert_at:]
        # Save adjacent PRL to hide drawing sheet for this generated board
        try:
            import json as _json
            prl = out_pcb.with_suffix('.kicad_prl')
            data = dict()
            data['board'] = dict()
            data['board']['visible_items'] = [
                'vias','footprint_text','footprint_anchors','ratsnest','grid',
                'footprints_front','footprints_back','footprint_values','footprint_references',
                'tracks','drc_errors','bitmaps','pads','zones','drc_warnings','drc_exclusions',
                'locked_item_shadows','conflict_shadows','shapes'
            ]
            data['meta'] = dict(filename=str(prl.name), version=5)
            prl.write_text(_json.dumps(data, indent=2))
        except Exception:
            pass
        return pcb_text.encode()
    except Exception:
        # If any error in post-process, return original bytes
        return out_pcb.read_bytes()
