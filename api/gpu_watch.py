"""GPU power-cap watcher for AKARI.

Closes a real gap in the failover path. The Ollama liveness probe in
inference.py only checks /api/version, which a throttled GPU still answers
instantly (the Ollama process is alive, it is just pinned to ~10W). The request
then picks the crippled local host and hangs up to the generate timeout (600s)
with no fallback. This watcher detects the throttle directly off nvidia-smi and
flips an in-memory "local degraded" flag so inference.py routes around the local PC
to Plan B/C until the cap clears.

The recurring fault on this hardware (RTX 3050 4GB): enforced power limit drops
to ~10W / P8 / 210MHz (normal 35-40W), throttle-reason mask 0x24 at a cold ~52C
(phantom SwThermalSlowdown). No software lifts it (nvidia-smi -pl is blocked,
a service bounce does not work); only a reboot does. So this watcher does NOT
try to remediate. Its two jobs are: (1) inform the admin, (2) fail over.

Two actions on a confirmed throttle: an admin alert (via the caller's callback)
and the degraded flag. Recovery (cap cleared without us) restores local routing
and fires a recovery alert.

Config (env, read live so a restart is not needed to retune):
  AKARI_GPU_WATCH_ENABLED   "true" (default) to run the watcher.
  AKARI_GPU_POWER_FLOOR_W   throttle trips below this many watts (default 20).
  AKARI_GPU_POLL_SECONDS    seconds between reads (default 30).
  AKARI_GPU_DEBOUNCE        consecutive reads needed to flip state (default 2).

Opsec: this only ever feeds the admin channel (alert email + /admin/health).
Nothing here touches the public /health or any user-facing surface.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

_NVIDIA_SMI_TIMEOUT_SECONDS = 2.0


# ---------------- config ----------------

def _enabled() -> bool:
    return os.environ.get("AKARI_GPU_WATCH_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _power_floor_w() -> float:
    try:
        return float(os.environ.get("AKARI_GPU_POWER_FLOOR_W", "20"))
    except ValueError:
        return 20.0


def _poll_seconds() -> int:
    try:
        return max(5, int(os.environ.get("AKARI_GPU_POLL_SECONDS", "30")))
    except ValueError:
        return 30


def _debounce() -> int:
    try:
        return max(1, int(os.environ.get("AKARI_GPU_DEBOUNCE", "2")))
    except ValueError:
        return 2


def _has_nvidia_smi() -> bool:
    return shutil.which("nvidia-smi") is not None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------- shared state ----------------
# Module-global so inference.py can read is_local_degraded() without importing
# main.py (which would be a circular import). main.py owns the loop that writes
# it; inference.py is a pure reader.

_status: dict[str, Any] = {
    "available": False,    # nvidia-smi present and readable on this host
    "degraded": False,     # local GPU is currently power-capped (debounced)
    "since": None,         # iso ts the current degraded/healthy state began
    "episode": 0,          # count of throttle episodes since boot
    "last": None,          # last raw reading dict
    "floor_w": _power_floor_w(),
}

_thr_count = 0
_ok_count = 0


def is_local_degraded() -> bool:
    """True only when we have positively confirmed a power cap. Any uncertainty
    (no GPU, unreadable nvidia-smi) returns False so we never falsely strand the
    local host."""
    return bool(_status["available"] and _status["degraded"])


def snapshot() -> dict[str, Any]:
    """Admin-only view for /admin/health."""
    return {
        "available": _status["available"],
        "degraded": _status["degraded"],
        "since": _status["since"],
        "episodes": _status["episode"],
        "floor_w": _status["floor_w"],
        "last": _status["last"],
    }


# ---------------- reading ----------------

def read_gpu_state() -> Optional[dict[str, Any]]:
    """One nvidia-smi read. Returns a reading dict or None on any failure.

    enforced.power.limit is the signal that matters: the recurring fault pins it
    to ~10W (normal 35-40). The other fields are context for the admin alert.
    """
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=enforced.power.limit,power.draw,pstate,"
                "temperature.gpu,clocks_throttle_reasons.active",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
            text=True,
        )
        line = out.strip().splitlines()[0]
        limit_s, draw_s, pstate_s, temp_s, reasons_s = (p.strip() for p in line.split(","))
        return {
            "power_limit_w": float(limit_s),
            "power_draw_w": _safe_float(draw_s),
            "pstate": pstate_s,
            "temp_c": _safe_float(temp_s),
            "throttle_reasons": reasons_s,
            "ts": _now_iso(),
        }
    except Exception:
        return None


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ---------------- loop ----------------

async def watch_loop(alert_cb: Optional[Callable[[str, dict], None]] = None) -> None:
    """Poll the GPU and maintain the degraded flag. Fires alert_cb(kind, snapshot)
    on a state transition: kind="throttle" when a cap is confirmed, "recover"
    when it clears. alert_cb must be exception-safe and quick (callers offload
    the actual send to a thread).

    Runs in the FastAPI event loop, started from startup like the other loops.
    Reads are blocking subprocess calls but tiny (~10-20ms) and gated by a 2s
    timeout, so we keep them inline rather than thread-hopping every tick.
    """
    import asyncio

    global _thr_count, _ok_count

    if not _enabled():
        print("[gpu-watch] disabled via AKARI_GPU_WATCH_ENABLED", flush=True)
        return
    if not _has_nvidia_smi():
        print("[gpu-watch] nvidia-smi not found; watcher idle (non-GPU host)", flush=True)
        _status["available"] = False
        return

    debounce = _debounce()
    floor = _power_floor_w()
    _status["floor_w"] = floor
    _status["since"] = _now_iso()
    print(
        f"[gpu-watch] loop start: floor={floor}W poll={_poll_seconds()}s debounce={debounce}",
        flush=True,
    )

    while True:
        try:
            reading = await asyncio.to_thread(read_gpu_state)
            if reading is None:
                # Transient nvidia-smi failure. Leave the flag as-is (do not
                # strand the host on a hiccup), but mark availability so the
                # admin view shows the gap.
                _status["available"] = False
            else:
                _status["available"] = True
                _status["last"] = reading
                capped = reading["power_limit_w"] <= floor

                if capped:
                    _thr_count += 1
                    _ok_count = 0
                else:
                    _ok_count += 1
                    _thr_count = 0

                if not _status["degraded"] and _thr_count >= debounce:
                    _status["degraded"] = True
                    _status["episode"] += 1
                    _status["since"] = _now_iso()
                    print(
                        f"[gpu-watch] THROTTLE confirmed (episode {_status['episode']}): "
                        f"{reading['power_limit_w']}W / {reading['pstate']} / "
                        f"{reading['temp_c']}C / reasons={reading['throttle_reasons']} "
                        f"-> failing over to Plan B/C",
                        flush=True,
                    )
                    _fire(alert_cb, "throttle")
                elif _status["degraded"] and _ok_count >= debounce:
                    _status["degraded"] = False
                    _status["since"] = _now_iso()
                    print(
                        f"[gpu-watch] RECOVERED: {reading['power_limit_w']}W / "
                        f"{reading['pstate']} -> local inference restored",
                        flush=True,
                    )
                    _fire(alert_cb, "recover")
        except Exception as e:
            print(f"[gpu-watch] loop error: {type(e).__name__}: {e}", flush=True)

        await asyncio.sleep(_poll_seconds())


def _fire(alert_cb: Optional[Callable[[str, dict], None]], kind: str) -> None:
    if alert_cb is None:
        return
    try:
        alert_cb(kind, snapshot())
    except Exception as e:
        print(f"[gpu-watch] alert callback error: {e}", flush=True)
