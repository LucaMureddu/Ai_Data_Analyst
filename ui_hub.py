import os
import sys
import threading

import customtkinter as ctk

from ui_constants import (
    BG_MAIN, SIDEBAR_BG, AI_BG, ACCENT, ACCENT_DIM, ACCENT_HOV,
    TEXT_PRI, TEXT_SEC, TEXT_ERR,
    BORDER, BTN_IDLE, BTN_HOV,
    FONT_SMALL, FONT_MICRO, FONT_BADGE,
    _font, _OS,
)
from core_engine import trova_modelli, _APP_ROOT


class ModelHubWindow(ctk.CTkToplevel):
    """
    Finestra modale che mostra i 4 tier di modelli AI.
    Legge la RAM del sistema, evidenzia il modello consigliato,
    verifica la presenza dei file .gguf in models/ e li copia in locale
    usando un loop a chunk (senza bloccare la UI).
    Zero chiamate di rete.
    """

    CATALOGO = [
        {
            "tier":       "Base",
            "nome":       "Qwen 2.5 Coder 7B",
            "file":       "qwen2.5-coder-7b.gguf",
            "peso":       "~4.7 GB",
            "ram_soglia": 0,
            "desc": (
                "Veloce e leggero. Ideale per task quotidiani e analisi\n"
                "standard. Lascia respiro al sistema operativo."
            ),
            "colore": "#00c896",
        },
        {
            "tier":       "Pro",
            "nome":       "Qwen 2.5 Coder 14B",
            "file":       "qwen2.5-coder-14b.gguf",
            "peso":       "~9.0 GB",
            "ram_soglia": 12,
            "desc": (
                "Il bilanciamento perfetto. Capacità logiche avanzate,\n"
                "quasi zero allucinazioni su grafici complessi."
            ),
            "colore": "#3b82f6",
        },
        {
            "tier":       "Ultra",
            "nome":       "Qwen 2.5 Coder 32B",
            "file":       "qwen2.5-coder-32b.gguf",
            "peso":       "~20.0 GB",
            "ram_soglia": 24,
            "desc": (
                "Potenza pura. Livello di ragionamento da Senior Data\n"
                "Analyst. Perfetto per dataset molto complessi."
            ),
            "colore": "#a855f7",
        },
        {
            "tier":       "Enterprise",
            "nome":       "Qwen 2.5 Coder 72B",
            "file":       "qwen2.5-coder-72b.gguf",
            "peso":       "~42.0 GB",
            "ram_soglia": 40,
            "desc": (
                "L'intelligenza definitiva. Prestazioni paragonabili a\n"
                "GPT-4, interamente offline sul tuo hardware."
            ),
            "colore": "#f59e0b",
        },
    ]

    _CHUNK_BYTES = 4 * 1024 * 1024

    def __init__(self, parent):
        super().__init__(parent)
        self._app = parent

        self.title("Hub Installazione Modelli  ·  Data-Whisperer")
        self.geometry("720x640")
        self.resizable(False, False)
        self.configure(fg_color=BG_MAIN)
        self.grab_set()

        import psutil as _psutil
        self._ram_gb: float = _psutil.virtual_memory().total / (1024 ** 3)

        # In dev: sorgente = models/, destinazione = models/
        # In frozen: sorgente = accanto al .app/models/, destinazione = accanto al .app
        self._src_dir = os.path.join(_APP_ROOT, "models")
        if getattr(sys, "frozen", False):
            self._dst_dir = _APP_ROOT
        else:
            self._dst_dir = os.path.join(_APP_ROOT, "models")

        if self._ram_gb < 12:
            self._tier_consigliato = "Base"
        elif self._ram_gb < 24:
            self._tier_consigliato = "Pro"
        elif self._ram_gb < 40:
            self._tier_consigliato = "Ultra"
        else:
            self._tier_consigliato = "Enterprise"

        self._installing = False
        self._widgets: dict[str, dict] = {}

        self._build_ui()

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color=SIDEBAR_BG, corner_radius=0, height=68)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🗄️  Hub Installazione Modelli",
                     font=_font(16, "bold"), text_color=TEXT_PRI).pack(side="left", padx=24, pady=18)
        ctk.CTkLabel(hdr,
                     text=f"RAM: {self._ram_gb:.0f} GB  ·  Consigliato: {self._tier_consigliato}",
                     font=FONT_SMALL, text_color=TEXT_SEC).pack(side="right", padx=20)

        scroll = ctk.CTkScrollableFrame(
            self, fg_color=BG_MAIN,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT_DIM,
        )
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1)

        for modello in self.CATALOGO:
            self._build_card(scroll, modello)

        ftr = ctk.CTkFrame(self, fg_color=SIDEBAR_BG, corner_radius=0, height=34)
        ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)
        ctk.CTkLabel(ftr, text=f"Sorgente: {self._src_dir}",
                     font=FONT_MICRO, text_color=TEXT_SEC).pack(side="left", padx=16, pady=8)

    def _build_card(self, parent, modello: dict):
        tier   = modello["tier"]
        colore = modello["colore"]
        src    = os.path.join(self._src_dir, modello["file"])
        dst    = os.path.join(self._dst_dir, modello["file"])
        in_src = os.path.exists(src)
        in_dst = os.path.exists(dst)
        consig = (tier == self._tier_consigliato)

        card = ctk.CTkFrame(
            parent, fg_color="#12122a" if consig else AI_BG,
            border_color=colore if consig else BORDER,
            border_width=2 if consig else 1, corner_radius=14,
        )
        card.pack(fill="x", padx=16, pady=(10, 2))
        card.grid_columnconfigure(1, weight=1)

        striscia = ctk.CTkFrame(card, width=6, fg_color=colore, corner_radius=0)
        striscia.grid(row=0, column=0, rowspan=5, sticky="nsw")
        striscia.grid_propagate(False)

        hdr_frame = ctk.CTkFrame(card, fg_color="transparent")
        hdr_frame.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(10, 14), pady=(12, 4))
        ctk.CTkLabel(hdr_frame, text=f"  {tier.upper()}  ",
                     font=_font(9, "bold"), fg_color=colore,
                     text_color="#000000" if tier == "Base" else "#ffffff",
                     corner_radius=5, height=20).pack(side="left", padx=(0, 8))
        if consig:
            ctk.CTkLabel(hdr_frame, text="  ⭐ CONSIGLIATO  ",
                         font=_font(9, "bold"), fg_color="#2a1e00",
                         text_color="#fbbf24", corner_radius=5, height=20).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(hdr_frame, text=modello["peso"],
                     font=FONT_SMALL, text_color=TEXT_SEC).pack(side="right")

        ctk.CTkLabel(card, text=modello["nome"],
                     font=_font(13, "bold"), text_color=TEXT_PRI, anchor="w").grid(
            row=1, column=1, columnspan=2, sticky="w", padx=(10, 14), pady=(0, 4))
        ctk.CTkLabel(card, text=modello["desc"],
                     font=FONT_SMALL, text_color=TEXT_SEC,
                     justify="left", anchor="nw", wraplength=500).grid(
            row=2, column=1, columnspan=2, sticky="w", padx=(10, 14), pady=(0, 10))

        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(10, 14), pady=(0, 6))
        btn_frame.grid_columnconfigure(0, weight=1)

        if in_dst:
            btn_txt, btn_state, btn_fg, btn_tc, btn_hov = (
                "✓  Già installato", "disabled", ACCENT_DIM, ACCENT, ACCENT_DIM)
        elif in_src:
            os_name = "Mac" if _OS == "Darwin" else "PC"
            btn_txt, btn_state, btn_fg, btn_tc, btn_hov = (
                f"⬇  Installa sul {os_name}", "normal", colore,
                "#000000" if tier == "Base" else "#ffffff", ACCENT_HOV)
        else:
            btn_txt, btn_state, btn_fg, btn_tc, btn_hov = (
                "✗  Non presente nel supporto", "disabled", BTN_IDLE, TEXT_SEC, BTN_IDLE)

        btn = ctk.CTkButton(
            btn_frame, text=btn_txt, height=36,
            font=_font(11, "bold"), fg_color=btn_fg, hover_color=btn_hov,
            text_color=btn_tc, corner_radius=10, state=btn_state,
            command=lambda m=modello, s=src, d=dst: self._avvia_installazione(m, s, d),
            anchor="w",
        )
        btn.grid(row=0, column=0, sticky="w")

        pf = ctk.CTkFrame(btn_frame, fg_color="transparent")
        pf.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        pf.grid_columnconfigure(0, weight=1)
        pf.grid_remove()

        prog = ctk.CTkProgressBar(pf, height=8, corner_radius=4,
                                  fg_color=BORDER, progress_color=colore)
        prog.set(0)
        prog.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        lbl_prog = ctk.CTkLabel(pf, text="", font=FONT_MICRO, text_color=TEXT_SEC, anchor="w")
        lbl_prog.grid(row=1, column=0, sticky="w")

        self._widgets[tier] = {
            "btn": btn, "prog_frame": pf, "prog": prog,
            "lbl_prog": lbl_prog, "src": src, "dst": dst,
        }

    # ── Installazione ─────────────────────────────────────────────────────────

    def _avvia_installazione(self, modello: dict, src: str, dst: str):
        if self._installing:
            return
        self._installing = True
        for w in self._widgets.values():
            w["btn"].configure(state="disabled")

        tier = modello["tier"]
        ww   = self._widgets[tier]
        ww["prog_frame"].grid()
        ww["prog"].set(0)
        ww["lbl_prog"].configure(text="Avvio installazione...", text_color=TEXT_SEC)

        threading.Thread(target=self._copia_thread, args=(modello, src, dst),
                         daemon=True).start()

    def _copia_thread(self, modello: dict, src: str, dst: str):
        tier = modello["tier"]
        try:
            dim     = os.path.getsize(src)
            copiati = 0
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                while True:
                    chunk = fsrc.read(self._CHUNK_BYTES)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    copiati += len(chunk)
                    p  = copiati / dim if dim > 0 else 0
                    mc = copiati / (1024 ** 2)
                    mt = dim     / (1024 ** 2)
                    self.after(0, lambda _p=p, _mc=mc, _mt=mt, _t=tier:
                               self._aggiorna_progresso(_t, _p, _mc, _mt))
            self.after(0, lambda: self._installazione_ok(modello, dst))
        except Exception as exc:
            try:
                if os.path.exists(dst):
                    os.unlink(dst)
            except OSError:
                pass
            self.after(0, lambda e=str(exc): self._installazione_errore(tier, e))

    def _aggiorna_progresso(self, tier: str, p: float, mc: float, mt: float):
        ww = self._widgets.get(tier)
        if not ww:
            return
        ww["prog"].set(p)
        ww["lbl_prog"].configure(
            text=f"Installazione in corso: {mc:,.0f} MB / {mt:,.0f} MB  ({p * 100:.1f}%)")

    def _installazione_ok(self, modello: dict, dst: str):
        tier = modello["tier"]
        ww   = self._widgets.get(tier)
        if ww:
            ww["prog"].set(1.0)
            ww["lbl_prog"].configure(text="✓  Installazione completata!", text_color=ACCENT)
            ww["btn"].configure(text="✓  Già installato", state="disabled",
                                fg_color=ACCENT_DIM, text_color=ACCENT)
        self._installing = False
        self._riabilita_bottoni()
        self.after(300, lambda: self._app._aggiorna_opt_modello_dopo_install(
            os.path.basename(dst)))

    def _installazione_errore(self, tier: str, msg: str):
        ww = self._widgets.get(tier)
        if ww:
            ww["prog"].set(0)
            ww["lbl_prog"].configure(text=f"✗  Errore: {msg[:70]}", text_color=TEXT_ERR)
        self._installing = False
        self._riabilita_bottoni()

    def _riabilita_bottoni(self):
        os_name = "Mac" if _OS == "Darwin" else "PC"
        for modello in self.CATALOGO:
            tier = modello["tier"]
            ww   = self._widgets.get(tier)
            if not ww or os.path.exists(ww["dst"]):
                continue
            if os.path.exists(ww["src"]):
                ww["btn"].configure(
                    state="normal", fg_color=modello["colore"],
                    text_color="#000000" if tier == "Base" else "#ffffff",
                    text=f"⬇  Installa sul {os_name}",
                )
