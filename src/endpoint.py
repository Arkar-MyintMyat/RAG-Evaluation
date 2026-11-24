"""Cached, rate-limited client for the LiteratureExplorer endpoint (system under test).

Every request/response is appended to data/raw/endpoint_raw.jsonl (raw responses deliverable).
Before a request is sent, the cache is checked: an identical (route, payload, variant) is never
sent twice, so re-running any script costs zero endpoint requests.

Rules respected: <=2 parallel requests, back-off on 429/502/503/504, global request budget.
"""
import hashlib, json, os, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
BASE = os.environ["ENDPOINT_BASE_URL"].rstrip("/")
KEY = os.environ["ENDPOINT_API_KEY"]
RAW = ROOT / "data" / "raw" / "endpoint_raw.jsonl"
BUDGET = int(os.environ.get("ENDPOINT_BUDGET", "950"))
MAX_PARALLEL = 2

_lock = threading.Lock()
_cache = {}


def _load():
    if RAW.exists():
        for line in RAW.open(encoding="utf-8"):
            r = json.loads(line)
            _cache[r["key"]] = r


_load()


def requests_sent():
    """Total number of HTTP requests sent to the endpoint so far (incl. retries)."""
    return sum(r.get("attempts", 1) for r in _cache.values())


def make_key(route, payload, variant=""):
    s = json.dumps([route, payload, variant], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode()).hexdigest()[:24]


def call(route, payload, tag="", variant="", headers=None, raw_body=None, method="POST",
         auth=True, timeout=120, retry=True):
    """Send one request (or return the cached one).

    route: '/v1/chat/completions' or '/v1/context' (or anything, for negative tests)
    payload: JSON-serialisable body (ignored if raw_body is given)
    variant: extra cache-key component, e.g. 'rep2' for deliberate repeats
    Returns the cached record: {key, tag, route, payload, status, latency_s, body, ...}
    """
    key = make_key(route, payload if raw_body is None else {"raw": raw_body}, variant + str(headers) + method + str(auth))
    with _lock:
        if key in _cache:
            return _cache[key]
        if requests_sent() >= BUDGET:
            raise RuntimeError(f"Endpoint request budget ({BUDGET}) reached")
    h = {"Content-Type": "application/json"}
    if auth:
        h["Authorization"] = f"Bearer {KEY}"
    if headers:
        h.update(headers)
    data = raw_body if raw_body is not None else json.dumps(payload)
    attempts, waits = 0, [5, 15, 30]
    while True:
        attempts += 1
        t0 = time.perf_counter()
        try:
            resp = requests.request(method, BASE + route, data=data.encode() if isinstance(data, str) else data,
                                    headers=h, timeout=timeout)
            lat = time.perf_counter() - t0
            status, text = resp.status_code, resp.text
            rid = resp.headers.get("x-amzn-RequestId")
        except requests.RequestException as e:
            lat, status, text, rid = time.perf_counter() - t0, -1, f"{type(e).__name__}: {e}", None
        if retry and status in (429, 502, 503, 504, -1) and attempts <= len(waits):
            time.sleep(waits[attempts - 1])
            continue
        break
    try:
        body = json.loads(text)
    except Exception:
        body = text
    rec = {"key": key, "tag": tag, "route": route, "method": method, "variant": variant,
           "payload": payload if raw_body is None else {"raw": raw_body[:2000] if isinstance(raw_body, str) else "<bytes>"},
           "status": status, "latency_s": round(lat, 3), "attempts": attempts, "request_id": rid,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "body": body}
    with _lock:
        _cache[key] = rec
        with RAW.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def chat(question, tag="", variant="", **extra):
    payload = {"messages": [{"role": "user", "content": question}], **extra}
    return call("/v1/chat/completions", payload, tag=tag, variant=variant)


def context(query, tag="", variant="", **extra):
    return call("/v1/context", {"query": query, **extra}, tag=tag, variant=variant)


def run_parallel(fn, items, workers=MAX_PARALLEL):
    with ThreadPoolExecutor(max_workers=min(workers, MAX_PARALLEL)) as ex:
        return list(ex.map(fn, items))


if __name__ == "__main__":
    print("cached records:", len(_cache), "requests sent:", requests_sent(), "budget:", BUDGET)
