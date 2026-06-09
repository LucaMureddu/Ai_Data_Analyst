"""
test_core_engine_utils.py
-------------------------
Test unitari per le funzioni di utilità di core_engine.py
che NON richiedono un modello LLM caricato in RAM.

Copre: _pulisci_codice, trova_modelli, _app_data_dir.
llama_cpp è mockato in conftest.py.
"""
import os
import sys
import tempfile

import pytest

# conftest.py ha già mockato llama_cpp — possiamo importare core_engine
import core_engine
from core_engine import _pulisci_codice, trova_modelli, _app_data_dir


# ---------------------------------------------------------------------------
# _pulisci_codice
# ---------------------------------------------------------------------------

class TestPulisciCodice:
    def test_rimuove_markdown_python(self):
        codice = "```python\nprint('ciao')\n```"
        assert _pulisci_codice(codice) == "print('ciao')"

    def test_rimuove_markdown_generico(self):
        codice = "```\nprint('ciao')\n```"
        assert _pulisci_codice(codice) == "print('ciao')"

    def test_rimuove_plt_show(self):
        codice = "plt.bar(x, y)\nplt.show()\nplt.title('T')"
        risultato = _pulisci_codice(codice)
        assert "plt.show()" not in risultato
        assert "plt.bar" in risultato

    def test_rimuove_plt_show_indentato(self):
        codice = "if True:\n    plt.show()\nplt.title('T')"
        assert "plt.show()" not in _pulisci_codice(codice)

    def test_rimuove_righe_commento(self):
        codice = "# Questo è un commento\nprint('ok')\n# Altro commento"
        risultato = _pulisci_codice(codice)
        assert "#" not in risultato
        assert "print('ok')" in risultato

    def test_mantiene_inline_comment(self):
        """Un commento inline (codice + # nota) NON deve essere rimosso."""
        codice = "x = 42  # valore di default"
        assert _pulisci_codice(codice) == "x = 42  # valore di default"

    def test_comprime_righe_vuote_consecutive(self):
        codice = "a = 1\n\n\n\nb = 2"
        risultato = _pulisci_codice(codice)
        assert "\n\n\n" not in risultato

    def test_codice_gia_pulito_invariato(self):
        codice = "totale = df['Fatturato'].sum()\nprint(totale)"
        assert _pulisci_codice(codice) == codice

    def test_stringa_vuota_restituisce_vuoto(self):
        assert _pulisci_codice("") == ""

    def test_solo_markdown_restituisce_vuoto(self):
        assert _pulisci_codice("```python\n```") == ""


# ---------------------------------------------------------------------------
# trova_modelli
# ---------------------------------------------------------------------------

class TestTrovaModelli:
    def test_cartella_vuota(self, tmp_path):
        assert trova_modelli(str(tmp_path)) == []

    def test_trova_file_gguf(self, tmp_path):
        modello = tmp_path / "mio_modello.gguf"
        modello.write_bytes(b"\x00" * 10)
        risultato = trova_modelli(str(tmp_path))
        assert len(risultato) == 1
        assert risultato[0] == str(modello)

    def test_ignora_file_non_gguf(self, tmp_path):
        (tmp_path / "readme.txt").write_text("ciao")
        (tmp_path / "config.json").write_text("{}")
        assert trova_modelli(str(tmp_path)) == []

    def test_ordine_per_dimensione_decrescente(self, tmp_path):
        piccolo = tmp_path / "piccolo.gguf"
        grande  = tmp_path / "grande.gguf"
        piccolo.write_bytes(b"\x00" * 100)
        grande.write_bytes(b"\x00" * 1000)
        risultato = trova_modelli(str(tmp_path))
        assert risultato[0] == str(grande)
        assert risultato[1] == str(piccolo)

    def test_cartella_inesistente_non_crasha(self):
        risultato = trova_modelli("/percorso/che/non/esiste/mai")
        assert risultato == []


# ---------------------------------------------------------------------------
# _app_data_dir
# ---------------------------------------------------------------------------

class TestAppDataDir:
    def test_restituisce_stringa(self):
        assert isinstance(_app_data_dir(), str)

    def test_directory_creata(self):
        path = _app_data_dir()
        assert os.path.isdir(path)

    def test_contiene_nome_app(self):
        path = _app_data_dir()
        assert "Data-Whisperer" in path
