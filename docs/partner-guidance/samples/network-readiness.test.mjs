import assert from "node:assert/strict";
import test from "node:test";

import { validateNetworkBinding } from "./network-readiness.mjs";

test("fails closed when the RPC binding is absent", () => {
  assert.throws(
    () => validateNetworkBinding({ rpcUrl: undefined }),
    /verified RPC binding is required/,
  );
});

test("rejects a non-HTTPS RPC binding", () => {
  assert.throws(
    () => validateNetworkBinding({ rpcUrl: "http://127.0.0.1:8545" }),
    /must use HTTPS/,
  );
});

test("returns a redacted record for an HTTPS binding", () => {
  const result = validateNetworkBinding({
    name: "JUNCA Social Ecosystem Chain Public Preview Testnet",
    chainId: 20260723,
    rpcUrl: "https://rpc.example.invalid",
    notice: "Public Testnet / No Monetary Value",
  });

  assert.equal(result.rpcUrl, "[configured / redacted]");
  assert.equal(result.chainId, 20260723);
});
