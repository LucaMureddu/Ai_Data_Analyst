"""
build_script.py
---------------
Automatizza la compilazione di Data-Whisperer per macOS Apple Silicon.

Cosa fa:
  1. Verifica che PyInstaller sia installato (e lo installa se manca)
  2. Pulisce le build precedenti (dist/ e build/)
  3. Lancia PyInstaller con Data-Whisperer.spec
  4. Organizza l'output in una cartella "distribuzione/" pronta per la chiavetta
  5. Stampa un riepilogo finale con le istruzioni di consegna

Uso:
  python build_script.py

Durata stimata: 2-5 minuti (dipende dalla velocità del disco).
"""

import sys
import shutil
import subprocess
import platform
from pathlib import Path

# =============================================================================
# CONFIGURAZIONE
# =============================================================================

PROGETTO_DIR  = Path(__file__).parent.resolve()
SPEC_FILE     = PROGETTO_DIR / "Data-Whisperer.spec"
DIST_DIR      = PROGETTO_DIR / "dist"
BUILD_DIR     = PROGETTO_DIR / "build"
OUTPUT_DIR    = PROGETTO_DIR / "distribuzione"   # cartella finale per la chiavetta
APP_NAME      = "Data-Whisperer"
MODELLO_GGUF  = "modello-locale.gguf"

# =============================================================================
# UTILITY
# =============================================================================

def stampa(msg: str, livello: str = "info"):
    simboli = {"info": "·", "ok": "✔", "warn": "⚠", "err": "✖", "step": "▶"}
    print(f"  {simboli.get(livello, '·')}  {msg}")


def esegui(cmd: list[str], descrizione: str) -> bool:
    """Esegue un comando di shell e ritorna True se ha successo."""
    stampa(descrizione, "step")
    result = subprocess.run(cmd, cwd=str(PROGETTO_DIR))
    if result.returncode != 0:
        stampa(f"Comando fallito (exit {result.returncode}): {' '.join(cmd)}", "err")
        return False
    return True


# =============================================================================
# STEP 1: VERIFICA / INSTALLA PYINSTALLER
# =============================================================================

def verifica_pyinstaller():
    try:
        import PyInstaller
        stampa(f"PyInstaller {PyInstaller.__version__} già installato.", "ok")
    except ImportError:
        stampa("PyInstaller non trovato. Installazione in corso...", "warn")
        ok = esegui(
            [sys.executable, "-m", "pip", "install", "pyinstaller", "--break-system-packages"],
            "pip install pyinstaller"
        )
        if not ok:
            stampa("Impossibile installare PyInstaller. Abortito.", "err")
            sys.exit(1)
        stampa("PyInstaller installato.", "ok")


# =============================================================================
# STEP 2: PULIZIA BUILD PRECEDENTE
# =============================================================================

def pulisci_build():
    for cartella in (DIST_DIR, BUILD_DIR, OUTPUT_DIR):
        if cartella.exists():
            shutil.rmtree(cartella)
            stampa(f"Rimossa: {cartella.name}/", "ok")


# =============================================================================
# STEP 3: COMPILAZIONE CON SPEC FILE
# =============================================================================

def compila():
    if not SPEC_FILE.exists():
        stampa(f"File .spec non trovato: {SPEC_FILE}", "err")
        sys.exit(1)

    ok = esegui(
        [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm"],
        f"pyinstaller {SPEC_FILE.name}"
    )
    if not ok:
        stampa("Compilazione fallita. Leggi l'output sopra per i dettagli.", "err")
        sys.exit(1)

    app_path = DIST_DIR / f"{APP_NAME}.app"
    if not app_path.exists():
        stampa(f".app non trovata in dist/: {app_path}", "err")
        sys.exit(1)

    stampa(f"Bundle creato: {app_path}", "ok")
    return app_path


# =============================================================================
# STEP 4: ORGANIZZA LA DISTRIBUZIONE
# =============================================================================

def organizza_distribuzione(app_path: Path):
    """
    Crea la struttura finale per la chiavetta USB:

      distribuzione/
        ├── Data-Whisperer.app     ← l'app cliccabile
        ├── modello-locale.gguf    ← COPIATO dalla cartella progetto (se esiste)
        └── ISTRUZIONI_AVVIO.txt   ← guida per l'utente finale
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Copia il bundle .app
    dest_app = OUTPUT_DIR / f"{APP_NAME}.app"
    shutil.copytree(str(app_path), str(dest_app), symlinks=True)
    stampa(f"App copiata in: distribuzione/{APP_NAME}.app", "ok")

    # Copia il modello GGUF se presente nel progetto
    src_modello = PROGETTO_DIR / MODELLO_GGUF
    if src_modello.exists():
        dest_modello = OUTPUT_DIR / MODELLO_GGUF
        stampa(f"Copia modello GGUF ({src_modello.stat().st_size / 1e9:.2f} GB)...", "step")
        shutil.copy2(str(src_modello), str(dest_modello))
        stampa(f"Modello copiato: distribuzione/{MODELLO_GGUF}", "ok")
    else:
        stampa(
            f"ATTENZIONE: {MODELLO_GGUF} non trovato nella cartella progetto.\n"
            f"           Copia manualmente il file GGUF in:\n"
            f"           {OUTPUT_DIR}/",
            "warn"
        )
        # Crea un placeholder visibile
        placeholder = OUTPUT_DIR / f"METTI_QUI_{MODELLO_GGUF}.txt"
        placeholder.write_text(
            f"Posiziona qui il file '{MODELLO_GGUF}'\n"
            f"accanto a Data-Whisperer.app prima di consegnare la chiavetta.\n"
        )

    # Crea le istruzioni per l'utente finale
    istruzioni = OUTPUT_DIR / "ISTRUZIONI_AVVIO.txt"
    istruzioni.write_text(
        "════════════════════════════════════════════\n"
        "  DATA-WHISPERER  •  Analista AI Offline\n"
        "════════════════════════════════════════════\n\n"
        "COME AVVIARE:\n"
        "  1. Apri questa cartella.\n"
        "  2. Fai doppio clic su 'Data-Whisperer.app'.\n"
        "  3. Se macOS mostra un avviso di sicurezza:\n"
        "       Vai in Impostazioni → Privacy e sicurezza → clicca 'Apri comunque'.\n\n"
        "STRUTTURA NECESSARIA (non spostare nulla):\n"
        "  ├── Data-Whisperer.app\n"
        "  └── modello-locale.gguf   ← deve stare QUI accanto all'app\n\n"
        "UTILIZZO:\n"
        "  1. Clicca 'Seleziona File' e scegli il tuo CSV o Excel.\n"
        "  2. Scrivi la tua domanda in linguaggio naturale.\n"
        "  3. Premi Invio o 'Analizza'.\n"
        "  4. I grafici vengono salvati automaticamente accanto al file dati.\n\n"
        "PRIVACY:\n"
        "  Nessun dato lascia il tuo computer. Zero connessioni internet.\n"
        "  Il modello AI gira interamente in locale.\n",
        encoding="utf-8"
    )
    stampa("Istruzioni create: distribuzione/ISTRUZIONI_AVVIO.txt", "ok")


# =============================================================================
# STEP 5: RIEPILOGO FINALE
# =============================================================================

def riepilogo_finale():
    print()
    print("  " + "═" * 54)
    print("  ✔  BUILD COMPLETATA")
    print("  " + "═" * 54)

    # Dimensione cartella
    size_bytes = sum(f.stat().st_size for f in OUTPUT_DIR.rglob("*") if f.is_file())
    size_gb    = size_bytes / 1e9
    stampa(f"Dimensione totale distribuzione: {size_gb:.2f} GB", "ok")
    stampa(f"Cartella output: {OUTPUT_DIR}", "ok")

    print()
    print("  PROSSIMI PASSI:")
    print("  ① Verifica che 'modello-locale.gguf' sia in distribuzione/")
    print("  ② Testa l'app: apri distribuzione/Data-Whisperer.app")
    print("  ③ Se macOS blocca l'app (Gatekeeper):")
    print("       xattr -cr distribuzione/Data-Whisperer.app")
    print("  ④ Copia l'intera cartella 'distribuzione/' sulla chiavetta USB/NVMe")
    print()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print()
    print("  ══════════════════════════════════════════════")
    print("    Data-Whisperer  •  Build Script  •  macOS")
    print("  ══════════════════════════════════════════════")
    print()

    # Verifica piattaforma
    if platform.system() != "Darwin":
        stampa("Attenzione: questo script è ottimizzato per macOS. Procedo comunque.", "warn")

    verifica_pyinstaller()
    pulisci_build()
    app_path = compila()
    organizza_distribuzione(app_path)
    riepilogo_finale()
