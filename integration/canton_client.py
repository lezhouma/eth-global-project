"""Minimal Canton JSON Ledger API v2 client for the liquidation-auction demo.

Talks to a Five North DevNet validator (the Seaport "Validator Development
Access"). Pure standard library (urllib) so the matching engine can drop it in
with no extra dependencies.

Hard-won facts baked in (discovered against the live participant, Canton 3.5.3):
  * Auth is OIDC client_credentials -> JWT, expiring every ~8h (auto-refreshed).
  * A command's `userId` MUST equal the token's user (the JWT `sub`), else 403.
  * That user needs `CanActAs` rights for every party it submits as
    (see grant_rights); allocating a party does NOT grant them automatically.
  * Moving a confidential Holding requires attaching it as a `disclosedContract`
    (explicit disclosure) — the exchange is not a stakeholder and can't see it.

Config comes from environment (or integration/.env). See .env.example.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


def _load_dotenv(path: str) -> None:
    """Tiny .env loader (KEY=VALUE lines). No python-dotenv dependency."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


_load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


class LedgerError(Exception):
    def __init__(self, status, body):
        super().__init__(f"Ledger API {status}: {body}")
        self.status = status
        self.body = body


class LedgerClient:
    def __init__(self):
        self.token_url = os.environ["FN_TOKEN_URL"]
        self.client_id = os.environ["FN_CLIENT_ID"]
        self.client_secret = os.environ["FN_CLIENT_SECRET"]
        self.base = os.environ["FN_LEDGER_BASE"].rstrip("/")
        self.package_id = os.environ["FN_PACKAGE_ID"]
        self._token = None
        self._token_exp = 0.0
        self._user_id = None

    # ---- auth -------------------------------------------------------------
    def _fetch_token(self) -> None:
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "audience": self.client_id,
            "scope": "daml_ledger_api",
        }).encode()
        req = urllib.request.Request(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode())
        self._token = payload["access_token"]
        # refresh a minute before expiry
        self._token_exp = time.time() + int(payload.get("expires_in", 3600)) - 60
        claims = json.loads(_b64url(self._token.split(".")[1]))
        self._user_id = str(claims["sub"])  # commands must carry this as userId

    @property
    def token(self) -> str:
        if self._token is None or time.time() >= self._token_exp:
            self._fetch_token()
        return self._token

    @property
    def user_id(self) -> str:
        self.token  # ensure fetched
        return self._user_id

    # ---- low-level call ---------------------------------------------------
    def _call(self, method: str, path: str, body=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": ctype},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                text = r.read().decode()
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            raise LedgerError(e.code, e.read().decode()) from None

    def tid(self, name: str) -> str:
        """Fully-qualified template id from a `Module:Entity` short name."""
        return f"{self.package_id}:{name}"

    # ---- admin / setup ----------------------------------------------------
    def ledger_end(self) -> int:
        return self._call("GET", "/v2/state/ledger-end")["offset"]

    def upload_dar(self, dar_path: str):
        with open(dar_path, "rb") as fh:
            return self._call("POST", "/v2/packages", raw=fh.read(), ctype="application/octet-stream")

    def allocate_party(self, hint: str) -> str:
        resp = self._call("POST", "/v2/parties", {"partyIdHint": hint, "identityProviderId": ""})
        return resp["partyDetails"]["party"]

    def grant_rights(self, act_as=(), read_as=(), user_id=None):
        user_id = user_id or self.user_id
        rights = [{"kind": {"CanActAs": {"value": {"party": p}}}} for p in act_as]
        rights += [{"kind": {"CanReadAs": {"value": {"party": p}}}} for p in read_as]
        return self._call("POST", f"/v2/users/{user_id}/rights", {"userId": user_id, "rights": rights})

    # ---- commands ---------------------------------------------------------
    def submit(self, commands, act_as, command_id, disclosed=None, read_as=None):
        body = {
            "commands": commands,
            "commandId": command_id,
            "userId": self.user_id,            # MUST match the token's user
            "actAs": list(act_as),
            "readAs": list(read_as or []),
        }
        if disclosed:
            body["disclosedContracts"] = disclosed
        return self._call("POST", "/v2/commands/submit-and-wait", body)

    def create(self, template, args, act_as, command_id):
        cmd = {"CreateCommand": {"templateId": self.tid(template), "createArguments": args}}
        return self.submit([cmd], [act_as], command_id)

    def create_and_exercise(self, template, create_args, choice, choice_arg,
                            act_as, command_id, disclosed=None):
        cmd = {"CreateAndExerciseCommand": {
            "templateId": self.tid(template),
            "createArguments": create_args,
            "choice": choice,
            "choiceArgument": choice_arg,
        }}
        return self.submit([cmd], [act_as], command_id, disclosed=disclosed)

    # ---- queries ----------------------------------------------------------
    def active_contracts(self, party, with_blob=False, at_offset=None):
        at_offset = self.ledger_end() if at_offset is None else at_offset
        wildcard = {"WildcardFilter": {"value": {"includeCreatedEventBlob": bool(with_blob)}}}
        body = {
            "filter": {"filtersByParty": {party: {"cumulative": [{"identifierFilter": wildcard}]}}},
            "verbose": True,
            "activeAtOffset": at_offset,
        }
        out = []
        for e in self._call("POST", "/v2/state/active-contracts", body):
            ac = e.get("contractEntry", {}).get("JsActiveContract")
            if not ac:
                continue
            ce = ac["createdEvent"]
            mod, ent = ce["templateId"].split(":")[-2:]
            out.append({
                "cid": ce["contractId"],
                "template": f"{mod}:{ent}",
                "args": ce["createArgument"],
                "blob": ce.get("createdEventBlob"),
                "synchronizerId": ac.get("synchronizerId"),
            })
        return out

    def disclosed_contract(self, party, template, **match):
        """Build a disclosedContracts entry for a contract `party` can see."""
        for c in self.active_contracts(party, with_blob=True):
            if c["template"] == template and all(c["args"].get(k) == v for k, v in match.items()):
                return {
                    "templateId": self.tid(template),
                    "contractId": c["cid"],
                    "createdEventBlob": c["blob"],
                    "synchronizerId": c["synchronizerId"],
                }
        raise LookupError(f"no {template} matching {match} visible to {party}")


def _b64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
