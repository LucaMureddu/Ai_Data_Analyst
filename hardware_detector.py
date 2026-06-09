# =============================================================================
# INSTALLAZIONE DIPENDENZE (eseguire una volta nel terminale)
# =============================================================================
# pip install psutil --break-system-packages
# =============================================================================

"""
hardware_detector.py
--------------------
Rileva il profilo hardware dell'host e restituisce i parametri ottimali
per llama-cpp-python (n_gpu_layers, n_ctx, n_threads).
Zero chiamate di rete. Zero dipendenze esterne oltre psutil.
"""

import platform
import struct
import subprocess
import sys
from dataclasses import dataclass

import psutil


# =============================================================================
# STRUTTURA PROFILO
# =============================================================================

@dataclass
class HardwareProfilo:
    architettura: str        # "apple_silicon" | "x86_cuda" | "x86_cpu"
    ram_totale_gb: float
    ram_disponibile_gb: float
    cpu_cores: int
    n_gpu_layers: int        # layer da caricare sulla GPU (-1 = tutti, 0 = CPU puro)
    n_ctx: int               # dimensione contesto in token
    n_threads: int           # thread CPU per l'inferenza
    note: str                # descrizione human-readable del profilo


# =============================================================================
# RILEVAMENTO ARCHITETTURA
# =============================================================================

def _is_apple_silicon() -> bool:
    """True se siamo su macOS con chip ARM (M1/M2/M3/M4)."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def _has_nvidia_gpu() -> bool:
    """True se nvidia-smi risponde correttamente (Linux/Windows)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _vram_nvidia_gb() -> float:
    """Ritorna la VRAM della prima GPU Nvidia in GB, oppure 0.0."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            mb = float(result.stdout.strip().splitlines()[0])
            return mb / 1024.0
    except Exception:
        pass
    return 0.0


# =============================================================================
# LOGICA DI CALIBRAZIONE
# =============================================================================

def _calibra_apple_silicon(ram_gb: float, cpu_cores: int) -> HardwareProfilo:
    """
    Su Apple Silicon la GPU e la CPU condividono la RAM unificata (UMA).
    Possiamo caricare tutti i layer sulla GPU Metal quasi sempre.
    Regoliamo n_ctx in base alla RAM disponibile.
    """
    if ram_gb >= 32:
        n_ctx, n_gpu = 8192, -1
        note = f"Apple Silicon {ram_gb:.0f}GB — Metal full offload, contesto esteso"
    elif ram_gb >= 16:
        n_ctx, n_gpu = 4096, -1
        note = f"Apple Silicon {ram_gb:.0f}GB — Metal full offload, contesto standard"
    else:
        # 8 GB: pipeline multi-agente richiede almeno 3072 per il Dattilografo
        # (SP_DATTILOGRAFO ~600 token + schema + piano ≈ 1500 token input)
        n_ctx, n_gpu = 3072, -1
        note = f"Apple Silicon {ram_gb:.0f}GB — Metal full offload, contesto adeguato pipeline"

    return HardwareProfilo(
        architettura="apple_silicon",
        ram_totale_gb=ram_gb,
        ram_disponibile_gb=psutil.virtual_memory().available / 1e9,
        cpu_cores=cpu_cores,
        n_gpu_layers=n_gpu,
        n_ctx=n_ctx,
        n_threads=cpu_cores,
        note=note,
    )


def _calibra_nvidia(ram_gb: float, vram_gb: float, cpu_cores: int) -> HardwareProfilo:
    """
    GPU Nvidia discreta: stimiamo quanti layer entrano in VRAM.
    Regola empirica: ~0.13 GB per layer per un modello 7-8B Q4.
    """
    GB_PER_LAYER = 0.13
    layer_max    = int(vram_gb / GB_PER_LAYER)
    # Cap a 40 (numero di layer tipico di Llama 3 8B)
    n_gpu = min(layer_max, 40)

    if vram_gb >= 8:
        n_ctx = 4096
        note = f"Nvidia {vram_gb:.1f}GB VRAM — {n_gpu} layer GPU, contesto standard"
    else:
        n_ctx = 2048
        note = f"Nvidia {vram_gb:.1f}GB VRAM — {n_gpu} layer GPU, contesto ridotto"

    return HardwareProfilo(
        architettura="x86_cuda",
        ram_totale_gb=ram_gb,
        ram_disponibile_gb=psutil.virtual_memory().available / 1e9,
        cpu_cores=cpu_cores,
        n_gpu_layers=n_gpu,
        n_ctx=n_ctx,
        n_threads=cpu_cores,
        note=note,
    )


def _calibra_cpu_only(ram_gb: float, cpu_cores: int) -> HardwareProfilo:
    """
    CPU pura (PC aziendali, laptop senza GPU discreta).
    Zero layer sulla GPU, contesto e thread aggressivamente conservativi.
    """
    # Riserviamo almeno 2 GB al sistema operativo
    ram_utile = max(ram_gb - 2.0, 1.0)

    if ram_utile >= 10:
        n_ctx    = 3072   # pipeline multi-agente: Dattilografo richiede ~1500 token input
        n_thread = min(cpu_cores, 8)
        note = f"CPU only {ram_gb:.0f}GB RAM — inferenza su {n_thread} thread"
    elif ram_utile >= 5:
        n_ctx    = 2048   # minimo sicuro per SP_DATTILOGRAFO + schema + piano
        n_thread = min(cpu_cores, 4)
        note = f"CPU only {ram_gb:.0f}GB RAM — contesto standard, {n_thread} thread"
    else:
        n_ctx    = 2048   # mai scendere sotto: il Dattilografo troncato genera codice errato
        n_thread = min(cpu_cores, 2)
        note = f"CPU only {ram_gb:.0f}GB RAM CRITICA — contesto minimo garantito"

    return HardwareProfilo(
        architettura="x86_cpu",
        ram_totale_gb=ram_gb,
        ram_disponibile_gb=psutil.virtual_memory().available / 1e9,
        cpu_cores=cpu_cores,
        n_gpu_layers=0,
        n_ctx=n_ctx,
        n_threads=n_thread,
        note=note,
    )


# =============================================================================
# FUNZIONE PUBBLICA
# =============================================================================

def rileva_hardware(verbose: bool = True) -> HardwareProfilo:
    """
    Punto di ingresso principale.
    Rileva automaticamente il profilo hardware e restituisce i parametri
    ottimali per llama-cpp-python.

    Uso:
        from hardware_detector import rileva_hardware
        profilo = rileva_hardware()
        llm = Llama(model_path=..., n_gpu_layers=profilo.n_gpu_layers,
                    n_ctx=profilo.n_ctx, n_threads=profilo.n_threads)
    """
    mem       = psutil.virtual_memory()
    ram_gb    = mem.total / 1e9
    cpu_cores = psutil.cpu_count(logical=False) or 2

    if _is_apple_silicon():
        profilo = _calibra_apple_silicon(ram_gb, cpu_cores)
    elif _has_nvidia_gpu():
        vram = _vram_nvidia_gb()
        profilo = _calibra_nvidia(ram_gb, vram, cpu_cores)
    else:
        profilo = _calibra_cpu_only(ram_gb, cpu_cores)

    if verbose:
        _stampa_report(profilo)

    return profilo


def _stampa_report(p: HardwareProfilo):
    linea = "─" * 52
    print(linea)
    print("  Data-Whisperer  •  Hardware Detector")
    print(linea)
    print(f"  OS            : {platform.system()} {platform.release()}")
    print(f"  Arch          : {p.architettura}")
    print(f"  RAM totale    : {p.ram_totale_gb:.1f} GB")
    print(f"  RAM libera    : {p.ram_disponibile_gb:.1f} GB")
    print(f"  CPU core      : {p.cpu_cores}")
    print(linea)
    print(f"  n_gpu_layers  : {p.n_gpu_layers}  (-1 = tutti su GPU)")
    print(f"  n_ctx         : {p.n_ctx} token")
    print(f"  n_threads     : {p.n_threads}")
    print(linea)
    print(f"  Profilo       : {p.note}")
    print(linea)


# =============================================================================
# TEST STANDALONE
# =============================================================================

if __name__ == "__main__":
    profilo = rileva_hardware(verbose=True)
    sys.exit(0)
