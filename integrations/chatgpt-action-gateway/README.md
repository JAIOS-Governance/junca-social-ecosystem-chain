# JAIOS JUNCA Chain ChatGPT Action Gateway

Status: **IMPLEMENTATION PACKAGE / DEPLOYMENT PENDING**

This package provides one fail-closed, read-only API surface for a dedicated
JUNCA Chain Custom GPT. It combines:

- current public explorer JSON;
- GitHub Actions run and job state;
- bounded GitHub Actions job-log tails;
- exact commit CI status;
- retrieval timestamps and SHA-256 evidence metadata.

It does not expose write or deployment operations.

## Why a gateway is required

A GPT can be configured with Apps or with Actions, but not both in the same GPT.
A direct GitHub App plus a separate Explorer Action therefore cannot be combined
inside one Custom GPT. This gateway keeps both sources behind one Actions-based,
read-only OpenAPI contract.

A direct GitHub logs action is also weak because GitHub returns temporary redirect
URLs for log downloads. The gateway follows the redirect server-side, bounds the
returned text, and adds a SHA-256 digest without exposing the GitHub credential.

## Fixed boundaries

- Repository: `JAIOS-Governance/junca-social-ecosystem-chain`
- Explorer host: `explorer.jaios-governance.org`
- Methods: `GET` only
- Mainnet changed: `false`
- Assets moved: `false`
- Bridge activated: `false`

The gateway rejects a repository or explorer host outside the fixed allowlist.

## Files

- `src/handler.mjs` — AWS Lambda handler.
- `template.yaml` — AWS SAM deployment definition.
- `openapi.yaml` — Custom GPT Actions schema.
- `GPT_INSTRUCTIONS.md` — governed GPT instruction block.
- `test/handler.test.mjs` — authorization, boundary, and evidence tests.

## Deployment

### 1. Create Secrets Manager secrets (authorized AWS operator)

Create one required secret containing a random action key:

- `junca/chatgpt-action-key`

Optional but recommended for GitHub API rate limits, create a fine-grained GitHub
token secret:

- `junca/chatgpt-github-read-token`

The GitHub token must be restricted to the canonical repository with read-only:

- Actions
- Commit statuses / checks as required by GitHub
- Metadata

Do not grant Contents write, Actions write, Administration, Secrets, or Environments.
The public repository can be queried without a token, but unauthenticated rate
limits are lower.

### 2. Build and deploy (authorized AWS operator)

From this directory:

```bash
sam build
sam deploy --guided
```

Supply the Secrets Manager ARNs when prompted. The template stores only secret
ARNs in the Lambda environment; secret values are read at runtime.

### 3. Validate the gateway

Copy the `ActionGatewayUrl` output and call:

```bash
curl -sS \
  -H 'X-JAIOS-Action-Key: <secret value>' \
  '<ActionGatewayUrl>v1/health'
```

Expected boundary response includes:

```json
{
  "status": "ok",
  "mode": "read-only",
  "mainnet_changed": false,
  "assets_moved": false,
  "bridge_activated": false
}
```

Then validate Explorer and GitHub reads before configuring ChatGPT.

### 4. Configure the Custom GPT

This is the only ChatGPT UI step that cannot be performed from the repository:

1. Create or edit the dedicated GPT.
2. Do not enable Apps in that GPT.
3. Add a Custom Action.
4. Select API key authentication, custom header.
5. Header name: `X-JAIOS-Action-Key`.
6. Store the action key value in the GPT editor.
7. Replace `https://replace-me.example.invalid` in `openapi.yaml` with the exact
   Lambda Function URL origin, then paste/import the schema.
8. Add `GPT_INSTRUCTIONS.md` to Instructions.
9. Test every operation in Preview.
10. Keep the GPT private or workspace-restricted until Security Review passes.

Custom Actions cannot run when the workspace action-domain allowlist blocks the
deployed domain. In that case, an admin must allow the exact gateway domain.

## Verification gates

Deployment is not complete until all gates pass:

- `GET /v1/health` returns the fixed read-only boundaries.
- Explorer returns HTTP 200 and valid JSON through the gateway.
- Workflow runs can be listed for the canonical repository.
- Jobs can be listed for a known run.
- A known job log can be read without exposing authorization headers or tokens.
- Commit status accepts only a full 40-character SHA.
- Non-GET requests return `405 READ_ONLY_GATEWAY`.
- Invalid action keys return `401 UNAUTHORIZED`.
- Non-allowlisted hosts and repositories fail closed.

## Production status language

Before AWS deployment and Custom GPT Preview tests, report this package as:

- Production: complete
- Review: local validation complete or pending, as applicable
- Deployment: pending
- Custom GPT action: pending

Do not report the integration as connected or live until the deployed URL and
Custom GPT action calls have been read back successfully.

## Manual authorization boundary

The implementation files can be produced and reviewed without CEO interaction. The
following steps require an authenticated human or an authorized deployment cell:

- create or select the two AWS Secrets Manager secrets;
- authorize the AWS deployment if the deployment workflow is not already trusted;
- enter the action key in the Custom GPT editor;
- paste/import the final OpenAPI schema and run Preview approval prompts.

Do not send secret values through GitHub issues, pull requests, chat messages, logs,
or deployment outputs.

If the GPT is later shared publicly or published to the GPT Store, configure a valid
Privacy Policy URL before publication. Keep it private during initial acceptance.
