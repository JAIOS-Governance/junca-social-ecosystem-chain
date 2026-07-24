# Developer Handoff

## Scope

This package implements the controlled institutional technical-reference layer. It does not
change chain runtime, validator configuration, genesis, Mainnet or an existing
production site.

## Technical source baseline

- Repository: `juncaGlobal/junca-Project`
- Pull request: `#158`
- Evidence baseline:
  `df74d30f95faf4e0c18f7927494ab20f0dee8766`
- Delivery branch: `agent/junca-social-ecosystem-chain`

The evidence baseline remains fixed even when this documentation commit advances
the PR head. Re-audit every technical value if runtime or configuration files
change.

## Web

The public editorial surface is a technical reference, not a developer message or sales landing page. Preserve protocol-led headings, evidence classification and the approved typography hierarchy.

The production source is in `web/app/`:

- `page.tsx` — content, diagrams, copy control and readiness logic
- `globals.css` — quiet-luxury responsive system
- `layout.tsx` — metadata and noindex/nofollow policy

The current Sites checkpoint is owner-restricted. Do not change access to public
without explicit approval and a passed publication gate.

## Document

The canonical Google Doc is:

https://docs.google.com/document/d/1Zi17JkJNHtD_4mnSudrnDBo8DrUTYKQSdJUb8EoCmxo/edit?usp=drivesdk

The latest revision was read back with the official name, governance label,
mandatory testnet notice, 20 chapters, Ethereum/ERC, BSC and TRON evidence, expanded checklist
and `NO-GO` publication recommendation intact.

## Validation commands

From the Sites project:

```bash
npm run lint
npm run test
```

For the published guard:

```bash
node --test samples/network-readiness.test.mjs
```

## Release blockers

1. Public Testnet runtime acceptance is BLOCKED.
2. Validator custody-bound addresses and attestations are pending.
3. Public RPC, WebSocket, Explorer and Faucet URLs are unverified.
4. The Chain ID candidate is not approved for public wallet use.
5. Smart-contract, token and NFT compatibility is unverified.
6. Mainnet snapshot audit and continuity decision are pending.
7. Ethereum / ERC target-network binding, Chain ID, RPC and contracts are pending.
8. BSC/TRON contracts and routes are not deployed; custody, key and incident
   attestations remain incomplete.
9. TRON Shasta TVM compatibility requires a verified TRON deployment toolchain.

## Next engineering action

Replace placeholder runtime bindings with custody-bound values, pass independent
runtime acceptance, complete bridge custody and incident attestations, and
verify Ethereum/ERC, BSC and TRON Shasta toolchains through repository CI and accepted Public
Testnet evidence. Only after those gates pass should runnable contract or bridge
deployment examples be added.
