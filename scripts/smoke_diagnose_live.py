"""Live end-to-end smoke test: fire real user-style questions at the RUNNING
AKARI server (127.0.0.1:8000) and check that the answer (a) is served live,
(b) actually retrieves the newly digested wiki pages, and (c) is grounded.

This is the "does digested knowledge reach a real-time user query" check, not
the deterministic picker test. It runs real inference, so each query can take
60-200s on the 4GB GPU.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"

# Each query targets knowledge that only exists in the newly digested pages.
QUERIES = [
    {"label": "miracast",
     "expect_page": "miracast",
     "req": {"problem": "Miracast screen mirroring keeps failing to connect from a Windows laptop. How can I fix it?",
             "depth_tier": "balanced"}},
    {"label": "hdmi-hdcp",
     "expect_page": "connectivity-digital",
     "req": {"problem": "No image over HDMI. The same source works on another display. Could this be an HDCP handshake problem, and how do I check the signal?",
             "depth_tier": "balanced"}},
    {"label": "hdr-dark",
     "expect_page": "hdr-basics",
     "req": {"problem": "HDR movies look too dark and washed out on this projector. What should I check?",
             "depth_tier": "balanced"}},
    {"label": "ye-laser",
     "expect_page": "ye",
     "req": {"problem": "Large-venue laser projector reports a YE error with LDTH over temperature. What are the likely parts and the repair steps?",
             "model": "EB-PU2220B", "depth_tier": "balanced"}},
]


def post(req: dict) -> str:
    data = json.dumps(req).encode()
    r = urllib.request.urlopen(
        urllib.request.Request(BASE + "/diagnose", data=data,
                               headers={"Content-Type": "application/json"}),
        timeout=30,
    )
    return json.loads(r.read())["diagnosis_id"]


def poll(did: str, timeout: int = 300):
    t0 = time.time()
    last_step = ""
    while time.time() - t0 < timeout:
        try:
            r = urllib.request.urlopen(BASE + "/diagnose/" + did, timeout=30)
            body = json.loads(r.read())
            src = r.headers.get("X-Akari-Src", "?")
            if "metadata" in body or "diagnosis" in body:
                return body, src, round(time.time() - t0, 1)
            step = body.get("current_step", "")
            if step != last_step:
                print(f"      ...{step}", flush=True)
                last_step = step
        except urllib.error.HTTPError as e:
            if e.code == 502:
                return {"_error": e.read().decode()[:300]}, "?", round(time.time() - t0, 1)
        time.sleep(3)
    return {"_error": "timeout"}, "?", timeout


def main() -> None:
    print(f"=== Live /diagnose smoke test: {len(QUERIES)} real queries ===\n", flush=True)
    passed = 0
    for q in QUERIES:
        print(f"[{q['label']}] {q['req']['problem'][:70]}...", flush=True)
        did = post(q["req"])
        res, src, secs = poll(did)
        if "_error" in res:
            print(f"   FAIL: {res['_error']}\n", flush=True)
            continue
        md = res.get("metadata", {})
        diag = res.get("diagnosis", {})
        sols = res.get("solutions", [])
        pages = md.get("wiki_pages_used", [])
        used_expected = any(q["expect_page"] in p for p in pages)
        passed += used_expected
        print(f"   src={src}  {secs}s  coverage={md.get('wiki_coverage')}  conf={diag.get('confidence')}")
        print(f"   expected page '{q['expect_page']}' used: {'YES' if used_expected else 'NO'}")
        print(f"   pages_used: {[p.split('/')[-2] + '/' + p.split('/')[-1] for p in pages]}")
        print(f"   primary_cause: {str(diag.get('primary_cause'))[:160]}")
        if sols:
            s0 = sols[0]
            print(f"   top solution: [{s0.get('difficulty')}/{s0.get('cost')}] {str(s0.get('action'))[:160]}")
        print(flush=True)
    print(f"=== {passed}/{len(QUERIES)} answers used the expected newly-digested page ===", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
