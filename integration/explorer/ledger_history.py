"""Party-scoped transaction history via the Canton JSON Ledger API v2.

`transactions_for(client, party)` reads the flat-transaction stream
(`POST /v2/updates/flats`) for ONE party and decodes it into a compact,
display-ready list. There is no redaction logic here: the ledger only returns
events the party is a stakeholder/observer of, so the privacy tiers fall out for
free (a per-party query is the whole mechanism).

Verified envelope (Canton 3.5.3): the request mirrors the proven ACS filter
shape; the response is a JSON array of
  {"update": {"Transaction": {"value": {updateId, effectiveAt, events: [...]}}}}
where each event is {"CreatedEvent": {...}} or {"ArchivedEvent": {...}}, each
carrying offset / contractId / templateId (+ createArgument on creates).

Run directly to eyeball the raw history for a role:
    python3 integration/explorer/ledger_history.py public
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from canton_client import LedgerClient  # noqa: E402


def transactions_for(client, party, begin=0, end=None):
    """Return this party's transactions (newest first), package events only."""
    end = client.ledger_end() if end is None else end
    wildcard = {"identifierFilter": {"WildcardFilter": {"value": {"includeCreatedEventBlob": False}}}}
    body = {
        "beginExclusive": begin,
        "endInclusive": end,
        "filter": {"filtersByParty": {party: {"cumulative": [wildcard]}}},
        "verbose": True,
    }
    out = []
    for u in client._call("POST", "/v2/updates/flats", body):
        tx = u.get("update", {}).get("Transaction", {}).get("value")
        if not tx:
            continue
        events, offset = [], None
        for ev in tx.get("events", []):
            kind = next(iter(ev))                       # CreatedEvent | ArchivedEvent
            v = ev[kind]
            if not v.get("templateId", "").startswith(client.package_id):
                continue                                # drop non-package (admin/script) noise
            offset = v.get("offset", offset)
            events.append({
                "kind": "created" if kind == "CreatedEvent" else "archived",
                "template": ":".join(v["templateId"].split(":")[-2:]),
                "contractId": v.get("contractId"),
                "args": v.get("createArgument", {}),    # {} for archives
            })
        if events:
            out.append({"updateId": tx["updateId"], "offset": offset,
                        "time": tx.get("effectiveAt"), "events": events})
    out.sort(key=lambda t: t["offset"] or 0, reverse=True)
    return out


if __name__ == "__main__":
    import json
    role = sys.argv[1] if len(sys.argv) > 1 else "public"
    state = json.load(open(os.path.join(os.path.dirname(__file__), "..", "devnet_state.json")))
    party = state["parties"][role]
    txs = transactions_for(LedgerClient(), party)
    print(f"{role}: {len(txs)} transaction(s)")
    print(json.dumps(txs, indent=2)[:4000])
