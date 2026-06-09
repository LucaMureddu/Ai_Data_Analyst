# =============================================================================
# Data-Whisperer.spec
# PyInstaller spec file — macOS Apple Silicon (arm64)
#
# Modalità: --onedir + BUNDLE (.app)
# Il file modello-locale.gguf rimane ESTERNO al bundle, nella stessa cartella.
#
# Comando per ricompilare (dopo modifiche al codice):
#   pyinstaller Data-Whisperer.spec
# =============================================================================

block_cipher = None

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    collect_all,
)

# ── CustomTkinter: assets (temi JSON, immagini, font) ─────────────────────────
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")

# ── llama_cpp: librerie dinamiche Metal + BLAS ────────────────────────────────
llama_datas, llama_binaries, llama_hiddenimports = collect_all("llama_cpp")

# ── matplotlib: dati locali (font, stili, colormap) ──────────────────────────
mpl_datas = collect_data_files("matplotlib")

# ── openpyxl: schemi XML necessari per leggere .xlsx ─────────────────────────
openpyxl_datas = collect_data_files("openpyxl")

# ── chardet: charset tables ───────────────────────────────────────────────────
chardet_datas = collect_data_files("chardet")

# =============================================================================
# ANALYSIS
# =============================================================================

a = Analysis(
    ["app_ui.py"],
    pathex=["."],
    binaries=ctk_binaries + llama_binaries,
    datas=(
        ctk_datas
        + llama_datas
        + mpl_datas
        + openpyxl_datas
        + chardet_datas
        # Moduli interni Data-Whisperer (inclusi come sorgente)
        + [
            ("hardware_detector.py", "."),
            ("data_loader.py",       "."),
            ("secure_executor.py",   "."),
            ("core_engine.py",       "."),
        ]
    ),
    hiddenimports=[
        # ── UI ────────────────────────────────────────────────────────
        "customtkinter",
        *ctk_hiddenimports,
        # ── LLM ──────────────────────────────────────────────────────
        "llama_cpp",
        *llama_hiddenimports,
        # ── Pandas (i .so/_pyd interni non vengono rilevati automaticamente)
        "pandas",
        "pandas._libs",
        "pandas._libs.tslibs",
        "pandas._libs.tslibs.timedeltas",
        "pandas._libs.tslibs.np_datetime",
        "pandas._libs.tslibs.nattype",
        "pandas._libs.tslibs.parsing",
        "pandas._libs.tslibs.timestamps",
        "pandas._libs.tslibs.offsets",
        "pandas._libs.tslibs.period",
        "pandas._libs.hashtable",
        "pandas._libs.index",
        "pandas._libs.internals",
        "pandas._libs.interval",
        "pandas._libs.join",
        "pandas._libs.lib",
        "pandas._libs.missing",
        "pandas._libs.ops",
        "pandas._libs.reshape",
        "pandas._libs.skiplist",
        "pandas._libs.sparse",
        "pandas._libs.writers",
        "pandas.io.formats.style",
        "pandas.core.arrays.integer",
        "pandas.core.arrays.string_",
        # ── openpyxl ─────────────────────────────────────────────────
        "openpyxl",
        "openpyxl.cell._cell",
        "openpyxl.styles.stylesheet",
        "openpyxl.workbook",
        "openpyxl.worksheet._read_only",
        "openpyxl.worksheet.worksheet",
        # ── numpy ────────────────────────────────────────────────────
        "numpy",
        "numpy.core._methods",
        "numpy.lib.format",
        "numpy.random",
        # ── matplotlib ───────────────────────────────────────────────
        "matplotlib",
        "matplotlib.backends.backend_agg",   # backend non interattivo
        "matplotlib.figure",
        "matplotlib.pyplot",
        # ── altre ────────────────────────────────────────────────────
        "chardet",
        "chardet.universaldetector",
        "psutil",
        "PIL",                               # pillow (usato da customtkinter)
        "PIL.Image",
        # ── moduli interni Data-Whisperer ─────────────────────────────
        "hardware_detector",
        "data_loader",
        "secure_executor",
        "core_engine",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Riduci il bundle escludendo ciò che non usiamo mai
        "tkinter.test",
        "test",
        "unittest",
        "distutils",
        "setuptools",
        "email",
        # "html",    # rimosso: pandas lo importa internamente all'avvio
        # "http",    # rimosso: pandas lo importa internamente all'avvio
        # "urllib",  # rimosso: pandas lo importa internamente all'avvio
        "xmlrpc",
        "ftplib",
        "smtplib",
        "imaplib",
        "poplib",
        "telnetlib",
        "socketserver",
        # "sqlite3",  # rimosso: usato dal modulo di cache interno di llama_cpp
        "doctest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# =============================================================================
# PYZ — archivio bytecode compresso
# =============================================================================

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# =============================================================================
# EXE — binario eseguibile (SENZA console, windowed)
# =============================================================================

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,    # i binari vanno in COLLECT, non embedded nell'exe
    name="Data-Whisperer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX rovina i binari Metal — mai abilitare
    console=False,            # nessun terminale nero in background
    disable_windowed_traceback=False,
    target_arch="arm64",      # Apple Silicon M-series
    codesign_identity=None,
    entitlements_file=None,
)

# =============================================================================
# COLLECT — directory onedir con tutti i binari/dati separati
# =============================================================================

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Data-Whisperer",
)

# =============================================================================
# BUNDLE — pacchetto .app nativo macOS
# =============================================================================

app = BUNDLE(
    coll,
    name="Data-Whisperer.app",
    icon=None,                # sostituisci con "icon.icns" se disponibile
    bundle_identifier="com.datawhisperer.offline",
    info_plist={
        "CFBundleDisplayName":        "Data-Whisperer",
        "CFBundleName":               "Data-Whisperer",
        "CFBundleVersion":            "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable":    True,
        "NSRequiresAquaSystemAppearance": False,   # dark mode nativo
        "LSMinimumSystemVersion":     "12.0",      # macOS Monterey+
        "NSHumanReadableCopyright":   "© 2025 Data-Whisperer",
        # Permessi necessari per leggere file utente (CSV/Excel)
        "NSDocumentsFolderUsageDescription": "Accesso ai file dati dell'utente.",
        "NSDownloadsFolderUsageDescription": "Accesso ai file scaricati.",
    },
)
