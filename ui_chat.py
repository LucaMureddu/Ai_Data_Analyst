import io
import os
import re
import threading
from datetime import datetime

import customtkinter as ctk
from PIL import Image

from ui_constants import (
    AI_BG, CODE_BG, USER_BG, BG_MAIN,
    ACCENT, ACCENT_HOV, ACCENT_SIDE, ACCENT_DIM,
    ERR_BAR, BORDER, BTN_IDLE, BTN_HOV, BTN_BORDER,
    TEXT_PRI, TEXT_SEC, TEXT_ERR, TEXT_CODE,
    FONT_CHAT, FONT_BADGE, FONT_MICRO, FONT_MONO,
    BUBBLE_MAX, WRAP_CODE,
    _font,
)
from core_engine import elabora_query_multi_agente, RisultatoMultiAgente, _APP_ROOT, ERRORE_ANNULLATO


def _strip_markdown(testo: str) -> str:
    """Rimuove markdown semplice (bold, italic, heading, bullet, inline code) dal testo."""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", testo, flags=re.DOTALL)
    t = re.sub(r"\*(.+?)\*",     r"\1", t,     flags=re.DOTALL)
    t = re.sub(r"^#{1,6}\s+",   "",    t,     flags=re.MULTILINE)
    t = re.sub(r"^[-*]\s+",     "• ",  t,     flags=re.MULTILINE)
    t = re.sub(r"`(.+?)`",      r"\1", t)
    return t


class ChatMixin:
    """Rendering messaggi chat, scroll, avvio analisi e nuova chat."""

    # ── Messaggi ──────────────────────────────────────────────────────────────

    def _msg_utente(self, testo: str):
        row = ctk.CTkFrame(self._chat, fg_color="transparent")
        row.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=(8, 2))
        row.grid_columnconfigure(0, weight=1)

        bubble = ctk.CTkFrame(row, fg_color=USER_BG, corner_radius=15)
        bubble.grid(row=0, column=0, sticky="e")
        ctk.CTkLabel(
            bubble, text=testo,
            font=FONT_CHAT, text_color=TEXT_PRI,
            wraplength=BUBBLE_MAX, justify="left", anchor="w",
        ).pack(padx=18, pady=12)

        self._chat_row += 1
        self._scroll_bottom()

    def _msg_assistente(self, testo: str, tag: str = "text"):
        if tag == "text":
            testo = _strip_markdown(testo)
        WARN_BAR  = "#d97706"
        TEXT_WARN = "#fbbf24"
        bar_color = ERR_BAR  if tag == "err"  else WARN_BAR  if tag == "warn" else ACCENT_SIDE
        txt_color = TEXT_ERR if tag == "err"  else TEXT_WARN if tag == "warn" else TEXT_PRI

        row = ctk.CTkFrame(self._chat, fg_color="transparent")
        row.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=(2, 2))
        ctk.CTkFrame(row, width=3, corner_radius=2, fg_color=bar_color).pack(
            side="left", fill="y", padx=(0, 10), pady=2)

        bubble = ctk.CTkFrame(row, fg_color=AI_BG, corner_radius=15)
        bubble.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            bubble, text=testo,
            font=FONT_CHAT, text_color=txt_color,
            wraplength=BUBBLE_MAX, justify="left", anchor="w",
        ).pack(padx=18, pady=12, anchor="w")

        self._chat_row += 1
        self._scroll_bottom()

    def _msg_piano(self, piano: str):
        # Rimuovi markdown residuo dal testo del modello (**grassetto**, *corsivo*)
        piano_clean = re.sub(r'\*\*(.+?)\*\*', r'\1', piano)
        piano_clean = re.sub(r'\*(.+?)\*',     r'\1', piano_clean)

        row = ctk.CTkFrame(self._chat, fg_color="transparent")
        row.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=(6, 2))
        ctk.CTkFrame(row, width=3, corner_radius=2, fg_color="#7c3aed").pack(
            side="left", fill="y", padx=(0, 10), pady=2)

        bubble = ctk.CTkFrame(row, fg_color=AI_BG, corner_radius=15)
        bubble.pack(side="left", fill="x", expand=True)

        # ── Header cliccabile ─────────────────────────────────────────────────
        _aperto = [False]

        header = ctk.CTkFrame(bubble, fg_color="#110d1f", corner_radius=0, height=32)
        header.pack(fill="x")
        header.pack_propagate(False)

        lbl_toggle = ctk.CTkLabel(
            header, text="  🏛️  Piano Architetto  ▸",
            font=FONT_BADGE, text_color="#a78bfa", anchor="w", cursor="hand2",
        )
        lbl_toggle.pack(side="left", padx=12, pady=6)

        # ── Contenuto collassabile (nascosto di default) ───────────────────────
        content = ctk.CTkFrame(bubble, fg_color="transparent")

        ctk.CTkLabel(
            content, text=piano_clean,
            font=FONT_CHAT, text_color="#c4b5fd",
            wraplength=BUBBLE_MAX, justify="left", anchor="w",
        ).pack(padx=18, pady=(10, 14), anchor="w")

        def _toggle(_event=None):
            if _aperto[0]:
                content.pack_forget()
                lbl_toggle.configure(text="  🏛️  Piano Architetto  ▸")
                _aperto[0] = False
            else:
                content.pack(fill="x")
                lbl_toggle.configure(text="  🏛️  Piano Architetto  ▾")
                _aperto[0] = True
            self._scroll_bottom()

        header.bind("<Button-1>", _toggle)
        lbl_toggle.bind("<Button-1>", _toggle)

        self._chat_row += 1
        self._scroll_bottom()

    # ── Widget elaborazione (progress bar durante l'analisi) ──────────────────

    def _crea_widget_elaborazione(self):
        """Inserisce nella chat una progress bar animata mentre gli agenti lavorano."""
        row = ctk.CTkFrame(self._chat, fg_color="transparent")
        row.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=(8, 2))
        ctk.CTkFrame(row, width=3, corner_radius=2, fg_color=ACCENT_SIDE).pack(
            side="left", fill="y", padx=(0, 10), pady=2)

        card = ctk.CTkFrame(row, fg_color=AI_BG, corner_radius=15)
        card.pack(side="left", fill="x", expand=True)

        header = ctk.CTkFrame(card, fg_color="#0d0d20", corner_radius=0, height=28)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text="  ⚙  Analisi in corso",
            font=FONT_BADGE, text_color=ACCENT, anchor="w",
        ).pack(side="left", padx=12, pady=4)

        self._elab_prog = ctk.CTkProgressBar(
            card, height=6, corner_radius=3,
            fg_color=BORDER, progress_color=ACCENT,
        )
        self._elab_prog.set(0.05)
        self._elab_prog.pack(fill="x", padx=16, pady=(10, 4))

        self._elab_lbl = ctk.CTkLabel(
            card, text="Avvio analisi...",
            font=FONT_MICRO, text_color=TEXT_SEC, anchor="w",
        )
        self._elab_lbl.pack(anchor="w", padx=16, pady=(0, 12))

        self._elab_row = row
        self._chat_row += 1
        self._scroll_bottom()

    def _aggiorna_elaborazione(self, frac: float, label: str):
        """Aggiorna progress bar e testo step — chiamato dal thread agenti via after()."""
        if not hasattr(self, "_elab_prog"):
            return
        try:
            if self._elab_prog.winfo_exists():
                self._elab_prog.set(frac)
            if self._elab_lbl.winfo_exists():
                self._elab_lbl.configure(text=label)
        except Exception:
            pass

    def _rimuovi_elaborazione(self):
        """Rimuove il widget progress dalla chat prima di mostrare i risultati."""
        if hasattr(self, "_elab_row"):
            try:
                if self._elab_row.winfo_exists():
                    self._elab_row.destroy()
            except Exception:
                pass
            for attr in ("_elab_row", "_elab_prog", "_elab_lbl"):
                self.__dict__.pop(attr, None)

    def _msg_codice(self, codice: str):
        row = ctk.CTkFrame(self._chat, fg_color="transparent")
        row.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=(2, 2))
        ctk.CTkFrame(row, width=3, corner_radius=2, fg_color="#3d5a80").pack(
            side="left", fill="y", padx=(0, 10), pady=2)

        card = ctk.CTkFrame(row, fg_color=CODE_BG, corner_radius=15)
        card.pack(side="left", fill="x", expand=True)

        header = ctk.CTkFrame(card, fg_color="#0f0f22", corner_radius=0, height=28)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text="  python",
            font=FONT_BADGE, text_color=TEXT_SEC, anchor="w",
        ).pack(side="left", padx=12, pady=5)

        ctk.CTkLabel(
            card, text=codice,
            font=FONT_MONO, text_color=TEXT_CODE,
            justify="left", anchor="w", wraplength=WRAP_CODE,
        ).pack(padx=16, pady=(10, 14), anchor="w")

        self._chat_row += 1
        self._scroll_bottom()

    def _msg_grafico(self, png_bytes: bytes, nome_file: str = ""):
        try:
            img_pil = Image.open(io.BytesIO(png_bytes))
            max_w   = BUBBLE_MAX + 60
            ratio   = max_w / img_pil.width
            new_h   = int(img_pil.height * ratio)
            img_pil = img_pil.resize((max_w, new_h), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img_pil, dark_image=img_pil,
                                   size=(max_w, new_h))
            self._img_refs.append(ctk_img)
        except Exception as e:
            self._msg_assistente(f"Impossibile renderizzare il grafico: {e}", tag="err")
            return

        row = ctk.CTkFrame(self._chat, fg_color="transparent")
        row.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=(6, 4))
        ctk.CTkFrame(row, width=3, corner_radius=2, fg_color=ACCENT).pack(
            side="left", fill="y", padx=(0, 10), pady=2)

        card = ctk.CTkFrame(row, fg_color=AI_BG, corner_radius=15)
        card.pack(side="left")
        lbl_img = ctk.CTkLabel(card, image=ctk_img, text="", cursor="hand2")
        lbl_img.pack(padx=10, pady=(10, 6))
        lbl_img.bind("<Button-1>", lambda _e, b=png_bytes: self._apri_grafico_fullscreen(b))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=12, pady=(0, 10))
        if nome_file:
            ctk.CTkLabel(
                footer, text=f"  {nome_file}",
                font=FONT_MICRO, text_color=TEXT_SEC, anchor="w",
            ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            footer,
            text="↓  Salva Grafico",
            height=28, font=_font(11, "bold"),
            fg_color=ACCENT_DIM, hover_color=ACCENT,
            text_color=ACCENT, border_color=ACCENT_DIM,
            border_width=1, corner_radius=8,
            command=lambda b=png_bytes: self._salva_grafico_su_disco(b),
        ).pack(side="right")

        self._chat_row += 1
        self._scroll_bottom()

    def _salva_grafico_su_disco(self, png_bytes: bytes):
        from tkinter import filedialog as _fd
        percorso = _fd.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("Immagine PNG", "*.png"), ("Tutti i file", "*.*")],
            title="Esporta grafico",
            initialfile=f"grafico_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
        )
        if not percorso:
            return
        try:
            with open(percorso, "wb") as f:
                f.write(png_bytes)
            self._msg_sistema(f"Grafico esportato: {os.path.basename(percorso)}")
        except OSError as e:
            self._msg_assistente(f"Errore salvataggio grafico: {e}", tag="err")

    def _msg_sistema(self, testo: str):
        row = ctk.CTkFrame(self._chat, fg_color="transparent")
        row.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=4)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=testo, font=FONT_MICRO, text_color=TEXT_SEC).grid(row=0, column=0)
        self._chat_row += 1
        self._scroll_bottom()

    def _msg_query_suggerite(self, suggerimenti: list):
        if not suggerimenti:
            return
        outer = ctk.CTkFrame(self._chat, fg_color="transparent")
        outer.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=(2, 8))
        ctk.CTkFrame(outer, width=3, corner_radius=2, fg_color=ACCENT_SIDE).pack(
            side="left", fill="y", padx=(0, 10), pady=2)

        card = ctk.CTkFrame(outer, fg_color=AI_BG, corner_radius=15)
        card.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            card,
            text="  💡  Domande suggerite — clicca per usare",
            font=FONT_BADGE, text_color=TEXT_SEC, anchor="w",
        ).pack(padx=12, pady=(10, 6), anchor="w")

        chips = ctk.CTkFrame(card, fg_color="transparent")
        chips.pack(fill="x", padx=10, pady=(0, 10))

        for q in suggerimenti:
            ctk.CTkButton(
                chips,
                text=f"  {q}", height=30,
                font=_font(10),
                fg_color=BTN_IDLE, hover_color=ACCENT_DIM,
                text_color=TEXT_PRI, border_color=BORDER,
                border_width=1, corner_radius=15,
                command=lambda query=q: self._riusa_query(query),
                anchor="w",
            ).pack(fill="x", padx=4, pady=2)

        self._chat_row += 1
        self._scroll_bottom()

    def _msg_anteprima_dataset(self, df):
        import pandas as pd
        MAX_COLS = 7
        MAX_ROWS = 5

        cols = list(df.columns[:MAX_COLS])
        n_extra = len(df.columns) - len(cols)
        sample = df[cols].head(MAX_ROWS)

        try:
            col_widths = []
            for c in cols:
                try:
                    max_val = int(sample[c].astype(str).str.len().max())
                except Exception:
                    max_val = 8
                col_widths.append(min(max(len(str(c)), max_val) + 1, 22))

            header = "  ".join(str(c).ljust(w) for c, w in zip(cols, col_widths))
            sep    = "--".join("-" * w for w in col_widths)
            lines  = [header, sep]
            for _, row_vals in sample.iterrows():
                line = "  ".join(
                    str(v)[:w].ljust(w) for v, w in zip(row_vals, col_widths)
                )
                lines.append(line)
            table_text = "\n".join(lines)
            if n_extra > 0:
                table_text += f"\n... +{n_extra} colonne non mostrate"
        except Exception:
            table_text = df.head(MAX_ROWS).to_string(index=False)

        outer = ctk.CTkFrame(self._chat, fg_color="transparent")
        outer.grid(row=self._chat_row, column=0, sticky="ew", padx=20, pady=(4, 2))
        ctk.CTkFrame(outer, width=3, corner_radius=2, fg_color="#2563eb").pack(
            side="left", fill="y", padx=(0, 10), pady=2)

        card = ctk.CTkFrame(outer, fg_color=CODE_BG, corner_radius=15)
        card.pack(side="left", fill="x", expand=True)

        header_bar = ctk.CTkFrame(card, fg_color="#0f0f22", corner_radius=0, height=28)
        header_bar.pack(fill="x")
        ctk.CTkLabel(
            header_bar,
            text=f"  📊  Anteprima — prime {min(len(df), MAX_ROWS)} righe",
            font=FONT_BADGE, text_color=TEXT_SEC, anchor="w",
        ).pack(side="left", padx=12, pady=5)

        txt = ctk.CTkTextbox(
            card,
            font=FONT_MONO,
            text_color=TEXT_CODE,
            fg_color="transparent",
            height=min(40 + len(sample) * 22, 200),
            wrap="none",
            state="normal",
            activate_scrollbars=True,
        )
        txt.pack(padx=16, pady=(8, 12), fill="x")
        txt.insert("1.0", table_text)
        txt.configure(state="disabled")

        self._chat_row += 1
        self._scroll_bottom()

    def _apri_grafico_fullscreen(self, png_bytes: bytes):
        viewer = ctk.CTkToplevel(self)
        viewer.title("Data-Whisperer — Grafico")
        viewer.configure(fg_color=BG_MAIN)
        viewer.resizable(True, True)

        screen_w = viewer.winfo_screenwidth()
        screen_h = viewer.winfo_screenheight()
        max_w = min(screen_w - 100, 1400)
        max_h = min(screen_h - 160, 900)

        img_pil = Image.open(io.BytesIO(png_bytes))
        ratio   = min(max_w / img_pil.width, max_h / img_pil.height, 1.0)
        new_w   = int(img_pil.width  * ratio)
        new_h   = int(img_pil.height * ratio)
        img_res = img_pil.resize((new_w, new_h), Image.LANCZOS)

        ctk_img = ctk.CTkImage(light_image=img_res, dark_image=img_res, size=(new_w, new_h))
        self._img_refs.append(ctk_img)

        win_w, win_h = new_w + 40, new_h + 80
        x = max(0, (screen_w - win_w) // 2)
        y = max(0, (screen_h - win_h) // 2)
        viewer.geometry(f"{win_w}x{win_h}+{x}+{y}")

        ctk.CTkLabel(viewer, image=ctk_img, text="", cursor="arrow").pack(
            padx=20, pady=(16, 8))

        bottom = ctk.CTkFrame(viewer, fg_color="transparent")
        bottom.pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkButton(
            bottom, text="↓  Salva PNG", width=130, height=34,
            font=_font(11, "bold"),
            fg_color=ACCENT_DIM, hover_color=ACCENT, text_color=ACCENT,
            corner_radius=10,
            command=lambda: self._salva_grafico_su_disco(png_bytes),
        ).pack(side="left")

        ctk.CTkButton(
            bottom, text="Chiudi  ✕", width=120, height=34,
            font=_font(11, "bold"),
            fg_color=BTN_IDLE, hover_color=BTN_HOV, text_color=TEXT_SEC,
            corner_radius=10, command=viewer.destroy,
        ).pack(side="right")

        viewer.bind("<Escape>", lambda e: viewer.destroy())
        viewer.focus()

    # ── Scroll ────────────────────────────────────────────────────────────────

    def _scroll_bottom(self):
        self.after(80, lambda: self._chat._parent_canvas.yview_moveto(1.0))
        self._bind_mouse_scroll(self._chat)

    def _bind_mouse_scroll(self, widget):
        """Lega ricorsivamente MouseWheel a tutti i figli — fix macOS CTkScrollableFrame."""
        if getattr(widget, "_scroll_bound", False):
            return
        widget._scroll_bound = True
        widget.bind("<MouseWheel>", self._on_mousewheel)
        for child in widget.winfo_children():
            self._bind_mouse_scroll(child)

    def _on_mousewheel(self, event):
        if hasattr(self._chat, "_mouse_wheel_all"):
            self._chat._mouse_wheel_all(event)

    # ── Analisi ───────────────────────────────────────────────────────────────

    def _avvia_analisi(self):
        if self._busy:
            return
        query = self._txt_query.get().strip()
        if not query:
            return
        if self._dataset is None:
            self._msg_assistente("Carica prima un file dati.", tag="err")
            return

        self._query_in_elaborazione = query
        self._msg_utente(query)
        self._txt_query.delete(0, "end")
        self._busy = True
        self._cancel_event.clear()
        self._btn_run.configure(
            state="normal", text="✕  Annulla",
            fg_color="#7f1d1d", hover_color="#991b1b",
            text_color="#ffffff", command=self._on_annulla_analisi,
        )
        self._txt_query.configure(state="disabled")
        self._crea_widget_elaborazione()
        threading.Thread(target=self._analisi_thread, args=(query,), daemon=True).start()

    def _analisi_thread(self, query: str):
        import traceback as _tb
        try:
            def _cb(frac: float, label: str):
                self.after(0, lambda f=frac, l=label: self._aggiorna_elaborazione(f, l))

            risultato_ma = elabora_query_multi_agente(
                self._llm,
                self._dataset,
                query,
                max_tentativi_qa=3,
                ultimo_codice_valido=self._ultimo_codice_eseguito,
                progress_callback=_cb,
                cancel_event=self._cancel_event,
                memoria_conversazione=list(self._memoria_conversazione),
            )
            self.after(0, lambda: self._mostra_risultato_ma(risultato_ma))
        except Exception:
            tb = _tb.format_exc()
            self.after(0, self._rimuovi_elaborazione)
            self.after(0, lambda: self._msg_assistente(tb, tag="err"))
            self.after(0, self._reset_ui)

    def _mostra_risultato_ma(self, r: "RisultatoMultiAgente"):
        self._rimuovi_elaborazione()

        if r.errore_pipeline == ERRORE_ANNULLATO:
            self._msg_sistema("Analisi annullata.")
            self._reset_ui()
            return

        if not r.successo and not r.codice_finale:
            self._msg_assistente(r.errore_pipeline, tag="warn")
            self._reset_ui()
            return

        if r.piano_logico:
            self._msg_piano(r.piano_logico)
        if r.codice_finale:
            self._msg_codice(r.codice_finale)
        if r.tentativi_qa > 0:
            self._msg_sistema(
                f"🔧 Auto-corretto in {r.tentativi_qa} "
                f"tentativo{'i' if r.tentativi_qa > 1 else ''} dal QA."
            )

        if r.risultato:
            if r.risultato.successo:
                _testo = (r.risultato.output_testo or "").strip()
                if _testo and _testo.lower() != "none":
                    self._msg_assistente(_testo)

                self._report_items.append({
                    "ts":           datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "query":        self._query_in_elaborazione,
                    "piano":        r.piano_logico,
                    "codice":       r.codice_finale,
                    "output_testo": _testo,
                    "grafici_png":  list(r.risultato.grafici_png),
                    "tentativi_qa": r.tentativi_qa,
                })

                # Aggiorna memoria conversazione (max 3 entry)
                _risposta_mem = _testo[:200] if _testo else ""
                if not _risposta_mem and r.risultato.grafici_png:
                    _risposta_mem = "Grafico generato."
                if _risposta_mem:
                    self._memoria_conversazione.append({
                        "query":   self._query_in_elaborazione,
                        "risposta": _risposta_mem,
                    })
                    self._memoria_conversazione = self._memoria_conversazione[-3:]

                _grafici_nomi: list = []
                if r.risultato.grafici_png:
                    self._ultimo_codice_eseguito = r.codice_finale
                    output_dir = os.path.join(_APP_ROOT, "output")
                    os.makedirs(output_dir, exist_ok=True)
                    for i, png_bytes in enumerate(r.risultato.grafici_png):
                        nome_img = f"grafico_{datetime.now().strftime('%H%M%S')}_{i+1}.png"
                        try:
                            with open(os.path.join(output_dir, nome_img), "wb") as f:
                                f.write(png_bytes)
                            _grafici_nomi.append(nome_img)
                        except OSError:
                            nome_img = ""
                        self._msg_grafico(png_bytes, nome_file=nome_img)

                if not r.risultato.output_testo and not r.risultato.grafici_png:
                    self._msg_sistema("Esecuzione completata (nessun output testuale).")

                self._salva_storia(
                    self._query_in_elaborazione,
                    output_testo=_testo,
                    grafici_nomi=_grafici_nomi,
                )
                self.after(50, self._aggiorna_storia_sidebar)
            else:
                self._msg_assistente(r.errore_pipeline or r.risultato.errore, tag="err")
        elif not r.successo:
            self._msg_assistente(r.errore_pipeline, tag="err")

        self._reset_ui()

    def _reset_ui(self):
        self._busy = False
        self._btn_run.configure(
            state="normal", text="Invia",
            fg_color=ACCENT, hover_color=ACCENT_HOV,
            text_color="#000000", command=self._avvia_analisi,
        )
        self._txt_query.configure(state="normal")
        self._txt_query.focus()

    def _nuova_chat(self):
        if self._busy:
            return
        for widget in self._chat.winfo_children():
            widget.destroy()
        self._chat_row = 0
        self._img_refs.clear()
        self._report_items.clear()
        self._ultimo_codice_eseguito = None
        if self._dataset:
            self._msg_sistema(f"Nuova chat — Dataset attivo: {self._dataset.nome_file}")
        else:
            self._msg_sistema("Nuova chat avviata. Carica un file per iniziare.")
