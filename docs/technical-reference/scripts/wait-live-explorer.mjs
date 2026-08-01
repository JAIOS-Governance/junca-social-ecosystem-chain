const explorerUrl = "https://explorer.jaios-governance.org/explorer.json";
const attempts = Number.parseInt(process.env.JUNCA_EXPLORER_WAIT_ATTEMPTS ?? "180", 10);
const intervalMs = Number.parseInt(process.env.JUNCA_EXPLORER_WAIT_INTERVAL_MS ?? "10000", 10);
const expectedNotice = "Public Testnet / Protocol Validation Environment";
const commitPattern = /^[0-9a-f]{40}$/;
const digestPattern = /^[0-9a-f]{64}$/;

if (!Number.isInteger(attempts) || attempts < 1) throw new Error("Invalid wait attempt count");
if (!Number.isInteger(intervalMs) || intervalMs < 1000) throw new Error("Invalid wait interval");

const accepted = (value) => {
  const observedAt = Date.parse(String(value?.observed_at ?? ""));
  const ageMs = Date.now() - observedAt;
  return (
    value?.status === "ready" &&
    value?.notice === expectedNotice &&
    value?.read_only === true &&
    value?.finalized_only === true &&
    value?.mainnet_changed === false &&
    value?.assets_moved === false &&
    value?.bridge_activated === false &&
    Number.isInteger(value?.head?.height) &&
    value.head.height > 1 &&
    value.head.signed_power === 3 &&
    value.head.total_power === 3 &&
    value?.network?.peer_count === 2 &&
    Number.isFinite(ageMs) &&
    ageMs >= -30_000 &&
    ageMs <= 180_000 &&
    commitPattern.test(value?.runtime_artifact?.source_commit ?? "") &&
    digestPattern.test(value?.runtime_artifact?.genesis_sha256 ?? "") &&
    digestPattern.test(value?.runtime_artifact?.node_artifact_sha256 ?? "")
  );
};

let lastReason = "no readback attempted";
for (let attempt = 1; attempt <= attempts; attempt += 1) {
  try {
    const response = await fetch(explorerUrl, {
      cache: "no-store",
      headers: { Accept: "application/json", "User-Agent": "JUNCA-Docs-Release-Wait/1.0" },
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) {
      lastReason = `HTTP ${response.status}`;
    } else {
      const value = await response.json();
      if (accepted(value)) {
        console.log(`Explorer publication accepted at finalized height ${value.head.height}.`);
        process.exit(0);
      }
      lastReason = `boundary not yet accepted (notice=${JSON.stringify(value?.notice)}, height=${value?.head?.height ?? "missing"}, provenance=${value?.runtime_artifact?.source_commit ? "present" : "missing"})`;
    }
  } catch (error) {
    lastReason = error instanceof Error ? error.message : String(error);
  }
  if (attempt === attempts) break;
  if (attempt === 1 || attempt % 12 === 0) {
    console.log(`Waiting for rolling Explorer publication: attempt ${attempt}/${attempts}; ${lastReason}`);
  }
  await new Promise((resolve) => setTimeout(resolve, intervalMs));
}

throw new Error(`Explorer publication was not accepted after ${attempts} attempts: ${lastReason}`);
