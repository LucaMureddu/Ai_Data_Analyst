"""
test_secure_executor.py
-----------------------
Test unitari per secure_executor.py — i tre livelli di sicurezza
e la corretta esecuzione di codice valido.

Nessuna dipendenza da llama_cpp o da un modello GGUF.
"""
import pandas as pd
import pytest

from secure_executor import esegui_sicuro, _analisi_ast


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def df_vendite() -> pd.DataFrame:
    """DataFrame minimo con struttura tipica dei dataset di vendite."""
    return pd.DataFrame({
        "Mese":      ["Gen", "Feb", "Mar", "Apr"],
        "Fatturato": [12_000, 15_400, 9_800, 18_200],
        "Costi":     [8_000,   9_100, 7_500, 10_300],
    })


# ---------------------------------------------------------------------------
# Livello 0 — esecuzione valida
# ---------------------------------------------------------------------------

class TestEsecuzioneValida:
    def test_calcolo_testuale(self, df_vendite):
        codice = "print(df['Fatturato'].sum())"
        r = esegui_sicuro(codice, df_vendite)
        assert r.successo
        assert "55400" in r.output_testo

    def test_output_multiriga(self, df_vendite):
        codice = (
            "totale = df['Fatturato'].sum()\n"
            "media  = df['Fatturato'].mean()\n"
            "print(f'Totale: {totale}')\n"
            "print(f'Media: {media}')\n"
        )
        r = esegui_sicuro(codice, df_vendite)
        assert r.successo
        assert "Totale" in r.output_testo
        assert "Media" in r.output_testo

    def test_codice_vuoto_restituisce_errore(self, df_vendite):
        r = esegui_sicuro("", df_vendite)
        assert not r.successo
        assert r.errore

    def test_grafico_matplotlib_catturato(self, df_vendite):
        codice = (
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots()\n"
            "ax.bar(df['Mese'], df['Fatturato'])\n"
        )
        r = esegui_sicuro(codice, df_vendite)
        assert r.successo
        assert len(r.grafici_png) == 1
        # PNG valido: header magic bytes
        assert r.grafici_png[0][:4] == b"\x89PNG"

    def test_df_disponibile_senza_import(self, df_vendite):
        """df, pd, np devono essere disponibili senza che il codice li importi."""
        codice = "print(len(df))"
        r = esegui_sicuro(codice, df_vendite)
        assert r.successo
        assert "4" in r.output_testo


# ---------------------------------------------------------------------------
# Livello 1 — Analisi AST: import vietati
# ---------------------------------------------------------------------------

class TestBloccoAST:
    def test_import_os_bloccato(self, df_vendite):
        codice = "import os\nprint(os.getcwd())"
        r = esegui_sicuro(codice, df_vendite)
        assert not r.successo
        assert "os" in r.errore.lower() or "AST" in r.errore

    def test_import_requests_bloccato(self, df_vendite):
        codice = "import requests\nprint(requests.get('http://example.com').text)"
        r = esegui_sicuro(codice, df_vendite)
        assert not r.successo

    def test_dunder_import_bloccato(self, df_vendite):
        """__import__("os") deve essere bloccato dall'analisi AST."""
        codice = "os = __import__('os')\nos.system('echo pwned')"
        r = esegui_sicuro(codice, df_vendite)
        assert not r.successo

    def test_importlib_bloccato(self, df_vendite):
        """importlib.import_module deve essere bloccato."""
        codice = "import importlib\nimportlib.import_module('os')"
        r = esegui_sicuro(codice, df_vendite)
        assert not r.successo

    def test_pandas_consentito(self, df_vendite):
        """pandas è nella whitelist e deve funzionare."""
        codice = "import pandas as pd2\nprint(pd2.__version__)"
        r = esegui_sicuro(codice, df_vendite)
        assert r.successo

    def test_numpy_consentito(self, df_vendite):
        codice = "import numpy as np\nprint(np.pi)"
        r = esegui_sicuro(codice, df_vendite)
        assert r.successo

    def test_syntax_error_nel_codice(self, df_vendite):
        codice = "def broken(\nprint('ciao')"
        r = esegui_sicuro(codice, df_vendite)
        assert not r.successo


# ---------------------------------------------------------------------------
# Livello 2 — Blocco socket (air-gap)
# ---------------------------------------------------------------------------

class TestBloccoSocket:
    def test_socket_import_bloccato_da_ast(self, df_vendite):
        """'import socket' è fuori dalla whitelist AST: bloccato prima dell'esecuzione."""
        codice = "import socket\nsocket.socket()\n"
        r = esegui_sicuro(codice, df_vendite)
        assert not r.successo

    def test_blocca_socket_context_manager(self):
        """_blocca_socket deve impedire socket.socket() nel suo scope
        e ripristinare il riferimento originale all'uscita."""
        import socket as _sock
        from secure_executor import _blocca_socket

        originale = _sock.socket

        with _blocca_socket():
            with pytest.raises(PermissionError):
                _sock.socket()   # deve esplodere qui

        # Fuori dal context manager il socket torna funzionante
        assert _sock.socket is originale


# ---------------------------------------------------------------------------
# Livello 3 — Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_loop_infinito_interrotto(self, df_vendite):
        codice = "while True: pass"
        r = esegui_sicuro(codice, df_vendite, timeout_secondi=2)
        assert not r.successo
        assert "TIMEOUT" in r.errore.upper()


# ---------------------------------------------------------------------------
# Test helper _analisi_ast direttamente
# ---------------------------------------------------------------------------

class TestAnalisiAST:
    def test_codice_pulito_restituisce_none(self):
        assert _analisi_ast("x = 1 + 2") is None

    def test_import_vietato_restituisce_nome(self):
        risultato = _analisi_ast("import subprocess")
        assert risultato == "subprocess"

    def test_from_import_vietato(self):
        risultato = _analisi_ast("from subprocess import run")
        assert risultato == "subprocess"

    def test_import_nidificato_vietato(self):
        risultato = _analisi_ast("import os.path")
        assert risultato == "os"

    def test_syntax_error_restituisce_stringa_errore(self):
        risultato = _analisi_ast("def broken(")
        assert risultato is not None
        assert "SyntaxError" in risultato
