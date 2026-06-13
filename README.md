# Liquidation Auction on Canton

A liquidation auction where matched orders settle **atomically** on a Canton
ledger, and the *same* set of contracts exposes **three different views to three
different audiences** — public, regulated, and confidential. Privacy is the
product; authorization is declarative (delegated authority via
signatory/controller roles, never keys).

This repo covers the **delegation** and **settlement** modules and the
**privacy model** that spans them. Matching is an external module, consumed only
through the fixed `MatchResult` seam type (see [docs/mdd.md](docs/mdd.md)).

## Architecture

```
 Asset owner ──grants capped authority──▶ Delegation (TradingAuthority)
                                                  │ active authorities
 Matching engine ──matched legs + price──▶ Settlement (SettlementRequest.Execute)
   (external, off-ledger)                         │ atomic transfer of Holdings
                                                  ▼
                          Disclosure contracts (public / regulated tiers)
```

Only delegation and settlement are in scope here; matching is a black box.

## Privacy tiers (the demo centerpiece)

All three tiers are built from the same mechanism — `observer` declarations.
Same auction, three views:

| Tier             | Contract           | Visible to                                   | Contents                       |
| ---------------- | ------------------ | -------------------------------------------- | ------------------------------ |
| **Public**       | `AuctionResult`    | `publicParty`, `regulator`, `exchange`       | Clearing price, volume, time   |
| **Regulated**    | `SettlementRecord` | `regulator`, the two counterparties, `exchange` | Full per-leg detail         |
| **Confidential** | `Holding`          | owner + `issuer` (+ `exchange`, only via just-in-time disclosure during a settlement it runs) | Individual positions |

## Toolchain

Uses [`dpm`](docs/mdd.md) (NOT the deprecated `daml-assistant`). The SDK version
is pinned in `liquidation-auction/multi-package.yaml` (`sdk-version: 3.5.1`).

```sh
dpm install 3.5.1   # once, if not already installed
```

## Build & test

From `liquidation-auction/`:

```sh
cd liquidation-auction
dpm build --all                 # builds the `main` (contracts) and `test` packages
dpm test --package-root test    # runs the Daml Script suite
```

Expected: `daml/Test.daml:testPrivacyTiers: ok`. The build is warning-clean.

## Layout

```
liquidation-auction/
├── multi-package.yaml          # pins sdk-version; lists the two packages
├── main/                       # contracts -> liquidation-auction-main-0.0.1.dar
│   └── daml/
│       ├── Types.daml          # MatchedLeg / MatchResult seam + SettlementError
│       ├── Holding.daml        # native token; confidential tier
│       ├── Delegation.daml     # TradingAuthority: capped, revocable delegation
│       └── Settlement.daml     # SettlementRequest.Execute; AuctionResult, SettlementRecord
└── test/
    └── daml/
        └── Test.daml           # privacy-tier assertions + stub-choice exercises
```

## Build plan (checkpoints)

Each checkpoint builds, is checked with a Daml Script, and is committed before
the next. See [docs/mdd.md](docs/mdd.md) §7.

- **Checkpoint 1 — Skeleton (current).** All templates/choices with real
  signatures and stub bodies; the Script asserts the three privacy tiers hold
  and exercises every stub choice. ✅ builds + passes locally.
- **Checkpoint 2 — Delegation logic (current).** Real `UseAuthority`
  (instrument + ceiling checks), `Revoke`; over-limit and instrument-mismatch
  fail closed, revoke archives the authority. ✅ builds + passes locally
  (`testDelegation`).
- **Checkpoint 3 — Settlement logic.** Real `Execute` + `validateBatch`; atomic
  swap, rollback on a failing leg, tiers re-asserted on real data.

## Deployment

The contracts deploy to Canton **DevNet** by uploading the built
`liquidation-auction-main-0.0.1.dar`. Deployment is performed manually (see
[docs/mdd.md](docs/mdd.md) for the Seaport reference).

## Design notes

- **Why no clearing counterparty:** settlement is one atomic Daml transaction —
  all legs commit or none do, so the settlement-risk window is zero.
- **Delegation, not keys:** the exchange moves an owner's asset only by
  exercising that owner's `TradingAuthority`, which carries the owner's
  authority into the sub-transaction. The ceiling and instrument checks bound
  exactly what the exchange can do.
- **Confidential holdings + delegated movement:** the exchange is *not* a
  permanent observer of holdings. To move one, the owner discloses it to the
  exchange just for that transaction (Canton explicit disclosure), so
  confidentiality is preserved while delegation still works.
