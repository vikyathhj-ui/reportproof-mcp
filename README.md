# ReportProof MCP server

**Stop your AI agent from putting wrong numbers in client reports.**

LLMs write good marketing reports, but they get numbers wrong. A rise becomes "down", 25.58% becomes "25%", a total gets invented. This MCP server gives Claude, Cursor or any MCP client three tools that do the maths in code and check every number:

| Tool | What it does |
|---|---|
| `check_report` | Data + draft report → **PASS**, or **FAIL** listing each wrong number, its line, the problem (not in the data / wrong direction) and the closest real value |
| `compute_metrics` | Data → exact totals, % change (month-on-month or year-on-year), CTR / CPC / CPA / ROAS recomputed from totals, goal progress, top movers, anomalies, with ready-to-print strings (incl. Indian lakh/crore) |
| `verify_report` | Draft + metrics from `compute_metrics` → PASS / FAIL |

There's no LLM inside: the same input always gives the same answer.

It pairs with the official **Google Analytics MCP** and **Google Ads MCP** servers. Pass their raw `run_report` / `search` output straight in.

## Data it accepts
- **CSV exports** from GA4, Google Ads, Meta Ads, Search Console, LinkedIn Ads, or any CSV with a date column: `files: [{name, content}]`
- **Plain JSON rows** (Meta Insights API rows work as-is): `data: [{name, rows: [...]}]`
- **GA4 Data API `runReport` response**, unchanged: `data: [{name, ga4_report: {...}}]`
- **Google Ads API `search` / `searchStream` response**, unchanged: `data: [{name, google_ads: {...}}]`

## Install
**Try it first, no sign-up:** https://reportproof-api.onrender.com/try

You need a ReportProof API key. The **free plan** (50 calls/month) is at [rapidapi.com/VikyathJ/api/reportproof](https://rapidapi.com/VikyathJ/api/reportproof).

**Claude Desktop / Cursor / any MCP client** (needs [uv](https://docs.astral.sh/uv/)):
```json
{
  "mcpServers": {
    "reportproof": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/vikyathhj-ui/reportproof-mcp", "reportproof-mcp"],
      "env": { "RAPIDAPI_KEY": "your-rapidapi-key" }
    }
  }
}
```
**Without uv:** clone this repo and use `"command": "python", "args": ["-m", "reportproof_mcp"]` with `"cwd"` set to the clone. Python 3.9+, no dependencies.

## Example agent instruction
> Pull last month's GA4 and Google Ads data, write the client report, then call `check_report` with the raw data and your draft. If it says FAIL, fix only the flagged numbers using the closest real values and check again until it passes.

## How it works / privacy
- This package is a thin client. The calculation and verification run in the ReportProof API.
- The API processes each request in a temporary folder that is deleted afterwards. It stores nothing and doesn't log request contents.
- The first call after a quiet period can take up to about a minute while the server wakes.
- **Known limit:** verification checks that each number exists in the data with the right direction. It doesn't check that it's used in the right context. In a planted-error test it caught 37 of 40 errors.

## Development
```bash
python tests/test_mcp.py                                   # protocol tests (offline)
REPORTPROOF_URL=http://localhost:8080 REPORTPROOF_KEY=... python tests/test_mcp.py   # + API tests
```
MIT licensed.
