"""End-to-end tests: drive the MCP server over stdio like an MCP client would.

Protocol tests always run. API tests need a ReportProof server:
  REPORTPROOF_URL=http://... REPORTPROOF_KEY=... python tests/test_mcp.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), str(detail)[:200]))


def session(messages, env_extra=None, drop=("RAPIDAPI_KEY", "REPORTPROOF_URL", "REPORTPROOF_KEY")):
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, "-m", "reportproof_mcp"], cwd=ROOT, env=env, timeout=300,
                       input="".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages),
                       capture_output=True, text=True)
    return [json.loads(l) for l in p.stdout.splitlines() if l.strip()], p.stderr


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}}
INITED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
ROWS = [{"date": "2026-09-01", "campaign": "Brand", "impressions": 2000, "clicks": 100, "cost": 200, "conversions": 10},
        {"date": "2026-10-01", "campaign": "Brand", "impressions": 3000, "clicks": 150, "cost": 240, "conversions": 15}]
SRC = {"data": [{"name": "google_ads", "rows": ROWS}], "currency": "USD", "start": "2026-10-01", "end": "2026-10-31"}


def call(i, name, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}


# ---------------------------------------------------------------- protocol (offline)
out, err = session([INIT, INITED, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "ping"},
                    {"jsonrpc": "2.0", "id": 4, "method": "nope/x"}, "{not json",
                    {"jsonrpc": "2.0", "id": 5, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
                    call(6, "check_report", {"report": "x"}), call(7, "no_such_tool", {})])
by = {m.get("id"): m for m in out}
check("initialize echoes a supported protocol version", by[1]["result"]["protocolVersion"] == "2025-06-18", by.get(1))
check("initialize advertises tools capability and server name",
      "tools" in by[1]["result"]["capabilities"] and by[1]["result"]["serverInfo"]["name"] == "reportproof")
check("notification gets no response", len([m for m in out if m.get("id") is None and "result" in m]) == 0)
tools = {t["name"]: t for t in by[2]["result"]["tools"]}
check("tools/list returns 3 tools with input schemas",
      set(tools) == {"check_report", "compute_metrics", "verify_report"} and all("inputSchema" in t for t in tools.values()))
check("ping -> empty result", by[3]["result"] == {})
check("unknown method -> -32601", by[4]["error"]["code"] == -32601)
check("malformed JSON -> -32700", any(m.get("error", {}).get("code") == -32700 for m in out))
check("unsupported protocol version -> server's latest", by[5]["result"]["protocolVersion"] == "2025-11-25")
check("no API config -> tool error explaining RAPIDAPI_KEY",
      by[6]["result"]["isError"] and "RAPIDAPI_KEY" in by[6]["result"]["content"][0]["text"], by.get(6))
check("unknown tool -> -32602", by[7]["error"]["code"] == -32602)

# ---------------------------------------------------------------- against a real API
if os.environ.get("REPORTPROOF_URL"):
    env = {"REPORTPROOF_URL": os.environ["REPORTPROOF_URL"], "REPORTPROOF_KEY": os.environ.get("REPORTPROOF_KEY", "")}
    out, err = session([INIT, INITED,
                        call(2, "check_report", dict(SRC, report="In October 2026 clicks fell 50.0% to 150.")),
                        call(3, "check_report", dict(SRC, report="In October 2026 clicks rose 50.0% to 150.")),
                        call(4, "compute_metrics", SRC),
                        call(5, "check_report", {"data": [{"name": "x", "rows": []}], "report": "x"})], env_extra=env)
    by = {m.get("id"): m for m in out}
    r2 = by[2]["result"]
    check("check_report: wrong direction -> FAIL text with the issue",
          not r2["isError"] and r2["content"][0]["text"].startswith("FAIL") and "says down but data says up" in r2["content"][0]["text"],
          r2["content"][0]["text"][:200])
    check("check_report: structuredContent carries metrics + verification",
          r2["structuredContent"]["verification"]["status"] == "FAIL" and r2["structuredContent"]["metrics"]["tool"] == "reportproof")
    check("check_report: correct draft -> PASS", by[3]["result"]["content"][0]["text"].startswith("PASS"), by[3]["result"]["content"][0]["text"][:120])
    r4 = by[4]["result"]
    check("compute_metrics: summary lists period and metrics",
          "October 2026 vs September 2026" in r4["content"][0]["text"] and "clicks 150" in r4["content"][0]["text"], r4["content"][0]["text"][:200])
    metrics = r4["structuredContent"]
    out2, _ = session([INIT, call(2, "verify_report", {"report": "Clicks were 150 and cost was $240.", "metrics": metrics})], env_extra=env)
    v = {m.get("id"): m for m in out2}[2]["result"]
    check("verify_report on compute_metrics output -> PASS", v["content"][0]["text"].startswith("PASS"), v["content"][0]["text"][:120])
    r5 = by[5]["result"]
    check("API validation error -> isError with the API's message", r5["isError"] and "ReportProof API 400" in r5["content"][0]["text"],
          r5["content"][0]["text"][:200])
    check("no stray output on stderr", err.strip() == "", err[:200])
else:
    print("(REPORTPROOF_URL not set: skipping API tests)")

for n, ok, d in results:
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else "  -> " + d))
passed = sum(ok for _, ok, _ in results)
print(f"\n{passed} passed, {len(results) - passed} failed")
sys.exit(0 if passed == len(results) else 1)
