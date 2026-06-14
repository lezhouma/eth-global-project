"""Call the on-ledger settlement from code — this is what the matching engine uses.

`settle(match_result)` takes a MatchResult whose legs reference parties by ROLE
LABEL (ownerA / ownerB / ...), resolves them against devnet_state.json, finds the
current giver Holdings + the relevant TradingAuthorities on the ledger, and
submits one atomic `SettlementRequest.Execute` as the exchange — debiting every
giver and crediting every receiver in a single transaction.

The confidential giver Holdings are attached as `disclosedContracts` (the
exchange can't otherwise see them); the receiving holdings, the public
AuctionResult, and the regulated SettlementRecord are emitted by Execute.

CLI:
    python3 integration/settle.py            # runs the default demo swap
    python3 integration/settle.py legs.json  # legs.json = a MatchResult (labels)
"""

import json
import os
import sys

from canton_client import LedgerClient

STATE_PATH = os.path.join(os.path.dirname(__file__), "devnet_state.json")

# Default demo: ownerA swaps 1 wETH for 2000 USDC with ownerB at 2000 USDC/wETH.
DEMO_MATCH = {
    "legs": [
        {"party": "ownerA", "instrument": "wETH", "delta": "-1.0"},
        {"party": "ownerA", "instrument": "USDC", "delta": "2000.0"},
        {"party": "ownerB", "instrument": "wETH", "delta": "1.0"},
        {"party": "ownerB", "instrument": "USDC", "delta": "-2000.0"},
    ],
    "clearingPrice": "2000.0",
    "totalVolume": "1.0",
}


def load_state():
    with open(STATE_PATH) as fh:
        return json.load(fh)


def settle(match, client=None, command_id=None):
    """Submit one atomic settlement.

    Returns a dict the front end can use directly:
        {
          "transactionId": "1220…",      # the Canton transaction (update) id
          "updateId": "1220…",           # same value, kept for back-compat
          "completionOffset": 2281002,
          "createdContracts": {          # contract ids this settlement emitted,
            "Settlement:AuctionResult": "00…",   # so the UI can link to each
            "Settlement:SettlementRecord": "00…",
          },
        }
    """
    c = client or LedgerClient()
    parties = load_state()["parties"]
    pid = lambda label: parties[label]
    legs = match["legs"]

    # Authorities: the exchange observes every TradingAuthority, so one ACS read
    # as the exchange yields all of them, keyed by (owner, instrument).
    auth_by = {}
    for a in c.active_contracts(pid("exchange")):
        if a["template"] == "Delegation:TradingAuthority":
            auth_by[(a["args"]["owner"], a["args"]["instrument"])] = a["cid"]

    # Givers (delta < 0): find a holding with enough balance and disclose it.
    holdings, disclosed = [], []
    for leg in legs:
        if float(leg["delta"]) >= 0:
            continue
        owner_id, inst, need = pid(leg["party"]), leg["instrument"], -float(leg["delta"])
        match_h = next(
            (h for h in c.active_contracts(owner_id, with_blob=True)
             if h["template"] == "Holding:Holding"
             and h["args"]["instrument"] == inst
             and float(h["args"]["amount"]) >= need),
            None,
        )
        if not match_h:
            raise LookupError(f"{leg['party']} has no {inst} holding >= {need}")
        holdings.append(match_h["cid"])
        disclosed.append({
            "templateId": c.tid("Holding:Holding"),
            "contractId": match_h["cid"],
            "createdEventBlob": match_h["blob"],
            "synchronizerId": match_h["synchronizerId"],
        })

    # Every (party, instrument) the batch touches needs its authority present.
    authorities, seen = [], set()
    for leg in legs:
        key = (pid(leg["party"]), leg["instrument"])
        if key in auth_by and key not in seen:
            authorities.append(auth_by[key])
            seen.add(key)

    result = {
        "legs": [{"party": pid(l["party"]), "instrument": l["instrument"],
                  "delta": str(l["delta"])} for l in legs],
        "clearingPrice": str(match["clearingPrice"]),
        "totalVolume": str(match["totalVolume"]),
    }
    resp = c.create_and_exercise(
        "Settlement:SettlementRequest",
        {"exchange": pid("exchange"), "publicParty": pid("publicParty"),
         "regulator": pid("regulator"), "result": result},
        "Execute", {"authorities": authorities, "holdings": holdings},
        pid("exchange"), command_id or f"settle-{os.urandom(5).hex()}",
        disclosed=disclosed,
    )
    update_id = resp.get("updateId")
    offset = resp.get("completionOffset")
    return {
        "transactionId": update_id,
        "updateId": update_id,
        "completionOffset": offset,
        "createdContracts": _created_in_tx(c, pid("exchange"), update_id, offset),
    }


def _created_in_tx(client, exchange_pid, update_id, offset):
    """Contract ids created by the settlement transaction, keyed by template.

    Best-effort: reads the exchange's update stream around `offset` and matches
    the transaction by id. Lets the front end deep-link to the AuctionResult and
    SettlementRecord this settlement produced. The transactionId is authoritative
    regardless; if this lookup fails it just returns {}.
    """
    if not update_id or offset is None:
        return {}
    wildcard = {"identifierFilter": {"WildcardFilter": {"value": {"includeCreatedEventBlob": False}}}}
    body = {
        "beginExclusive": max(0, offset - 5),
        "endInclusive": offset,
        "filter": {"filtersByParty": {exchange_pid: {"cumulative": [wildcard]}}},
        "verbose": True,
    }
    created = {}
    try:
        for u in client._call("POST", "/v2/updates/flats", body):
            tx = u.get("update", {}).get("Transaction", {}).get("value")
            if not tx or tx.get("updateId") != update_id:
                continue
            for ev in tx.get("events", []):
                v = ev.get("CreatedEvent")
                if v:
                    created[":".join(v["templateId"].split(":")[-2:])] = v["contractId"]
    except Exception:
        pass
    return created


def _print_balances(c, parties):
    for role in ("ownerA", "ownerB"):
        bal = {}
        for h in c.active_contracts(parties[role]):
            if h["template"] == "Holding:Holding":
                bal[h["args"]["instrument"]] = bal.get(h["args"]["instrument"], 0.0) + float(h["args"]["amount"])
        print(f"  {role}: " + ", ".join(f"{v:g} {k}" for k, v in sorted(bal.items())))


def main():
    match = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else DEMO_MATCH
    c = LedgerClient()
    parties = load_state()["parties"]
    print("balances before:")
    _print_balances(c, parties)
    resp = settle(match, client=c)
    print("settled — transactionId:", resp["transactionId"])
    for tmpl, cid in resp["createdContracts"].items():
        print(f"  created {tmpl}: {cid}")
    print("balances after:")
    _print_balances(c, parties)


if __name__ == "__main__":
    main()
