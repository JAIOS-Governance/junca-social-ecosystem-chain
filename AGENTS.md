# JUNCA / JAIOS Codex Cloud Operating Rules

All cells, agents, workflows, and handoffs in this repository must apply the latest CEO instruction first, then read the Creative Constitution before work and before every material decision:

https://docs.google.com/document/d/1D_uQWXWfRKdrjQjHybTV9bgpBvknauRc0ZkOSe0jBE8/edit

Google Drive official masters remain the source of truth.

## P0 — PC Complete Independence

Read and enforce `docs/CODEX_PC_COMPLETE_INDEPENDENCE_POLICY.md`.

- Every personal computer, local IDE, GitHub Desktop installation, local clone, local scheduler, localhost service, self-hosted runner, and local secret store is optional only.
- Codex Cloud, connected GitHub repositories, GitHub-hosted Actions, approved cloud runtimes, Google Drive, connectors, and API readback form the mandatory execution surface.
- Development, continuation, review, deployment, monitoring, recovery, and evidence retrieval must continue while all personal computers are powered off or offline.
- The CEO is involved only for platform-enforced identity verification, MFA, legally binding approval, payment approval, or a material business decision that cannot be delegated.
- Never return connector-capable setup, file operations, command execution, validation, monitoring, or recovery work to the CEO.
- Never write directly to `main` or `master`; use a feature branch, independent review, CI, rollback, and exact readback.
- Never expose or commit credentials, tokens, private keys, or secret-bearing environment files.

A local dependency is a governance defect. Replace it with a verified cloud route before activation.
