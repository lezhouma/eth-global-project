"""
Canton Settlement Bridge
------------------------
Converts matched trades into per-wallet settlement instructions and submits
them to Canton Network via integration/settle.py.

TOKEN_INSTRUMENT / CURRENCY_INSTRUMENT can be overridden via env vars.
"""

import json
import os
import sys

TOKEN_INSTRUMENT    = os.environ.get("AUCTION_INSTRUMENT", "wETH")
CURRENCY_INSTRUMENT = os.environ.get("AUCTION_CURRENCY",   "USDC")

_INTEGRATION_DIR = os.path.join(os.path.dirname(__file__), "..", "integration")


# ---------------------------------------------------------------------------
# Settlement instruction builder (per-wallet net deltas — included in API response)
# ---------------------------------------------------------------------------

def build_settlement_instructions(trades: list) -> list:
    """Aggregate trades into net per-wallet positions for the API response payload."""
    wallets: dict = {}

    for trade in trades:
        qty      = trade["quantity"]
        notional = qty * trade["price"]

        for wallet, delta_token, delta_usdc in [
            (trade["buyer_wallet"],  +qty, -notional),
            (trade["seller_wallet"], -qty, +notional),
        ]:
            if wallet not in wallets:
                wallets[wallet] = {"delta_token": 0.0, "delta_usdc": 0.0}
            wallets[wallet]["delta_token"] += delta_token
            wallets[wallet]["delta_usdc"]  += delta_usdc

    return [
        {
            "wallet":      wallet,
            "delta_token": round(pos["delta_token"], 10),
            "delta_usdc":  round(pos["delta_usdc"],  10),
        }
        for wallet, pos in wallets.items()
    ]


# ---------------------------------------------------------------------------
# Canton submission
# ---------------------------------------------------------------------------

def _build_canton_match_result(trades: list, clearing_price: float, total_volume: float) -> dict:
    """Convert matched trades to the legs format expected by integration/settle.py.

    Aggregates per-(user_id, instrument) so multi-trade participants get one net leg.
    user_id must equal the party role label in devnet_state.json (e.g. "ownerA").
    """
    deltas: dict = {}

    for trade in trades:
        qty      = trade["quantity"]
        notional = qty * trade["price"]
        buyer    = trade["buyer"]
        seller   = trade["seller"]

        deltas[(buyer,  TOKEN_INSTRUMENT)]    = deltas.get((buyer,  TOKEN_INSTRUMENT),    0.0) + qty
        deltas[(buyer,  CURRENCY_INSTRUMENT)] = deltas.get((buyer,  CURRENCY_INSTRUMENT), 0.0) - notional
        deltas[(seller, TOKEN_INSTRUMENT)]    = deltas.get((seller, TOKEN_INSTRUMENT),    0.0) - qty
        deltas[(seller, CURRENCY_INSTRUMENT)] = deltas.get((seller, CURRENCY_INSTRUMENT), 0.0) + notional

    legs = [
        {"party": party, "instrument": instrument, "delta": str(round(delta, 10))}
        for (party, instrument), delta in deltas.items()
        if round(delta, 10) != 0.0
    ]

    return {
        "legs":          legs,
        "clearingPrice": str(clearing_price),
        "totalVolume":   str(total_volume),
    }


def submit_settlement(trades: list, clearing_price: float, total_volume: float, auction_id: str) -> dict:
    """Submit matched trades to Canton. Falls back to placeholder if integration is unavailable."""
    try:
        if _INTEGRATION_DIR not in sys.path:
            sys.path.insert(0, _INTEGRATION_DIR)
        from settle import settle  # type: ignore[import]
        match_result = _build_canton_match_result(trades, clearing_price, total_volume)
        return settle(match_result, command_id=f"auction-{auction_id}")
    except Exception as exc:
        print(f"[SETTLEMENT] Canton settle failed ({exc!r}), using placeholder")
        return _placeholder(trades, auction_id)


def _placeholder(trades: list, auction_id: str) -> dict:
    instructions = build_settlement_instructions(trades)
    payload = {"auction_id": auction_id, "settlements": instructions}
    print("\n[SETTLEMENT] Placeholder — would call Canton with:")
    print(json.dumps(payload, indent=2))
    return {"status": "placeholder", "auction_id": auction_id}
