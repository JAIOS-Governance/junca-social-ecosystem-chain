const explorerUrl = "https://explorer.jaios-governance.org/explorer.json";
const originalFetch = globalThis.fetch;

const fixture = {
  schema_version: "junca-public-explorer/v4",
  status: "ready",
  notice: "Public Testnet / Protocol Validation Environment",
  observed_at: new Date().toISOString(),
  read_only: true,
  finalized_only: true,
  network: {
    chain_id: "0x1352773",
    chain_id_decimal: 20260723,
    client_version: "JUNCA-Social-Ecosystem-Chain/public-testnet-python-v1",
    peer_count: 2,
    peer_count_hex: "0x2",
  },
  head: {
    certificate_hash: "0x208ed55acbb135cba61a039318ef942bfb0236ddce5c80f2636ee4a74f3995fa",
    hash: "0x63f659b354eb6d4ff778bb5d32811bd7a625c4e90088ee4beb33db70cd100d22",
    height: 269,
    parent_hash: "0xe2aa58de2255c7566837d7a27aa3c639350ae63bc892d48e5d541b2b9f941546",
    signed_power: 3,
    state_root: "0x4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    timestamp: "0x6a6ddb6a",
    total_power: 3,
    transaction_count: 0,
  },
  runtime_artifact: {
    evidence_source: "approved immutable validator runtime",
    genesis_sha256: "a".repeat(64),
    node_artifact_sha256: "b".repeat(64),
    source_commit: "f444d7e13cb1811d0ca5386978c627be3a48bc00",
  },
  mainnet_changed: false,
  assets_moved: false,
  bridge_activated: false,
};

globalThis.fetch = async (input, init) => {
  const url = input instanceof Request ? input.url : String(input);
  if (url === explorerUrl) {
    return new Response(JSON.stringify(fixture), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }
  return originalFetch(input, init);
};
