# Canton Settlement Explorer

A party-scoped transaction explorer for the liquidation auction — "same transaction,
three views." Switch viewer (Public / Regulator / Owner A / Owner B) and watch the
*same* settlement reveal different detail. A **Run settlement** button submits a real
swap on DevNet so you can watch a new transaction appear across the perspectives.

It is **not** a global block explorer (no party can see the whole Canton ledger — that's
the privacy thesis). The tiering is **Canton's**, not the app's: the backend just queries
the ledger *as* each party and renders whatever Canton returns. A per-party query only
returns events that party is a stakeholder/observer of, so the tiers fall out for free.

## Run

```sh
# Prereqs: integration/.env filled (client secret) and integration/devnet_state.json
# present (from `python3 integration/onboard.py`). The DAR must be vetted on the
# participant (it is, from the integration step).
python3 integration/explorer/server.py        # -> http://127.0.0.1:8000
```

Then open `http://127.0.0.1:8000`. The OIDC token stays **server-side** — the browser
only ever calls `/api/*`, and the server binds `127.0.0.1` only.

## What each viewer sees after a settlement

| Viewer | Sees | Does NOT see |
|---|---|---|
| **Public** | `AuctionResult` only (clearing price, volume) | any leg, any holding |
| **Regulator** | `AuctionResult` + `SettlementRecord` (all 4 legs) | individual `Holding`s |
| **Owner A** | `SettlementRecord` + own `Holding` deltas (−1 wETH, +2000 USDC) | Owner B's holdings; `AuctionResult` |
| **Owner B** | `SettlementRecord` + own `Holding` deltas (+1 wETH, −2000 USDC) | Owner A's holdings |

The same `updateId` appears under every viewer — switch tabs and watch the detail
appear/vanish. That is the privacy model, made visual.

## Files

| File | Role |
|---|---|
| `server.py` | stdlib `http.server` backend: `GET /api/tx?party=<role>`, `POST /api/settle`, static serving. Holds the token; relabels party ids → roles. |
| `ledger_history.py` | `transactions_for(client, party)` — reads `POST /v2/updates/flats` and decodes it (the only net-new ledger call). Run directly to dump raw history for a role. |
| `static/` | zero-dep UI: viewer switcher, tx list (color-coded event chips), click-to-expand detail modal, Run-settlement button. |

Reuses `../canton_client.py` (`LedgerClient`) and `../settle.py` (`settle`, `DEMO_MATCH`,
`load_state`) — nothing is duplicated.

## Reusable seam for the real front-end

`GET /api/tx?party=<role>` returns tier-scoped JSON
(`{viewer, ledgerEnd, transactions:[{updateId, offset, time, events:[{kind, template, contractId, args}]}]}`).
The eth-nyc-26 front-end can consume this endpoint unchanged (add an
`Access-Control-Allow-Origin` header in `server.py` if it calls cross-origin).

## Deep-linking from the auction result

The explorer accepts a deep-link so a button on the front-end's auction result can
open a specific transaction directly:

```
{EXPLORER_URL}/?party=<role>&tx=<transactionId>
```

- `party` ∈ `publicParty | regulator | ownerA | ownerB` — the viewer/lens to open as
  (`regulator` shows the full legs).
- `tx` is the `transactionId` returned by `settle()`.

On load the explorer selects that viewer and auto-opens that transaction's detail
modal (and toasts if the transaction isn't visible to the chosen party). This is a
plain navigation, so **no CORS is needed** — the explorer serves its own page and
calls its own same-origin `/api/*`.

Front-end button:

```jsx
const EXPLORER_URL = process.env.NEXT_PUBLIC_EXPLORER_URL;
<a href={`${EXPLORER_URL}/?party=regulator&tx=${transactionId}`}
   target="_blank" rel="noopener noreferrer">View settlement →</a>
```

## Public URL (when the deployed front end links here)

The server holds the DevNet token, so it stays a long-running process (not Vercel
serverless). For a demo, expose it with a tunnel:

```sh
cloudflared tunnel --url http://localhost:8000     # or: ngrok http 8000
```

Set `NEXT_PUBLIC_EXPLORER_URL` to the tunnel's HTTPS URL. Note: a public explorer is
viewable by anyone with the URL and (by design here) leaves `POST /api/settle` open,
so anyone can trigger a settlement — acceptable on sandbox DevNet, not for anything
real.
