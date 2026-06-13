"""
Canton Settlement Bridge
------------------------
Converts matched trades into per-wallet settlement instructions and submits
them to Canton Network.

HOW TO CONNECT TO CANTON
-------------------------
Canton's Ledger API is gRPC. Python can reach it in two ways:

Option A — Canton JSON API (recommended for hackathon)
  Canton exposes a REST wrapper at http://<validator-node>:7575
  Your teammate just needs to make sure it's enabled on their Canton node.
  You POST to /v1/exercise with the contract + choice + args. No codegen needed.

Option B — Thin Java/TS bridge service (cleanest long-term)
  Your teammate building the Daml contract also exposes a simple HTTP endpoint
  (e.g. POST /settle) on their backend. You POST the settlement JSON there,
  and their code calls the Ledger API. Keeps Canton details out of Python.

For now, submit_settlement() logs the payload and returns a placeholder.
Swap in one of the real implementations below when your teammate is ready.
"""

import json
import requests

# ---------------------------------------------------------------------------
# Config — update these when your teammate's contract is ready
# ---------------------------------------------------------------------------

CANTON_JSON_API_URL   = "http://localhost:7575"          # Canton validator JSON API
SETTLEMENT_TEMPLATE   = "Auction:AuctionSettlement"      # Daml template ID (ask teammate)
SETTLEMENT_CONTRACT   = "PLACEHOLDER_CONTRACT_ID"        # contract ID to exercise on
SETTLEMENT_CHOICE     = "Settle"                         # Daml choice name (ask teammate)
CANTON_AUTH_TOKEN     = ""                               # bearer token if auth is enabled

# If using Option B (bridge service):
BRIDGE_SERVICE_URL    = "http://localhost:8080/settle"   # your teammate's REST endpoint


# ---------------------------------------------------------------------------
# Settlement instruction builder
# ---------------------------------------------------------------------------

def build_settlement_instructions(trades: list) -> list:
    """
    Aggregate all trades into net per-wallet positions.

    Each trade contributes two legs:
      buyer_wallet  : +quantity token,  -(quantity * price) USDC
      seller_wallet : -quantity token,  +(quantity * price) USDC

    Returns a list of dicts ready to pass to submit_settlement():
      [
        { "wallet": "0xBen",  "delta_token":  6.0, "delta_usdc": -630.0 },
        { "wallet": "0xDave", "delta_token": -6.0, "delta_usdc":  630.0 },
        ...
      ]
    """
    wallets: dict = {}

    for trade in trades:
        qty      = trade["quantity"]
        notional = qty * trade["price"]   # USDC cost = qty * clearing_price

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
# Canton submission  — swap implementation when ready
# ---------------------------------------------------------------------------

def submit_settlement(instructions: list, auction_id: str) -> dict:
    """Submit settlement instructions to Canton. Currently a logged placeholder."""
    return _placeholder(instructions, auction_id)

    # Uncomment ONE of these when your teammate is ready:
    # return _via_canton_json_api(instructions, auction_id)
    # return _via_bridge_service(instructions, auction_id)


# ---------------------------------------------------------------------------
# Implementation A — Canton JSON API (REST wrapper around Ledger API)
# ---------------------------------------------------------------------------

def _via_canton_json_api(instructions: list, auction_id: str) -> dict:
    """
    Exercise a Daml choice via Canton's JSON API.

    Your Daml choice signature should look something like:
      choice Settle : ()
        with
          auctionId   : Text
          settlements : [SettlementLeg]
        controller appOperator
        do
          forA_ settlements \\leg -> ...

    where SettlementLeg = { wallet: Text, deltaToken: Decimal, deltaUsdc: Decimal }
    """
    payload = {
        "templateId": SETTLEMENT_TEMPLATE,
        "contractId": SETTLEMENT_CONTRACT,
        "choice":     SETTLEMENT_CHOICE,
        "argument": {
            "auctionId":   auction_id,
            "settlements": [
                {
                    "wallet":      leg["wallet"],
                    "deltaToken":  str(leg["delta_token"]),   # Daml Decimal → string
                    "deltaUsdc":   str(leg["delta_usdc"]),
                }
                for leg in instructions
            ],
        },
    }

    headers = {"Content-Type": "application/json"}
    if CANTON_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {CANTON_AUTH_TOKEN}"

    resp = requests.post(
        f"{CANTON_JSON_API_URL}/v1/exercise",
        json=payload,
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Implementation B — Thin bridge service (your teammate's REST endpoint)
# ---------------------------------------------------------------------------

def _via_bridge_service(instructions: list, auction_id: str) -> dict:
    """
    POST settlement to a simple HTTP service your teammate exposes.
    They handle the Canton Ledger API call on their side.
    """
    payload = {
        "auction_id":   auction_id,
        "settlements":  instructions,
    }
    resp = requests.post(BRIDGE_SERVICE_URL, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Placeholder — logs what would be sent, no network call
# ---------------------------------------------------------------------------

def _placeholder(instructions: list, auction_id: str) -> dict:
    payload = {
        "auction_id":  auction_id,
        "settlements": instructions,
    }
    print("\n[SETTLEMENT] Placeholder — would call Canton with:")
    print(json.dumps(payload, indent=2))
    print("[SETTLEMENT] Uncomment _via_canton_json_api or _via_bridge_service in submit_settlement()\n")
    return {"status": "placeholder", "auction_id": auction_id}
