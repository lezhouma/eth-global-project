"""One-time DevNet onboarding for the liquidation-auction demo.

Allocates the parties, grants the token's user CanActAs/CanReadAs rights, seeds
initial Holdings, and creates the TradingAuthority delegations. Writes the
resulting party ids to devnet_state.json, which settle.py then consumes.

Idempotent guard: if devnet_state.json already exists this refuses to run again
(delete it to re-onboard a fresh set). Re-onboarding allocates *new* parties
(party ids are never pruned), so don't do it casually.

Usage:
    python3 integration/onboard.py            # uses FN_* from integration/.env
"""

import json
import os
import secrets
import sys

from canton_client import LedgerClient

STATE_PATH = os.path.join(os.path.dirname(__file__), "devnet_state.json")

# Role -> party hint. A short random run-suffix avoids colliding with parties
# left by earlier runs on the shared validator.
ROLES = ["exchange", "ownerA", "ownerB", "regulator", "publicParty", "issuer"]

# Initial holdings to mint: (owner role, instrument, amount).
SEED_HOLDINGS = [
    ("ownerA", "wETH", "10.0000000000"),
    ("ownerB", "USDC", "20000.0000000000"),
]
# Instruments each owner delegates to the exchange (give + receive sides).
DELEGATIONS = [("ownerA", "wETH"), ("ownerA", "USDC"),
               ("ownerB", "wETH"), ("ownerB", "USDC")]
CEILING = "1000000.0000000000"


def main():
    if os.path.exists(STATE_PATH):
        sys.exit(f"{STATE_PATH} already exists — delete it to re-onboard.")

    c = LedgerClient()
    run = secrets.token_hex(3)
    print(f"onboarding run {run} as user {c.user_id}")

    parties = {role: c.allocate_party(f"la-{role}-{run}") for role in ROLES}
    for role, p in parties.items():
        print(f"  allocated {role:12s} {p}")

    # The token's user must be allowed to act as the parties it submits for.
    c.grant_rights(
        act_as=[parties["ownerA"], parties["ownerB"], parties["exchange"]],
        read_as=[parties["regulator"], parties["publicParty"], parties["issuer"]],
    )
    print("  granted actAs(ownerA, ownerB, exchange) + readAs(regulator, public, issuer)")

    for owner, inst, amt in SEED_HOLDINGS:
        c.create("Holding:Holding",
                 {"issuer": parties["issuer"], "owner": parties[owner],
                  "instrument": inst, "amount": amt},
                 parties[owner], f"seed-{owner}-{inst}-{run}")
        print(f"  minted {owner} {amt} {inst}")

    for owner, inst in DELEGATIONS:
        c.create("Delegation:TradingAuthority",
                 {"owner": parties[owner], "exchange": parties["exchange"],
                  "instrument": inst, "maxAmount": CEILING},
                 parties[owner], f"auth-{owner}-{inst}-{run}")
        print(f"  delegated {owner} {inst} (ceiling {CEILING})")

    with open(STATE_PATH, "w") as fh:
        json.dump({"run": run, "parties": parties, "packageId": c.package_id}, fh, indent=2)
    print(f"wrote {STATE_PATH}")


if __name__ == "__main__":
    main()
