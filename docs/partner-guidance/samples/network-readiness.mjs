export const candidate = Object.freeze({
  name: "JUNCA Social Ecosystem Chain Public Preview Testnet",
  chainId: 20260723,
  rpcUrl: process.env.JUNCA_TESTNET_RPC_URL,
  notice: "Public Testnet / No Monetary Value",
});

export function validateNetworkBinding(config = candidate) {
  if (!config.rpcUrl) {
    throw new Error("BLOCKED: verified RPC binding is required");
  }

  const url = new URL(config.rpcUrl);
  if (url.protocol !== "https:") {
    throw new Error("BLOCKED: RPC binding must use HTTPS");
  }

  return {
    ...config,
    rpcUrl: "[configured / redacted]",
  };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  console.log(JSON.stringify(validateNetworkBinding(), null, 2));
}
