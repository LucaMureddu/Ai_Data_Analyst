# =============================================================================
# INSTALLAZIONE DIPENDENZE (eseguire una volta nel terminale)
# =============================================================================
# pip install pandas psutil chardet openpyxl --break-system-packages
#
# Per llama-cpp-python con accelerazione Metal (Apple Silicon):
# CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python --force-reinstall --no-cache-dir --break-system-packages
# =============================================================================

import os
import platform
import sys
import threading
from dataclasses import dataclass, field

from llama_cpp import Llama

ERRORE_ANNULLATO = "__DW_ANNULLATO__"

# ── Moduli interni Data-Whisperer ─────────────────────────────────────────────
from hardware_detector import rileva_hardware
from data_loader       import carica_file, DatasetCaricato
from secure_executor   import esegui_sicuro, RisultatoEsecuzione

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

    print(f"[INFO] Caricamento modello: {os.path.basename(model_path)}")
    print(f"[INFO] GPU layers: {n_gpu_layers}  |  ctx: {n_ctx}  |  threads: {n_threads}")

    llm = Llama(
        model_path=model_path,
        n_gpu_layers=n_gpu_layers,
        n_ctx=n_ctx,
        n_threads=n_threads,
        verbose=False,
    )

    print("[INFO] Modello caricato con successo.\n")
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

    print(f"[INFO] File caricato: {dataset.nome_file}")
    print(f"[INFO] {dataset.n_righe} righe  •  {dataset.n_colonne} colonne  •  {dataset.formato.upper()}")
    if dataset.colonne_rimosse:
        print(f"[INFO] Colonne vuote rimosse: {dataset.colonne_rimosse}")
    print()

    return dataset.schema_prompt, dataset


# =============================================================================
# 3. ASSEMBLY LINE A 4 MICRO-AGENTI — 1 solo modello in RAM
#
#  VALIDATORE  →  ARCHITETTO  →  DATTILOGRAFO  →  ISPETTORE (loop)
#  (controllo)    (piano)         (codice)          (QA fix)
# =============================================================================

# ── Agente 1: VALIDATORE ─────────────────────────────────────────────────────
# Buttafuori anti-allucinazione. Non sa nulla di codice o di grafici.
# Conosce solo colonne e domande. Output: "OK" oppure "ERRORE: La colonna X…"
SP_VALIDATORE = (
    "Sei un validatore semantico. Il tuo UNICO compito: decidere se la domanda ha "
    "QUALCHE SPERANZA di essere risposta con le colonne disponibili.\n\n"

    "PRINCIPIO FONDAMENTALE — BIAS VERSO OK:\n"
    "In caso di dubbio rispondi SEMPRE OK. Bloccare una domanda valida e' un errore grave. "
    "Lasciarne passare una marginale e' accettabile: il motore a valle corregge.\n\n"

    "RISPONDI OK SE (anche uno solo basta):\n"
    "- La domanda usa sinonimi: 'costi' ~ 'Costo_Produzione', 'ricavi' ~ 'Fatturato', "
    "'negozio' ~ 'Sede', 'prodotto' ~ 'Nome_Prodotto', 'voce' ~ qualsiasi colonna.\n"
    "- La domanda usa parole parziali: 'fattur' trova 'Fatturato', 'costo' trova 'Costo_Totale'.\n"
    "- La domanda contiene numeri, anni o valori di filtro (es. '2024', 'Milano', 'alto', "
    "'100'): questi NON sono nomi di colonne, ignorali del tutto.\n"
    "- La domanda e' generica o vaga: 'analizza', 'fammi vedere', 'cosa c'e' di interessante', "
    "'dimmi qualcosa sui dati' — rispondi OK senza esitare.\n"
    "- La domanda corregge un'analisi precedente: 'hai sbagliato', 'riprova', 'non e' corretto'.\n"
    "- Hai il MINIMO dubbio che esista una colonna compatibile.\n\n"

    "RISPONDI ERRORE SOLO SE:\n"
    "La domanda chiede un concetto che e' PALESEMENTE IMPOSSIBILE trovare nel dataset, "
    "con ZERO colonne anche lontanamente compatibili. "
    "Esempio: 'quanti dipendenti lavorano?' in un dataset di vendite senza alcuna "
    "colonna relativa al personale.\n\n"

    "FORMATO RISPOSTA — solo due forme possibili:\n"
    "  OK\n"
    "oppure\n"
    "  ERRORE: non trovo nel dataset la colonna '<nome richiesto>'.\n\n"
    "ESEMPIO ERRORE CORRETTO:\n"
    "  Colonne: Data, Sede, Fatturato\n"
    "  Domanda: quanti dipendenti ci sono per reparto?\n"
    "  Risposta: ERRORE: non trovo nel dataset la colonna 'dipendenti'.\n\n"
    "Non aggiungere altro testo. Non spiegare. Non suggerire."
)

# ── Agente 2: ARCHITETTO MATEMATICO ──────────────────────────────────────────
# Pianificatore logico. Non scrive codice Python.
# Decide: temporale vs categoriale, print vs grafico, quale tipo di grafico.
SP_ARCHITETTO = (
    "Sei un architetto matematico specializzato in analisi dati. "
    "Ragioni sulla logica delle trasformazioni, ma non scrivi mai codice Python.\n\n"
    "COMPITO: Ricevi lo schema di un DataFrame e una domanda. "
    "Scrivi le istruzioni logiche numerate in italiano per rispondere alla domanda.\n\n"
    "REGOLE LOGICHE — leggi nell'ordine:\n\n"
    "REGOLA 0 — ADATTAMENTO ALLA RICHIESTA (priorità assoluta):\n"
    "Ogni piano deve essere costruito esclusivamente sulla domanda attuale. "
    "NON riutilizzare ciecamente raggruppamenti, colonne o strutture di analisi precedenti. "
    "Adatta sempre il piano alla nuova richiesta: se la domanda è cambiata, il piano cambia.\n\n"
    "REGOLA 1 — CATEGORIALE (priorità massima):\n"
    "Se la domanda chiede un confronto per CATEGORIA (Sede, Dipartimento, Prodotto, Fornitore…), "
    "raggruppa DIRETTAMENTE per quella colonna. "
    "NON creare mai la colonna AnnoMese per query categoriali. "
    "NON menzionare la colonna Data se la domanda non riguarda un trend temporale.\n\n"
    "REGOLA 2 — TEMPORALE:\n"
    "Se la domanda chiede un andamento nel TEMPO (per mese, per anno, trend, evoluzione, "
    "'mese per mese', 'andamento annuale', 'nell'ultimo trimestre'): "
    "la PRIMA istruzione del piano DEVE essere la conversione della colonna temporale. "
    "Usa pd.to_datetime() per assicurarti che la colonna sia datetime, poi estrai il "
    "periodo richiesto con .dt.month, .dt.year, .dt.to_period('M') o simili. "
    "Esempio: \"Converti la colonna Data con pd.to_datetime(), poi estrai l'anno e il mese "
    "per creare la colonna 'AnnoMese'.\"\n\n"
    "REGOLA 3 — TIPO OUTPUT:\n"
    "- Se la risposta è un NUMERO o un TESTO: l'ultima istruzione è \"Stampa il risultato con print().\"\n"
    "- Se la risposta è un GRAFICO: specifica il tipo (barre verticali, barre orizzontali, linea, torta).\n"
    "- Non usare grafici a torta se i valori possono essere negativi o zero.\n\n"
    "REGOLA 4 — CONFRONTO ANNO SU ANNO:\n"
    "Per confronti tra due anni diversi per la stessa categoria (es. fatturato 2023 vs 2024 per sede): "
    "l'unica istruzione corretta è "
    "\"Usa la funzione helper confronta_anni per calcolare la variazione percentuale tra anno1 e anno2 per categoria.\" "
    "Non pianificare filtri manuali per anno né merge: causano errori.\n\n"
    "REGOLA 5 — AGGREGAZIONE GLOBALE (priorità alta):\n"
    "Se la domanda chiede UN singolo valore aggregato ('totale', 'somma', 'media', 'massimo', "
    "'minimo', 'quanti') e NON menziona esplicitamente una categoria ('per sede', 'per dipartimento', "
    "'per prodotto'...), calcola quel valore sull'intero dataset (o sul subset filtrato per anno/filtro) "
    "e stampalo con print(). "
    "NON creare groupby, NON creare top-N, NON aggiungere categorie che l'utente non ha chiesto. "
    "Esempi: 'fatturato totale' → sum(). 'fatturato totale nel 2023' → filtra anno + sum() + print().\n\n"
    "Max 6 istruzioni. Ogni istruzione deve essere atomica e chiara."
)

# ── Agente 3: DATTILOGRAFO PYTHON ────────────────────────────────────────────
# Traduttore meccanico. Non decide nulla, copia la sintassi dagli esempi.
# Il few-shot teaching è la sua forza: un esempio vale più di dieci regole.
SP_DATTILOGRAFO = (
    "Sei un traduttore Python. Ricevi un piano logico numerato e lo traduci "
    "in codice Python eseguibile. Non devi pensare ne' decidere: "
    "traduci ogni istruzione usando la sintassi degli esempi qui sotto.\n\n"

    "DIVIETO ASSOLUTO — COMMENTI:\n"
    "Non scrivere MAI righe che iniziano con '#'. Zero commenti, zero. "
    "Non trasporre i passi del piano come commenti nel codice. "
    "Il piano e' solo per te come guida: non deve mai apparire nel codice.\n\n"

    "REGOLE ASSOLUTE:\n"
    "- Il DataFrame e' gia' in `df`. Non usare pd.read_csv() o pd.read_excel().\n"
    "- Rispondi SOLO con codice Python puro. Niente markdown (```), niente commenti (#).\n"
    "- La colonna Data e' gia' datetime64. Non usare pd.to_datetime().\n"
    "- Non chiamare mai plt.show(): i grafici vengono catturati automaticamente.\n\n"

    "═══ ESEMPIO 1 — Calcolo testuale ═══\n"
    "Piano: Calcola la media del Fatturato e stampala.\n"
    "Codice:\n"
    "media = df['Fatturato'].mean()\n"
    "print(f'Media Fatturato: {media:,.2f}')\n\n"

    "═══ ESEMPIO 2 — Raggruppamento categoriale con grafico a barre ═══\n"
    "Piano: Raggruppa per Dipartimento, somma il Fatturato, grafico a barre verticali.\n"
    "Codice:\n"
    "import matplotlib.pyplot as plt\n"
    "grouped = df.groupby('Dipartimento')['Fatturato'].sum().reset_index()\n"
    "plt.figure()\n"
    "plt.bar(grouped['Dipartimento'], grouped['Fatturato'])\n"
    "plt.title('Fatturato per Dipartimento')\n"
    "plt.xlabel('Dipartimento')\n"
    "plt.ylabel('Fatturato')\n"
    "plt.xticks(rotation=45)\n\n"

    "═══ ESEMPIO 3 — Raggruppamento temporale (AnnoMese) con grafico a linea ═══\n"
    "Piano: Crea colonna AnnoMese, raggruppa per essa, somma Fatturato, grafico a linea.\n"
    "Codice:\n"
    "import matplotlib.pyplot as plt\n"
    "df['AnnoMese'] = df['Data'].dt.year.astype(str) + '-' + df['Data'].dt.month.astype(str).str.zfill(2)\n"
    "grouped = df.groupby('AnnoMese')['Fatturato'].sum().reset_index()\n"
    "plt.figure()\n"
    "plt.plot(grouped['AnnoMese'], grouped['Fatturato'], marker='o')\n"
    "plt.title('Andamento Fatturato nel Tempo')\n"
    "plt.xticks(rotation=45)\n\n"

    "═══ ESEMPIO 4 — Filtro per anno + idxmax con controllo vuoto ═══\n"
    "Piano: Filtra per anno 2024, trova la Sede con Fatturato massimo, stampa.\n"
    "Codice:\n"
    "df_filtrato = df[df['Data'].dt.year == 2024]\n"
    "if df_filtrato.empty:\n"
    "    print('Nessun dato per il 2024.')\n"
    "else:\n"
    "    per_sede = df_filtrato.groupby('Sede')['Fatturato'].sum()\n"
    "    sede_max = per_sede.idxmax()\n"
    "    print(f'Sede con fatturato massimo nel 2024: {sede_max} ({per_sede[sede_max]:,.2f})')\n\n"

    "═══ ESEMPIO 5 — Confronto anno su anno per categoria ═══\n"
    "Piano: Confronta la variazione percentuale del Fatturato tra 2023 e 2024 per Sede.\n"
    "Codice:\n"
    "variazione = confronta_anni(df, 'Data', 'Fatturato', 'Sede', 2023, 2024)\n"
    "if not variazione.empty:\n"
    "    print(variazione.sort_values(ascending=False).to_string())\n"
    "else:\n"
    "    print('Dati insufficienti per il confronto.')\n\n"

    "═══ ESEMPIO 6 — Top N con nlargest ═══\n"
    "Piano: Trova le 5 Sedi con Fatturato totale piu' alto, stampa in ordine decrescente.\n"
    "Codice:\n"
    "top5 = df.groupby('Sede')['Fatturato'].sum().nlargest(5).reset_index()\n"
    "top5.columns = ['Sede', 'Fatturato Totale']\n"
    "top5['Fatturato Totale'] = top5['Fatturato Totale'].map(lambda x: f'{x:,.2f}')\n"
    "print(top5.to_string(index=False))\n\n"

    "═══ ESEMPIO 7 — Percentuale sul totale ═══\n"
    "Piano: Calcola la percentuale di Fatturato per ogni Sede rispetto al totale, "
    "ordina decrescente, stampa.\n"
    "Codice:\n"
    "per_sede = df.groupby('Sede')['Fatturato'].sum().reset_index()\n"
    "totale = per_sede['Fatturato'].sum()\n"
    "per_sede['Percentuale %'] = (per_sede['Fatturato'] / totale * 100).round(1)\n"
    "per_sede = per_sede.sort_values('Percentuale %', ascending=False)\n"
    "print(per_sede.to_string(index=False))\n\n"

    "═══ ESEMPIO 8 — Filtro anno + raggruppamento con grafico a barre orizzontali ═══\n"
    "Piano: Filtra l'anno 2023, raggruppa per Prodotto, somma le Quantita', "
    "grafico a barre orizzontali.\n"
    "Codice:\n"
    "import matplotlib.pyplot as plt\n"
    "df_anno = df[df['Data'].dt.year == 2023]\n"
    "if df_anno.empty:\n"
    "    print('Nessun dato per il 2023.')\n"
    "else:\n"
    "    grouped = df_anno.groupby('Prodotto')['Quantita'].sum().sort_values()\n"
    "    plt.figure()\n"
    "    plt.barh(grouped.index, grouped.values)\n"
    "    plt.title('Quantita per Prodotto (2023)')\n"
    "    plt.xlabel('Quantita')\n"
    "    plt.tight_layout()\n"
)

# ── Agente 4: ISPETTORE (QA loop) ────────────────────────────────────────────
# Il meccanico. Legge il traceback, corregge il codice, non spiega mai.
SP_ISPETTORE = (
    "Sei un debugger Python esperto. Ricevi codice che ha generato un errore e devi correggerlo.\n\n"
    "COMPITO:\n"
    "1. Leggi il traceback e individua la causa precisa dell'errore.\n"
    "2. Riscrivi il codice completo con la correzione applicata.\n"
    "3. Rispondi SOLO con il codice Python corretto. Niente markdown (```), niente spiegazioni.\n\n"
    "REGOLE INVARIABILI:\n"
    "- Il DataFrame è già in memoria nella variabile `df`. Non usare pd.read_csv().\n"
    "- La colonna Data è già datetime64. Non usare pd.to_datetime(), non usare .str su date.\n"
    "- Per estrarre anno/mese usa sempre .dt.year e .dt.month.\n"
    "- La funzione `confronta_anni(df, col_data, col_valore, col_categoria, anno1, anno2)` "
    "è già disponibile nel namespace: usala per confronti anno su anno."
)

# ── Agente 0: VIGILE (Router) ─────────────────────────────────────────────────
# Classificatore a 3 intenti, attivo su OGNI richiesta.
# Output: SOLO una delle parole "NUOVA", "MODIFICA", "INFO".
PROMPT_VIGILE = (
    "Sei un router intelligente. Classifica la richiesta dell'utente in UNA di queste 3 categorie:\n\n"

    "NUOVA   → L'utente vuole analizzare dati: calcoli, aggregazioni, filtri, grafici nuovi, "
    "confronti, trend, ranking, statistiche su colonne del dataset.\n"
    "  Esempi: 'mostra il fatturato per sede', 'qual è il totale?', 'crea un grafico a barre'.\n"
    "  IMPORTANTE — classifica NUOVA anche nei seguenti casi:\n"
    "  - L'utente corregge un errore precedente (es. 'hai sbagliato', 'non è corretto').\n"
    "  - L'utente chiede di riprovare o rieseguire (es. 'riprova', 'rifai', 'prova di nuovo').\n"
    "  - L'utente chiede un grafico completamente nuovo o diverso dal precedente "
    "(es. 'fammi un grafico nuovo', 'mostrami un altro tipo di analisi').\n"
    "  - La richiesta riguarda i DATI (valori, colonne, filtri, calcoli), "
    "anche se il grafico precedente è sullo schermo.\n\n"

    "MODIFICA → L'utente vuole cambiare ESCLUSIVAMENTE l'aspetto visivo di un grafico "
    "GIA' MOSTRATO SULLO SCHERMO, senza toccare i dati o il tipo di analisi.\n"
    "  MODIFICA è valida SOLO per: tipo di grafico (torta, barre, linea), colori, "
    "titolo, etichette degli assi, legenda, orientamento (orizzontale/verticale).\n"
    "  Esempi validi: 'fallo a torta', 'cambia i colori in rosso', 'metti il titolo X', "
    "'rendi orizzontale', 'aggiungi una legenda', 'usa colori più chiari'.\n"
    "  ATTENZIONE: se la richiesta implica un cambio di dati, colonne, filtri o aggregazioni, "
    "NON è MODIFICA — è NUOVA.\n\n"

    "INFO    → L'utente saluta, fa domande sull'app, chiede cosa puoi fare, "
    "o scrive qualcosa che non riguarda l'analisi del dataset.\n"
    "  Esempi: 'ciao', 'come funzioni?', 'cosa sai fare?', 'chi sei?', "
    "'grazie', 'mi aiuti?', 'che differenza c'è tra...'\n\n"

    "REGOLA ASSOLUTA: rispondi ESCLUSIVAMENTE con UNA sola parola: NUOVA, MODIFICA o INFO.\n"
    "Non aggiungere spiegazioni, punteggiatura o altro testo."
)

# ── Agente 6: CONCIERGE (conversazione generale) ──────────────────────────────
# Risponde a saluti, domande sull'app e richieste non legate al dataset.
# Temperatura alta: deve sembrare naturale e non robotico.
# Output: testo libero in italiano, mai codice Python.
PROMPT_CONCIERGE = (
    "Sei Data-Whisperer, un analista dati AI che gira completamente offline sul computer "
    "dell'utente — nessun dato viene mai inviato in rete.\n\n"

    "Parli italiano, sei diretto e cordiale come un collega esperto seduto accanto. "
    "Rispondi sempre in modo naturale e conversazionale: niente liste puntate, niente "
    "intestazioni in maiuscolo, niente strutture formali. Scrivi come se stessi "
    "chiacchierando, non compilando una scheda tecnica.\n\n"

    "Quello che sai fare: analizzare file CSV ed Excel caricati dall'utente, rispondere "
    "a domande sui dati in linguaggio naturale, produrre grafici, calcoli, aggregazioni, "
    "confronti e trend. L'utente carica il file dalla sidebar, poi scrive la domanda "
    "in italiano e tu produci l'analisi.\n\n"

    "Se nel messaggio trovi il contesto del dataset caricato (nome file, colonne), usalo: "
    "suggerisci analisi CONCRETE basate su quelle colonne reali, non esempi generici. "
    "Se non c'e' nessun dataset caricato, invita l'utente a caricarne uno.\n\n"

    "Non generare mai codice Python. Non usare mai elenchi puntati o numerati nelle risposte. "
    "Sii breve: 2-4 frasi sono quasi sempre sufficienti."
)

# ── Agente 5: STILISTA ────────────────────────────────────────────────────────
# Riceve il codice Python dell'ultimo grafico generato con successo e applica
# SOLO le modifiche estetiche Matplotlib richieste. Non tocca mai la logica Pandas.
# Output: SOLO codice Python pulito, senza markdown.
PROMPT_STILISTA = (
    "Sei un esperto di visualizzazione dati con Matplotlib. "
    "Ricevi codice Python che genera un grafico e una richiesta di modifica estetica. "
    "Il tuo compito è applicare SOLO le modifiche visive richieste.\n\n"
    "REGOLE ASSOLUTE:\n"
    "- NON modificare MAI la logica Pandas: groupby, filtri, calcoli, selezione colonne "
    "devono rimanere identici all'originale.\n"
    "- Modifica SOLO le righe Matplotlib: tipo grafico (bar/barh/plot/pie), "
    "colori (color=, cmap=), titolo (plt.title()), etichette assi (plt.xlabel/ylabel()), "
    "stile, legenda (plt.legend()), rotazioni (plt.xticks(rotation=)).\n"
    "- Il DataFrame è già in memoria nella variabile `df`. Non usare pd.read_csv().\n"
    "- Non chiamare mai plt.show().\n"
    "- Rispondi SOLO con il codice Python completo e modificato. "
    "Niente blocchi markdown (```), niente commenti, niente spiegazioni.\n\n"
    "ESEMPI DI TRASFORMAZIONI VALIDE:\n"
    "  'fallo a torta'     → plt.bar(x, y) diventa plt.pie(y, labels=x)\n"
    "  'colori rossi'      → aggiungi color='crimson' o cmap='Reds'\n"
    "  'titolo X'          → plt.title('X')\n"
    "  'rendi orizzontale' → plt.bar(x, y) diventa plt.barh(x, y)\n"
    "  'aggiungi legenda'  → aggiungi plt.legend() prima della fine"
)


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
    import re as _re

    # 1. Markdown
    pulito = testo.replace("```python", "").replace("```", "")

    # 2. plt.show() — qualsiasi indentazione
    pulito = _re.sub(r"[ \t]*plt\.show\(\)[ \t]*\n?", "", pulito)

    # 3. Righe-solo-commento
    righe_pulite = []
    for riga in pulito.splitlines():
        if riga.strip().startswith("#"):
            continue          # salta commenti del Dattilografo
        righe_pulite.append(riga)

    # 4. Max una riga vuota consecutiva
    pulito = "\n".join(righe_pulite)
    pulito = _re.sub(r"\n{3,}", "\n\n", pulito)

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
    ultimo_codice_valido: "str | None" = None,
    progress_callback: "callable | None" = None,
    cancel_event: "threading.Event | None" = None,
    memoria_conversazione: "list[dict] | None" = None,
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
    print(f"[A0 — VIGILE] Classificazione richiesta: {query_utente[:70]}...")

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
    print(f"[A0] Decisione Vigile: {decisione_vigile!r}")

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
        print("[A6 — CONCIERGE] Risposta conversazionale...")

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
        print(f"[A6] Risposta generata ({len(risposta_concierge)} chars).")
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
            print("[A5 — STILISTA] Applicazione modifiche estetiche al grafico...")
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
            print(f"[A5] Codice stilizzato ({len(codice_stilista)} chars).")

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
            print("[A0] Nessun grafico attivo — MODIFICA declassata a NUOVA.")

    if _check_cancel(cancel_event):
        return _risultato_annullato()

    # ─────────────────────────────────────────────────────────────────────────
    # BRANCH NUOVA — AGENTE 1: VALIDATORE: anti-allucinazione, verifica colonne
    # ─────────────────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.20, "Validatore  ·  verifica colonne")
    print(f"[A1 — VALIDATORE] Controllo colonne per: {query_utente[:70]}...")

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

    print(f"[A1] Esito: {esito_validazione[:60]}")

    # Cerca "OK" tra le prime 4 parole — robusto a modelli verbosi
    # es. "OK", "OK.", "Okay", "Yes, OK" → passa | "ERRORE: …" → blocca
    prime_parole = esito_validazione.strip().upper().split()[:4]
    if not any(w.startswith("OK") for w in prime_parole):
        # ── Falso positivo numerico: il Validatore ha scambiato un anno/numero
        # (es. "2050", "100") per un nome di colonna. Estrai il nome segnalato
        # e, se è puramente numerico, ignora il blocco e continua la pipeline.
        import re as _re

        def _msg_errore_pulito(raw: str) -> str:
            """
            Trasforma l'output grezzo del Validatore in un messaggio
            user-friendly. Evita che testo di istruzioni appaia in chat.
            """
            body = raw.strip()
            if body.upper().startswith("ERRORE:"):
                body = body[7:].strip()
            # Estrai i nomi di colonne citati tra apici singoli o doppi
            _quoted = _re.findall(r"[\"']([^\"']{2,40})[\"']", body)
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

        _match = _re.search(r'"([^"]+)"', esito_validazione)
        if _match:
            _nome = _match.group(1).strip()
            if _nome.lstrip("-").replace(".", "", 1).isdigit():
                print(f"[A1] Falso positivo ignorato: '{_nome}' è un numero/anno, non una colonna.")
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
    print("[A2 — ARCHITETTO] Costruzione piano logico...")

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
            print("[A2] AnnoMese rimosso dal piano: query categoriale, nessuna parola temporale.")

    print(f"[A2] Piano: {piano_logico[:100]}...")

    if _check_cancel(cancel_event):
        return _risultato_annullato()

    # ─────────────────────────────────────────────────────────────────────────
    # AGENTE 3 — DATTILOGRAFO: traduzione few-shot piano → codice
    # ─────────────────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.62, "Dattilografo  ·  scrittura codice Python")
    print("[A3 — DATTILOGRAFO] Traduzione piano in codice Python...")

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
    print(f"[A3] Codice prodotto ({len(codice)} chars).")

    # ─────────────────────────────────────────────────────────────────────────
    # AGENTE 4 — ISPETTORE: esecuzione + reflexion loop (QA)
    # ─────────────────────────────────────────────────────────────────────────
    history_ispettore:  list[dict]                  = []
    tentativi_qa:       int                         = 0
    risultato_finale:   "RisultatoEsecuzione | None" = None

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
        print(
            f"[A4 — ISPETTORE] Esecuzione "
            f"(tentativo {tentativi_qa + 1}/{max_tentativi_qa + 1})..."
        )
        risultato = esegui_sicuro(codice, dataset.df, timeout_secondi=30)
        risultato_finale = risultato

        if risultato.successo:
            print(f"[A4] Codice approvato al tentativo {tentativi_qa + 1}.")
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
        print(f"[A4] Errore rilevato → riparazione {tentativi_qa}/{max_tentativi_qa}...")

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
    print(f"[A4] Tentativi esauriti ({max_tentativi_qa}).")
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
