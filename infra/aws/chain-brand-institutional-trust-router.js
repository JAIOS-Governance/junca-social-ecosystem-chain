import cf from 'cloudfront';

const CHAIN_HOST = 'chain.jaios-governance.org';
const NATIVE_ORIGIN = 'junca-social-ecosystem-chain.juncajapan-inc.chatgpt.site';
const DOCS_ORIGIN = 'docs.jaios-governance.org';

function useOrigin(domainName) {
  cf.updateRequestOrigin({
    domainName,
    protocol: 'https',
    port: 443,
    sslProtocols: ['TLSv1.2'],
    connectionAttempts: 3,
    connectionTimeout: 10,
    originPath: '',
  });
}

function handler(event) {
  const request = event.request;
  const host = request.headers.host && request.headers.host.value
    ? request.headers.host.value.toLowerCase()
    : '';
  if (host !== CHAIN_HOST) {
    return request;
  }

  if (request.uri === '/' || request.uri === '/index.html') {
    useOrigin(DOCS_ORIGIN);
    request.uri = '/chain-brand-root/index.html';
    return request;
  }
  if (request.uri === '/robots.txt') {
    useOrigin(DOCS_ORIGIN);
    request.uri = '/chain-brand-root/robots.txt';
    return request;
  }
  if (request.uri === '/sitemap.xml') {
    useOrigin(DOCS_ORIGIN);
    request.uri = '/chain-brand-root/sitemap.xml';
    return request;
  }
  if (request.uri === '/runtime-status.json' || request.uri === '/runtime-parity.json') {
    useOrigin(DOCS_ORIGIN);
    request.uri = '/runtime-parity.json';
    return request;
  }
  if (request.uri === '/network-registry.json') {
    useOrigin(DOCS_ORIGIN);
    request.uri = '/network-registry.json';
    return request;
  }

  useOrigin(NATIVE_ORIGIN);
  return request;
}
