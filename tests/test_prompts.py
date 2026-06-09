"""
test_prompts.py
---------------
Verifica che tutti i prompt siano presenti, non vuoti e
contengano le keyword chiave che ne definiscono il comportamento.
"""
import pytest

from prompts import (
    PROMPT_VIGILE,
    SP_VALIDATORE,
    SP_ARCHITETTO,
    SP_DATTILOGRAFO,
    SP_ISPETTORE,
    PROMPT_STILISTA,
    PROMPT_CONCIERGE,
)

ALL_PROMPTS = [
    ("PROMPT_VIGILE",    PROMPT_VIGILE),
    ("SP_VALIDATORE",    SP_VALIDATORE),
    ("SP_ARCHITETTO",    SP_ARCHITETTO),
    ("SP_DATTILOGRAFO",  SP_DATTILOGRAFO),
    ("SP_ISPETTORE",     SP_ISPETTORE),
    ("PROMPT_STILISTA",  PROMPT_STILISTA),
    ("PROMPT_CONCIERGE", PROMPT_CONCIERGE),
]


@pytest.mark.parametrize("nome,testo", ALL_PROMPTS)
def test_prompt_non_vuoto(nome, testo):
    assert isinstance(testo, str)
    assert len(testo) > 100, f"{nome} sembra troppo corto"


def test_vigile_contiene_categorie():
    for categoria in ("NUOVA", "MODIFICA", "INFO"):
        assert categoria in PROMPT_VIGILE

def test_validatore_contiene_ok_ed_errore():
    assert "OK" in SP_VALIDATORE
    assert "ERRORE" in SP_VALIDATORE

def test_dattilografo_contiene_esempi():
    assert "ESEMPIO" in SP_DATTILOGRAFO
    assert "df[" in SP_DATTILOGRAFO

def test_ispettore_non_contiene_markdown():
    """L'ispettore non deve chiedere markdown nel codice output."""
    assert "```" not in SP_ISPETTORE

def test_stilista_non_tocca_pandas():
    assert "Pandas" in PROMPT_STILISTA or "pandas" in PROMPT_STILISTA.lower()
    assert "NON modificare" in PROMPT_STILISTA

def test_concierge_e_offline():
    assert "offline" in PROMPT_CONCIERGE.lower() or "rete" in PROMPT_CONCIERGE.lower()
