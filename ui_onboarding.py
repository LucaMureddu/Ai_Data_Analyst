from datetime import datetime
import customtkinter as ctk

from ui_constants import (
    ACCENT, ACCENT_HOV,
    TEXT_PRI,
    _font, _F_UI,
)

# ── Colori interni al tour (non condivisi col resto dell'app) ─────────────────
_BG_WIN    = "#050510"   # outer window — leggermente più scuro dell'app
_BG_CARD   = "#111128"   # card principale — percettibilmente elevata sul bg
_BG_BAR    = "#09091e"   # top-bar e nav-bar
_CARD_BRD  = "#252550"   # bordo card (visibile ma non invadente)
_BAR_DIV   = "#181838"   # separatore 1-px tra sezioni
_TEXT_BODY = "#9090b8"   # testo corpo slide — leggibile sul dark senza bruciare
_TEXT_STEP = "#44446a"   # "Passaggio X / Y" — discreto


class OnboardingTourWindow(ctk.CTkToplevel):
    """
    Tour guidato a carosello (4 slide) — primo avvio automatico.
    Riapribile dal pulsante '?' nella sidebar.
    Tastiera: frecce ←/→ per navigare, Esc per chiudere.
    """

    SLIDES = [
        {
            "step":   "1 / 4",
            "titolo": "Benvenuto in Data-Whisperer",
            "testo": (
                "Hai appena aperto il tuo analista dati AI personale.\n"
                "Funziona completamente offline: zero cloud, zero rete,\n"
                "zero tracce sul computer dell'utente.\n\n"
                "I tuoi dati restano dove sono — sul tuo drive."
            ),
            "icona":  "◈",
            "colore": "#00c896",
            "badge":  "#002920",
        },
        {
            "step":   "2 / 4",
            "titolo": "Installa il Motore AI",
            "testo": (
                "Clicca su  🗄️ Hub Modelli  nella barra laterale.\n\n"
                "Troverai modelli calibrati per ogni hardware:\n"
                "Apple Silicon, schede Nvidia e CPU standard.\n\n"
                "Un click per installare — poi sei pronto."
            ),
            "icona":  "🗄️",
            "colore": "#3b82f6",
            "badge":  "#0a1635",
        },
        {
            "step":   "3 / 4",
            "titolo": "Carica un File e Chiediti Tutto",
            "testo": (
                "Apri un CSV o Excel dalla sidebar.\n"
                "Poi scrivi in italiano quello che vuoi sapere:\n\n"
                "  «Qual è la sede con il fatturato più alto?»\n"
                "  «Mostrami il trend mensile delle vendite»\n\n"
                "L'IA scrive il codice, lo esegue e ti mostra il risultato."
            ),
            "icona":  "📊",
            "colore": "#a855f7",
            "badge":  "#1a0a35",
        },
        {
            "step":   "4 / 4",
            "titolo": "Conversa con i Grafici",
            "testo": (
                "Dopo che l'IA genera un grafico, puoi modificarlo a voce:\n\n"
                "  «Fallo a torta»  ·  «Usa colori più chiari»\n"
                "  «Aggiungi la legenda»  ·  «Rendi orizzontale»\n\n"
                "L'assistente ricorda il contesto e applica le modifiche\n"
                "in un istante, senza rielaborare i dati."
            ),
            "icona":  "✨",
            "colore": "#f59e0b",
            "badge":  "#2d1a00",
        },
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self._app = parent
        self._idx = 0

        self.title("Tour Guidato  ·  Data-Whisperer")
        self.geometry("680x530")
        self.resizable(False, False)
        self.configure(fg_color=_BG_WIN)
        self.grab_set()

        # Tasti freccia + Esc
        self.bind("<Right>",  lambda _e: self._avanti())
        self.bind("<Left>",   lambda _e: self._indietro())
        self.bind("<Escape>", lambda _e: self._chiudi())

        self.after(10, self._centra)
        self._build_shell()
        self._mostra_slide(0)

    # ── Posizionamento centrato sul parent ────────────────────────────────────

    def _centra(self):
        px = self._app.winfo_x() + self._app.winfo_width()  // 2 - 340
        py = self._app.winfo_y() + self._app.winfo_height() // 2 - 265
        self.geometry(f"680x530+{px}+{py}")

    # ── Struttura fissa: top-bar | card | nav-bar ─────────────────────────────

    def _build_shell(self):

        # ── Top bar: step counter (sx) + indicator dots (dx) ─────────────────
        top = ctk.CTkFrame(self, fg_color=_BG_BAR, corner_radius=0, height=50)
        top.pack(fill="x")
        top.pack_propagate(False)

        self._lbl_step = ctk.CTkLabel(
            top, text="", font=_font(11), text_color=_TEXT_STEP,
        )
        self._lbl_step.pack(side="left", padx=28, pady=0)

        dots_frame = ctk.CTkFrame(top, fg_color="transparent")
        dots_frame.pack(side="right", padx=28, pady=0)
        self._dots: list[ctk.CTkLabel] = []
        for _ in range(len(self.SLIDES)):
            d = ctk.CTkLabel(dots_frame, text="●", font=_font(9), text_color="#1e1e42")
            d.pack(side="left", padx=4)
            self._dots.append(d)

        # Separatore
        ctk.CTkFrame(self, height=1, fg_color=_BAR_DIV, corner_radius=0).pack(fill="x")

        # ── Area contenuto: outer padding + card elevata ──────────────────────
        outer = ctk.CTkFrame(self, fg_color=_BG_WIN)
        outer.pack(fill="both", expand=True, padx=22, pady=14)

        self._content = ctk.CTkFrame(
            outer, fg_color=_BG_CARD,
            corner_radius=16, border_width=1, border_color=_CARD_BRD,
        )
        self._content.pack(fill="both", expand=True)

        # Separatore
        ctk.CTkFrame(self, height=1, fg_color=_BAR_DIV, corner_radius=0).pack(fill="x")

        # ── Nav bar: Salta (sx) | ← Indietro + Avanti → (dx) ─────────────────
        nav = ctk.CTkFrame(self, fg_color=_BG_BAR, corner_radius=0, height=66)
        nav.pack(fill="x", side="bottom")
        nav.pack_propagate(False)

        ctk.CTkButton(
            nav, text="Salta", width=80, height=34,
            font=_font(11), fg_color="transparent", hover_color="#151530",
            text_color="#404060", border_width=0, corner_radius=8,
            command=self._chiudi,
        ).pack(side="left", padx=24, pady=16)

        self._btn_avanti = ctk.CTkButton(
            nav, text="Avanti  →", width=148, height=40,
            font=_font(13, "bold"), fg_color=ACCENT, hover_color=ACCENT_HOV,
            text_color="#000000", corner_radius=12, command=self._avanti,
        )
        self._btn_avanti.pack(side="right", padx=24, pady=16)

        self._btn_indietro = ctk.CTkButton(
            nav, text="←", width=46, height=40,
            font=_font(14), fg_color="transparent", hover_color="#151530",
            text_color="#5a5a8a", border_color="#252550", border_width=1,
            corner_radius=12, command=self._indietro,
        )
        self._btn_indietro.pack(side="right", padx=(0, 6), pady=16)

    # ── Rendering slide ───────────────────────────────────────────────────────

    def _mostra_slide(self, idx: int):
        self._idx  = idx
        slide      = self.SLIDES[idx]
        colore     = slide["colore"]
        badge_bg   = slide["badge"]
        is_ultima  = (idx == len(self.SLIDES) - 1)

        # Svuota la card
        for w in self._content.winfo_children():
            w.destroy()

        # Striscia colorata in cima alla card (identità visiva della slide)
        ctk.CTkFrame(
            self._content, height=5, fg_color=colore, corner_radius=0,
        ).pack(fill="x")

        # Corpo (centrato verticalmente nella card)
        body = ctk.CTkFrame(self._content, fg_color="transparent")
        body.pack(expand=True)

        # Badge icona: cerchio con bordo colorato + emoji interna
        badge = ctk.CTkFrame(
            body, width=84, height=84, corner_radius=22,
            fg_color=badge_bg, border_width=1, border_color=colore,
        )
        badge.pack(pady=(26, 0))
        badge.pack_propagate(False)
        ctk.CTkLabel(
            badge, text=slide["icona"],
            font=(_F_UI, 34), text_color=colore,
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Titolo
        ctk.CTkLabel(
            body, text=slide["titolo"],
            font=(_F_UI, 20, "bold"), text_color=TEXT_PRI,
        ).pack(pady=(14, 0))

        # Sottile separatore colorato sotto il titolo
        ctk.CTkFrame(
            body, width=44, height=2, fg_color=colore, corner_radius=1,
        ).pack(pady=(8, 12))

        # Testo corpo
        ctk.CTkLabel(
            body, text=slide["testo"],
            font=_font(13), text_color=_TEXT_BODY,
            justify="center", anchor="center", wraplength=510,
        ).pack(pady=(0, 30))

        # ── Aggiorna top-bar ──────────────────────────────────────────────────
        self._lbl_step.configure(text=f"Passaggio  {slide['step']}")

        for i, dot in enumerate(self._dots):
            if i < idx:
                # slide già vista — puntino piccolo, grigio caldo
                dot.configure(text_color="#2e2e58", font=_font(8))
            elif i == idx:
                # slide attiva — puntino grande, colore slide
                dot.configure(text_color=colore, font=_font(14))
            else:
                # slide futura — puntino minimo
                dot.configure(text_color="#1a1a3a", font=_font(8))

        # ── Aggiorna pulsanti nav ─────────────────────────────────────────────
        self._btn_indietro.configure(state="normal" if idx > 0 else "disabled")
        self._btn_avanti.configure(
            text="✓  Inizia!" if is_ultima else "Avanti  →",
            fg_color=colore   if is_ultima else ACCENT,
            hover_color=ACCENT_HOV,
        )

    # ── Navigazione ───────────────────────────────────────────────────────────

    def _avanti(self):
        if self._idx < len(self.SLIDES) - 1:
            self._mostra_slide(self._idx + 1)
        else:
            self._chiudi()

    def _indietro(self):
        if self._idx > 0:
            self._mostra_slide(self._idx - 1)

    def _chiudi(self):
        try:
            with open(self._app._tour_flag_path, "w") as f:
                f.write(datetime.now().isoformat())
        except OSError:
            pass
        self.grab_release()
        self.destroy()
