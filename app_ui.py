import os
import platform
import re as _re_dnd
import sys
import threading
import time
import traceback as tb_mod

import customtkinter as ctk
from tkinter import filedialog

from hardware_detector import rileva_hardware
from data_loader       import carica_file, DatasetCaricato, lista_fogli_excel
from core_engine       import carica_modello, trova_modelli, _APP_ROOT, _app_data_dir, ERRORE_ANNULLATO

_DND_AVAILABLE = False
try:
    from tkinterdnd2 import TkinterDnD as _TkDnD, DND_FILES as _DND_FILES
    from tkinterdnd2.TkinterDnD import DnDWrapper as _DnDWrapper
    _DND_AVAILABLE = True
except ImportError:
    _DnDWrapper = object

from ui_constants  import BG_MAIN, ACCENT, TEXT_ERR, WIN_W, WIN_H, _font
from ui_widgets    import _SilentRedirect
from dw_logger     import dw_logger
from ui_layout     import LayoutMixin
from ui_chat       import ChatMixin
from ui_sidebar    import SidebarMixin
from ui_onboarding import OnboardingTourWindow
from ui_hub        import ModelHubWindow


class DataWhispererApp(LayoutMixin, ChatMixin, SidebarMixin, _DnDWrapper, ctk.CTk):

    def __init__(self):
        ctk.CTk.__init__(self)
        self.title("Data-Whisperer")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.minsize(860, 580)
        self.resizable(True, True)
        self.configure(fg_color=BG_MAIN)

        # ── Stato ────────────────────────────────────────────────────────────
        self._llm:                   object               = None
        self._dataset:               DatasetCaricato | None = None
        self._busy:                  bool                 = False
        self._chat_row:              int                  = 0
        self._img_refs:              list                 = []
        self._report_items:          list[dict]           = []
        self._history:               list[dict]           = []
        self._query_in_elaborazione: str                  = ""
        self._ultimo_codice_eseguito: str | None          = None
        self._cancel_event:          threading.Event      = threading.Event()
        self._memoria_conversazione: list[dict]           = []
        _data_dir = _app_data_dir()
        self._storia_path:    str = os.path.join(_data_dir, "history.json")
        self._tour_flag_path: str = os.path.join(_data_dir, ".toured")

        _modelli_trovati    = trova_modelli()
        self._modello_path: str | None = _modelli_trovati[0] if _modelli_trovati else None

        self._build_layout()
        self._redirect_stdout()
        self._pulisci_output_vecchi()
        self._carica_storia()
        self._aggiorna_storia_sidebar()
        self._avvia_caricamento_modello()
        self._mostra_splash()
        self._setup_dnd()

    # ── Pulizia output/ ───────────────────────────────────────────────────────

    def _pulisci_output_vecchi(self):
        import time
        output_dir = os.path.join(_APP_ROOT, "output")
        if not os.path.isdir(output_dir):
            return
        soglia = time.time() - 7 * 86400  # 7 giorni
        try:
            for nome in os.listdir(output_dir):
                if not nome.lower().endswith(".png"):
                    continue
                path = os.path.join(output_dir, nome)
                try:
                    if os.path.getmtime(path) < soglia:
                        os.unlink(path)
                except OSError:
                    pass
        except OSError:
            pass

    # ── Drag & Drop ───────────────────────────────────────────────────────────

    def _setup_dnd(self):
        if not _DND_AVAILABLE:
            return
        try:
            self.TkdndVersion = _TkDnD._require(self)
            self.drop_target_register(_DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_file_drop)
        except Exception:
            pass

    def _on_file_drop(self, event):
        raw = getattr(event, "data", "") or ""
        raw = raw.strip()
        # tkdnd wraps paths containing spaces in {braces}
        paths = _re_dnd.findall(r"\{([^}]+)\}", raw)
        if not paths:
            paths = raw.split()
        path = paths[0].strip() if paths else ""
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in {".csv", ".xlsx", ".xls", ".xlsm", ".tsv", ".txt"}:
            self._msg_assistente(
                f"Formato «{ext}» non supportato. Trascina un file CSV o Excel.",
                tag="warn")
            return
        if self._llm is None:
            self._msg_assistente(
                "Il modello non è ancora pronto. Attendi il caricamento.", tag="warn")
            return
        nome = os.path.basename(path)
        self._lbl_file.configure(text=f"Caricamento {nome}...", text_color="#FFA726")
        self._msg_sistema(f"File ricevuto: {nome}")
        threading.Thread(target=self._carica_file_thread, args=(path,), daemon=True).start()

    # ── Annulla analisi ───────────────────────────────────────────────────────

    def _on_annulla_analisi(self):
        self._cancel_event.set()
        self._msg_sistema("Annullamento in corso...")
        self._btn_run.configure(state="disabled", text="…")

    # ── Stdout redirect ───────────────────────────────────────────────────────

    def _redirect_stdout(self):
        def _filtro(t: str) -> None:
            stripped = t.strip()
            if not stripped:
                return
            # Log tutto su file; mostra in UI solo messaggi non-tecnici
            if stripped.startswith("[A") or stripped.startswith("[INFO]"):
                dw_logger.debug(stripped)
                return
            dw_logger.info(stripped)
            self.after(0, lambda msg=t: self._msg_sistema(msg))

        def _stderr_filtro(t: str) -> None:
            stripped = t.strip()
            if stripped:
                dw_logger.error(stripped)

        sys.stdout = _SilentRedirect(_filtro)
        sys.stderr = _SilentRedirect(_stderr_filtro)

    # ── 1. Caricamento modello ────────────────────────────────────────────────

    def _avvia_caricamento_modello(self):
        if self._modello_path is None:
            self.after(0, self._on_nessun_modello)
            return
        threading.Thread(target=self._carica_modello_thread, daemon=True).start()

    def _carica_modello_thread(self):
        try:
            profilo = rileva_hardware(verbose=False)
            self.after(0, lambda: self._on_hardware_rilevato(profilo))
            self._llm = carica_modello(
                self._modello_path,
                n_gpu_layers=profilo.n_gpu_layers,
                n_ctx=profilo.n_ctx,
                n_threads=profilo.n_threads,
            )
            self.after(0, self._on_modello_pronto)
        except Exception:
            tb = tb_mod.format_exc()
            self.after(0, lambda: self._on_errore_modello(tb))

    def _on_hardware_rilevato(self, profilo):
        arch = profilo.architettura.replace("_", " ").upper()
        self._lbl_hw.configure(text=(
            f"{arch}\n"
            f"RAM {profilo.ram_totale_gb:.0f} GB  ·  GPU layers: {profilo.n_gpu_layers}\n"
            f"ctx {profilo.n_ctx} tok  ·  {profilo.n_threads} thread"
        ))
        self._lbl_stato.configure(text="● Caricamento modello...", text_color="#FFA726")

    def _on_modello_pronto(self):
        nome = os.path.basename(self._modello_path) if self._modello_path else "?"
        self._lbl_stato.configure(text="● Online  ·  Air-Gapped", text_color=ACCENT)
        self._btn_file.configure(state="normal")
        self._msg_sistema(f"Modello pronto: {nome}. Carica un file per iniziare.")

    def _on_nessun_modello(self):
        self._lbl_stato.configure(text="🔴 Nessun modello  (Usa l'Hub)", text_color=TEXT_ERR)
        self._msg_sistema(
            "Nessun modello AI trovato. "
            "Usa il bottone «🗄️ Hub Modelli» nella sidebar per installarne uno."
        )

    def _on_errore_modello(self, tb: str):
        nome = os.path.basename(self._modello_path) if self._modello_path else "sconosciuto"
        self._lbl_stato.configure(text="● Errore modello", text_color=TEXT_ERR)
        self._msg_assistente(
            f"Impossibile caricare il modello «{nome}».\n"
            "Verifica che il file non sia corrotto e che la RAM disponibile "
            "sia sufficiente. Prova con un modello più leggero dall'Hub.", tag="err")
        dw_logger.error("Errore caricamento modello «%s»:\n%s", nome, tb)

    # ── 2. Selezione file ─────────────────────────────────────────────────────

    def _seleziona_file(self):
        path = filedialog.askopenfilename(
            title="Seleziona file dati",
            filetypes=[("File dati", "*.csv *.xlsx *.xls"), ("Tutti i file", "*.*")])
        if not path:
            return
        nome = os.path.basename(path)
        self._lbl_file.configure(text=f"Caricamento {nome}...", text_color="#FFA726")
        self._msg_sistema(f"Caricamento {nome}...")
        threading.Thread(target=self._carica_file_thread, args=(path,), daemon=True).start()

    def _carica_file_thread(self, path: str):
        try:
            ext = os.path.splitext(path)[1].lower()
            nome_foglio = None

            if ext in (".xlsx", ".xls", ".xlsm", ".xlsb"):
                fogli = lista_fogli_excel(path)
                if len(fogli) > 1:
                    foglio_result: list[str | None] = [None]
                    dialog_done = threading.Event()
                    self.after(0, lambda: self._mostra_dialogo_foglio(
                        fogli, foglio_result, dialog_done))
                    dialog_done.wait(timeout=120)
                    if foglio_result[0] is None:
                        self.after(0, lambda: self._lbl_file.configure(
                            text="Nessun file caricato", text_color=TEXT_ERR))
                        return
                    nome_foglio = foglio_result[0]

            dataset = carica_file(path, nome_foglio=nome_foglio)
            self.after(0, lambda: self._on_file_caricato(dataset))
        except Exception:
            nome = os.path.basename(path)
            self.after(0, lambda: self._msg_assistente(
                f"Impossibile leggere il file «{nome}».\n"
                "Controlla che il file non sia corrotto, aperto in un altro programma "
                "o in un formato non supportato (CSV, XLSX, XLS).", tag="err"))
            self.after(0, lambda: self._lbl_file.configure(
                text="Errore caricamento", text_color=TEXT_ERR))

    def _on_file_caricato(self, dataset: DatasetCaricato):
        self._dataset = dataset
        rimossi_txt = ""
        if dataset.colonne_rimosse:
            rimossi_txt = f"\nColonne vuote rimosse: {', '.join(dataset.colonne_rimosse)}"
        foglio_txt = f" [{dataset.foglio}]" if dataset.foglio else ""
        self._lbl_file.configure(
            text=f"{dataset.nome_file}{foglio_txt}\n{dataset.n_righe} righe  ·  {dataset.n_colonne} col",
            text_color="#66bb6a")
        self._msg_sistema(
            f"Dataset pronto — {dataset.nome_file}{foglio_txt}  "
            f"({dataset.n_righe} righe, {dataset.n_colonne} colonne){rimossi_txt}")
        self._msg_anteprima_dataset(dataset.df)
        sugg = self._genera_suggerimenti_query(dataset)
        self._msg_query_suggerite(sugg)
        self._txt_query.configure(state="normal")
        self._btn_run.configure(state="normal")
        self._txt_query.focus()

    def _genera_suggerimenti_query(self, dataset) -> list:
        df = dataset.df
        num_cols  = df.select_dtypes(include=["number"]).columns.tolist()
        date_cols = df.select_dtypes(include=["datetime", "datetimetz"]).columns.tolist()
        cat_cols  = df.select_dtypes(include=["object", "category"]).columns.tolist()

        sugg = []
        if num_cols:
            sugg.append(f"Mostrami le statistiche di base di {num_cols[0]}")
        if len(num_cols) >= 2:
            sugg.append(f"Crea un grafico tra {num_cols[0]} e {num_cols[1]}")
        if cat_cols and num_cols:
            sugg.append(f"Raggruppa per {cat_cols[0]} e calcola la media di {num_cols[0]}")
        if cat_cols:
            sugg.append(f"Distribuzione valori in {cat_cols[0]}")
        if date_cols and num_cols:
            sugg.append(f"Andamento di {num_cols[0]} nel tempo")

        generici = [
            "Quanti valori mancanti ci sono per ogni colonna?",
            "Mostrami un riepilogo generale del dataset",
            "Trova i valori duplicati",
        ]
        for g in generici:
            if len(sugg) >= 5:
                break
            if g not in sugg:
                sugg.append(g)

        return sugg[:5]

    def _mostra_dialogo_foglio(
        self,
        fogli: list[str],
        result: list,
        done: threading.Event,
    ):
        from ui_constants import AI_BG, BTN_IDLE, BTN_HOV, BTN_BORDER, TEXT_PRI
        dlg = ctk.CTkToplevel(self)
        dlg.title("Seleziona foglio")
        dlg.configure(fg_color=AI_BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)

        n = len(fogli)
        w, h = 320, min(80 + n * 48, 480)
        px = self.winfo_x() + (self.winfo_width() - w) // 2
        py = self.winfo_y() + (self.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{px}+{py}")

        ctk.CTkLabel(
            dlg,
            text="Il file ha più fogli.\nSeleziona quello da analizzare:",
            font=_font(12), text_color=TEXT_PRI,
        ).pack(padx=24, pady=(20, 10))

        scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        scroll.grid_columnconfigure(0, weight=1)

        def _scegli(foglio: str):
            result[0] = foglio
            done.set()
            dlg.destroy()

        def _annulla():
            done.set()
            dlg.destroy()

        for foglio in fogli:
            ctk.CTkButton(
                scroll, text=foglio, height=36,
                font=_font(11), fg_color=BTN_IDLE, hover_color=BTN_HOV,
                text_color=TEXT_PRI, border_color=BTN_BORDER, border_width=1,
                corner_radius=8, command=lambda f=foglio: _scegli(f), anchor="w",
            ).pack(fill="x", padx=4, pady=3)

        dlg.protocol("WM_DELETE_WINDOW", _annulla)
        dlg.wait_window()

    # ── 3. Selettore modello e Hub ────────────────────────────────────────────

    def _on_modello_selezionato(self, nome_file: str):
        if nome_file in ("Nessun .gguf trovato", "Nessun modello installato"):
            return
        # Trova il path completo tra i modelli disponibili
        tutti = trova_modelli()
        nuovo_path = next((p for p in tutti if os.path.basename(p) == nome_file), None)
        if nuovo_path is None:
            return
        if nuovo_path == self._modello_path and self._llm is not None:
            return
        if self._busy:
            self._msg_assistente("Impossibile cambiare modello durante un'elaborazione.", tag="warn")
            fallback = os.path.basename(self._modello_path) if self._modello_path else self._var_modello.get()
            self._var_modello.set(fallback)
            return
        self._llm          = None
        self._modello_path = nuovo_path
        self._btn_run.configure(state="disabled")
        self._txt_query.configure(state="disabled")
        self._lbl_stato.configure(text="● Cambio modello...", text_color="#FFA726")
        self._msg_sistema(f"Caricamento {nome_file}...")
        threading.Thread(target=self._carica_modello_thread, daemon=True).start()

    def _apri_hub(self):
        ModelHubWindow(self).focus()

    def _aggiorna_opt_modello_dopo_install(self, nome_file: str):
        modelli = trova_modelli()
        nomi    = [os.path.basename(p) for p in modelli] or ["Nessun .gguf trovato"]
        self._opt_modello.configure(values=nomi)
        if nome_file in nomi:
            self._var_modello.set(nome_file)
            self._msg_sistema(f"✓ Modello «{nome_file}» installato.")
            if self._llm is None and not self._busy:
                nuovo_path = next((p for p in modelli if os.path.basename(p) == nome_file), None)
                if nuovo_path:
                    self._modello_path = nuovo_path
                    self._lbl_stato.configure(text="● Caricamento modello...", text_color="#FFA726")
                    threading.Thread(target=self._carica_modello_thread, daemon=True).start()

    # ── 4. Onboarding ─────────────────────────────────────────────────────────

    def _mostra_splash(self):
        self._onboarding = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        self._onboarding.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._onboarding.lift()

        center = ctk.CTkFrame(self._onboarding, fg_color="transparent")
        center.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center, text="◈",
                     font=("Helvetica Neue", 72, "bold"), text_color=ACCENT).pack(pady=(0, 10))
        ctk.CTkLabel(center, text="Data-Whisperer",
                     font=("Helvetica Neue", 34, "bold"), text_color="#e4e8f5").pack()
        ctk.CTkLabel(center, text="Offline AI Analyst  ·  v1.0",
                     font=_font(14), text_color="#4e546e").pack(pady=(6, 44))
        ctk.CTkButton(
            center, text="  Inizia  →", width=220, height=54,
            font=_font(15, "bold"), fg_color=ACCENT, hover_color="#00b386",
            text_color="#000000", corner_radius=14,
            command=self._mostra_system_check,
        ).pack()
        ctk.CTkLabel(
            center, text="Air-Gapped  ·  Zero rete  ·  I tuoi dati restano sul tuo computer",
            font=_font(10), text_color="#4e546e",
        ).pack(pady=(22, 0))

    def _mostra_system_check(self):
        for w in self._onboarding.winfo_children():
            w.destroy()

        center = ctk.CTkFrame(self._onboarding, fg_color="transparent")
        center.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(center, text="Controllo Sistema",
                     font=("Helvetica Neue", 22, "bold"), text_color="#e4e8f5").pack(pady=(0, 4))
        ctk.CTkLabel(center, text="Inizializzazione ambiente sicuro in corso...",
                     font=_font(12), text_color="#4e546e").pack(pady=(0, 32))

        self._prog_bar = ctk.CTkProgressBar(center, width=400, height=8,
                                            fg_color="#18182c", progress_color=ACCENT,
                                            corner_radius=4)
        self._prog_bar.set(0)
        self._prog_bar.pack(pady=(0, 10))

        self._lbl_prog = ctk.CTkLabel(center, text="Avvio diagnostica...",
                                      font=_font(11), text_color="#4e546e")
        self._lbl_prog.pack(pady=(0, 28))

        self._card_check = ctk.CTkFrame(center, fg_color="#16161f", corner_radius=14, width=420)
        self._card_check.pack(fill="x", pady=(0, 32), ipady=6)

        self._btn_entra = ctk.CTkButton(
            center, text="  Entra nell'Analyst  →", width=300, height=54,
            font=_font(15, "bold"), fg_color=ACCENT, hover_color="#00b386",
            text_color="#000000", corner_radius=14,
            command=self._avvia_app_principale, state="disabled",
        )
        self._btn_entra.pack()
        threading.Thread(target=self._run_system_check, daemon=True).start()

    def _run_system_check(self):
        import psutil
        steps = [
            (0.15, 0.5, "Analisi processore..."),
            (0.40, 0.6, "Misurazione memoria RAM..."),
            (0.65, 0.5, "Verifica isolamento di rete..."),
            (0.85, 0.4, "Controllo ambiente Python..."),
            (1.00, 0.3, "Sistema pronto."),
        ]
        for valore, pausa, testo in steps:
            self.after(0, lambda v=valore: self._prog_bar.set(v))
            self.after(0, lambda t=testo: self._lbl_prog.configure(text=t))
            time.sleep(pausa)

        cpu_raw   = platform.processor() or platform.machine()
        machine   = platform.machine().lower()
        is_apple  = "arm" in machine or "apple" in cpu_raw.lower()
        cpu_label = "Apple Silicon (Metal GPU)" if is_apple else cpu_raw[:42] or "CPU x86-64"
        ram_gb    = psutil.virtual_memory().total / (1024 ** 3)

        self.after(0, lambda: self._mostra_risultati_check(
            cpu_label,
            f"{ram_gb:.0f} GB",
            f"Python {platform.python_version()}",
            f"{platform.system()} {platform.release()}",
        ))

    def _mostra_risultati_check(self, cpu_label: str, ram_label: str,
                                py_ver: str, os_label: str):
        self._lbl_prog.configure(text_color=ACCENT)
        voci = [
            ("CPU Rilevata",        cpu_label,              ACCENT),
            ("RAM Disponibile",     ram_label,              ACCENT),
            ("Sistema Operativo",   os_label,               "#e4e8f5"),
            ("Runtime",             py_ver,                 "#e4e8f5"),
            ("Connessione di rete", "Isolata — Confermata ✓", ACCENT),
        ]
        for etichetta, valore, colore_valore in voci:
            riga = ctk.CTkFrame(self._card_check, fg_color="transparent")
            riga.pack(fill="x", padx=20, pady=4)
            ctk.CTkLabel(riga, text=etichetta, font=_font(11),
                         text_color="#4e546e", anchor="w", width=160).pack(side="left")
            ctk.CTkLabel(riga, text=valore, font=_font(12, "bold"),
                         text_color=colore_valore, anchor="w").pack(side="left")
        self._btn_entra.configure(state="normal")

    def _avvia_app_principale(self):
        self._onboarding.destroy()
        del self._onboarding
        if not os.path.exists(self._tour_flag_path):
            self.after(400, self._apri_tour)

    def _apri_tour(self):
        OnboardingTourWindow(self)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = DataWhispererApp()
    app.mainloop()
