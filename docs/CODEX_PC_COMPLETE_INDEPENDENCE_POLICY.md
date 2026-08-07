# P0 — PC Complete Independence & Cloud-Only Operations
# PC完全不要・クラウド完結運用

**Status:** MANDATORY / P0  
**Scope:** JUNCA / JAIOS / J Global repositories, agents, CI, deployment, monitoring, recovery, and handoff

## Absolute Requirement

JUNCA / JAIOS / J Global development and operations must continue while every personal computer is powered off or offline. A desktop PC, laptop, local IDE, GitHub Desktop, local clone, local scheduler, localhost service, self-hosted runner, local secret store, or manual copy-and-paste operation must never be a required execution dependency or Completion Gate.

## Canonical Execution Surface

The mandatory execution surface is:

1. Codex Cloud or another approved cloud agent
2. Connected GitHub repository
3. GitHub-hosted Actions and cloud automation
4. Approved cloud runtime and deployment provider
5. Google Drive source of truth
6. Connector/API-based evidence and readback

Local tools are optional diagnostic conveniences only. Their absence, shutdown, disconnection, replacement, or loss must not stop development, QA, deployment, monitoring, recovery, or evidence retrieval.

## CEO Burden Boundary

The CEO may be asked only for an operation that no agent or connector can perform, such as platform-enforced identity verification, MFA, legally binding approval, payment approval, or a material business decision. The CEO must not be assigned repository setup, file movement, command execution, monitoring, validation, or operational work that can be completed through cloud routes.

## Design Prohibitions

The following are prohibited:

- PC-always-on architecture
- local IDE or local clone as the source of truth
- local scheduler or resident desktop agent as a production dependency
- self-hosted runner as the only execution route
- `localhost` or a private workstation path as a production endpoint
- completion claims based only on a local screen
- returning connector-capable work to the CEO
- AI self-judgment that weakens or replaces this requirement

## Required Evidence

A compliant repository must provide:

- repository-resident Codex policy and configuration
- scheduled GitHub-hosted health audit
- pull-request and `main` validation gates
- machine-readable evidence artifact
- exact commit SHA and stored-file readback
- recovery and rollback instructions
- no secret material in repository content or logs

## Enforcement

Any proposed or implemented local dependency is a governance defect. The affected scope must return immediately to Repair & Remediation. The local dependency must be removed or replaced with a verified cloud route before activation. No agent may reinterpret “PC completely unnecessary” as “PC optional but required for setup, continuation, monitoring, or recovery.”

Only an explicit, task-specific CEO instruction may authorize a bounded exception. The exception must not become a general operating dependency.
