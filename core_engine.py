# =============================================================================
# INSTALLAZIONE DIPENDENZE (eseguire una volta nel terminale)
# =============================================================================
# pip install pandas psutil chardet openpyxl --break-system-packages
#
# Per llama-cpp-python con accelerazione Metal (Apple Silicon):
# CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python --force-reinstall --no-cache-dir --break-system-packages
# =============================================================================

from __future__ import annotations

import os
import platform
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable

from llama_cpp import Llama

from data_loader import carica_file, DatasetCaricato
from dw_logger import dw_logger
from hardware_detector import rileva_hardware
from prompts import (
    PROMPT_CONCIERGE,
    PROMPT_STILISTA,
    PROMPT_VIGILE,
    SP_ARCHITETTO,
    SP_DATTILOGRAFO,
    SP_ISPETTORE,
    SP_VALIDATORE,
)
from secure_executor import esegui_sicuro, RisultatoEsecuzione

ERRORE_ANNULLATO = "__DW_ANNULLATO__"

# =============================================================================
# CONFIGURAZIONE — path compatibile con app nativa PyInstaller
# =============================================================================

def _get_app_root() -> str:
    """
    Restituisce la cartella "root" dell'applicazione:
      - App nativa (.app bundle): la cartella che CONTIENE Data-Whisperer.app,
        dove l'utente ha posizionato modello-locale.gguf accanto all'icona.
        sys.executable → .app/Contents/MacOS/Data-Whisperer  (3 livelli su)
      - Sviluppo normale (python app_ui.py / core_engine.py):
        la cartella del file sorgente.
    """
    if getattr(sys, "frozen", False):
        # Siamo dentro un bundle PyInstaller compilato
        exe_dir = os.path.dirname(sys.executable)           # .app/Contents/MacOS/
        return os.path.abspath(os.path.join(exe_dir, "..", "..", ".."))
    return os.path.dirname(os.path.abspath(__file__))


_APP_ROOT  = _get_app_root()
MODEL_PATH = os.path.join(_APP_ROOT, "modello-locale.gguf")
CSV_PATH   = os.path.join(_APP_ROOT, "dati_test.csv")


def _app_data_dir() -> str:
    """
    Cartella persistente per dati utente (storia, flag tour, ecc.).
    Separata da _APP_ROOT per compatibilità con .app bundle firmati.
      macOS   → ~/Library/Application Support/Data-Whisperer/
      Windows → %APPDATA%/Data-Whisperer/
      Linux   → ~/.local/share/Data-Whisperer/
    """
    system = platform.system()
    if system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~/.local/share")
    data_dir = os.path.join(base, "Data-Whisperer")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        data_dir = os.path.expanduser("~")
    return data_dir


def trova_modelli(cartella: str | None = None) -> list[str]:
    """
    Scansiona la cartella dell'app per file .gguf.
    In modalità sviluppo cerca anche nella sottocartella models/.
    Restituisce lista di path assoluti ordinata per dimensione decrescente
    (modelli più grandi tendono ad essere più capaci).
    Zero chiamate di rete.
    """
    cartella = cartella or _APP_ROOT
    trovati: list[str] = []
    da_scansionare = [cartella]

    # In modalità sviluppo (non frozen) cerca anche in models/ accanto ai sorgenti
    if not getattr(sys, "frozen", False):
        models_dir = os.path.join(cartella, "models")
        if os.path.isdir(models_dir):
            da_scansionare.append(models_dir)

    for cartella_corrente in da_scansionare:
        try:
            trovati.extend(
                os.path.join(cartella_corrente, f)
                for f in os.listdir(cartella_corrente)
                if f.lower().endswith(".gguf")
                and os.path.isfile(os.path.join(cartella_corrente, f))
            )
        except OSError:
            pass

    return sorted(trovati, key=lambda p: os.path.getsize(p), reverse=True)

# =============================================================================
# 1. SETUP DEL MODELLO — parametri calibrati da hardware_detector
# =============================================================================

def carica_modello(
    model_path: str,
    n_gpu_layers: int | None = None,
    n_ctx:        int | None = None,
    n_threads:    int | None = None,
) -> Llama:
    """
    Carica il modello GGUF locale.

    Se n_gpu_layers / n_ctx / n_threads sono None, li ricava automaticamente
    da hardware_detector.rileva_hardware() — questo è il comportamento di default
    per qualsiasi macchina target (Apple Silicon, Nvidia, CPU pura).

    I parametri espliciti servono solo per override manuali (debug/test).
    """
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Modello non trovato: {model_path}")

    # ── Rilevamento hardware (silent=False per log nella console) ──────────────
    if any(v is None for v in (n_gpu_layers, n_ctx, n_threads)):
        profilo      = rileva_hardware(verbose=True)
        n_gpu_layers = n_gpu_layers if n_gpu_layers is not None else profilo.n_gpu_layers
        n_ctx        = n_ctx        if n_ctx        is not None else profilo.n_ctx
        n_threads    = n_threads    if n_threads    is not None else profilo.n_threads

    dw_logger.info("Caricamento modello: %s", os.path.basename(model_path))
    dw_logger.info("GPU layers: %s  |  ctx: %s  |  threads: %s", n_gpu_layers, n_ctx, n_threads)

    llm = Llama(
        model_path=model_path,
        n_gpu_layers=n_gpu_layers,
        n_ctx=n_ctx,
        n_threads=n_threads,
        verbose=False,
    )

    dw_logger.info("Modello caricato con successo.")
    return llm


# =============================================================================
# 2. LETTURA DATI — delegata a data_loader
# =============================================================================

def estrai_schema_csv(percorso: str) -> tuple[str, "DatasetCaricato"]:
    """
    Carica il file (CSV o Excel) tramite data_loader.carica_file().
    Restituisce (schema_prompt, DatasetCaricato) per passare entrambi
    al motore di inferenza e all'esecutore sicuro.

    Il nome è mantenuto per compatibilità con il __main__ del PoC,
    ma ora gestisce qualsiasi formato supportato da data_loader.
    """
    dataset = carica_file(percorso)

    dw_logger.info("File caricato: %s", dataset.nome_file)
    dw_logger.info("%d righe  •  %d colonne  •  %s", dataset.n_righe, dataset.n_colonne, dataset.formato.upper())
    if dataset.colonne_rimosse:
        dw_logger.info("Colonne vuote rimosse: %s", dataset.colonne_rimosse)

    return dataset.schema_prompt, dataset


# =============================================================================
# 3. ASSEMBLY LINE A 4 MICRO-AGENTI — 1 solo modello in RAM
#
#  VALIDATORE  →  ARCHITETTO  →  DATTILOGRAFO  →  ISPETTORE (loop)
#  (controllo)    (piano)         (codice)          (QA fix)
# =============================================================================



# ── Struttura risultato pipeline ─────────────────────────────────────────────

@dataclass
class RisultatoMultiAgente:
    successo:         bool
    piano_logico:     str                        # output Agente 1
    codice_finale:    str                        # codice dopo eventuale QA
    risultato:        "RisultatoEsecuzione | None"  # risultato ultima esecuzione
    tentativi_qa:     int                        # quanti cicli QA sono serviti
    errore_pipeline:  str                        # errore a livello di pipeline


# ── Helpers interni ───────────────────────────────────────────────────────────

def _chiama_agente(
    llm: Llama,
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 1024,
    temperature: float = 0.1,
) -> str:
    """
    Chiama llm.create_chat_completion con system_prompt preposto ai messages.
    Ogni agente riceve un contesto fresco — nessuna contaminazione tra ruoli.
    """
    risposta = llm.create_chat_completion(
        messages=[{"role": "system", "content": system_prompt}] + messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=0.9,
        repeat_penalty=1.1,   # previene loop di ripetizione nei modelli quantizzati
    )
    return risposta["choices"][0]["message"]["content"].strip()


def _pulisci_codice(testo: str) -> str:
    """
    Normalizza il codice generato prima di eseguirlo e mostrarlo in chat.

    Operazioni in ordine:
    1. Rimuove wrapper markdown  ``` / ```python
    2. Rimuove plt.show()  (i grafici vengono catturati dal backend Agg)
    3. Rimuove le righe che sono SOLO commenti  (# ...) — il modello tende a
       trascrivere i passi del piano come commenti; questa pulizia programmatica
       e' piu' affidabile di qualsiasi istruzione nel system-prompt.
       Sono mantenuti gli inline-comment (codice + # nota) perche' non iniziano
       con '#' dopo lo strip dell'indentazione.
    4. Comprime le righe vuote consecutive in una sola riga vuota.
    """
    # 1. Markdown
    pulito = testo.replace("```python", "").replace("```", "")

    # 2. plt.show() — qualsiasi indentazione
    pulito = re.sub(r"[ \t]*plt\.show\(\)[ \t]*\n?", "", pulito)

    # 3. Righe-solo-commento
    righe_pulite = []
    for riga in pulito.splitlines():
        if riga.strip().startswith("#"):
            continue          # salta commenti del Dattilografo
        righe_pulite.append(riga)

    # 4. Max una riga vuota consecutiva
    pulito = "\n".join(righe_pulite)
    pulito = re.sub(r"\n{3,}", "\n\n", pulito)

    return pulito.strip()


# ── Pipeline principale ───────────────────────────────────────────────────────

def _check_cancel(cancel_event: "threading.Event | None") -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _risultato_annullato() -> "RisultatoMultiAgente":
    return RisultatoMultiAgente(
        successo=False, piano_logico="", codice_finale="",
        risultato=None, tentativi_qa=0, errore_pipeline=ERRORE_ANNULLATO,
    )


def elabora_query_multi_agente(
    llm: Llama,
    dataset: "DatasetCaricato",
    query_utente: str,
    max_tentativi_qa: int = 3,
    ultimo_codice_valido: str | None = None,
    progress_callback: Callable | None = None,
    cancel_event: threading.Event | None = None,
    memoria_conversazione: list[dict] | None = None,
) -> RisultatoMultiAgente:
    """
    Assembly line a 7 micro-agenti su un singolo modello Llama in RAM.

    Flusso INFO (saluti / domande generali sull'app):
      VIGILE     → classifica come INFO
      CONCIERGE  → risposta conversazionale, bypassa tutto il resto

    Flusso MODIFICA estetica (solo se esiste un grafico precedente):
      VIGILE     → classifica come MODIFICA
      STILISTA   → applica solo le modifiche Matplotlib, bypassa A1/A2/A3

    Flusso NUOVA analisi (default):
      VIGILE     → classifica come NUOVA (o MODIFICA declassata senza grafico attivo)
      VALIDATORE → controlla che le colonne richieste esistano
      ARCHITETTO → produce il piano logico numerato
      DATTILOGRAFO → traduce il piano in codice Python
      ISPETTORE  → esegue il codice; se fallisce, corregge (max N tentativi)
    """
    schema_csv          = dataset.schema_prompt
    colonne_disponibili = ", ".join(dataset.df.columns.tolist())

    # ─────────────────────────────────────────────────────────────────────────
    # AGENTE 0 — VIGILE (Router): classifica in NUOVA / MODIFICA / INFO
    # Attivo su OGNI richiesta — non solo quando esiste un grafico precedente.
    # ─────────────────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.08, "Vigile  ·  classificazione richiesta")
    dw_logger.info("[A0 — VIGILE] Classificazione richiesta: %s...", query_utente[:70])

    _contesto_grafico = (
        "Grafico attivo sullo schermo: SI\n"
        if ultimo_codice_valido else
        "Nessun grafico precedente.\n"
    )
    decisione_vigile = _chiama_agente(
        llm,
        PROMPT_VIGILE,
        [{
            "role": "user",
            "content": (
                f"{_contesto_grafico}"
                f"Richiesta utente: {query_utente}"
            ),
        }],
        max_tokens=10,
        temperature=0.01,    # quasi-deterministico: output ternario
    ).strip().upper()
    dw_logger.info("[A0] Decisione Vigile: %r", decisione_vigile)

    if _check_cancel(cancel_event):
        return _risultato_annullato()

    # ── Estrai la categoria dalle prime parole (robusto a modelli verbosi) ──
    _prime = decisione_vigile.split()[:2]
    if any("INFO" in w for w in _prime):
        _intento = "INFO"
    elif any("MODIFICA" in w for w in _prime):
        _intento = "MODIFICA"
    else:
        _intento = "NUOVA"

    # ─────────────────────────────────────────────────────────────────────────
    # BRANCH INFO — AGENTE 6: CONCIERGE (risposta conversazionale)
    # Bypassa completamente Validatore, Architetto, Dattilografo, Ispettore.
    # ─────────────────────────────────────────────────────────────────────────
    if _intento == "INFO":
        if progress_callback:
            progress_callback(0.50, "Concierge  ·  risposta in corso")
        dw_logger.info("[A6 — CONCIERGE] Risposta conversazionale...")

        # Passa il contesto del dataset al Concierge: permette risposte specifiche
        # sulle colonne reali invece di suggerimenti generici.
        _dataset_ctx = (
            f"[Dataset caricato: '{dataset.nome_file}', "
            f"{dataset.n_righe} righe, {dataset.n_colonne} colonne. "
            f"Colonne: {colonne_disponibili}]\n\n"
        )
        _memoria_ctx = ""
        if memoria_conversazione:
            _items = [
                f"- «{m['query']}» → {m['risposta']}"
                for m in memoria_conversazione[-3:]
            ]
            _memoria_ctx = "[Analisi precedenti in questa sessione]:\n" + "\n".join(_items) + "\n\n"
        risposta_concierge = _chiama_agente(
            llm,
            PROMPT_CONCIERGE,
            [{"role": "user", "content": f"{_dataset_ctx}{_memoria_ctx}{query_utente}"}],
            max_tokens=400,
            temperature=0.7,   # leggermente piu' creativo per risposte naturali
        )
        dw_logger.info("[A6] Risposta generata (%d chars).", len(risposta_concierge))
        return RisultatoMultiAgente(
            successo=True,
            piano_logico="",   # nessuna bolla "Piano Architetto"
            codice_finale="",  # nessun blocco codice
            risultato=RisultatoEsecuzione(
                successo=True,
                output_testo=risposta_concierge,
            ),
            tentativi_qa=0,
            errore_pipeline="",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # BRANCH MODIFICA — AGENTE 5: STILISTA (modifica estetica)
    # Se non c'è un grafico attivo, declassa silenziosamente a NUOVA.
    # ─────────────────────────────────────────────────────────────────────────
    if _intento == "MODIFICA":
        if ultimo_codice_valido:
            if progress_callback:
                progress_callback(0.50, "Stilista  ·  modifica estetica grafico")
            dw_logger.info("[A5 — STILISTA] Applicazione modifiche estetiche al grafico...")
            codice_stilista_raw = _chiama_agente(
                llm,
                PROMPT_STILISTA,
                [{
                    "role": "user",
                    "content": (
                        f"Codice attuale:\n{ultimo_codice_valido}\n\n"
                        f"Modifica richiesta: {query_utente}"
                    ),
                }],
                max_tokens=1024,
                temperature=0.1,
            )
            codice_stilista = _pulisci_codice(codice_stilista_raw)
            dw_logger.info("[A5] Codice stilizzato (%d chars).", len(codice_stilista))

            risultato_stilista = esegui_sicuro(
                codice_stilista, dataset.df, timeout_secondi=30
            )
            return RisultatoMultiAgente(
                successo=risultato_stilista.successo,
                piano_logico="🎨 Richiesta estetica rilevata. Modifica del grafico in corso...",
                codice_finale=codice_stilista,
                risultato=risultato_stilista,
                tentativi_qa=0,
                errore_pipeline="" if risultato_stilista.successo else (
                    risultato_stilista.errore or "Errore nella modifica estetica."
                ),
            )
        else:
            # Nessun grafico attivo: la MODIFICA non ha senso → trattala come NUOVA
            dw_logger.info("[A0] Nessun grafico attivo — MODIFICA declassata a NUOVA.")

    if _check_cancel(cancel_event):
        return _risultato_annullato()

    # ─────────────────────────────────────────────────────────────────────────
    # BRANCH NUOVA — AGENTE 1: VALIDATORE: anti-allucinazione, verifica colonne
    # ─────────────────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.20, "Validatore  ·  verifica colonne")
    dw_logger.info("[A1 — VALIDATORE] Controllo colonne per: %s...", query_utente[:70])

    esito_validazione = _chiama_agente(
        llm,
        SP_VALIDATORE,
        [{
            "role": "user",
            "content": (
                f"Colonne disponibili: {colonne_disponibili}\n\n"
                f"Domanda dell'utente: {query_utente}"
            ),
        }],
        max_tokens=150,      # margine per messaggi di errore con nomi di colonne lunghi
        temperature=0.01,    # quasi-deterministico (0.0 causa instabilità in alcuni GGUF)
    )

    dw_logger.info("[A1] Esito: %s", esito_validazione[:60])

    # Cerca "OK" tra le prime 4 parole — robusto a modelli verbosi
    # es. "OK", "OK.", "Okay", "Yes, OK" → passa | "ERRORE: …" → blocca
    prime_parole = esito_validazione.strip().upper().split()[:4]
    if not any(w.startswith("OK") for w in prime_parole):
        # ── Falso positivo numerico: il Validatore ha scambiato un anno/numero
        # (es. "2050", "100") per un nome di colonna. Estrai il nome segnalato
        # e, se è puramente numerico, ignora il blocco e continua la pipeline.

        def _msg_errore_pulito(raw: str) -> str:
            """
            Trasforma l'output grezzo del Validatore in un messaggio
            user-friendly. Evita che testo di istruzioni appaia in chat.
            """
            body = raw.strip()
            if body.upper().startswith("ERRORE:"):
                body = body[7:].strip()
            # Estrai i nomi di colonne citati tra apici singoli o doppi
            _quoted = re.findall(r"[\"']([^\"']{2,40})[\"']", body)
            _nomi_reali = [n for n in _quoted
                           if not n.lstrip("-").replace(".", "", 1).isdigit()]
            # Se il messaggio sembra copiato dalle istruzioni (troppo lungo
            # o contiene keyword interne), usa un messaggio standard
            _is_template = (
                len(body) > 90
                or any(kw in body.upper() for kw in
                       ["PALESEMENTE", "ZERO COLONNE", "IMPOSSIBILE TROVARE",
                        "CONCETTO", "LONTANAMENTE"])
            )
            if _is_template:
                if _nomi_reali:
                    _nomi_str = " e ".join(f"«{n}»" for n in _nomi_reali[:2])
                    return (
                        f"Non ho trovato nel dataset le colonne necessarie "
                        f"per rispondere: {_nomi_str}.\n"
                        f"Colonne disponibili: {colonne_disponibili}."
                    )
                return (
                    "La tua domanda non sembra compatibile con le colonne "
                    "del dataset caricato.\n"
                    f"Colonne disponibili: {colonne_disponibili}."
                )
            # Messaggio breve e pulito del modello — usalo direttamente
            return body if body else (
                f"Colonne non compatibili. Disponibili: {colonne_disponibili}."
            )

        _match = re.search(r'"([^"]+)"', esito_validazione)
        if _match:
            _nome = _match.group(1).strip()
            if _nome.lstrip("-").replace(".", "", 1).isdigit():
                dw_logger.info("[A1] Falso positivo ignorato: '%s' è un numero/anno, non una colonna.", _nome)
                # Non bloccare — salta direttamente all'Architetto
            else:
                return RisultatoMultiAgente(
                    successo=False,
                    piano_logico="",
                    codice_finale="",
                    risultato=None,
                    tentativi_qa=0,
                    errore_pipeline=_msg_errore_pulito(esito_validazione),
                )
        else:
            # Nessun nome di colonna estraibile — blocca comunque
            return RisultatoMultiAgente(
                successo=False,
                piano_logico="",
                codice_finale="",
                risultato=None,
                tentativi_qa=0,
                errore_pipeline=_msg_errore_pulito(esito_validazione),
            )

    if _check_cancel(cancel_event):
        return _risultato_annullato()

    # ─────────────────────────────────────────────────────────────────────────
    # AGENTE 2 — ARCHITETTO: piano logico (nessun codice)
    # ─────────────────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.40, "Architetto  ·  costruzione piano logico")
    dw_logger.info("[A2 — ARCHITETTO] Costruzione piano logico...")

    _memoria_arch = ""
    if memoria_conversazione:
        _items_arch = [
            f"- «{m['query']}» → {m['risposta'][:120]}"
            for m in memoria_conversazione[-3:]
        ]
        _memoria_arch = "[Contesto: analisi precedenti della sessione]\n" + "\n".join(_items_arch) + "\n\n"

    piano_logico = _chiama_agente(
        llm,
        SP_ARCHITETTO,
        [{
            "role": "user",
            "content": (
                f"Schema del dataset:\n{schema_csv}\n\n"
                f"{_memoria_arch}"
                f"Domanda: {query_utente}"
            ),
        }],
        max_tokens=400,      # piano max ~6 step: non serve molto spazio
        temperature=0.1,
    )

    # ── Guardia anti-AnnoMese categoriale ────────────────────────────────────
    # Se la query non contiene parole temporali (mese, anno, trend…), l'Architetto
    # non avrebbe dovuto creare AnnoMese. Se lo ha fatto per abitudine, lo rimuoviamo
    # dal piano prima che il Dattilografo lo traduca in codice inutile.
    _PAROLE_TEMPORALI = {
        "mese", "mensile", "anno", "annuale", "trend", "tempo", "andamento",
        "temporale", "periodo", "trimestre", "settimana", "storico", "evoluzione",
        "giornaliero", "quotidiano", "orario", "data", "date", "cronolog",
    }
    _query_lower = query_utente.lower()
    if not any(kw in _query_lower for kw in _PAROLE_TEMPORALI):
        _righe = piano_logico.splitlines()
        _filtrate = [r for r in _righe if "annomese" not in r.lower()]
        if len(_filtrate) < len(_righe):
            piano_logico = "\n".join(_filtrate).strip()
            dw_logger.info("[A2] AnnoMese rimosso dal piano: query categoriale, nessuna parola temporale.")

    dw_logger.info("[A2] Piano: %s...", piano_logico[:100])

    if _check_cancel(cancel_event):
        return _risultato_annullato()

    # ─────────────────────────────────────────────────────────────────────────
    # AGENTE 3 — DATTILOGRAFO: traduzione few-shot piano → codice
    # ─────────────────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.62, "Dattilografo  ·  scrittura codice Python")
    dw_logger.info("[A3 — DATTILOGRAFO] Traduzione piano in codice Python...")

    codice_raw = _chiama_agente(
        llm,
        SP_DATTILOGRAFO,
        [{
            "role": "user",
            "content": (
                f"Schema del dataset:\n{schema_csv}\n\n"
                f"Piano logico da tradurre in codice:\n{piano_logico}"
            ),
        }],
        max_tokens=1024,
        temperature=0.05,    # minima creatività — copia la sintassi degli esempi
    )
    codice = _pulisci_codice(codice_raw)
    dw_logger.info("[A3] Codice prodotto (%d chars).", len(codice))

    # ─────────────────────────────────────────────────────────────────────────
    # AGENTE 4 — ISPETTORE: esecuzione + reflexion loop (QA)
    # ─────────────────────────────────────────────────────────────────────────
    history_ispettore:  list[dict]                 = []
    tentativi_qa:       int                        = 0
    risultato_finale:   RisultatoEsecuzione | None = None

    while True:
        if _check_cancel(cancel_event):
            return _risultato_annullato()
        if progress_callback:
            _frac = 0.78 + (tentativi_qa * 0.06)
            _lbl  = (
                "Ispettore  ·  esecuzione codice"
                if tentativi_qa == 0 else
                f"Ispettore  ·  correzione QA {tentativi_qa}/{max_tentativi_qa}"
            )
            progress_callback(min(_frac, 0.95), _lbl)
        dw_logger.info(
            "[A4 — ISPETTORE] Esecuzione (tentativo %d/%d)...",
            tentativi_qa + 1, max_tentativi_qa + 1,
        )
        risultato = esegui_sicuro(codice, dataset.df, timeout_secondi=30)
        risultato_finale = risultato

        if risultato.successo:
            dw_logger.info("[A4] Codice approvato al tentativo %d.", tentativi_qa + 1)
            return RisultatoMultiAgente(
                successo=True,
                piano_logico=piano_logico,
                codice_finale=codice,
                risultato=risultato,
                tentativi_qa=tentativi_qa,
                errore_pipeline="",
            )

        if tentativi_qa >= max_tentativi_qa:
            break

        tentativi_qa += 1
        errore_raw = risultato.errore_tecnico or risultato.errore
        dw_logger.info("[A4] Errore rilevato → riparazione %d/%d...", tentativi_qa, max_tentativi_qa)

        history_ispettore.append({
            "role": "user",
            "content": (
                f"Il seguente codice ha generato un errore:\n\n"
                f"{codice}\n\n"
                f"Traceback:\n{errore_raw}\n\n"
                f"Riscrivi il codice completamente corretto."
            ),
        })

        codice_riparato_raw = _chiama_agente(
            llm,
            SP_ISPETTORE,
            history_ispettore,
            max_tokens=1024,
            temperature=0.2,   # leggermente più creativo per uscire dai loop
        )
        codice_riparato = _pulisci_codice(codice_riparato_raw)

        # Mantieni la cronologia dei tentativi: l'Ispettore vede i propri errori passati
        history_ispettore.append({"role": "assistant", "content": codice_riparato_raw})
        codice = codice_riparato

    # Tutti i tentativi esauriti
    dw_logger.info("[A4] Tentativi esauriti (%d).", max_tentativi_qa)
    return RisultatoMultiAgente(
        successo=False,
        piano_logico=piano_logico,
        codice_finale=codice,
        risultato=risultato_finale,
        tentativi_qa=tentativi_qa,
        errore_pipeline=(
            "⚠️ L'IA ha generato un codice non compatibile con i dati.\n"
            "Prova a riformulare la domanda in modo più semplice o pulisci la chat."
        ),
    )



# =============================================================================
# MAIN — PoC da terminale (debug interno)
# =============================================================================

if __name__ == "__main__":
    import os

    # 1. Carica modello
    llm = carica_modello(MODEL_PATH)

    # 2. Carica dataset
    _, dataset = estrai_schema_csv(CSV_PATH)

    # 3. Query di test
    query = "Calcola la somma totale della colonna 'Fatturato' e stampa il risultato."

    # 4. Pipeline multi-agente
    risultato_ma = elabora_query_multi_agente(llm, dataset, query)

    print(f"\n{'='*60}")
    print(f"Piano logico:\n{risultato_ma.piano_logico}")
    print(f"\nCodice finale:\n{risultato_ma.codice_finale}")
    print(f"\nTentativi QA: {risultato_ma.tentativi_qa}")
    print(f"Successo: {risultato_ma.successo}")

    if risultato_ma.risultato:
        print(f"\nOutput:\n{risultato_ma.risultato.output_testo}")

    # 5. Salva grafici se presenti
    if risultato_ma.risultato and risultato_ma.risultato.grafici_png:
        for i, png_bytes in enumerate(risultato_ma.risultato.grafici_png):
            out_path = os.path.join(os.path.dirname(CSV_PATH), f"grafico_{i+1}.png")
            with open(out_path, "wb") as f:
                f.write(png_bytes)
            print(f"[INFO] Grafico salvato: {out_path}")
