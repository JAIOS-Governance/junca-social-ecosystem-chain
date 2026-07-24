# JUNCA Social Ecosystem Chain — Public Preview Testnet

This bundle defines a three-validator PoSV testnet and a separate public RPC node.

Release label: **Public Testnet / No Monetary Value**

Issuance management: **JAIOS Institutional Governance**

Audience: **Public Technical Evaluation**

The bundle intentionally contains no validator keys, passwords, wallet mnemonics,
funded accounts, production endpoints, or legacy-team credentials. Genesis must be
generated only after the three deployment-environment validator addresses and the
JAIOS-governed foundation address exist. Public RPC is limited to `eth`, `net`, and
`web3`; administrative, personal, miner, debug, and txpool APIs remain private.

The compose file is a deployment contract. Runtime publication remains blocked until
Genesis fingerprint, new-key custody, 3/3 quorum, RPC boundary, explorer parity,
faucet rate limiting, status page, rollback package, and independent readback pass.
