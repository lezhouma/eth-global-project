# CLAUDE.md

## Toolchain

- Use `dpm`, NOT `daml-assistant` (deprecated for Canton 3.4+).
- `dpm` is a two-layer tool: the meta-CLI (`install`, `version`) and the dpm-SDK (provides `build`, `sandbox`, `test`). If `dpm build` says "unknown command", no SDK is active — the "Dpm-SDK Commands" section in
`dpm --help` will be empty.
- SDK is selected per-project by `sdk-version:` in `daml.yaml`. Without it, the build won't run even if an SDK is installed globally. Install with `dpm install <version>`.

## Daml learnings from training video

- **File name must match the module name, case-sensitive.** `module Invoice` → `Invoice.daml`, not `invoice.daml`.
- **Capitalization is enforced**: modules, templates, choices, types → uppercase. Variables → lowercase.
- `import Daml.Script` — capital S.
- Inside `submit`/`submitMustFail`, use `createCmd` / `exerciseCmd`. Plain `create` / `exercise` are for choice bodies (Update monad).
- A choice declared `: ContractId X` must actually `create X` in its body; listing field names is not a body.
- `with` blocks use newlines or commas, not semicolons.
- Use `->`, not `→` (unicode arrow needs `UnicodeSyntax`). Don't paste from formatted sources.
- Layout matters — a second `submit` indented under the first's `do` becomes part of it. Keep sibling submits at the same indent.
- `allocatePartyWithHint` is deprecated. Use `allocatePartyByHint(PartyIdHint "...")` — single arg, no display name.

## Build-failure checklist

1. `sdk-version:` missing from `daml.yaml`.
2. File name vs `module` declaration mismatch.
3. Casing on module / template / choice / type names.
4. `Daml.script` instead of `Daml.Script`.
5. Choice body doesn't `create` anything.
6. Nested `submit` blocks.
7. Typos in builtins — Daml's error message rarely points at the typo directly; grep the file.
8. Unicode arrows / bullets from copy-paste.

## Canton MCP

`.mcp.json` wires Claude Code to a local `canton-mcp` Docker image
(`Build-on-Canton-MCP-main/`). Tools: `canton_get_started`, `canton_lookup`,
`canton_check`, `canton_faq`, `canton_api_ref`, `canton_compare_evm`,
`canton_network_info`.

Rebuild after editing the MCP source:
`docker build -t canton-mcp Build-on-Canton-MCP-main`

Stdio MCP containers occasionally leak across Claude Code sessions despite
`--rm`. Clean up:
`docker ps --filter ancestor=canton-mcp -q | xargs -r docker stop`

## Debugging stdio MCP servers

Piping a JSON-RPC message and `head`-ing the output appears to hang — the
server stays open on stdio. To verify a server boots, run detached and read
logs:

```sh
CID=$(docker run -d canton-mcp); sleep 5; docker logs "$CID"; docker rm -f "$CID"
```
