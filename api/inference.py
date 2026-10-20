"""Inference backend selection for AKARI /diagnose.

Ollama hosts from settings.ollama_hosts are tried in listed order. The first
host that answers /api/version within ollama_health_timeout (and serves the
requested model) handles the request. Today that list holds one entry: the
model server on this machine, reached over the loopback interface. If no host
is usable the request fails. There is no external fallback.

The object returned from generate_diagnosis() mimics the subset of the ollama
GenerateResponse that _run_diagnose reads: `.response` (the JSON string) plus the
optional token / duration counters (None when a backend can't supply them), so
the existing downstream code path is untouched.

Opsec: the user-facing label is opaque ("local-pc" / "remote"); the
precise host and model are recorded in the admin-only audit blob, never the UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx
from ollama import AsyncClient

from api import gpu_watch  # local GPU power-cap watcher (degraded-flag reader)


@dataclass
class InferenceResult:
    response: str                       # JSON string, same contract as ollama .response
    backend: str                        # opaque label: "local-pc" | "remote"
    backend_kind: str                   # "ollama"
    host: Optional[str] = None
    model: Optional[str] = None
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    eval_duration: Optional[int] = None
    prompt_eval_duration: Optional[int] = None


# Reuse one AsyncClient per host (each holds a connection pool).
_clients: dict[str, AsyncClient] = {}


def _client_for(host: str) -> AsyncClient:
    client = _clients.get(host)
    if client is None:
        client = AsyncClient(host=host, timeout=600)
        _clients[host] = client
    return client


def parse_hosts(ollama_hosts: str, ollama_host: str) -> list[str]:
    """Ordered, de-duplicated host list. Falls back to the legacy single host."""
    raw = [h.strip() for h in (ollama_hosts or "").split(",") if h.strip()]
    if not raw:
        raw = [ollama_host]
    seen: set[str] = set()
    out: list[str] = []
    for h in raw:
        h = h.rstrip("/")
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def label_for_host(host: str) -> str:
    h = host.lower()
    if "localhost" in h or "127.0.0.1" in h:
        return "local-pc"
    return "remote"


# Opaque source codes for the private indicator. A = the model server on this
# machine, which is the only node in use. B is reserved for a second node and
# is not configured.
_SRC_CODE = {"local-pc": "A", "remote": "B"}


def src_code(label: Optional[str]) -> str:
    return _SRC_CODE.get(label or "", "?")


async def _ollama_alive(host: str, timeout: float) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as cx:
            r = await cx.get(f"{host}/api/version")
            return r.status_code == 200
    except Exception:
        return False


async def select_ollama_host(hosts: list[str], timeout: float) -> Optional[str]:
    """First reachable host in priority order, or None if all are down."""
    for host in hosts:
        if await _ollama_alive(host, timeout):
            return host
    return None


# Sentinel so generate_diagnosis can tell "no host passed, select one" apart from
# "host explicitly None, meaning nothing is available".
_UNSET = object()


def _model_present(model: str, names: set[str]) -> bool:
    if model in names:
        return True
    if ":" not in model and f"{model}:latest" in names:
        return True
    return False


async def _host_has_model(host: str, model: str, timeout: float) -> bool:
    """True if `host` is reachable AND actually serves `model`. One /api/tags call
    confirms both liveness and model presence."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as cx:
            r = await cx.get(f"{host}/api/tags")
            if r.status_code != 200:
                return False
            names = {m.get("name") for m in r.json().get("models", [])}
            return _model_present(model, names)
    except Exception:
        return False


async def select_backend(settings, model_name: Optional[str] = None) -> Optional[str]:
    """Pick the inference host by priority order + GPU-degraded routing, or None when
    nothing is usable. Split out of generate_diagnosis so /diagnose can run
    engine selection as its own visible phase (Plan A -> B -> C probe). When
    model_name is given, a host qualifies only if it actually serves that model, so a
    primary-only model (e.g. gemma4:e2b on the remote host) is never dispatched to the local PC
    that lacks it; the request fails instead."""
    hosts = parse_hosts(settings.ollama_hosts, settings.ollama_host)
    # If the local PC is power-capped, route around it: a throttled host still
    # answers the probe but then crawls. Prefer the other hosts.
    if gpu_watch.is_local_degraded():
        preferred = [h for h in hosts if label_for_host(h) != "local-pc"]
    else:
        preferred = hosts

    async def usable(host: str) -> bool:
        if model_name:
            return await _host_has_model(host, model_name, settings.ollama_health_timeout)
        return await _ollama_alive(host, settings.ollama_health_timeout)

    for host in preferred:
        if await usable(host):
            return host
    # No preferred host usable: widen to any host (including the capped local)
    # rather than failing the request outright.
    for host in hosts:
        if await usable(host):
            return host
    return None


async def generate_diagnosis(*, prompt: str, model_name: str, options: dict, settings, host=_UNSET, images: Optional[list[str]] = None) -> InferenceResult:
    """Run the diagnosis prompt on the chosen (or first-available) backend.

    `host` may be pre-selected by select_backend() so /diagnose can show engine
    selection as its own phase; when omitted we select here. A str host hits
    Ollama; None means every Ollama host was down.
    `images` is an optional list of raw base64 photos passed to the multimodal
    model (the Ollama models are multimodal).
    Raises RuntimeError only when nothing is available.
    """
    if host is _UNSET:
        host = await select_backend(settings, model_name=model_name)

    if host is not None:
        client = _client_for(host)
        res = await client.generate(
            model=model_name,
            prompt=prompt,
            format="json",
            keep_alive=settings.ollama_keep_alive,
            options=options,
            images=images or None,
        )
        return InferenceResult(
            response=res.response,
            backend=label_for_host(host),
            backend_kind="ollama",
            host=host,
            model=model_name,
            prompt_eval_count=getattr(res, "prompt_eval_count", None),
            eval_count=getattr(res, "eval_count", None),
            eval_duration=getattr(res, "eval_duration", None),
            prompt_eval_duration=getattr(res, "prompt_eval_duration", None),
        )

    hosts = parse_hosts(settings.ollama_hosts, settings.ollama_host)
    raise RuntimeError(
        f"No inference backend available: Ollama hosts unreachable "
        f"({', '.join(hosts)})."
    )


async def backends_status(settings) -> dict:
    """Snapshot of every configured backend for /health. Source identity is coded
    (A/B) so this endpoint never reveals which host is in use."""
    hosts = parse_hosts(settings.ollama_hosts, settings.ollama_host)
    sources = []
    for host in hosts:
        label = label_for_host(host)
        sources.append({
            "host": host,
            "code": src_code(label),
            "alive": await _ollama_alive(host, settings.ollama_health_timeout),
        })
    active = next((s for s in sources if s["alive"]), None)
    serving = active["code"] if active else "none"
    return {"sources": sources, "serving": serving}
