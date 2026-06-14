# integration/ — calling settlement from code

A dependency-free Python client (stdlib only) that drives the deployed
`liquidation-auction` contracts on the Five North DevNet validator via the
**Canton JSON Ledger API v2**. This is how the matching engine triggers
settlement.

## Files

| File | Purpose |
|------|---------|
| `canton_client.py` | `LedgerClient`: OIDC auth (+refresh), party allocation, rights, create / create-and-exercise, ACS queries, disclosure blobs. |
| `onboard.py` | One-time: allocate parties, grant rights, mint Holdings, create TradingAuthorities → writes `devnet_state.json`. |
| `settle.py` | `settle(match_result)` — the call the matching engine makes. Submits one atomic `Execute`. |
| `.env.example` | Config template. Copy to `.env` (gitignored) and add the client secret. |

## Setup

```sh
cp integration/.env.example integration/.env   # then paste the client secret
cd integration
python3 onboard.py        # one-time: parties + holdings + authorities on DevNet
python3 settle.py         # runs the demo swap (1 wETH <-> 2000 USDC)
```

`onboard.py` writes `devnet_state.json` (party ids); `settle.py` reads it.

## Calling it from the matching engine

```python
from settle import settle

# legs reference parties by role label (resolved against devnet_state.json)
match_result = {
    "legs": [
        {"party": "ownerA", "instrument": "wETH", "delta": "-1.0"},
        {"party": "ownerA", "instrument": "USDC", "delta": "2000.0"},
        {"party": "ownerB", "instrument": "wETH", "delta": "1.0"},
        {"party": "ownerB", "instrument": "USDC", "delta": "-2000.0"},
    ],
    "clearingPrice": "2000.0",
    "totalVolume": "1.0",
}
resp = settle(match_result)
# -> {"transactionId": "1220…",      # the Canton transaction (update) id
#     "updateId": "1220…",           # alias, back-compat
#     "completionOffset": 2282147,
#     "createdContracts": {          # so the UI can deep-link to each
#       "Settlement:AuctionResult":   "00…",
#       "Settlement:SettlementRecord":"00…"}}
```

Decimals are JSON strings. The batch must net to zero per instrument (the Daml
`validateBatch` rejects it otherwise) and every leg fails closed if it would
exceed a delegation ceiling — the whole settlement then rolls back atomically.

## Gotchas (learned against the live participant, Canton 3.5.3)

- **`userId` must equal the token's user** (the JWT `sub`, e.g. `6`) on every
  command, or you get `403`. `LedgerClient` does this automatically.
- **Acting parties need `CanActAs`** granted to that user (`grant_rights`);
  allocating a party does not grant it. Reads (other tiers) need `CanReadAs`.
- **Confidential Holdings need explicit disclosure.** The exchange isn't a
  stakeholder, so each giver Holding is attached as a `disclosedContract`
  (`createdEventBlob` from an ACS read as the owner). `settle.py` does this.
- **The DAR must be vetted on this participant** (`LedgerClient.upload_dar`);
  uploading via Seaport's UI does not necessarily land it on this ledger node.
- Token expires every ~8h — `LedgerClient` refreshes automatically.

## Transaction explorer (next)

`GET /v2/state/ledger-end` + `POST /v2/updates/flats` (or the `wss://…` stream)
give a **party-scoped** update history — the basis for a "Canton tx viewer"
where each viewer sees only their tier (public tape / regulated legs / own
positions). Not a global explorer (that's impossible by design), which is the
privacy story made visual.
