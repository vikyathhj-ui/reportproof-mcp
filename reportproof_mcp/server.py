"""ReportProof MCP server: give AI agents a deterministic number checker for marketing reports.

Tools
  check_report     data + draft report -> metrics and PASS/FAIL for every number in the draft
  compute_metrics  data -> exact totals, % changes, CTR/CPC/CPA/ROAS (recomputed from totals), goals, anomalies
  verify_report    draft report + metrics (from compute_metrics) -> PASS/FAIL per number

Data can be CSV export text, plain JSON rows, a GA4 Data API runReport response (e.g. from the
official GA4 MCP server) or a Google Ads search response (e.g. from the official Google Ads MCP server).

This is a thin client: the maths runs in the ReportProof API.
  RAPIDAPI_KEY=...                                    -> calls https://reportproof.p.rapidapi.com (free plan available)
  REPORTPROOF_URL=... REPORTPROOF_KEY=...             -> calls a ReportProof server directly
Standard library only. Speaks MCP over stdio (newline-delimited JSON-RPC 2.0).
"""
import json
import os
import sys
import urllib.error
import urllib.request

__version__ = "0.1.0"
SUPPORTED = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
RAPID_HOST = "reportproof.p.rapidapi.com"

SOURCE_PROPS = {
    "files": {"type": "array", "description": "CSV exports: [{name, content}] (content = CSV text). Use content_base64 for UTF-16 files.",
              "items": {"type": "object", "properties": {"name": {"type": "string"}, "content": {"type": "string"},
                                                          "content_base64": {"type": "string"}}}},
    "data": {"type": "array", "description": "JSON sources: [{name, rows}] with plain row objects, [{name, ga4_report}] with a GA4 runReport "
                                             "response unchanged, or [{name, google_ads}] with a Google Ads search/searchStream response unchanged.",
             "items": {"type": "object", "properties": {"name": {"type": "string"}, "rows": {"type": "array", "items": {"type": "object"}},
                                                        "ga4_report": {"type": "object"}, "google_ads": {}}}},
    "start": {"type": "string", "description": "Current period start, YYYY-MM-DD. Omit to use the latest complete month."},
    "end": {"type": "string", "description": "Current period end, YYYY-MM-DD."},
    "compare": {"type": "string", "enum": ["previous", "yoy", "none"], "description": "Compare with the previous period (default) or the same period last year."},
    "currency": {"type": "string", "description": "3-letter currency code if the data doesn't say, e.g. USD or INR."},
    "number_style": {"type": "string", "enum": ["international", "indian"], "description": "indian = lakh/crore grouping."},
    "goals": {"type": "object", "additionalProperties": {"type": "number"}, "description": "Targets, e.g. {\"conversions\": 150, \"cpa@blended\": 40}."},
}
TOOLS = [
    {"name": "check_report",
     "description": "Check every number in a draft marketing report against the source data. Returns PASS, or FAIL with each wrong "
                    "number, its line, the problem (not in data / wrong direction) and the closest real value. Use after writing a "
                    "report from GA4, Google Ads, Meta Ads or Search Console data; rewrite only the flagged sentences and check again.",
     "inputSchema": {"type": "object", "properties": dict(SOURCE_PROPS, report={"type": "string", "description": "The draft report text."}),
                     "required": ["report"]}},
    {"name": "compute_metrics",
     "description": "Compute exact report metrics from marketing data: totals, % change vs previous period or last year, CTR, CPC, "
                    "CPA, ROAS and rates recomputed from totals (never averaged), blended ad totals, goal progress, top movers and "
                    "anomalies, with ready-to-print display strings. Use these numbers when writing a report.",
     "inputSchema": {"type": "object", "properties": SOURCE_PROPS}},
    {"name": "verify_report",
     "description": "Verify a draft report against a metrics object previously returned by compute_metrics.",
     "inputSchema": {"type": "object", "properties": {"report": {"type": "string"}, "metrics": {"type": "object"},
                                                      "allow": {"type": "array", "items": {"type": "number"},
                                                                "description": "Extra numbers allowed in the text, e.g. [30] for a 30-day window."}},
                     "required": ["report", "metrics"]}},
]
PATHS = {"check_report": "/v1/check", "compute_metrics": "/v1/compute", "verify_report": "/v1/verify"}


def endpoint():
    if os.environ.get("RAPIDAPI_KEY"):
        return f"https://{RAPID_HOST}", {"X-RapidAPI-Key": os.environ["RAPIDAPI_KEY"], "X-RapidAPI-Host": RAPID_HOST}
    if os.environ.get("REPORTPROOF_URL"):
        return os.environ["REPORTPROOF_URL"].rstrip("/"), {"X-API-Key": os.environ.get("REPORTPROOF_KEY", "")}
    return None, None


def api(path, body):
    base, headers = endpoint()
    if not base:
        raise RuntimeError("Set RAPIDAPI_KEY (free plan at https://rapidapi.com/VikyathJ/api/reportproof) "
                           "or REPORTPROOF_URL and REPORTPROOF_KEY.")
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={**headers, "Content-Type": "application/json",
                                          "User-Agent": f"reportproof-mcp/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:     # first call can wake a sleeping server
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except ValueError:
            err = {}
        msg = err.get("message") or e.reason
        fix = f" Fix: {err['fix']}" if err.get("fix") else ""
        raise RuntimeError(f"ReportProof API {e.code}: {msg}.{fix}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach ReportProof API: {e.reason}")


def summarise(name, res):
    v = res.get("verification") if name == "check_report" else (res if name == "verify_report" else None)
    lines = []
    if v:
        lines.append(f"{v['status']}: {v['checked']} numbers checked, {len(v['issues'])} issue(s).")
        for i in v["issues"]:
            lines.append(f"- line {i['line']}: '{i['number']}' {i['problem']}" +
                         (f" (closest real value: {i['closest']})" if i.get("closest") else "") + f" | {i['context']}")
        if v["status"] == "FAIL":
            lines.append("Rewrite only the flagged numbers using the data, then check again.")
    m = res.get("metrics") if name == "check_report" else (res if name == "compute_metrics" else None)
    if m:
        cur = (m.get("periods") or {}).get("current") or {}
        prev = (m.get("periods") or {}).get("previous") or {}
        lines.append(f"Period: {cur.get('label')} vs {prev.get('label') or 'n/a'}.")
        for s in m.get("sources", []):
            parts = []
            for k, mv in (s.get("metrics") or {}).items():
                d = mv.get("display") or {}
                parts.append(f"{k} {d.get('current', mv.get('current'))} ({d.get('pct_change', 'n/a')})")
            lines.append(f"{s.get('file')} [{s.get('platform')}]: " + "; ".join(parts[:14]))
        for w in m.get("warnings", []):
            lines.append(f"Warning: {w}")
    return "\n".join(lines) or json.dumps(res)[:2000]


def call_tool(name, args):
    if name not in PATHS:
        raise KeyError(name)
    res = api(PATHS[name], args or {})
    return {"content": [{"type": "text", "text": summarise(name, res)}], "structuredContent": res, "isError": False}


def handle(msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:                                   # notification (e.g. notifications/initialized)
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": want if want in SUPPORTED else SUPPORTED[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "reportproof", "title": "ReportProof", "version": __version__},
            "instructions": "Use compute_metrics for exact marketing numbers and check_report to verify every number "
                            "in a drafted report before sending it."}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        try:
            return {"jsonrpc": "2.0", "id": mid, "result": call_tool(name, params.get("arguments") or {})}
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        except Exception as e:                        # tool errors are returned to the model, not raised
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": str(e)}], "isError": True}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            out = handle(msg) if isinstance(msg, dict) else {"jsonrpc": "2.0", "id": None,
                                                              "error": {"code": -32600, "message": "Invalid request"}}
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
