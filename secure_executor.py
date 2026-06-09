# =============================================================================
# INSTALLAZIONE DIPENDENZE
# =============================================================================
# pip install pandas numpy matplotlib --break-system-packages
# =============================================================================

"""
secure_executor.py
------------------
Esegue in modo sicuro il codice Python generato dal modello LLM.

Architettura di sicurezza v2 — Enterprise (three-layer):

  ┌─────────────────────────────────────────────────────────────────────┐
  │  LIVELLO 1 — Analisi AST  (statica, PRIMA di exec)                  │
  │  Legge il codice LLM come albero sintattico strutturato.             │
  │  Blocca qualsiasi import non nella lista LLM_IMPORT_CONSENTITI.     │
  │  Impermeabile a: __import__("o"+"s"), from os import *, ecc.        │
  ├─────────────────────────────────────────────────────────────────────┤
  │  LIVELLO 2 — Blacklist socket  (runtime, sempre attiva)             │
  │  Sovrascrive socket.socket con un oggetto che lancia PermissionError.│
  │  L'air-gap è garantito a livello di connessione per TUTTE le lib.   │
  │  Pandas, Matplotlib, os, sys girano liberi: non possono connettersi. │
  ├─────────────────────────────────────────────────────────────────────┤
  │  LIVELLO 3 — Timeout  (thread daemon)                               │
  │  join(timeout) intercetta loop infiniti generati dall'AI.           │
  └─────────────────────────────────────────────────────────────────────┘

Perché non c'è più il custom __import__:
  L'analisi AST garantisce che il codice LLM non contenga import pericolosi.
  Tutto ciò che arriva a exec() è già certificato pulito.
  Pandas/Matplotlib/os/sys possono quindi importare le loro dipendenze interne
  senza essere intercettati da un guardiano che genera falsi positivi.

Zero chiamate di rete. Zero dipendenze esterne oltre pandas/numpy/matplotlib.
"""

from __future__ import annotations

import ast
import contextlib
import io
import locale as _locale_mod
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# Rileva il separatore decimale del sistema al momento dell'import (main thread)
try:
    _locale_mod.setlocale(_locale_mod.LC_NUMERIC, "")
    _DECIMAL_SEP: str = _locale_mod.localeconv().get("decimal_point", ".")
except Exception:
    _DECIMAL_SEP = "."


def _fmt_float(x: float) -> str:
    """Formatta un float rispettando il locale del sistema (es. 1.234,56 per italiano)."""
    if _DECIMAL_SEP == ",":
        s = f"{abs(x):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
        return f"-{s}" if x < 0 else s
    return f"{x:,.2f}"


# =============================================================================
# RISULTATO ESECUZIONE
# =============================================================================

@dataclass
class RisultatoEsecuzione:
    successo: bool
    output_testo: str                  # tutto ciò che il codice ha stampato
    grafici_png: list[bytes] = field(default_factory=list)   # PNG in memoria
    errore: str = ""                   # messaggio user-friendly se successo=False
    errore_tecnico: str = ""           # traceback grezzo (solo per debug interno)


# =============================================================================
# LIVELLO 1 — ANALISI AST
#
# Lista di moduli che il codice LLM può importare ESPLICITAMENTE.
# Non è una whitelist della stdlib: è la lista di cosa ha senso
# che un analista di dati usi. Tutto il resto della stdlib rimane
# accessibile alle librerie interne (pandas, matplotlib, ecc.) ma
# l'AI non può scriverlo direttamente nel codice generato.
# =============================================================================

LLM_IMPORT_CONSENTITI = frozenset({
    # ── Analisi dati ──────────────────────────────────────────────────────────
    "pandas", "numpy", "matplotlib", "seaborn", "scipy", "sklearn",
    # ── Stdlib per analisi e trasformazione dati ─────────────────────────────
    "math", "statistics", "decimal", "fractions", "random",
    "datetime", "calendar", "time",
    "collections", "itertools", "functools", "operator",
    "re", "string", "textwrap",
    "json", "csv",
    "pathlib", "io", "copy", "pprint",
    "typing", "types", "abc", "numbers", "enum", "weakref",
    "warnings", "contextlib",
    "struct", "hashlib", "base64", "codecs", "locale",
    "tempfile",
})


def _analisi_ast(codice: str) -> str | None:
    """
    Parsa il codice LLM come AST e verifica che tutti gli import espliciti
    siano in LLM_IMPORT_CONSENTITI.

    Restituisce None se il codice è sicuro.
    Restituisce il nome del modulo vietato se rileva una violazione.
    Restituisce una stringa di errore se il codice non è parsabile.

    Cosa intercetta:
      - import os                        → ast.Import
      - from os import system            → ast.ImportFrom
      - from os.path import join         → ast.ImportFrom (modulo "os.path")
      - __import__("os")                 → ast.Call con func.id == "__import__"
      - importlib.import_module("os")    → ast.Call con func.attr == "import_module"
    """
    try:
        tree = ast.parse(codice)
    except SyntaxError as e:
        return f"SyntaxError nel codice generato: {e}"

    for nodo in ast.walk(tree):

        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                nome_base = alias.name.split(".")[0]
                if nome_base not in LLM_IMPORT_CONSENTITI:
                    return alias.name

        elif isinstance(nodo, ast.ImportFrom):
            if nodo.module:
                nome_base = nodo.module.split(".")[0]
                if nome_base not in LLM_IMPORT_CONSENTITI:
                    return nodo.module

        elif isinstance(nodo, ast.Call):
            # __import__("qualcosa")
            if isinstance(nodo.func, ast.Name) and nodo.func.id == "__import__":
                return "__import__() dinamico"
            # importlib.import_module("qualcosa")
            if isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "import_module":
                return "importlib.import_module() dinamico"

    return None  # nessuna violazione rilevata


# =============================================================================
# LIVELLO 2 — BLOCCO RETE (air-gap software)
# Sovrascrive socket.socket per la durata dell'esecuzione e ripristina l'originale.
# Pandas, os, sys girano liberi ma non possono aprire connessioni.
# =============================================================================

@contextlib.contextmanager
def _blocca_socket():
    """
    Context manager: sovrascrive socket.socket con uno stub che lancia
    PermissionError, poi ripristina il riferimento originale all'uscita.
    Usabile nei test senza effetti permanenti sul processo.
    """
    try:
        import socket as _socket_mod
        _orig = _socket_mod.socket

        class _SocketVietato:
            def __init__(self, *a, **kw):
                raise PermissionError(
                    "[SICUREZZA] Connessioni di rete vietate in modalità Air-Gapped."
                )

        _socket_mod.socket = _SocketVietato
        try:
            yield
        finally:
            _socket_mod.socket = _orig
    except ImportError:
        yield


# =============================================================================
# INTERCETTAZIONE MATPLOTLIB
# =============================================================================

def _cattura_grafici_matplotlib() -> list[bytes]:
    """
    Salva tutte le figure matplotlib aperte come PNG in memoria (BytesIO)
    e chiude le finestre. Restituisce una lista di bytes.
    Chiamata DOPO exec() — nessun ImportGuard attivo, matplotlib gira libero.
    """
    grafici = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        for num in plt.get_fignums():
            fig = plt.figure(num)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)
            grafici.append(buf.read())

        plt.close("all")
    except Exception:
        pass

    return grafici


# =============================================================================
# ESECUTORE PRINCIPALE
# =============================================================================

def esegui_sicuro(
    codice: str,
    df: pd.DataFrame,
    timeout_secondi: int = 30,
) -> RisultatoEsecuzione:
    """
    Esegue `codice` in un namespace isolato con tre livelli di protezione.

    Parametri
    ---------
    codice           : stringa di codice Python generata dal modello
    df               : DataFrame pandas già caricato, disponibile nel namespace
    timeout_secondi  : secondi massimi concessi all'esecuzione (default 30)

    Ritorna
    -------
    RisultatoEsecuzione con output testuale, grafici PNG e/o traceback errore.
    """
    if not codice.strip():
        return RisultatoEsecuzione(
            successo=False,
            output_testo="",
            errore="Il codice generato è vuoto.",
        )

    # ── LIVELLO 1: Analisi AST (sincrona, fuori dal thread) ───────────────────
    modulo_vietato = _analisi_ast(codice)
    if modulo_vietato:
        # Distingue SyntaxError (codice troncato/malformato) da import vietato
        if modulo_vietato.startswith("SyntaxError"):
            errore_ast = (
                f"[CODICE TRONCATO] Il modello ha generato codice incompleto o malformato.\n"
                f"Dettaglio: {modulo_vietato}\n"
                f"Suggerimento: riformula la domanda in modo più semplice o suddividila in più passi."
            )
        else:
            errore_ast = (
                f"[SICUREZZA — AST] Import non autorizzato rilevato: '{modulo_vietato}'.\n"
                f"Il codice LLM può importare solo: {sorted(LLM_IMPORT_CONSENTITI)}"
            )
        return RisultatoEsecuzione(
            successo=False,
            output_testo="",
            errore=errore_ast,
        )

    # Contenitori condivisi tra thread
    risultato_container: dict[str, Any] = {}
    eccezione_container: dict[str, str] = {}

    def _esegui():
        # ── Configura matplotlib in modalità non interattiva ──────────
        try:
            import warnings as _warnings
            import matplotlib
            matplotlib.use("Agg")
            # Sopprime "FigureCanvasAgg is non-interactive" generato da plt.show()
            _warnings.filterwarnings(
                "ignore",
                message=".*FigureCanvasAgg is non-interactive.*",
                category=UserWarning,
            )
        except ImportError:
            pass

        # ── Namespace iniziale: df, pd, np, plt disponibili senza import ──
        import numpy as np
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            plt = None

        # ── Muro di Gomma — forzatura date prima di exec() ───────────
        # Indipendentemente da come l'IA scrive il codice temporale,
        # le colonne "data/date" sono SEMPRE datetime64[ns] in questa sandbox.
        # errors='coerce' trasforma valori non parsabili in NaT invece di crashare.
        df_sicuro = df.copy()
        for _col in df_sicuro.columns:
            if "data" in _col.lower() or "date" in _col.lower():
                try:
                    df_sicuro[_col] = pd.to_datetime(df_sicuro[_col], errors="coerce")
                except Exception:
                    pass

        # ── Helper pre-cotti — funzioni blindate per operazioni complesse ──
        def confronta_anni(
            df_: "pd.DataFrame",
            colonna_data: str,
            colonna_valore: str,
            colonna_categoria: str,
            anno1: int,
            anno2: int,
        ) -> "pd.Series":
            """
            Confronto anno su anno per categoria — sempre corretto.
            Usa groupby+unstack: non richiede merge e non produce mai NaN da indici disallineati.

            Esempio d'uso nel codice LLM:
                variazione = confronta_anni(df, 'Data', 'Fatturato', 'Sede', 2024, 2025)
                if not variazione.empty:
                    print(variazione.idxmax(), variazione.max())
            """
            pivot = (
                df_.groupby([colonna_categoria, df_[colonna_data].dt.year])[colonna_valore]
                .sum()
                .unstack(fill_value=0)
            )
            if anno1 not in pivot.columns or anno2 not in pivot.columns:
                return pd.Series(dtype=float)
            var = (
                ((pivot[anno2] - pivot[anno1]) / pivot[anno1] * 100)
                .replace([float("inf"), float("-inf")], 0)
                .dropna()
            )
            return var

        # ── Formattazione numeri leggibile, rispetta il locale di sistema ──
        pd.options.display.float_format = _fmt_float

        namespace = {
            "df":            df_sicuro,      # versione corazzata con date già convertite
            "pd":            pd,
            "np":            np,
            "confronta_anni": confronta_anni, # helper anno su anno — sempre corretto
        }
        if plt:
            namespace["plt"] = plt

        # ── Cattura stdout/stderr ─────────────────────────────────────
        buf_out = io.StringIO()
        buf_err = io.StringIO()

        # ── Phantom Styling — tema Dark Corporate iniettato di nascosto ──
        # Il modello scrive df.plot(), matplotlib renderizza Bloomberg Terminal.
        if plt:
            plt.rcParams["figure.figsize"]    = [10, 6]
            # Sfondi antracite coordinati con la UI
            plt.rcParams["figure.facecolor"]  = "#1e1e24"
            plt.rcParams["axes.facecolor"]    = "#1e1e24"
            plt.rcParams["savefig.facecolor"] = "#1e1e24"
            # Testi off-white leggibili
            plt.rcParams["text.color"]        = "#f8fafc"
            plt.rcParams["axes.labelcolor"]   = "#f8fafc"
            plt.rcParams["xtick.color"]       = "#cbd5e1"
            plt.rcParams["ytick.color"]       = "#cbd5e1"
            plt.rcParams["axes.titlecolor"]   = "#f8fafc"
            plt.rcParams["axes.titlesize"]    = 14
            plt.rcParams["axes.titleweight"]  = "bold"
            # Griglia sottile stile dashboard
            plt.rcParams["axes.grid"]         = True
            plt.rcParams["grid.color"]        = "#334155"
            plt.rcParams["grid.alpha"]        = 0.4
            plt.rcParams["axes.edgecolor"]    = "#334155"
            plt.rcParams["axes.linewidth"]    = 1.2
            # Palette premium: Teal · Blue Tech · Amber · Purple · Pink · Cyan
            plt.rcParams["axes.prop_cycle"]   = plt.cycler(
                color=["#10b981", "#3b82f6", "#f59e0b",
                       "#8b5cf6", "#ec4899", "#06b6d4"]
            )
            # Font enterprise cross-platform
            plt.rcParams["font.family"]       = "sans-serif"
            plt.rcParams["font.sans-serif"]   = [
                "Helvetica Neue", "Helvetica", "Arial",
                "Segoe UI", "DejaVu Sans"
            ]

        # ── LIVELLO 2: Blocca socket (air-gap runtime) ────────────────
        try:
            with _blocca_socket(), \
                 contextlib.redirect_stdout(buf_out), \
                 contextlib.redirect_stderr(buf_err):
                # Nessun custom __import__: il codice LLM è già certificato
                # pulito dall'analisi AST. Pandas/matplotlib girano liberi.
                exec(compile(codice, "<codice_llm>", "exec"), namespace)  # noqa: S102

            risultato_container["output"] = buf_out.getvalue()
            risultato_container["stderr"] = buf_err.getvalue()

        except Exception:
            eccezione_container["tb"] = traceback.format_exc()
            risultato_container["output"] = buf_out.getvalue()
            risultato_container["stderr"] = buf_err.getvalue()

        # Cattura grafici dopo exec (matplotlib gira senza restrizioni di import)
        risultato_container["grafici"] = _cattura_grafici_matplotlib()

    # ── LIVELLO 3: Thread con timeout ────────────────────────────────────────
    t = threading.Thread(target=_esegui, daemon=True)
    t.start()
    t.join(timeout=timeout_secondi)

    if t.is_alive():
        return RisultatoEsecuzione(
            successo=False,
            output_testo="",
            errore=(
                f"[TIMEOUT] Il codice non ha terminato entro {timeout_secondi}s. "
                "Possibile loop infinito intercettato."
            ),
        )

    if eccezione_container:
        return RisultatoEsecuzione(
            successo=False,
            output_testo=risultato_container.get("output", ""),
            errore=(
                "⚠️ L'IA ha generato un codice non compatibile con i dati.\n"
                "Prova a riformulare la domanda in modo più semplice o pulisci la chat."
            ),
            errore_tecnico=eccezione_container["tb"],   # conservato per debug
        )

    # Filtra warning cosmetici di matplotlib che non interessano l'utente finale
    _STDERR_DA_IGNORARE = (
        "FigureCanvasAgg is non-interactive",
        "UserWarning",
    )
    stderr_txt = risultato_container.get("stderr", "").strip()
    stderr_righe = [
        r for r in stderr_txt.splitlines()
        if not any(pattern in r for pattern in _STDERR_DA_IGNORARE)
    ]
    stderr_txt = "\n".join(stderr_righe).strip()

    output_txt = risultato_container.get("output", "").strip()
    if stderr_txt:
        output_txt = output_txt + ("\n" if output_txt else "") + f"[stderr] {stderr_txt}"

    return RisultatoEsecuzione(
        successo=True,
        output_testo=output_txt,
        grafici_png=risultato_container.get("grafici", []),
    )


# =============================================================================
# TEST STANDALONE
# =============================================================================

if __name__ == "__main__":
    import numpy as np  # noqa: F401

    df_test = pd.DataFrame({
        "Mese":      ["Gen", "Feb", "Mar", "Apr"],
        "Fatturato": [12000, 15400, 9800, 18200],
        "Costi":     [8000,  9100,  7500, 10300],
    })

    print("── Test 1: codice valido ─────────────────────────────────")
    codice_ok = """
totale = df['Fatturato'].sum()
print(f"Fatturato totale: € {totale:,.2f}")
margine = df['Fatturato'] - df['Costi']
print(f"Margine medio: € {margine.mean():,.2f}")
"""
    r = esegui_sicuro(codice_ok, df_test)
    print(f"Successo: {r.successo}")
    print(f"Output:\n{r.output_testo}")

    print("\n── Test 2: import vietato (blocco AST) ───────────────────")
    codice_rete = "import requests\nprint(requests.get('http://example.com').text)"
    r2 = esegui_sicuro(codice_rete, df_test)
    print(f"Successo: {r2.successo}")
    print(f"Errore: {r2.errore[:160]}")

    print("\n── Test 3: bypass furbo con __import__ (blocco AST) ──────")
    codice_furbo = "os = __import__('os')\nos.system('echo pwned')"
    r3 = esegui_sicuro(codice_furbo, df_test)
    print(f"Successo: {r3.successo}")
    print(f"Errore: {r3.errore[:160]}")

    print("\n── Test 4: timeout (loop infinito) ──────────────────────")
    codice_loop = "while True: pass"
    r4 = esegui_sicuro(codice_loop, df_test, timeout_secondi=3)
    print(f"Successo: {r4.successo}")
    print(f"Errore: {r4.errore}")

    print("\n── Test 5: grafico matplotlib ────────────────────────────")
    codice_plot = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.bar(df['Mese'], df['Fatturato'], color='steelblue')
ax.set_title('Fatturato mensile')
ax.set_ylabel('€')
"""
    r5 = esegui_sicuro(codice_plot, df_test)
    print(f"Successo: {r5.successo}")
    print(f"Grafici catturati: {len(r5.grafici_png)}  "
          f"({len(r5.grafici_png[0]) if r5.grafici_png else 0} bytes)")
