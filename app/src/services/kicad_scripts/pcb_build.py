import pcbnew
import math
import wx
from pathlib import Path

# Initialize minimal wxApp for plugin-dependent APIs
_app = wx.App(False)

board = pcbnew.BOARD()

# Units helper
mm = pcbnew.FromMM

# Set a rounded-rectangle outline on Edge.Cuts (fixed board size)
edge = board.GetLayerID('Edge.Cuts')
x0, y0 = 0, 0
x1, y1 = 300.0, 200.0
R = 8.0  # corner radius (mm)

def add_line(xa, ya, xb, yb):
    seg = pcbnew.PCB_SHAPE(board)
    seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
    seg.SetLayer(edge)
    seg.SetStart(pcbnew.VECTOR2I(mm(xa), mm(ya)))
    seg.SetEnd(pcbnew.VECTOR2I(mm(xb), mm(yb)))
    board.Add(seg)

def add_quarter_arc_segments(cx: float, cy: float, deg0: float, deg1: float, steps: int = 18):
    # Draw a quarter (or any) arc on Edge.Cuts as short segments (API-safe)
    rad = R
    a0 = math.radians(deg0)
    a1 = math.radians(deg1)
    px = cx + rad * math.cos(a0)
    py = cy + rad * math.sin(a0)
    for i in range(1, steps + 1):
        t = i / steps
        ang = a0 + (a1 - a0) * t
        nx = cx + rad * math.cos(ang)
        ny = cy + rad * math.sin(ang)
        add_line(px, py, nx, ny)
        px, py = nx, ny

# Straight edges shortened by radius
add_line(x0 + R, y0, x1 - R, y0)      # top
add_line(x1, y0 + R, x1, y1 - R)      # right
add_line(x1 - R, y1, x0 + R, y1)      # bottom
add_line(x0, y1 - R, x0, y0 + R)      # left

# Corner arcs as segmented quarter-circles (inward sweep)
# top-right corner center
add_quarter_arc_segments(x1 - R, y0 + R, -90.0, 0.0)
# bottom-right corner center
add_quarter_arc_segments(x1 - R, y1 - R, 0.0, 90.0)
# bottom-left corner center
add_quarter_arc_segments(x0 + R, y1 - R, 90.0, 180.0)
# top-left corner center
add_quarter_arc_segments(x0 + R, y0 + R, 180.0, 270.0)

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
    # Always try local_fallback library first when present
    try:
        fallback_pretty = (proj / 'local.pretty')
        if fallback_pretty.exists():
            try:
                print('TRY_LOCAL_FALLBACK', name)
                mod = pcbnew.FootprintLoad('local_fallback', name)
            except Exception as e:
                print(f'TRY_LOCAL_FALLBACK FAILED: {e}')
                mod = None
            if not mod:
                try:
                    io = pcbnew.PCB_IO()
                    mod = io.FootprintLoad(str(fallback_pretty), name)
                except Exception as e:
                    print(f'TRY_PCBIO_FALLBACK FAILED: {e}')
                    mod = None
            if not mod:
                try:
                    io = pcbnew.PCB_IO()
                    mod = io.FootprintLoad(str(fallback_pretty), name + '.kicad_mod')
                except Exception as e:
                    print(f'TRY_PCBIO_FALLBACK_SUFFIXED FAILED: {e}')
                    mod = None
            if mod:
                mod.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
                mod.SetOrientationDegrees(rot)
                mod.SetReference(ref_name)
                board.Add(mod)
                return
    except Exception:
        pass

    mod = None
    if nickname is not None:
        try:
            print(f'TRY_NICKNAME: {nickname}/{name}')
            mod = pcbnew.FootprintLoad(nickname, name)
        except Exception as e:
            print(f'TRY_NICKNAME FAILED: {e}')
            mod = None
    # Prefer direct file-path load if a root-level fallback file exists (most robust across KiCad builds)
    if not mod:
        try:
            alt = (proj / (name + ".kicad_mod"))
            if alt.exists():
                try:
                    print('TRY_LOAD_ALT_EMPTYLIB_NAMEPATH', alt)
                    mod = pcbnew.FootprintLoad("", str(alt))
                except Exception as e:
                    print(f'TRY_LOAD_ALT_EMPTYLIB_NAMEPATH FAILED: {e}')
                    mod = None
                if not mod:
                    try:
                        print('TRY_LOAD_ALT_LIBPATH_EMPTYNAME', alt)
                        mod = pcbnew.FootprintLoad(str(alt), "")
                    except Exception as e:
                        print(f'TRY_LOAD_ALT_LIBPATH_EMPTYNAME FAILED: {e}')
                        mod = None
                if not mod:
                    try:
                        print('TRY_PCBIO_ALT_PARENT_NAME', alt.parent, alt.name)
                        io = pcbnew.PCB_IO()
                        mod = io.FootprintLoad(str(alt.parent), alt.name)
                    except Exception as e:
                        print(f'TRY_PCBIO_ALT_PARENT_NAME FAILED: {e}')
                        mod = None
                if not mod:
                    try:
                        print('TRY_PCBIO_ALT_PARENT_STEM', alt.parent, alt.stem)
                        io = pcbnew.PCB_IO()
                        mod = io.FootprintLoad(str(alt.parent), alt.stem)
                    except Exception as e:
                        print(f'TRY_PCBIO_ALT_PARENT_STEM FAILED: {e}')
                        mod = None
                if not mod:
                    try:
                        print('TRY_IO_MGR_KICAD_SEXPR', alt)
                        io_mgr = pcbnew.IO_MGR()
                        plugin = io_mgr.PluginFind(pcbnew.IO_MGR.KICAD_SEXPR)
                        mod = plugin.FootprintLoad(str(alt), pcbnew.IO_MGR.KICAD_SEXPR)
                    except Exception as e:
                        print(f'TRY_IO_MGR_KICAD_SEXPR FAILED: {e}')
                        mod = None
        except Exception:
            mod = None
    if not mod:
        try:
            print('TRY_LOAD_PRETTY_NAME', pretty, name)
            mod = pcbnew.FootprintLoad(str(pretty), name)
        except Exception as e:
            print('ERR_LOAD_PRETTY_NAME', e)
            mod = None
    if not mod:
        # KiCad 7 fallback: some builds require the .kicad_mod suffix as name
        try:
            print('TRY_LOAD_PRETTY_NAME_WITH_EXT', pretty, name)
            mod = pcbnew.FootprintLoad(str(pretty), name + ".kicad_mod")
        except Exception as e:
            print(f'TRY_LOAD_PRETTY_NAME_WITH_EXT FAILED: {e}')
            mod = None
    if not mod:
        # Last resort 1: try giving full file path as the library argument
        try:
            target = (pretty / (name + ".kicad_mod"))
            print('TRY_LOAD_TARGET_AS_LIB_WITH_NAME', target, name)
            mod = pcbnew.FootprintLoad(str(target), name)
        except Exception as e:
            print(f'TRY_LOAD_TARGET_AS_LIB_WITH_NAME FAILED: {e}')
            mod = None
    if not mod:
        # Last resort 2: some KiCad 7 builds accept empty name when lib points to file
        try:
            target = (pretty / (name + ".kicad_mod"))
            print('TRY_LOAD_TARGET_AS_LIB_EMPTYNAME', target)
            mod = pcbnew.FootprintLoad(str(target), "")
        except Exception as e:
            print(f'TRY_LOAD_TARGET_AS_LIB_EMPTYNAME FAILED: {e}')
            mod = None
    if not mod:
        # Last resort 3: empty lib, full file path as name (observed on some builds)
        try:
            target = (pretty / (name + ".kicad_mod"))
            print('TRY_LOAD_EMPTYLIB_TARGET_AS_NAME', target)
            mod = pcbnew.FootprintLoad("", str(target))
        except Exception as e:
            print(f'TRY_LOAD_EMPTYLIB_TARGET_AS_NAME FAILED: {e}')
            mod = None
    if not mod:
        # Last resort 4: use PCB_IO plugin loader explicitly
        try:
            print('TRY_PCBIO_PRETTY_NAME', pretty, name)
            io = pcbnew.PCB_IO()
            mod = io.FootprintLoad(str(pretty), name)
        except Exception as e:
            print(f'TRY_PCBIO_PRETTY_NAME FAILED: {e}')
            mod = None
    if not mod:
        try:
            print('TRY_PCBIO_PRETTY_NAME_WITH_EXT', pretty, name)
            io = pcbnew.PCB_IO()
            mod = io.FootprintLoad(str(pretty), name + ".kicad_mod")
        except Exception as e:
            print(f'TRY_PCBIO_PRETTY_NAME_WITH_EXT FAILED: {e}')
            mod = None
    if not mod:
        try:
            target = (pretty / (name + ".kicad_mod"))
            print('TRY_PCBIO_PARENT_NAME', target.parent, target.name)
            io = pcbnew.PCB_IO()
            mod = io.FootprintLoad(str(target.parent), target.name)
        except Exception as e:
            print(f'TRY_PCBIO_PARENT_NAME FAILED: {e}')
            mod = None
    if not mod:
        # Last resort 5: load root-level fallback footprint file included in project template
        try:
            alt = (proj / (name + ".kicad_mod"))
            if alt.exists():
                # Try various loaders against direct file path
                try:
                    mod = pcbnew.FootprintLoad(str(alt), "")
                except Exception as e:
                    print(f'TRY_ROOT_FALLBACK_EMPTY_NAME FAILED: {e}')
                    mod = None
                if not mod:
                    try:
                        io = pcbnew.PCB_IO()
                        mod = io.FootprintLoad(str(alt.parent), alt.name)
                    except Exception as e:
                        print(f'TRY_ROOT_FALLBACK_PCBIO_PARENT_NAME FAILED: {e}')
                        mod = None
        except Exception as e:
            print(f'TRY_ROOT_FALLBACK_GENERAL FAILED: {e}')
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

# Place/move Pico (U1) to a fixed position (tolerate load failure on older KiCad)
try:
    load_and_place('raspberry-pi-pico.pretty', 'RPi_Pico_SMD_TH', 'U1', 150.0, 26.0, 0.0)
except Exception as _pico_err:
    print('WARN_PICO_FOOTPRINT_LOAD', _pico_err)

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
            try:
                load_and_place('mount.pretty', 'MountingHole_3.2mm_M3', _r, _hx, _hy, 0.0)
            except Exception as _mh_err:
                print('WARN_MOUNT_FOOTPRINT_LOAD', _mh_err)

# Place switches
switches = __SWITCHES__
for ref_name, x, y, rot, size in switches:
    fp_name = f"switch_{int(size)}"
    # fallback to 24 if not recognized
    if fp_name not in ['switch_18', 'switch_24', 'switch_30']:
        fp_name = 'switch_24'
    load_and_place('kailh-choc-hotswap.pretty', fp_name, ref_name, x, y, rot)

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
