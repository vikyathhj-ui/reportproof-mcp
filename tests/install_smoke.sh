#!/bin/sh
# Smoke test: pip-install the package and drive the `reportproof-mcp` console script over stdio.
set -e
cp -r /src /tmp/m
pip install -q /tmp/m
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"check_report","arguments":{"data":[{"name":"a","rows":[{"date":"2026-09-01","clicks":100},{"date":"2026-10-01","clicks":150}]}],"start":"2026-10-01","end":"2026-10-31","report":"Clicks rose 50% to 150."}}}' \
  | reportproof-mcp | cut -c1-170
