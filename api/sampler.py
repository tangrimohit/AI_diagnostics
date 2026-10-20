"""Per-diagnosis system metrics sampler.

Wraps a code block with periodic psutil + nvidia-smi sampling, then computes
peak / average on exit. Every probe fails soft: if psutil is missing or
nvidia-smi returns garbage, the corresponding metric is None rather than
raising. Inference never breaks because the sampler did.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Any, Optional


_SAMPLE_INTERVAL_SECONDS = 1.0
_NVIDIA_SMI_TIMEOUT_SECONDS = 2.0


def _has_nvidia_smi() -> bool:
    return shutil.which("nvidia-smi") is not None


def _read_gpu_once() -> Optional[tuple[float, int]]:
    """Returns (gpu_util_percent, vram_used_mb) or None on any failure."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
            text=True,
        )
        first_line = out.strip().splitlines()[0]
        util_s, mem_s = first_line.split(",")
        return float(util_s.strip()), int(mem_s.strip())
    except Exception:
        return None


def read_system_snapshot() -> dict[str, Optional[float]]:
    """One-shot read for the /admin/system endpoint. Includes total VRAM."""
    snap: dict[str, Optional[float]] = {
        "gpu_util_percent": None,
        "vram_used_mb": None,
        "vram_total_mb": None,
        "cpu_percent": None,
        "ram_used_mb": None,
        "ram_total_mb": None,
    }
    if _has_nvidia_smi():
        try:
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                stderr=subprocess.DEVNULL,
                timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
                text=True,
            )
            first_line = out.strip().splitlines()[0]
            util_s, used_s, tot_s = first_line.split(",")
            snap["gpu_util_percent"] = float(util_s.strip())
            snap["vram_used_mb"] = int(used_s.strip())
            snap["vram_total_mb"] = int(tot_s.strip())
        except Exception:
            pass
    try:
        import psutil  # type: ignore
        snap["cpu_percent"] = float(psutil.cpu_percent(interval=0.2))
        vm = psutil.virtual_memory()
        snap["ram_used_mb"] = int(vm.used // (1024 * 1024))
        snap["ram_total_mb"] = int(vm.total // (1024 * 1024))
    except Exception:
        pass
    return snap


class SystemSampler:
    """Context manager that samples GPU + CPU + RAM in a background thread.

    Use:
        with SystemSampler() as s:
            await ollama.generate(...)
        m = s.metrics()  # {gpu_util_percent_avg, vram_used_mb_peak,
                         #  cpu_percent_avg, ram_used_mb_peak}; any may be None
    """

    def __init__(self, interval_seconds: float = _SAMPLE_INTERVAL_SECONDS) -> None:
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._gpu_utils: list[float] = []
        self._vram_used: list[int] = []
        self._cpu_pct: list[float] = []
        self._ram_used: list[int] = []
        self._psutil = None
        try:
            import psutil  # type: ignore
            self._psutil = psutil
        except ImportError:
            pass
        self._gpu_available = _has_nvidia_smi()

    def __enter__(self) -> "SystemSampler":
        if self._psutil is not None:
            # Prime cpu_percent so the next non-blocking read returns a
            # meaningful delta rather than 0.0.
            try:
                self._psutil.cpu_percent(interval=None)
            except Exception:
                pass
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._gpu_available:
                snap = _read_gpu_once()
                if snap is not None:
                    self._gpu_utils.append(snap[0])
                    self._vram_used.append(snap[1])
            if self._psutil is not None:
                try:
                    self._cpu_pct.append(float(self._psutil.cpu_percent(interval=None)))
                except Exception:
                    pass
                try:
                    vm = self._psutil.virtual_memory()
                    self._ram_used.append(int(vm.used // (1024 * 1024)))
                except Exception:
                    pass
            self._stop.wait(self._interval)

    @staticmethod
    def _avg_float(values: list[float]) -> Optional[float]:
        return round(sum(values) / len(values), 1) if values else None

    @staticmethod
    def _peak_int(values: list[int]) -> Optional[int]:
        return max(values) if values else None

    def metrics(self) -> dict[str, Optional[float]]:
        return {
            "gpu_util_percent_avg": self._avg_float(self._gpu_utils),
            "vram_used_mb_peak":    self._peak_int(self._vram_used),
            "cpu_percent_avg":      self._avg_float(self._cpu_pct),
            "ram_used_mb_peak":     self._peak_int(self._ram_used),
        }
