# Data-Whisperer

**Analista dati AI completamente offline — doppio click, nessuna installazione, zero rete.**

Data-Whisperer è un'applicazione desktop che porta l'intelligenza artificiale nell'analisi di file CSV ed Excel senza richiedere connessione a internet, account cloud o competenze tecniche. Gira interamente sul computer dell'utente: i dati non lasciano mai la macchina.

---

## Indice

1. [Cos'è e come funziona](#cosè-e-come-funziona)
2. [Funzionalità principali](#funzionalità-principali)
3. [Requisiti di sistema](#requisiti-di-sistema)
4. [Modelli AI supportati](#modelli-ai-supportati)
5. [Installazione in sviluppo](#installazione-in-sviluppo)
6. [Struttura del progetto](#struttura-del-progetto)
7. [Architettura tecnica](#architettura-tecnica)
8. [Pipeline multi-agente](#pipeline-multi-agente)
9. [Sicurezza a tre livelli](#sicurezza-a-tre-livelli)
10. [Rilevamento hardware automatico](#rilevamento-hardware-automatico)
11. [Build e distribuzione](#build-e-distribuzione)
12. [Formato dei file supportati](#formato-dei-file-supportati)

---

## Cos'è e come funziona

L'utente carica un file CSV o Excel, poi digita una domanda in italiano:

> *"Mostrami il fatturato mensile per sede"*
> *"Qual è il prodotto con margine più alto?"*
> *"Crea un grafico a torta per categoria"*

Data-Whisperer risponde con un grafico, un numero o un testo. Internamente, una pipeline di 7 micro-agenti AI traduce la domanda in codice Python, lo esegue in isolamento e restituisce il risultato.

**Tutto accade localmente.** Non c'è nessuna API esterna, nessun server, nessun abbonamento.

---

## Funzionalità principali

| Funzionalità | Descrizione |
|---|---|
| **Drag & drop** | Trascina un file CSV o Excel direttamente nella finestra per caricarlo |
| **Anteprima dataset** | Dopo il caricamento mostra automaticamente le prime 5 righe in formato tabella |
| **Selettore foglio Excel** | Se il file contiene più fogli, apre un dialogo modale per scegliere quale analizzare |
| **Query suggerite** | Genera automaticamente 5 domande rilevanti basate sui tipi di colonne del dataset (euristica, senza LLM) |
| **Pulsante Annulla** | Durante l'analisi il pulsante "Invia" diventa "✕ Annulla" — interrompe la pipeline tra un agente e l'altro |
| **Memoria conversazione** | Gli agenti Architetto e Concierge ricevono le ultime 3 domande+risposte come contesto |
| **Zoom grafici** | Click su un grafico lo apre in una finestra fullscreen con possibilità di salvataggio |
| **Export PDF** | Genera un report PDF impaginato con domande, risposte, grafici e codice eseguito |
| **Export XLSX** | Genera un file Excel con un foglio "Sommario" (tabella analisi) e un foglio per ogni grafico (PNG incorporato) |
| **Cronologia sessione** | Tutte le analisi riuscite sono salvate con badge 📊/📝; click su una voce apre il dettaglio con miniatura grafico e pulsante "Re-esegui" |
| **Logging persistente** | Log rotante su file in `~/Library/Logs/Data-Whisperer/` (macOS) — invisibile all'utente, utile per il supporto |
| **Formato numeri locale** | I numeri nei risultati usano il separatore decimale del sistema (`,` per italiano, `.` per inglese) |

---

## Requisiti di sistema

| | Minimo | Raccomandato |
|---|---|---|
| **RAM** | 8 GB | 16 GB o più |
| **OS** | macOS 12+, Windows 10+, Linux | macOS con Apple Silicon |
| **Disco** | 5 GB liberi | 10–50 GB (dipende dal modello) |
| **GPU** | Non richiesta | Apple Metal o Nvidia CUDA |

---

## Modelli AI supportati

Data-Whisperer usa modelli in formato **GGUF** tramite `llama-cpp-python`. Il Model Hub integrato guida l'utente nella scelta in base alla RAM disponibile.

| Tier | Modello | Dimensione | RAM minima | Uso ideale |
|---|---|---|---|---|
| **Base** | Qwen 2.5 Coder 7B | ~4.7 GB | 8 GB | Analisi quotidiane, sistemi leggeri |
| **Pro** | Qwen 2.5 Coder 14B | ~9.0 GB | 12 GB | Uso professionale bilanciato |
| **Ultra** | Qwen 2.5 Coder 32B | ~20.0 GB | 24 GB | Dataset complessi, alta precisione |
| **Enterprise** | Qwen 2.5 Coder 72B | ~42.0 GB | 40 GB | Prestazioni paragonabili a GPT-4 |

I file `.gguf` vanno posizionati nella cartella `models/` in sviluppo, oppure accanto all'icona `.app` in produzione.

---

## Installazione in sviluppo

### 1. Clona il repository

```bash
git clone <repo-url>
cd ai_data_analyst
```

### 2. Crea e attiva l'ambiente virtuale

```bash
python3 -m venv venv
source venv/bin/activate   # macOS / Linux
# oppure: venv\Scripts\activate  (Windows)
```

### 3. Installa le dipendenze

```bash
pip install -r requirements.txt
```

### 4. Installa llama-cpp-python con accelerazione GPU

**Apple Silicon (Metal):**
```bash
CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python \
  --force-reinstall --no-cache-dir
```

**Nvidia CUDA:**
```bash
CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python \
  --force-reinstall --no-cache-dir
```

**CPU pura (fallback):**
```bash
pip install llama-cpp-python
```

### 5. Aggiungi un modello

Scarica un file `.gguf` e posizionalo in `models/`. Al primo avvio, il Model Hub ti guida nella selezione.

### 6. Avvia l'app

```bash
python app_ui.py
```

---

## Struttura del progetto

```
ai_data_analyst/
│
├── app_ui.py               # Entry point — coordinatore principale (DataWhispererApp)
│
├── core_engine.py          # Pipeline multi-agente: Vigile → Validatore → Architetto
│                           #   → Dattilografo → Ispettore + Concierge + Stilista
├── secure_executor.py      # Esecutore sicuro a 3 livelli (AST + socket + timeout)
├── data_loader.py          # Caricamento CSV/Excel con auto-detection encoding/separatore
├── hardware_detector.py    # Rilevamento hardware e calibrazione parametri LLM
│
├── ui_layout.py            # LayoutMixin — griglia finestra, area chat, barra input
├── ui_chat.py              # ChatMixin — rendering messaggi, analisi, scroll, query suggerite
├── ui_sidebar.py           # SidebarMixin — sidebar, cronologia, export PDF/XLSX, dettaglio analisi
├── ui_hub.py               # ModelHubWindow — installazione modelli con progress bar
├── ui_onboarding.py        # OnboardingTourWindow — tour guidato 4 slide
├── ui_constants.py         # Costanti condivise: palette, font, dimensioni layout
├── ui_widgets.py           # Widget riutilizzabili: _SilentRedirect, _HoverButton
├── dw_logger.py            # Logger rotante su file (2 MB × 3 backup) — invisibile all'utente
│
├── models/                 # File .gguf (esclusi da git)
├── output/                 # PNG generati a runtime (esclusi da git)
├── scripts/                # Script di utilità (es. crea_dataset.py)
├── tests/                  # Dati di test (CSV, Excel)
├── docs/                   # Documentazione di progetto
│
├── Data-Whisperer.spec     # Configurazione build PyInstaller
├── build_script.py         # Script di automazione build .app
├── requirements.txt        # Dipendenze Python
└── .gitignore
```

### Responsabilità dei moduli principali

| File | Responsabilità |
|---|---|
| `app_ui.py` | Inizializzazione, stato dell'app, caricamento modello/file, drag & drop, onboarding, query suggerite |
| `core_engine.py` | Orchestrazione pipeline AI, system prompt dei 7 agenti, path helper (`_APP_ROOT`, `_app_data_dir`) |
| `secure_executor.py` | Esecuzione sandbox del codice Python generato dall'AI, formato numeri locale |
| `data_loader.py` | Parsing CSV/Excel, normalizzazione colonne, schema per il prompt, lista fogli Excel |
| `hardware_detector.py` | Calibrazione automatica GPU layers, contesto e thread |
| `dw_logger.py` | Logger rotante su file in App Support; usato da `app_ui.py` per filtrare stdout/stderr |

---

## Architettura tecnica

### Pattern Mixin per la UI

La classe principale usa ereditarietà multipla per separare le responsabilità senza rompere i riferimenti a `self`:

```python
class DataWhispererApp(LayoutMixin, ChatMixin, SidebarMixin, DnDWrapper, ctk.CTk):
    ...
```

`DnDWrapper` (da `tkinterdnd2`) è aggiunto come mixin senza sostituire `ctk.CTk`: `TkinterDnD._require(self)` carica il pacchetto Tcl `tkdnd` nella finestra CTk esistente, preservando il tema dark. Se `tkinterdnd2` non è installato, `DnDWrapper` viene sostituito con `object` e il drag & drop è semplicemente disabilitato.

Ogni mixin accede agli attributi di stato (`self._chat`, `self._busy`, `self._dataset`, ecc.) inizializzati in `DataWhispererApp.__init__`. I moduli UI non si importano a vicenda: il coordinatore (`app_ui.py`) è l'unico punto di composizione.

### Gestione percorsi: dev vs produzione

`core_engine.py` espone due helper distinti:

- **`_APP_ROOT`** — cartella dell'eseguibile (o del sorgente in sviluppo). Usata per trovare i modelli `.gguf` e la cartella `output/`.
- **`_app_data_dir()`** — cartella dati utente in App Support. Usata per storia e flag di onboarding. Separata da `_APP_ROOT` perché un bundle `.app` firmato è read-only.

| OS | `_app_data_dir()` |
|---|---|
| macOS | `~/Library/Application Support/Data-Whisperer/` |
| Windows | `%APPDATA%/Data-Whisperer/` |
| Linux | `~/.local/share/Data-Whisperer/` |

```
USB drive/
├── Data-Whisperer.app     ← doppio click qui
├── modello-locale.gguf    ← o qualsiasi file .gguf nella stessa cartella
└── output/                ← PNG generati durante l'uso (pulizia auto dopo 7 giorni)
```

---

## Pipeline multi-agente

Un singolo modello GGUF in RAM serve 7 ruoli distinti. Ogni agente riceve un contesto fresco: nessuna contaminazione tra i ruoli.

```
Richiesta utente
      │
      ▼
┌─────────────┐
│  A0 VIGILE  │  Router ternario → NUOVA / MODIFICA / INFO
└──────┬──────┘
       │
       ├─── INFO ──────────────────────► A6 CONCIERGE
       │                                 Risposta conversazionale
       │
       ├─── MODIFICA (grafico attivo) ─► A5 STILISTA
       │                                 Modifica solo Matplotlib
       │                                 (non tocca la logica Pandas)
       │
       └─── NUOVA ─────────────────────► A1 VALIDATORE
                                          Verifica semantica colonne
                                               │
                                               ▼
                                         A2 ARCHITETTO
                                          Piano logico (max 6 step)
                                          Solo istruzioni, niente codice
                                               │
                                               ▼
                                         A3 DATTILOGRAFO
                                          Traduzione few-shot piano → Python
                                               │
                                               ▼
                                    ┌─── A4 ISPETTORE ────────────────┐
                                    │    Esegue via secure_executor    │
                                    │    Se errore: corregge e riprova │
                                    │    (max 3 tentativi QA)          │
                                    └─────────────────────────────────┘
```

### Dettaglio degli agenti

**A0 — Vigile (Router):** classifica ogni richiesta in `NUOVA`, `MODIFICA` o `INFO` con temperatura quasi-zero (0.01). Output massimo: 10 token.

**A1 — Validatore:** controlla che le colonne richieste esistano nel dataset con matching semantico (sinonimi, parole parziali, variazioni di case). Include un filtro anti-falso-positivo per numeri e anni.

**A2 — Architetto:** produce un piano logico numerato (max 6 step) senza scrivere codice. Distingue query temporali (→ `AnnoMese`, `.dt.year`) da query categoriali (→ `groupby` diretto). Include una guardia che rimuove `AnnoMese` dal piano se la query non contiene parole temporali.

**A3 — Dattilografo:** traduce il piano in codice Python tramite few-shot learning (5 esempi nel system prompt). Temperatura 0.05: copia la sintassi degli esempi, non inventa.

**A4 — Ispettore:** esegue il codice via `esegui_sicuro()`. Se fallisce, passa il traceback all'agente e richiede una correzione. Mantiene la cronologia dei tentativi: l'ispettore vede i propri errori passati. Loop: max 3 cicli QA.

**A5 — Stilista:** applicato solo su richieste di modifica estetica (`MODIFICA`) con un grafico attivo. Modifica esclusivamente le righe Matplotlib (tipo, colori, titolo, legenda) senza toccare la logica Pandas.

**A6 — Concierge:** risponde a saluti, domande sull'app e richieste generali. Temperatura 0.6 per risposte naturali. Non genera mai codice. Riceve come contesto le ultime 3 coppie domanda/risposta della sessione (memoria conversazione).

> **Memoria conversazione:** anche A2 (Architetto) riceve un riepilogo delle ultime 3 query per mantenere coerenza in analisi multi-step ("ora coloralo di rosso", "aggiungi una linea di tendenza", ecc.).

---

## Sicurezza a tre livelli

Il codice generato dall'AI viene eseguito tramite `exec()` in un ambiente isolato. Tre meccanismi indipendenti garantiscono che il codice non possa danneggiare il sistema.

### Livello 1 — Analisi AST (statica)

Prima di qualsiasi esecuzione, il codice viene parsato come albero sintattico. Qualsiasi `import` non presente nella lista `LLM_IMPORT_CONSENTITI` viene bloccato con errore immediato.

```python
LLM_IMPORT_CONSENTITI = frozenset({
    "pandas", "numpy", "matplotlib", "seaborn", "scipy", "sklearn",
    "math", "statistics", "datetime", "collections", "re", ...
})
```

Impermeabile a: `__import__("o"+"s")`, `from os import *`, `importlib.import_module(...)`.

### Livello 2 — Blacklist socket (runtime)

Un context manager sostituisce `socket.socket` con uno stub che lancia `PermissionError` per la durata dell'esecuzione, poi ripristina il riferimento originale:

```python
with _blocca_socket():
    exec(codice, namespace)
```

Garantisce l'air-gap a livello di connessione per tutte le librerie (pandas, matplotlib, scipy, ecc.), indipendentemente da quali import sono stati autorizzati dall'AST.

### Livello 3 — Thread con timeout

Il codice gira in un thread daemon con `join(timeout=30)`. Se non termina entro 30 secondi, viene classificato come loop infinito e restituisce un errore all'utente senza bloccare la UI.

---

## Rilevamento hardware automatico

`hardware_detector.py` rileva la configurazione hardware e calibra automaticamente i parametri per `llama-cpp-python`:

| Scenario | `n_gpu_layers` | `n_ctx` | Note |
|---|---|---|---|
| Apple Silicon ≥ 32 GB | -1 (tutti) | 8192 | Metal full offload, contesto esteso |
| Apple Silicon 16 GB | -1 (tutti) | 4096 | Metal full offload, contesto standard |
| Apple Silicon 8 GB | -1 (tutti) | 3072 | Metal full offload, contesto pipeline |
| Nvidia ≥ 8 GB VRAM | calcolato | 4096 | ~0.13 GB/layer, cap a 40 |
| Nvidia < 8 GB VRAM | calcolato | 2048 | Contesto ridotto |
| CPU pura ≥ 12 GB RAM | 0 | 3072 | Max 8 thread |
| CPU pura < 12 GB RAM | 0 | 2048 | Max 4 thread |

I parametri possono essere sovrascritti manualmente per debug passandoli esplicitamente a `carica_modello()`.

---

## Build e distribuzione

Data-Whisperer viene distribuito come bundle `.app` macOS (arm64) tramite **PyInstaller**.

### Prerequisiti build

```bash
pip install pyinstaller
```

### Eseguire la build

```bash
python build_script.py
# oppure direttamente:
pyinstaller Data-Whisperer.spec
```

L'output è in `dist/Data-Whisperer.app`.

### Note importanti per la build

- I file Python sorgente **devono restare nella root** del progetto. Il file `.spec` usa `pathex=["."]` e `Analysis(["app_ui.py"], ...)`. Spostare i sorgenti in una sottocartella rompe la build.
- I modelli `.gguf` **non vengono inclusi** nel bundle: sono troppo grandi e variano per utente. L'utente li posiziona accanto all'icona `.app` prima del primo avvio.
- In modalità frozen, `trova_modelli()` cerca i `.gguf` solo nella cartella che contiene il `.app`, non in `models/`.

### Struttura USB finale per il cliente

```
ChiavettaUSB/
├── Data-Whisperer.app          ← doppio click per avviare
└── qwen2.5-coder-14b.gguf     ← (o qualsiasi modello scelto)
```

---

## Formato dei file supportati

| Estensione | Formato | Encoding | Separatore |
|---|---|---|---|
| `.csv` | CSV | Auto-detection (chardet + fallback) | Auto-detection (`,` `;` `\t` `\|`) |
| `.tsv` | TSV | Auto-detection | Auto-detection |
| `.xlsx` | Excel 2007+ | — | — |
| `.xls` | Excel 97-2003 | — | — |
| `.xlsm` | Excel con macro | — | — |

Per i file Excel con più fogli, viene mostrato un dialogo modale che elenca tutti i fogli disponibili; l'utente sceglie quello da analizzare prima che il caricamento prosegua.

Le colonne completamente vuote vengono rimosse automaticamente. Le colonne con nomi tipo `Unnamed: 0` (generate da Excel) vengono eliminate. Le colonne con nomi duplicati ricevono un suffisso numerico (`_1`, `_2`, …). Le colonne con nomi che contengono parole come `data`, `date`, `time`, `mese`, `anno` vengono convertite automaticamente in `datetime64`.

---

## Dipendenze principali

| Libreria | Versione | Uso |
|---|---|---|
| `customtkinter` | ≥ 5.2 | UI desktop cross-platform |
| `tkinterdnd2` | ≥ 0.3 | Drag & drop file (opzionale, degrada gracefully) |
| `llama-cpp-python` | ≥ 0.2 | Inferenza GGUF locale |
| `pandas` | ≥ 2.0 | Manipolazione dati |
| `matplotlib` | ≥ 3.8 | Generazione grafici |
| `Pillow` | ≥ 10.0 | Rendering immagini nella UI e miniature cronologia |
| `psutil` | ≥ 5.9 | Rilevamento RAM e CPU |
| `openpyxl` | ≥ 3.1 | Lettura file Excel e generazione XLSX di export |
| `chardet` | ≥ 5.0 | Auto-detection encoding CSV |
| `fpdf2` | ≥ 2.7 | Esportazione PDF sessione |
| `pyinstaller` | ≥ 6.0 | Build applicazione nativa |
