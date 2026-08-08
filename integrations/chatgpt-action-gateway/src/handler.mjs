import { createHash, timingSafeEqual } from "node:crypto";

const DEFAULT_REPOSITORY = "JAIOS-Governance/junca-social-ecosystem-chain";
const DEFAULT_EXPLORER_URL = "https://explorer.jaios-governance.org/explorer.json";
const DEFAULT_GITHUB_API_VERSION = "2022-11-28";
const MAX_LOG_BYTES = 240_000;
const DEFAULT_TAIL_LINES = 400;
const MAX_TAIL_LINES = 2_000;

let cachedActionKey;
let cachedGitHubToken;

function json(statusCode, body, extraHeaders = {}) {
  return {
    statusCode,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...extraHeaders,
    },
    body: JSON.stringify(body),
  };
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function safeEqual(a, b) {
  const left = Buffer.from(String(a ?? ""));
  const right = Buffer.from(String(b ?? ""));
  return left.length === right.length && timingSafeEqual(left, right);
}

function getHeader(headers, name) {
  const target = name.toLowerCase();
  for (const [key, value] of Object.entries(headers ?? {})) {
    if (key.toLowerCase() === target) return value;
  }
  return undefined;
}

async function readSecret(secretArn, plaintextEnvName) {
  const plaintext = process.env[plaintextEnvName];
  if (plaintext) return plaintext;
  if (!secretArn) return undefined;

  const { SecretsManagerClient, GetSecretValueCommand } = await import(
    "@aws-sdk/client-secrets-manager"
  );
  const client = new SecretsManagerClient({});
  const response = await client.send(
    new GetSecretValueCommand({ SecretId: secretArn }),
  );
  if (response.SecretString) return response.SecretString;
  if (response.SecretBinary) {
    return Buffer.from(response.SecretBinary).toString("utf8");
  }
  throw new Error("Secret value is empty");
}

async function getActionKey() {
  if (!cachedActionKey) {
    cachedActionKey = await readSecret(
      process.env.ACTION_API_KEY_SECRET_ARN,
      "ACTION_API_KEY_PLAINTEXT",
    );
  }
  if (!cachedActionKey) throw new Error("Action API key is not configured");
  return cachedActionKey;
}

async function getGitHubToken() {
  if (cachedGitHubToken === undefined) {
    cachedGitHubToken =
      (await readSecret(
        process.env.GITHUB_TOKEN_SECRET_ARN,
        "GITHUB_TOKEN_PLAINTEXT",
      )) ?? null;
  }
  return cachedGitHubToken;
}

function parseEvent(event) {
  const method =
    event?.requestContext?.http?.method ?? event?.httpMethod ?? "GET";
  const path = event?.rawPath ?? event?.path ?? "/";
  const query = event?.queryStringParameters ?? {};
  return { method: method.toUpperCase(), path, query };
}

function positiveInt(value, fallback, max) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed) || parsed < 1) return fallback;
  return Math.min(parsed, max);
}

function assertExplorerUrl(rawUrl) {
  const url = new URL(rawUrl);
  if (url.protocol !== "https:") throw new Error("Explorer URL must use HTTPS");
  if (url.hostname !== "explorer.jaios-governance.org") {
    throw new Error("Explorer host is outside the fixed allowlist");
  }
  return url;
}

function githubUrl(pathname, query = {}) {
  const url = new URL(`https://api.github.com${pathname}`);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 15_000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetchWithTimeout(url, options);
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Upstream ${response.status}: ${text.slice(0, 500)}`);
  }
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("Upstream response is not valid JSON");
  }
  return { data, raw: text, status: response.status };
}

async function githubRequest(pathname, query = {}) {
  const token = await getGitHubToken();
  const headers = {
    Accept: "application/vnd.github+json",
    "User-Agent": "JAIOS-ChatGPT-Action-Gateway",
    "X-GitHub-Api-Version":
      process.env.GITHUB_API_VERSION ?? DEFAULT_GITHUB_API_VERSION,
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const url = githubUrl(pathname, query);
  const result = await fetchJson(url, { headers });
  return { ...result, sourceUrl: url.toString() };
}

function envelope(source, sourceUrl, raw, data, requestIdentity) {
  return {
    schema_version: "jaios-chatgpt-action-gateway/v1",
    source,
    source_url: sourceUrl,
    retrieved_at: new Date().toISOString(),
    request_digest: sha256(requestIdentity),
    payload_sha256: sha256(raw),
    data,
  };
}

function validateRepository() {
  const repository = process.env.GITHUB_REPOSITORY ?? DEFAULT_REPOSITORY;
  if (repository !== DEFAULT_REPOSITORY) {
    throw new Error("GitHub repository is outside the fixed allowlist");
  }
  return repository;
}

function isSha(value) {
  return /^[0-9a-f]{40}$/i.test(value);
}

function isNumericId(value) {
  return /^[1-9][0-9]*$/.test(value);
}

async function routeRequest({ method, path, query }) {
  if (method !== "GET") {
    return json(405, { error: "READ_ONLY_GATEWAY", message: "Only GET is allowed" });
  }

  if (path === "/v1/health") {
    return json(200, {
      schema_version: "jaios-chatgpt-action-gateway/v1",
      status: "ok",
      mode: "read-only",
      repository: DEFAULT_REPOSITORY,
      mainnet_changed: false,
      assets_moved: false,
      bridge_activated: false,
    });
  }

  if (path === "/v1/explorer/status") {
    const url = assertExplorerUrl(
      process.env.EXPLORER_STATUS_URL ?? DEFAULT_EXPLORER_URL,
    );
    const { data, raw } = await fetchJson(url, {
      headers: { "User-Agent": "JAIOS-ChatGPT-Action-Gateway" },
    });
    return json(
      200,
      envelope(
        "junca-public-explorer",
        url.toString(),
        raw,
        data,
        `${method} ${path}`,
      ),
    );
  }

  const repository = validateRepository();
  const [owner, repo] = repository.split("/");

  if (path === "/v1/github/workflow-runs") {
    const perPage = positiveInt(query.per_page, 10, 20);
    const page = positiveInt(query.page, 1, 10);
    const allowedStatuses = new Set([
      "completed",
      "action_required",
      "cancelled",
      "failure",
      "neutral",
      "skipped",
      "stale",
      "success",
      "timed_out",
      "in_progress",
      "queued",
      "requested",
      "waiting",
      "pending",
    ]);
    const status = query.status && allowedStatuses.has(query.status)
      ? query.status
      : undefined;
    const { data, raw, sourceUrl } = await githubRequest(
      `/repos/${owner}/${repo}/actions/runs`,
      {
        status,
        branch: query.branch,
        event: query.event,
        per_page: perPage,
        page,
      },
    );
    return json(
      200,
      envelope(
        "github-actions-runs",
        sourceUrl,
        raw,
        data,
        `${method} ${path}?${new URLSearchParams(query).toString()}`,
      ),
    );
  }

  const jobsMatch = path.match(/^\/v1\/github\/workflow-runs\/([^/]+)\/jobs$/);
  if (jobsMatch) {
    const runId = jobsMatch[1];
    if (!isNumericId(runId)) return json(400, { error: "INVALID_RUN_ID" });
    const perPage = positiveInt(query.per_page, 20, 100);
    const { data, raw, sourceUrl } = await githubRequest(
      `/repos/${owner}/${repo}/actions/runs/${runId}/jobs`,
      { filter: "latest", per_page: perPage },
    );
    return json(
      200,
      envelope(
        "github-actions-jobs",
        sourceUrl,
        raw,
        data,
        `${method} ${path}`,
      ),
    );
  }

  const logsMatch = path.match(/^\/v1\/github\/jobs\/([^/]+)\/logs$/);
  if (logsMatch) {
    const jobId = logsMatch[1];
    if (!isNumericId(jobId)) return json(400, { error: "INVALID_JOB_ID" });
    const token = await getGitHubToken();
    const headers = {
      Accept: "application/vnd.github+json",
      "User-Agent": "JAIOS-ChatGPT-Action-Gateway",
      "X-GitHub-Api-Version":
        process.env.GITHUB_API_VERSION ?? DEFAULT_GITHUB_API_VERSION,
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    const sourceUrl = githubUrl(
      `/repos/${owner}/${repo}/actions/jobs/${jobId}/logs`,
    );
    const response = await fetchWithTimeout(sourceUrl, {
      headers,
      redirect: "follow",
    }, 25_000);
    if (!response.ok) {
      throw new Error(`GitHub logs ${response.status}: ${(await response.text()).slice(0, 500)}`);
    }
    const fullText = await response.text();
    const tailLines = positiveInt(
      query.tail_lines,
      DEFAULT_TAIL_LINES,
      MAX_TAIL_LINES,
    );
    const lines = fullText.split(/\r?\n/);
    let selected = lines.slice(-tailLines).join("\n");
    let truncated = lines.length > tailLines;
    if (Buffer.byteLength(selected, "utf8") > MAX_LOG_BYTES) {
      selected = Buffer.from(selected, "utf8")
        .subarray(-MAX_LOG_BYTES)
        .toString("utf8");
      truncated = true;
    }
    const data = {
      job_id: Number(jobId),
      tail_lines_requested: tailLines,
      total_lines: lines.length,
      truncated,
      log_sha256: sha256(fullText),
      log_tail: selected,
    };
    return json(
      200,
      envelope(
        "github-actions-job-log",
        sourceUrl.toString(),
        fullText,
        data,
        `${method} ${path}?tail_lines=${tailLines}`,
      ),
    );
  }

  const commitStatusMatch = path.match(
    /^\/v1\/github\/commits\/([^/]+)\/status$/,
  );
  if (commitStatusMatch) {
    const sha = commitStatusMatch[1];
    if (!isSha(sha)) return json(400, { error: "INVALID_COMMIT_SHA" });
    const { data, raw, sourceUrl } = await githubRequest(
      `/repos/${owner}/${repo}/commits/${sha}/status`,
    );
    return json(
      200,
      envelope(
        "github-commit-status",
        sourceUrl,
        raw,
        data,
        `${method} ${path}`,
      ),
    );
  }

  return json(404, { error: "NOT_FOUND" });
}

export async function handler(event) {
  try {
    const expected = await getActionKey();
    const provided = getHeader(event?.headers, "x-jaios-action-key");
    if (!safeEqual(provided, expected)) {
      return json(401, { error: "UNAUTHORIZED" });
    }
    return await routeRequest(parseEvent(event));
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    console.error(JSON.stringify({ level: "error", message }));
    return json(502, {
      error: "UPSTREAM_OR_CONFIGURATION_ERROR",
      message,
    });
  }
}

export const __test = {
  sha256,
  safeEqual,
  parseEvent,
  positiveInt,
  assertExplorerUrl,
};
