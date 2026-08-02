(() => {
  const REFRESH_MS = 15_000;
  const TIMEOUT_MS = 10_000;
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
  const read = async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const response = await fetch("/explorer.json", {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) return;
      const explorer = await response.json();
      if (
        explorer?.status !== "ready" ||
        explorer?.read_only !== true ||
        explorer?.finalized_only !== true ||
        explorer?.mainnet_changed !== false ||
        explorer?.assets_moved !== false ||
        explorer?.bridge_activated !== false
      ) return;
      const head = explorer.head ?? {};
      const network = explorer.network ?? {};
      const artifact = explorer.runtime_artifact ?? {};
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
        `Mainnet Changed: ${explorer.mainnet_changed} · Assets Moved: ${explorer.assets_moved} · Bridge Activated: ${explorer.bridge_activated} · Mainnet Activation Authorized: false.`,
      );
    } catch {
      // Keep the last successful Explorer values and observed_at in view.
    } finally {
      window.clearTimeout(timeout);
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
