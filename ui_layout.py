import customtkinter as ctk
from ui_constants import (
    BG_MAIN, INPUT_BG, BORDER, ACCENT, ACCENT_HOV, ACCENT_DIM,
    TEXT_PRI, TEXT_SEC, FONT_CHAT, WIN_W, WIN_H,
    _font,
)


class LayoutMixin:
    """Costruisce lo scheletro della finestra: griglia principale, area chat, barra input."""

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()   # implementato in SidebarMixin
        self._build_main()

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self._chat = ctk.CTkScrollableFrame(
            main, fg_color=BG_MAIN, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT_DIM,
        )
        self._chat.grid(row=0, column=0, sticky="nsew")
        self._chat.grid_columnconfigure(0, weight=1)

        self._msg_sistema("Caricamento modello in corso — attendere...")

        ctk.CTkFrame(main, height=1, fg_color=BORDER).grid(row=1, column=0, sticky="ew")
        self._build_input(main)

    def _build_input(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=INPUT_BG, corner_radius=0, height=80)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_propagate(False)

        self._txt_query = ctk.CTkEntry(
            bar,
            placeholder_text="Scrivi la tua analisi…  (es. 'Mostra il trend del fatturato')",
            height=48,
            font=FONT_CHAT,
            fg_color="#0e0e1e",
            border_color=BORDER,
            text_color=TEXT_PRI,
            placeholder_text_color=TEXT_SEC,
            corner_radius=12,
            state="disabled",
        )
        self._txt_query.grid(row=0, column=0, padx=(20, 12), pady=16, sticky="ew")
        self._txt_query.bind("<Return>", lambda e: self._avvia_analisi())

        self._btn_run = ctk.CTkButton(
            bar,
            text="Invia",
            width=88, height=48,
            font=_font(13, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOV,
            text_color="#000000",
            corner_radius=12,
            command=self._avvia_analisi,
            state="disabled",
        )
        self._btn_run.grid(row=0, column=1, padx=(0, 20), pady=16)
