import test from "node:test";
import assert from "node:assert/strict";

process.env.ACTION_API_KEY_PLAINTEXT = "test-action-key";
process.env.GITHUB_REPOSITORY = "JAIOS-Governance/junca-social-ecosystem-chain";

const { handler, __test } = await import("../src/handler.mjs");

function event(path, query = {}, key = "test-action-key") {
  return {
    rawPath: path,
    headers: { "x-jaios-action-key": key },
    queryStringParameters: query,
    requestContext: { http: { method: "GET" } },
  };
}

test("rejects an invalid action key", async () => {
  const response = await handler(event("/v1/health", {}, "wrong"));
  assert.equal(response.statusCode, 401);
});

test("returns fixed read-only boundaries", async () => {
  const response = await handler(event("/v1/health"));
  assert.equal(response.statusCode, 200);
  const body = JSON.parse(response.body);
  assert.equal(body.mode, "read-only");
  assert.equal(body.mainnet_changed, false);
  assert.equal(body.assets_moved, false);
  assert.equal(body.bridge_activated, false);
});

test("wraps explorer JSON with evidence hashes", async () => {
  const originalFetch = global.fetch;
  global.fetch = async () =>
    new Response(JSON.stringify({ finalized_height: 42, quorum: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  try {
    const response = await handler(event("/v1/explorer/status"));
    assert.equal(response.statusCode, 200);
    const body = JSON.parse(response.body);
    assert.equal(body.source, "junca-public-explorer");
    assert.equal(body.data.finalized_height, 42);
    assert.match(body.payload_sha256, /^[0-9a-f]{64}$/);
  } finally {
    global.fetch = originalFetch;
  }
});

test("rejects non-allowlisted explorer hosts", () => {
  assert.throws(
    () => __test.assertExplorerUrl("https://example.com/explorer.json"),
    /allowlist/,
  );
});
