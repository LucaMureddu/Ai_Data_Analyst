# =============================================================================
# INSTALLAZIONE DIPENDENZE
# =============================================================================
# pip install pandas openpyxl chardet --break-system-packages
# =============================================================================

"""
data_loader.py
--------------
Carica e normalizza file CSV ed Excel per Data-Whisperer.

Funzionalità:
  - Auto-detection encoding (UTF-8, Latin-1, CP1252, ISO-8859-1…)
  - Auto-detection separatore CSV (virgola, punto-e-virgola, tabulazione, pipe)
  - Lettura nativa .xlsx / .xls / .xlsm (multi-foglio con selezione)
  - Pulizia colonne: strip spazi, normalizzazione nomi, rimozione colonne vuote
  - Schema strutturato pronto per essere passato al prompt LLM

Zero chiamate di rete.
"""

from __future__ import annotations

import csv
import io
import os
import warnings
from dataclasses import dataclass, field

import pandas as pd


# =============================================================================
# STRUTTURA RISULTATO
# =============================================================================

@dataclass
class DatasetCaricato:
    df: pd.DataFrame
    percorso: str
    nome_file: str
    formato: str                    # "csv" | "excel"
    encoding: str                   # es. "utf-8", "latin-1"
    separatore: str                 # solo per CSV: ",", ";", "\t", "|"
    foglio: str                     # solo per Excel: nome del foglio attivo
    n_righe: int
    n_colonne: int
    colonne_rimosse: list[str]      # colonne vuote eliminate automaticamente
    schema_prompt: str              # stringa pronta per il prompt LLM


# =============================================================================
# UTILITY: ENCODING
# =============================================================================

ENCODING_DA_PROVARE = ["utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1", "utf-16"]


def _rileva_encoding(percorso: str) -> str:
    """
    Prova gli encoding più comuni in ordine di probabilità.
    Usa chardet come fallback se disponibile.
    """
    # Prima proviamo chardet (più accurato)
    try:
        import chardet
        with open(percorso, "rb") as f:
            raw = f.read(65536)        # legge i primi 64 KB
        detected = chardet.detect(raw)
        if detected["confidence"] and detected["confidence"] > 0.75:
            enc = detected["encoding"] or "utf-8"
            # normalizza alias comuni
            return enc.lower().replace("windows-1252", "cp1252")
    except ImportError:
        pass

    # Fallback manuale
    for enc in ENCODING_DA_PROVARE:
        try:
            with open(percorso, "r", encoding=enc, errors="strict") as f:
                f.read(4096)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    return "utf-8"   # worst-case: proviamo comunque, pandas gestirà gli errori


# =============================================================================
# UTILITY: SEPARATORE CSV
# =============================================================================

def _rileva_separatore(percorso: str, encoding: str) -> str:
    """
    Usa csv.Sniffer sui primi 4 KB. Fallback su virgola.
    """
    try:
        with open(percorso, "r", encoding=encoding, errors="replace") as f:
            campione = f.read(4096)
        dialetto = csv.Sniffer().sniff(campione, delimiters=",;\t|")
        return dialetto.delimiter
    except csv.Error:
        return ","


# =============================================================================
# UTILITY: PULIZIA COLONNE
# =============================================================================

def _pulisci_colonne(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    1. Strip spazi nei nomi colonna
    2. Rimuovi colonne con tutti i valori NaN
    3. Normalizza nomi duplicati aggiungendo suffisso _N
    """
    # Strip
    df.columns = [str(c).strip() for c in df.columns]

    # Rimozione colonne vuote
    colonne_prima = list(df.columns)
    df = df.dropna(axis=1, how="all")
    # Rimuovi anche colonne "Unnamed: X" generate da Excel quando la colonna è vuota
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed:\s*\d+$")]
    colonne_rimosse = [c for c in colonne_prima if c not in df.columns]

    # Deduplica nomi colonne
    contatori: dict[str, int] = {}
    nuovi_nomi = []
    for nome in df.columns:
        if nome in contatori:
            contatori[nome] += 1
            nuovi_nomi.append(f"{nome}_{contatori[nome]}")
        else:
            contatori[nome] = 0
            nuovi_nomi.append(nome)
    df.columns = nuovi_nomi

    return df, colonne_rimosse


# =============================================================================
# UTILITY: CONVERSIONE AUTOMATICA DATE
# =============================================================================

def _converti_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converte automaticamente in datetime le colonne il cui nome contiene
    'data', 'date', 'time', 'giorno', 'mese', 'anno' (case-insensitive).
    Operazione silenziosa: se la conversione fallisce la colonna resta invariata.

    Questo garantisce che quando l'IA chiama .dt.strftime() la colonna
    sia già un dtype datetime64, eliminando i crash su dati stringa.
    """
    PAROLE_DATA = ("data", "date", "time", "giorno", "mese", "anno", "month", "year", "day")
    for col in df.columns:
        if any(kw in col.lower() for kw in PAROLE_DATA):
            try:
                df[col] = pd.to_datetime(df[col])
            except Exception:
                pass   # colonna non convertibile — lasciata intatta
    return df


# =============================================================================
# UTILITY: SCHEMA TESTO PER PROMPT
# =============================================================================

def _costruisci_schema_prompt(df: pd.DataFrame, nome_file: str) -> str:
    """
    Genera una stringa descrittiva del dataset da inserire nel prompt LLM.
    Include: nome file, colonne+tipi, statistiche base, prime 3 righe.
    """
    colonne_info = "\n".join(
        f"  - {col}  (tipo: {dtype})"
        for col, dtype in zip(df.columns, df.dtypes)
    )

    # Statistiche rapide solo per colonne numeriche
    numeriche = df.select_dtypes(include="number")
    stats_txt = ""
    if not numeriche.empty:
        stats = numeriche.describe().round(2)
        stats_txt = f"\nStatistiche colonne numeriche:\n{stats.to_string()}\n"

    sample = df.head(3).to_string(index=False)

    schema = (
        f"File: {nome_file}\n"
        f"Righe totali: {len(df)}  |  Colonne: {len(df.columns)}\n\n"
        f"Il DataFrame pandas è disponibile nella variabile `df`.\n"
        f"Colonne e tipi:\n{colonne_info}\n"
        f"{stats_txt}\n"
        f"Prime 3 righe di esempio:\n{sample}"
    )
    return schema


# =============================================================================
# CARICAMENTO CSV
# =============================================================================

def carica_csv(percorso: str) -> DatasetCaricato:
    """Carica un file CSV con auto-detection di encoding e separatore."""

    encoding  = _rileva_encoding(percorso)
    sep       = _rileva_separatore(percorso, encoding)
    nome_file = os.path.basename(percorso)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_csv(
            percorso,
            sep=sep,
            encoding=encoding,
            encoding_errors="replace",
            low_memory=False,
        )

    df, rimossi = _pulisci_colonne(df)
    df          = _converti_date(df)
    schema      = _costruisci_schema_prompt(df, nome_file)

    return DatasetCaricato(
        df=df,
        percorso=percorso,
        nome_file=nome_file,
        formato="csv",
        encoding=encoding,
        separatore=sep,
        foglio="",
        n_righe=len(df),
        n_colonne=len(df.columns),
        colonne_rimosse=rimossi,
        schema_prompt=schema,
    )


# =============================================================================
# CARICAMENTO EXCEL
# =============================================================================

def carica_excel(percorso: str, nome_foglio: str | None = None) -> DatasetCaricato:
    """
    Carica un file Excel (.xlsx/.xls/.xlsm).
    Se nome_foglio è None, usa il primo foglio non vuoto.
    """
    nome_file = os.path.basename(percorso)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xl = pd.ExcelFile(percorso, engine="openpyxl")

    fogli_disponibili = xl.sheet_names

    # Selezione foglio
    if nome_foglio and nome_foglio in fogli_disponibili:
        foglio_attivo = nome_foglio
    else:
        # Primo foglio con almeno una riga di dati
        foglio_attivo = fogli_disponibili[0]
        for f in fogli_disponibili:
            df_tmp = xl.parse(f, nrows=2)
            if not df_tmp.empty:
                foglio_attivo = f
                break

    df = xl.parse(foglio_attivo)
    df, rimossi = _pulisci_colonne(df)
    df          = _converti_date(df)
    schema      = _costruisci_schema_prompt(df, f"{nome_file} [{foglio_attivo}]")

    return DatasetCaricato(
        df=df,
        percorso=percorso,
        nome_file=nome_file,
        formato="excel",
        encoding="",
        separatore="",
        foglio=foglio_attivo,
        n_righe=len(df),
        n_colonne=len(df.columns),
        colonne_rimosse=rimossi,
        schema_prompt=schema,
    )


# =============================================================================
# FUNZIONE UNIFICATA (punto di ingresso)
# =============================================================================

def lista_fogli_excel(percorso: str) -> list[str]:
    """
    Restituisce l'elenco dei nomi dei fogli in un file Excel senza caricare i dati.
    Ritorna lista vuota in caso di errore.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            xl = pd.ExcelFile(percorso, engine="openpyxl")
        except Exception:
            try:
                xl = pd.ExcelFile(percorso)
            except Exception:
                return []
    return list(xl.sheet_names)


def carica_file(percorso: str, nome_foglio: Optional[str] = None) -> DatasetCaricato:
    """
    Punto di ingresso universale: rileva automaticamente il formato
    (CSV o Excel) ed esegue il caricamento appropriato.

    Uso:
        from data_loader import carica_file
        dataset = carica_file("bilancio_2024.xlsx")
        llm_context = dataset.schema_prompt
        df = dataset.df
    """
    if not os.path.exists(percorso):
        raise FileNotFoundError(f"File non trovato: {percorso}")

    estensione = os.path.splitext(percorso)[1].lower()

    if estensione in (".xlsx", ".xls", ".xlsm", ".xlsb"):
        return carica_excel(percorso, nome_foglio)
    elif estensione in (".csv", ".tsv", ".txt"):
        return carica_csv(percorso)
    else:
        # Prova CSV come fallback
        try:
            return carica_csv(percorso)
        except Exception as e:
            raise ValueError(
                f"Formato '{estensione}' non supportato. Usa .csv, .xlsx o .xls."
            ) from e


# =============================================================================
# TEST STANDALONE
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python data_loader.py <percorso_file>")
        print("\nCreazione dataset di test...")

        # Genera un CSV di test con encoding non standard e separatore ;
        test_csv = "/tmp/test_data_loader.csv"
        with open(test_csv, "w", encoding="latin-1") as f:
            f.write("Mese;Fatturato;Costi;Margine;\n")
            f.write("Gennaio;12000;8000;4000;\n")
            f.write("Febbraio;15400;9100;6300;\n")
            f.write("Marzo;9800;7500;2300;\n")
            f.write("Aprile;18200;10300;7900;\n")

        dataset = carica_file(test_csv)
        print(f"\n✔ Formato    : {dataset.formato}")
        print(f"✔ Encoding   : {dataset.encoding}")
        print(f"✔ Separatore : {repr(dataset.separatore)}")
        print(f"✔ Righe      : {dataset.n_righe}")
        print(f"✔ Colonne    : {dataset.n_colonne}")
        print(f"✔ Rimossi    : {dataset.colonne_rimosse}")
        print(f"\n── Schema prompt ────────────────────────────────────")
        print(dataset.schema_prompt)
    else:
        dataset = carica_file(sys.argv[1])
        print(dataset.schema_prompt)
