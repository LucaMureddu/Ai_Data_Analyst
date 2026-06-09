import io
import customtkinter as ctk
from ui_constants import ACCENT, BTN_IDLE, BTN_HOV, BTN_BORDER


class _SilentRedirect(io.TextIOWrapper):
    """Cattura i print() interni senza sporcare la chat."""
    def __init__(self, callback):
        super().__init__(io.BytesIO(), encoding="utf-8")
        self._cb = callback

    def write(self, t: str):
        if t.strip():
            self._cb(t)

    def flush(self):
        pass


class _HoverButton(ctk.CTkButton):
    """CTkButton con hover più pronunciato via bind on_enter/on_leave."""
    def __init__(self, *args, **kwargs):
        self._idle_fg  = kwargs.get("fg_color", BTN_IDLE)
        self._hover_fg = kwargs.get("hover_color", BTN_HOV)
        super().__init__(*args, **kwargs)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event=None):
        if self.cget("state") != "disabled":
            self.configure(fg_color=self._hover_fg, border_color=ACCENT)

    def _on_leave(self, _event=None):
        self.configure(fg_color=self._idle_fg, border_color=BTN_BORDER)
