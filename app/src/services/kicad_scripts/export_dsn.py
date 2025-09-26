import pcbnew
import wx
from pathlib import Path

# Initialize minimal wxApp
_app = wx.App(False)

pcb_path = Path(r"__PCB_PATH__")
out_path = Path(r"__OUT_PATH__")

board = pcbnew.LoadBoard(str(pcb_path))

ok = False
try:
    board.ExportSpecctraDSN(str(out_path))
    ok = True
except Exception as e1:
    fn = getattr(pcbnew, "ExportSpecctraDSN", None)
    if callable(fn):
        try:
            fn(board, str(out_path))
            ok = True
        except Exception as e2:
            print("EXPORT_DSN_ALT_FAILED", e2)
    else:
        print("EXPORT_DSN_METHOD_FAILED", e1)

if not ok:
    raise RuntimeError("DSN export failed")
