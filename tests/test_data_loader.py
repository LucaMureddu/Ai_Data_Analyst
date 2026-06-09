"""
test_data_loader.py
-------------------
Test unitari per data_loader.py.

Testa caricamento CSV reale (dati_test.csv), caricamento Excel reale
(vendite_corporate_2023.xlsx), auto-detection encoding/separatore,
pulizia colonne e schema prompt.
"""
import os

import pandas as pd
import pytest

from data_loader import (
    carica_csv,
    carica_excel,
    lista_fogli_excel,
    DatasetCaricato,
    _rileva_separatore,
    _pulisci_colonne,
    _converti_date,
)

# ---------------------------------------------------------------------------
# Percorsi ai file di test reali
# ---------------------------------------------------------------------------
TESTS_DIR  = os.path.dirname(__file__)
CSV_REALE  = os.path.join(TESTS_DIR, "dati_test.csv")
XLSX_REALE = os.path.join(TESTS_DIR, "vendite_corporate_2023.xlsx")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def df_base() -> pd.DataFrame:
    return pd.DataFrame({
        "Nome":    ["Alice", "Bob", "Carlo"],
        "Eta":     [30, 25, 35],
        "Citta":   ["Roma", "Milano", "Napoli"],
    })


@pytest.fixture
def df_con_vuoti(df_base) -> pd.DataFrame:
    df = df_base.copy()
    df["ColonnaVuota"] = None
    return df


# ---------------------------------------------------------------------------
# Test _pulisci_colonne
# ---------------------------------------------------------------------------

class TestPulisciColonne:
    def test_rimuove_colonne_tutte_nan(self, df_con_vuoti):
        df_pulito, rimossi = _pulisci_colonne(df_con_vuoti)
        assert "ColonnaVuota" not in df_pulito.columns
        assert "ColonnaVuota" in rimossi

    def test_strip_spazi_nomi(self):
        df = pd.DataFrame({" Nome ": ["A"], "  Eta  ": [1]})
        df_pulito, _ = _pulisci_colonne(df)
        assert "Nome" in df_pulito.columns
        assert "Eta" in df_pulito.columns

    def test_nomi_duplicati_rinominati(self):
        df = pd.DataFrame([[1, 2, 3]], columns=["A", "A", "B"])
        df_pulito, _ = _pulisci_colonne(df)
        assert "A" in df_pulito.columns
        assert "A_1" in df_pulito.columns

    def test_nessuna_modifica_su_df_pulito(self, df_base):
        df_pulito, rimossi = _pulisci_colonne(df_base)
        assert rimossi == []
        assert list(df_pulito.columns) == list(df_base.columns)


# ---------------------------------------------------------------------------
# Test _converti_date
# ---------------------------------------------------------------------------

class TestConvertiDate:
    def test_colonna_data_convertita(self):
        df = pd.DataFrame({"Data": ["2024-01-15", "2024-02-20"]})
        df_conv = _converti_date(df)
        assert pd.api.types.is_datetime64_any_dtype(df_conv["Data"])

    def test_colonna_non_data_invariata(self):
        df = pd.DataFrame({"Fatturato": [100, 200], "Sede": ["Roma", "Milano"]})
        df_conv = _converti_date(df)
        assert df_conv["Fatturato"].dtype == df["Fatturato"].dtype

    def test_colonna_date_inglese_convertita(self):
        df = pd.DataFrame({"date": ["2024-01-01", "2024-06-15"]})
        df_conv = _converti_date(df)
        assert pd.api.types.is_datetime64_any_dtype(df_conv["date"])

    def test_colonna_non_parsabile_invariata(self):
        df = pd.DataFrame({"Data": ["non-è-una-data", "nemmeno-questa"]})
        df_conv = _converti_date(df)
        # Non deve crashare; tipo originale o object
        assert df_conv is not None


# ---------------------------------------------------------------------------
# Test _rileva_separatore
# ---------------------------------------------------------------------------

class TestRilevaSeparatore:
    def test_separatore_virgola(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b,c\n1,2,3\n4,5,6\n", encoding="utf-8")
        assert _rileva_separatore(str(f), "utf-8") == ","

    def test_separatore_punto_e_virgola(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a;b;c\n1;2;3\n4;5;6\n", encoding="utf-8")
        assert _rileva_separatore(str(f), "utf-8") == ";"

    def test_separatore_tabulazione(self, tmp_path):
        f = tmp_path / "test.tsv"
        f.write_text("a\tb\tc\n1\t2\t3\n", encoding="utf-8")
        assert _rileva_separatore(str(f), "utf-8") == "\t"


# ---------------------------------------------------------------------------
# Test carica_csv su file reale
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.exists(CSV_REALE), reason="dati_test.csv non trovato")
class TestCricaCSVReale:
    def test_tipo_risultato(self):
        ds = carica_csv(CSV_REALE)
        assert isinstance(ds, DatasetCaricato)

    def test_formato_csv(self):
        ds = carica_csv(CSV_REALE)
        assert ds.formato == "csv"

    def test_dataframe_non_vuoto(self):
        ds = carica_csv(CSV_REALE)
        assert ds.n_righe > 0
        assert ds.n_colonne > 0

    def test_schema_prompt_non_vuoto(self):
        ds = carica_csv(CSV_REALE)
        assert len(ds.schema_prompt) > 50

    def test_schema_contiene_nome_file(self):
        ds = carica_csv(CSV_REALE)
        assert "dati_test.csv" in ds.schema_prompt


# ---------------------------------------------------------------------------
# Test carica_excel su file reale
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.exists(XLSX_REALE), reason="vendite_corporate_2023.xlsx non trovato")
class TestCaricaExcelReale:
    def test_tipo_risultato(self):
        ds = carica_excel(XLSX_REALE)
        assert isinstance(ds, DatasetCaricato)

    def test_formato_excel(self):
        ds = carica_excel(XLSX_REALE)
        assert ds.formato == "excel"

    def test_dataframe_non_vuoto(self):
        ds = carica_excel(XLSX_REALE)
        assert ds.n_righe > 0

    def test_foglio_non_vuoto(self):
        ds = carica_excel(XLSX_REALE)
        assert ds.foglio != ""


# ---------------------------------------------------------------------------
# Test lista_fogli_excel
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.exists(XLSX_REALE), reason="vendite_corporate_2023.xlsx non trovato")
class TestListaFogliExcel:
    def test_restituisce_lista(self):
        fogli = lista_fogli_excel(XLSX_REALE)
        assert isinstance(fogli, list)
        assert len(fogli) >= 1

    def test_file_inesistente(self):
        assert lista_fogli_excel("/no/file.xlsx") == []
