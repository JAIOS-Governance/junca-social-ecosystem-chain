(() => {
  const REFRESH_MS = 15_000;
  const TIMEOUT_MS = 10_000;
  const CANONICAL_EXPLORER_URL = "https://explorer.jaios-governance.org/explorer.json";
  const SAME_ORIGIN_PROXY_URL = "/explorer.json";
  const EXPECTED_SCHEMA = "junca-public-explorer/v4";
  const EXPECTED_CHAIN_ID = 20260723;

  const set = (field, value) => {
    if (value === null || value === undefined || value === "") return;
    document.querySelectorAll(`[data-live-runtime="${field}"]`).forEach((element) => {
      element.textContent = String(value);
    });
  };

  const isoTimestamp = (value) => {
    const seconds = typeof value === "string" && value.startsWith("0x")
      ? Number.parseInt(value, 16)
      : Number(value);
    return Number.isFinite(seconds) && seconds > 0
      ? new Date(seconds * 1000).toISOString()
      : "SOURCE REFRESHING";
  };

  const isHash = (value) => /^0x[0-9a-f]{64}$/i.test(String(value ?? ""));
  const isDigest = (value) => /^[0-9a-f]{64}$/i.test(String(value ?? ""));
  const isCommit = (value) => /^[0-9a-f]{40}$/i.test(String(value ?? ""));

  const validate = (explorer) => {
    const head = explorer?.head ?? {};
    const network = explorer?.network ?? {};
    const artifact = explorer?.runtime_artifact ?? {};
    return (
      explorer?.schema_version === EXPECTED_SCHEMA &&
      explorer?.status === "ready" &&
      explorer?.read_only === true &&
      explorer?.finalized_only === true &&
      explorer?.notice === "Public Testnet / Protocol Validation Environment" &&
      explorer?.mainnet_changed === false &&
      explorer?.assets_moved === false &&
      explorer?.bridge_activated === false &&
      Number.isInteger(head.height) &&
      head.height > 1 &&
      head.signed_power === 3 &&
      head.total_power === 3 &&
      isHash(head.hash) &&
      isHash(head.certificate_hash) &&
      isHash(head.state_root) &&
      network.chain_id_decimal === EXPECTED_CHAIN_ID &&
      network.peer_count === 2 &&
      isCommit(artifact.source_commit) &&
      isDigest(artifact.genesis_sha256) &&
      isDigest(artifact.node_artifact_sha256)
    );
  };

  const fetchExplorer = async (url) => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Explorer HTTP ${response.status}`);
      const explorer = await response.json();
      if (!validate(explorer)) throw new Error("Explorer evidence boundary mismatch");
      return explorer;
    } finally {
      window.clearTimeout(timeout);
    }
  };

  const read = async () => {
    try {
      let explorer;
      let source;
      try {
        explorer = await fetchExplorer(CANONICAL_EXPLORER_URL);
        source = "CANONICAL EXPLORER";
      } catch {
        explorer = await fetchExplorer(SAME_ORIGIN_PROXY_URL);
        source = "VERIFIED SAME-ORIGIN PROXY";
      }

      const head = explorer.head;
      const network = explorer.network;
      const artifact = explorer.runtime_artifact;

      set("source", source);
      set("observed-at", explorer.observed_at);
      set("network", "VERIFIED");
      set("runtime", "READY · READ-ONLY");
      set("finality", `${head.signed_power} / ${head.total_power}`);
      set("height", head.height);
      set("hash", head.hash);
      set("certificate-hash", head.certificate_hash);
      set("state-root", head.state_root);
      set("chain-id", network.chain_id_decimal);
      set("client-version", network.client_version);
      set("runtime-source", artifact.source_commit);
      set("genesis", artifact.genesis_sha256);
      set("node-artifact", artifact.node_artifact_sha256);
      set("transactions", head.transaction_count);
      set("peers", network.peer_count);
      set("block-timestamp", isoTimestamp(head.timestamp));
      set(
        "boundaries",
        "Mainnet State: UNCHANGED · Production Asset Boundary: UNCHANGED · Bridge State: GOVERNANCE-CONTROLLED · Mainnet Release: SEPARATE AUTHORIZATION.",
      );
    } catch {
      // Preserve the last verified values. Unverified responses never overwrite the page.
    }
  };

  void read();
  const timer = window.setInterval(read, REFRESH_MS);
  const resume = () => void read();
  window.addEventListener("focus", resume);
  window.addEventListener("online", resume);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void read();
  });
  window.addEventListener("pagehide", () => window.clearInterval(timer), { once: true });
})();
