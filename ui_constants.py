import platform
import customtkinter as ctk

_OS = platform.system()
if _OS == "Darwin":
    _F_UI   = "Helvetica Neue"
    _F_MONO = "Menlo"
elif _OS == "Windows":
    _F_UI   = "Segoe UI"
    _F_MONO = "Consolas"
else:
    _F_UI   = "Helvetica"
    _F_MONO = "Courier New"


def _font(size: int, weight: str = "normal") -> tuple:
    return (_F_UI, size, weight)

def _mono(size: int) -> tuple:
    return (_F_MONO, size, "normal")


FONT_TITLE  = _font(14, "bold")
FONT_LABEL  = _font(13)
FONT_SMALL  = _font(11)
FONT_MICRO  = _font(10)
FONT_CHAT   = _font(13)
FONT_BADGE  = _font(10, "bold")
FONT_MONO   = _mono(11)

# ── Palette Dark Corporate Premium ────────────────────────────────────────────
BG_MAIN     = "#09090f"
SIDEBAR_BG  = "#0c0c17"
USER_BG     = "#0b2d22"
AI_BG       = "#16161f"
CODE_BG     = "#0d0d1c"
INPUT_BG    = "#0f0f1c"
ACCENT      = "#00c896"
ACCENT_HOV  = "#00b386"
ACCENT_DIM  = "#052e22"
ACCENT_SIDE = "#00c896"
ERR_BAR     = "#c0392b"
TEXT_PRI    = "#e4e8f5"
TEXT_SEC    = "#4e546e"
TEXT_CODE   = "#7ecec4"
TEXT_ERR    = "#e57373"
TEXT_OK     = "#66bb6a"
BORDER      = "#18182c"
DIVIDER     = "#13132b"
BTN_IDLE    = "#141428"
BTN_HOV     = "#1e1e38"
BTN_BORDER  = "#2a2a48"

# ── Layout ────────────────────────────────────────────────────────────────────
SIDEBAR_W        = 240
WIN_W, WIN_H     = 1040, 720
BUBBLE_MAX       = 560
WRAP_CODE        = 600

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
