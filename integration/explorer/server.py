"""Backend for the party-scoped Canton transaction explorer.

A zero-dependency (stdlib http.server) backend that:
  * holds the OIDC token SERVER-SIDE (the browser only ever talks to /api/*),
  * GET  /api/tx?party=<role>  -> that party's tier-scoped transaction history,
  * POST /api/settle           -> runs one settlement (the demo "Run auction" button),
  * serves the static UI from the same origin (so there is no CORS to configure).

The privacy tiers are Canton's, not ours: /api/tx just queries the ledger AS the
requested party and relabels party ids to friendly roles. Run:

    python3 integration/explorer/server.py     # -> http://127.0.0.1:8000

Requires integration/.env (client secret) and integration/devnet_state.json.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from canton_client import LedgerClient, LedgerError       # noqa: E402
from settle import settle, load_state, DEMO_MATCH          # noqa: E402
from ledger_history import transactions_for                # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript",
                 ".css": "text/css", ".json": "application/json"}

CLIENT = LedgerClient()                       # one shared client; token stays in-process
ROLE_TO_PID = load_state()["parties"]
PID_TO_ROLE = {pid: role for role, pid in ROLE_TO_PID.items()}


def relabel(obj):
    """Replace Canton party ids with friendly role labels, recursively."""
    if isinstance(obj, str):
        if obj in PID_TO_ROLE:
            return PID_TO_ROLE[obj]
        return obj.split("::")[0] + "::…" if "::" in obj else obj
    if isinstance(obj, list):
        return [relabel(x) for x in obj]
    if isinstance(obj, dict):
        return {k: relabel(v) for k, v in obj.items()}
    return obj


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def _json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- GET: /api/tx + static ----
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/tx":
            role = (parse_qs(url.query).get("party") or [""])[0]
            if role not in ROLE_TO_PID:
                return self._json(400, {"error": f"unknown party '{role}'",
                                        "parties": list(ROLE_TO_PID)})
            try:
                txs = transactions_for(CLIENT, ROLE_TO_PID[role])
                for tx in txs:
                    for ev in tx["events"]:
                        ev["args"] = relabel(ev["args"])
                return self._json(200, {"viewer": role, "ledgerEnd": CLIENT.ledger_end(),
                                        "transactions": txs})
            except LedgerError as e:
                return self._json(502, {"error": str(e)})
        return self._serve_static(url.path)

    # ---- POST: /api/settle ----
    def do_POST(self):
        if urlparse(self.path).path != "/api/settle":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            match = json.loads(raw) if raw.strip() else DEMO_MATCH
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON body"})
        try:
            resp = settle(match, client=CLIENT)
            return self._json(200, resp)   # {transactionId, updateId, completionOffset, createdContracts}
        except (LedgerError, LookupError) as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:                       # never leak a stack to the browser
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._json(404, {"error": "not found"})
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    host = "127.0.0.1"
    port = int(os.environ.get("PORT") or os.environ.get("EXPLORER_PORT") or "8000")
    print(f"Canton transaction explorer on http://{host}:{port}  (user {CLIENT.user_id})")
    print(f"viewers: {', '.join(ROLE_TO_PID)}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
