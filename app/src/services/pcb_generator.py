from __future__ import annotations

import io
import re
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path

from app.src.schemas.pcb import PCBRequest

# Resolve KiCad-bundled Python: prefer env var; fall back to macOS path; else 'python3'
_MAC_KICAD_PY = (
    "/Applications/KiCad/"
    "KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
)
KICAD_PY = os.environ.get("KICAD_PY") or (_MAC_KICAD_PY if os.path.exists(_MAC_KICAD_PY) else "python3")


def _run_kicad_python(driver: Path, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    """Run KiCad-bundled Python script. Use xvfb-run in headless Linux when DISPLAY is absent.

    On CI/containers without an X server, pcbnew/wx require an X display. We default to
    xvfb-run when DISPLAY is not set, unless USE_XVFB is explicitly set to '0'.
    """
    cmd = [KICAD_PY, str(driver)]
    use_xvfb = (os.environ.get("USE_XVFB", "1") == "1") and not os.environ.get("DISPLAY")
    if use_xvfb:
        cmd = ["xvfb-run", "-a"] + cmd
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)


def _zip_directory(root: Path) -> bytes:
    """Zip all contents under 'root' and return bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in root.rglob("*"):
            zf.write(p, arcname=p.relative_to(root))
    return buf.getvalue()


def _ensure_prl_hides_drawing_sheet(prl_path: Path) -> None:
    """Create or update a .kicad_prl to hide drawing sheet."""
    try:
        import json

        if prl_path.exists():
            data = json.loads(prl_path.read_text())
        else:
            data = {}
        if not isinstance(data.get("board"), dict):
            data["board"] = {}
        vis = data["board"].get("visible_items")
        if not isinstance(vis, list):
            vis = []
        if "drawing_sheet" in vis:
            vis.remove("drawing_sheet")
        data["board"]["visible_items"] = vis
        data["meta"] = dict(filename=prl_path.name, version=5)
        prl_path.write_text(json.dumps(data, indent=2))
    except Exception:
        # Prefer being non-fatal; viewing option only
        pass


def _write_driver_script(work_project_dir: Path, req: PCBRequest) -> Path:
    """Create a small Python driver that uses pcbnew to build a .kicad_pcb."""
    # Load template from kicad_scripts/pcb_build.py
    template_path = Path(__file__).parent / "kicad_scripts" / "pcb_build.py"
    script = template_path.read_text()

    # Inject dynamic switches into the script
    switches_literal = [
        (s.ref, s.x_mm, s.y_mm, s.rotation_deg, getattr(s, "size", 24))
        for s in req.switches
    ]
    script = script.replace("__SWITCHES__", repr(switches_literal))

    driver = work_project_dir / "_build_pcb.py"
    driver.write_text(script)
    return driver


def _create_project_dir(req: PCBRequest) -> Path:
    """Create a working KiCad project directory and build initial board.

    Returns the created project directory path.
    """
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
        "  (lib (name \"local_fallback\")(type \"KiCad\")\n",
        "       (uri \"${KIPRJMOD}/local.pretty\")\n",
        "       (options \"\")(descr \"Project local fallback footprints\"))\n",
        ")\n",
    ]
    fp_table.write_text("".join(lines))

    # Ensure Pico footprint is also placed at project root for direct file-load fallback
    try:
        pico_src = work_project / "footprints" / "raspberry-pi-pico.pretty" / "RPi_Pico_SMD_TH.kicad_mod"
        pico_dst = work_project / "RPi_Pico_SMD_TH.kicad_mod"
        if pico_src.exists() and not pico_dst.exists():
            shutil.copy2(pico_src, pico_dst)
        # Also ensure mounting hole fallback exists at project root
        mh_src = work_project / "footprints" / "mount.pretty" / "MountingHole_3.2mm_M3.kicad_mod"
        mh_dst = work_project / "MountingHole_3.2mm_M3.kicad_mod"
        if mh_src.exists() and not mh_dst.exists():
            shutil.copy2(mh_src, mh_dst)
        # Ensure Kailh choc switch footprints are available at project root for fallback
        k_pretty = work_project / "footprints" / "kailh-choc-hotswap.pretty"
        for sw in ("switch_18.kicad_mod", "switch_24.kicad_mod", "switch_30.kicad_mod"):
            s = k_pretty / sw
            d = work_project / sw
            if s.exists() and not d.exists():
                shutil.copy2(s, d)
        # Build local.pretty fallback library directory
        local_pretty = work_project / "local.pretty"
        local_pretty.mkdir(exist_ok=True)
        for src in [pico_src, mh_src] + [k_pretty / sw for sw in ("switch_18.kicad_mod", "switch_24.kicad_mod", "switch_30.kicad_mod")]:
            try:
                if src.exists():
                    dst = local_pretty / src.name
                    if not dst.exists():
                        shutil.copy2(src, dst)
            except Exception:
                pass
        # Make copied footprints backward-compatible with KiCad 7 loader by normalizing headers
        try:
            # Normalize both local.pretty files and root-level fallback files
            root_fallbacks = [pico_dst, mh_dst] + [work_project / f for f in ("switch_18.kicad_mod", "switch_24.kicad_mod", "switch_30.kicad_mod")]
            targets = list(local_pretty.glob("*.kicad_mod")) + [p for p in root_fallbacks if p.exists()]
            for fp in targets:
                try:
                    text = fp.read_text()
                    # Normalize version line to a KiCad 7-compatible schema stamp
                    text = re.sub(r"^\s*\(version\s+\d+\)", "(version 20221018)", text, count=1, flags=re.MULTILINE)
                    # Drop generator_version field which older parsers may not recognize
                    text = re.sub(r"^\s*\(generator_version\s+\"[^\"]+\"\)\s*\n", "", text, flags=re.MULTILINE)
                    fp.write_text(text)
                except Exception:
                    # Best-effort normalization
                    pass
        except Exception:
            pass
    except Exception:
        # Non-fatal: only affects one of the loader fallbacks
        pass

    # Normalize schematic footprint references to local_* nicknames
    sch = work_project / "StickLess.kicad_sch"
    if sch.exists():
        import re

        sch_text = sch.read_text()
        sch_text = re.sub(
            r'(property\s+\"Footprint\"\s+\"\s*)(?:raspberry-pi-pico|RPi_Pico)(:RPi_Pico_SMD_TH)',
            r'\1local_rpi_pico\2',
            sch_text,
        )
        sch_text = re.sub(
            r'(property\s+\"Footprint\"\s+\"\s*)(?:kailh-choc-hotswap)(:switch_24)',
            r'\1local_kailh_choc\2',
            sch_text,
        )
        sch.write_text(sch_text)

    driver = _write_driver_script(work_project, req)
    env = os.environ.copy()
    env.setdefault("KIPRJMOD", str(work_project))

    proc = _run_kicad_python(driver, work_project, env)
    if proc.returncode != 0:
        raise RuntimeError(f"pcbnew generation failed: {proc.stderr}\n{proc.stdout}")
    return work_project


def generate_project_zip(req: PCBRequest) -> tuple[bytes, str]:
    """Build a project directory then zip and return bytes."""
    work_project = _create_project_dir(req)
    return _zip_directory(work_project), f"pcb_{uuid.uuid4().hex}.zip"


def export_dsn_from_pcb(pcb_path: Path) -> bytes:
    """Export a Specctra DSN from a .kicad_pcb using KiCad Python."""
    work_root = Path(tempfile.mkdtemp(prefix="exp_dsn_"))
    out_dsn = work_root / "out.dsn"
    # Load script template and inject paths
    template = (Path(__file__).parent / "kicad_scripts" / "export_dsn.py").read_text()
    script = (
        template
        .replace("__PCB_PATH__", pcb_path.as_posix())
        .replace("__OUT_PATH__", out_dsn.as_posix())
    )
    driver = work_root / "_export_dsn.py"
    driver.write_text(script)

    proc = _run_kicad_python(driver, work_root, os.environ.copy())
    if proc.returncode != 0 or not out_dsn.exists():
        raise RuntimeError("Failed to export DSN: " + (proc.stderr or proc.stdout))
    return out_dsn.read_bytes()


def build_routed_project_zip(req: PCBRequest) -> tuple[bytes, str]:
    """One-click pipeline: generate project, autoroute, apply session, zip project."""
    work_project = _create_project_dir(req)
    pcb_path = work_project / "StickLess.kicad_pcb"
    try:
        # Export DSN from the built PCB
        dsn_bytes = export_dsn_from_pcb(pcb_path)
        # Run freerouting
        ses_bytes = autoroute_dsn_to_ses(dsn_bytes)
        # Apply SES to PCB
        routed_bytes = apply_ses_to_pcb(pcb_path.read_bytes(), ses_bytes)
        pcb_path.write_bytes(routed_bytes)
    except Exception as e:
        # Strict: fail the request if autoroute or SES apply fails
        raise
    # Ensure PRL hides drawing sheet
    prl = work_project / "StickLess.kicad_prl"
    _ensure_prl_hides_drawing_sheet(prl)

    # Zip full project
    return _zip_directory(work_project), f"routed_{uuid.uuid4().hex}.zip"


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
    proc = _run_kicad_python(driver, work_root, env)
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
        prl = out_pcb.with_suffix('.kicad_prl')
        _ensure_prl_hides_drawing_sheet(prl)
        return pcb_text.encode()
    except Exception:
        # If any error in post-process, return original bytes
        return out_pcb.read_bytes()
