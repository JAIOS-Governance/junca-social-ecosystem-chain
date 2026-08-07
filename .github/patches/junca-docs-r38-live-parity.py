from pathlib import Path

build_path = Path("docs/technical-reference/scripts/build.mjs")
build = build_path.read_text(encoding="utf-8")
build_start = build.index("const validateOperationalParity =")
build_end = build.index("const fetchJson =", build_start)
build_function = r'''const validateOperationalParity = (operationalCandidate, explorerCandidate) => {
  const operationalNetwork = operationalCandidate?.network ?? {};
  const candidateHead = explorerCandidate.head;
  const candidateNetwork = explorerCandidate.network;
  const artifact = explorerCandidate.runtime_artifact;
  const finality = String(operationalNetwork.finality ?? "")
    .replace(/\s+/g, "")
    .split("/")
    .map((value) => integerValue(value));
  const operationalHeight = integerValue(operationalNetwork.height);
  const explorerHeight = integerValue(candidateHead.height);
  const heightDelta = Math.abs(operationalHeight - explorerHeight);
  const exactHeight = operationalHeight === explorerHeight;
  const exactHeadParity = !exactHeight || (
    operationalNetwork.headHash === candidateHead.hash &&
    operationalNetwork.certificateHash === candidateHead.certificate_hash &&
    operationalNetwork.stateRoot === candidateHead.state_root &&
    operationalNetwork.blockTimestamp === new Date(integerValue(candidateHead.timestamp) * 1000).toISOString() &&
    integerValue(operationalNetwork.transactions) === integerValue(candidateHead.transaction_count)
  );
  return (
    operationalNetwork.state === "VERIFIED" &&
    operationalNetwork.status === "READY · READ-ONLY" &&
    integerValue(operationalNetwork.chainId) === expectedChainId &&
    Number.isInteger(operationalHeight) && operationalHeight > 1 &&
    heightDelta <= 2 &&
    exactHeadParity &&
    integerValue(operationalNetwork.peers) === candidateNetwork.peer_count &&
    finality.length === 2 && finality[0] === candidateHead.signed_power && finality[1] === candidateHead.total_power &&
    operationalNetwork.clientVersion === candidateNetwork.client_version &&
    operationalNetwork.runtimeSourceCommit === artifact.source_commit &&
    operationalNetwork.nodeArtifactSha256 === artifact.node_artifact_sha256 &&
    operationalNetwork.genesisSha256 === artifact.genesis_sha256 &&
    operationalNetwork.mainnetChanged === false &&
    operationalNetwork.assetsMoved === false &&
    operationalNetwork.bridgeActivated === false &&
    operationalNetwork.source === explorerUrl
  );
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
  const artifact = explorerCandidate.runtime_artifact;
  const finality = String(candidate.finality ?? "").replace(/\s+/g, "").split("/").map(integerValue);
  const operationalHeight = integerValue(candidate.height);
  const explorerHeight = integerValue(head.height);
  const heightDelta = Math.abs(operationalHeight - explorerHeight);
  const exactHeight = operationalHeight === explorerHeight;
  const exactHeadParity = !exactHeight || (
    candidate.headHash === head.hash &&
    candidate.certificateHash === head.certificate_hash &&
    candidate.stateRoot === head.state_root &&
    candidate.blockTimestamp === new Date(integerValue(head.timestamp) * 1000).toISOString() &&
    integerValue(candidate.transactions) === integerValue(head.transaction_count)
  );
  return candidate.state === "VERIFIED" && candidate.status === "READY · READ-ONLY" &&
    integerValue(candidate.chainId) === expectedChainId &&
    Number.isInteger(operationalHeight) && operationalHeight > 1 &&
    heightDelta <= 2 && exactHeadParity &&
    integerValue(candidate.peers) === network.peer_count &&
    finality.length === 2 && finality[0] === head.signed_power && finality[1] === head.total_power &&
    candidate.clientVersion === network.client_version &&
    candidate.runtimeSourceCommit === artifact.source_commit &&
    candidate.nodeArtifactSha256 === artifact.node_artifact_sha256 &&
    candidate.genesisSha256 === artifact.genesis_sha256 &&
    candidate.mainnetChanged === false && candidate.assetsMoved === false &&
    candidate.bridgeActivated === false && candidate.source === explorerUrl;
};
'''
runtime = runtime[:runtime_start] + runtime_function + runtime[runtime_end:]
runtime_path.write_text(runtime, encoding="utf-8")

print(
    "Operational API parity now tolerates at most two finalized heights of live advancement "
    "while preserving identity, quorum, provenance and safety gates"
)
