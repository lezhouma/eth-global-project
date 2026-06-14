# datum

A liquidation auction where matched orders settle **atomically** on a Canton
ledger, and the *same* contracts expose **three views to three audiences** —
public, regulated, confidential. Privacy is the product; authorization is
declarative (delegated authority via signatory/controller roles, never keys).

## Privacy tiers (the centerpiece)

All three tiers come from one mechanism — `observer` declarations. Same auction,
three views:

| Tier             | Contract           | Visible to                                      | Contents                     |
| ---------------- | ------------------ | ----------------------------------------------- | ---------------------------- |
| **Public**       | `AuctionResult`    | `publicParty`, `regulator`, `exchange`          | Clearing price, volume, time |
| **Regulated**    | `SettlementRecord` | `regulator`, the two counterparties, `exchange` | Full per-leg detail          |
| **Confidential** | `Holding`          | owner + `issuer` (+ `exchange`, only via just-in-time disclosure during a settlement it runs) | Individual positions |

## Architecture

```
 Asset owner ──grants capped authority──▶ Delegation (TradingAuthority)
                                                  │ active authorities
 Matching engine ──matched legs + price──▶ Settlement (SettlementRequest.Execute)
   (off-ledger)                                   │ atomic transfer of Holdings
                                                  ▼
                          Disclosure contracts (public / regulated tiers)
```

Delegation and settlement are on-ledger; matching runs off-ledger and reaches the
ledger through the integration layer.

## Quick start

```sh
git clone --recursive https://github.com/lezhouma/eth-global-project.git
cd eth-global-project    # if you cloned without --recursive: git submodule update --init
```

**1 — Build & test the contracts.** Needs [`dpm`](docs/mdd.md) (NOT the deprecated
`daml-assistant`); the SDK is pinned in `liquidation-auction/multi-package.yaml`.

```sh
dpm install 3.5.1                  # once, if not already installed
cd liquidation-auction
dpm build --all                   # main (contracts) + test packages
dpm test --package-root test      # 4 scripts, warning-clean
```

All four pass: `testPrivacyTiers`, `testDelegation`, `testSettlement`,
`testSettlementRollback`.

**2 — Run the demo on DevNet.** Python 3, stdlib only. First put a client secret
in `integration/.env` (`cp integration/.env.example integration/.env`) — see
[integration/README.md](integration/README.md) for obtaining it.

```sh
cd integration
python3 onboard.py     # one-time: parties, holdings, authorities → devnet_state.json
python3 settle.py      # the demo swap: 1 wETH ⇄ 2000 USDC
```

**3 — Explorer.** The privacy model, made visual — switch viewer, watch the same
transaction reveal different detail.

```sh
python3 integration/explorer/server.py     # → http://127.0.0.1:8000
```

## Layout

- `liquidation-auction/` — Daml contracts (`Types` / `Holding` / `Delegation` /
  `Settlement`) plus the Daml Script test suite.
- `matching_engine/` — off-ledger matcher (Python/Flask, deploys to fly.io);
  consumed only through the fixed `MatchResult` seam ([docs/mdd.md](docs/mdd.md)).
- `integration/` — Python client for the Canton JSON Ledger API v2
  (`canton_client`, `onboard`, `settle`).
- `integration/explorer/` — party-scoped tx viewer; `explorer-cf/` deploys it to
  Cloudflare Pages. See [integration/explorer/README.md](integration/explorer/README.md).
- `front-end/eth-nyc-26/` — auction UI (git submodule, own README).
- `docs/mdd.md` — design doc: checkpoints, the seam, references.

## Deployment

Contracts → upload `liquidation-auction-main-0.0.1.dar` to Canton **DevNet**
(manual; see [docs/mdd.md](docs/mdd.md)). Engine → fly.io
(`matching_engine/fly.toml`). Explorer → Cloudflare Pages (`integration/explorer-cf/`).
