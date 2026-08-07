from pathlib import Path

build_path = Path("docs/technical-reference/scripts/build.mjs")
build = build_path.read_text(encoding="utf-8")
build_start = build.index("const validateOperationalParity =")
build_end = build.index("const fetchJson =", build_start)
build_function = r'''const validateOperationalParity = (operationalCandidate, explorerCandidate) => {
  const operationalNetwork = operationalCandidate?.network ?? {};
  const candidateHead = explorerCandidate.head;
  const candidateNetwork = explorerCandidate.network;
  const finality = String(operationalNetwork.finality ?? "")
    .replace(/\s+/g, "")
    .split("/")
    .map((value) => integerValue(value));
  const operationalHeight = integerValue(operationalNetwork.height);
  const failures = [];
  if (operationalNetwork.state !== "VERIFIED") failures.push("state");
  if (operationalNetwork.status !== "READY · READ-ONLY") failures.push("status");
  if (integerValue(operationalNetwork.chainId) !== expectedChainId) failures.push("chain_id");
  if (!Number.isInteger(operationalHeight) || operationalHeight <= 1) failures.push("height");
  if (integerValue(operationalNetwork.peers) !== candidateNetwork.peer_count) failures.push("peers");
  if (!(finality.length === 2 && finality[0] === candidateHead.signed_power && finality[1] === candidateHead.total_power)) failures.push("finality");
  if (operationalNetwork.clientVersion !== candidateNetwork.client_version) failures.push("client_version");
  if (!isCommit(operationalNetwork.runtimeSourceCommit)) failures.push("source_commit_format");
  if (!isDigest(operationalNetwork.nodeArtifactSha256)) failures.push("node_artifact_format");
  if (!isDigest(operationalNetwork.genesisSha256)) failures.push("genesis_format");
  if (operationalNetwork.mainnetChanged !== false) failures.push("mainnet_boundary");
  if (operationalNetwork.assetsMoved !== false) failures.push("asset_boundary");
  if (operationalNetwork.bridgeActivated !== false) failures.push("bridge_boundary");
  if (operationalNetwork.source !== explorerUrl) failures.push("canonical_source");
  if (failures.length > 0) {
    console.error(`Operational API corroboration mismatch: ${failures.join(",")}`);
    return false;
  }
  return true;
};
'''
build = build[:build_start] + build_function + build[build_end:]
build_path.write_text(build, encoding="utf-8")

runtime_path = Path("docs/technical-reference/scripts/runtime-current-state-normalize.mjs")
runtime = runtime_path.read_text(encoding="utf-8")
runtime_start = runtime.index("const validateOperational =")
runtime_end = runtime.index("const fetchJson =", runtime_start)
runtime_function = r'''const validateOperational = (operationalCandidate, explorerCandidate) => {
  const candidate = operationalCandidate?.network ?? {};
  const head = explorerCandidate.head;
  const network = explorerCandidate.network;
  const finality = String(candidate.finality ?? "").replace(/\s+/g, "").split("/").map(integerValue);
  const operationalHeight = integerValue(candidate.height);
  const failures = [];
  if (candidate.state !== "VERIFIED") failures.push("state");
  if (candidate.status !== "READY · READ-ONLY") failures.push("status");
  if (integerValue(candidate.chainId) !== expectedChainId) failures.push("chain_id");
  if (!Number.isInteger(operationalHeight) || operationalHeight <= 1) failures.push("height");
  if (integerValue(candidate.peers) !== network.peer_count) failures.push("peers");
  if (!(finality.length === 2 && finality[0] === head.signed_power && finality[1] === head.total_power)) failures.push("finality");
  if (candidate.clientVersion !== network.client_version) failures.push("client_version");
  if (!isCommit(candidate.runtimeSourceCommit)) failures.push("source_commit_format");
  if (!isDigest(candidate.nodeArtifactSha256)) failures.push("node_artifact_format");
  if (!isDigest(candidate.genesisSha256)) failures.push("genesis_format");
  if (candidate.mainnetChanged !== false) failures.push("mainnet_boundary");
  if (candidate.assetsMoved !== false) failures.push("asset_boundary");
  if (candidate.bridgeActivated !== false) failures.push("bridge_boundary");
  if (candidate.source !== explorerUrl) failures.push("canonical_source");
  if (failures.length > 0) {
    console.error(`Operational API corroboration mismatch: ${failures.join(",")}`);
    return false;
  }
  return true;
};
'''
runtime = runtime[:runtime_start] + runtime_function + runtime[runtime_end:]
runtime_path.write_text(runtime, encoding="utf-8")

print(
    "Operational API now corroborates valid runtime provenance independently of Explorer release cadence, "
    "while the canonical Explorer remains the strict rendered-state authority"
)
