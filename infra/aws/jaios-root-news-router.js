import cf from 'cloudfront';

// Release trigger: Chain CloudFront SDK schema repair v2 (no routing change).
const JAIOS_HOST = 'jaios-governance.org';
const CHAIN_HOST = 'chain.jaios-governance.org';
const GOVERNED_ORIGIN = 'docs.jaios-governance.org';
const CHAIN_NATIVE_ORIGIN = 'junca-social-ecosystem-chain.juncajapan-inc.chatgpt.site';
const ROOT_ARTIFACT = '/jaios-root-news/index.html';
const BROWSER_APP_ARTIFACT = '/jaios-browser-app/index.html';
const CHAIN_ROOT_ARTIFACT = '/chain-brand-root/index.html';
const CHAIN_ROBOTS_ARTIFACT = '/chain-brand-root/robots.txt';
const CHAIN_SITEMAP_ARTIFACT = '/chain-brand-root/sitemap.xml';

function routeToOrigin(request, domainName) {
  cf.updateRequestOrigin({
    domainName,
    hostHeader: domainName,
    sni: domainName,
    allowedCertificateNames: [domainName]
  });
}

function routeToGovernedArtifact(request, artifact) {
  request.uri = artifact;
  routeToOrigin(request, GOVERNED_ORIGIN);
}

function handler(event) {
  var request = event.request;
  var hostHeader = request.headers && request.headers.host;
  var host = hostHeader && hostHeader.value ? hostHeader.value.toLowerCase() : '';
  var isRoot = request.uri === '/' || request.uri === '/index.html';
  var isBrowserApp = request.uri === '/browser/app' || request.uri === '/browser/app/';
  var isReadableMethod = request.method === 'GET' || request.method === 'HEAD';

  if (host === JAIOS_HOST) {
    if (isRoot && isReadableMethod) {
      routeToGovernedArtifact(request, ROOT_ARTIFACT);
    } else if (isBrowserApp && isReadableMethod) {
      routeToGovernedArtifact(request, BROWSER_APP_ARTIFACT);
    }
    return request;
  }

  if (host === CHAIN_HOST) {
    if (isReadableMethod && isRoot) {
      routeToGovernedArtifact(request, CHAIN_ROOT_ARTIFACT);
    } else if (isReadableMethod && request.uri === '/robots.txt') {
      routeToGovernedArtifact(request, CHAIN_ROBOTS_ARTIFACT);
    } else if (isReadableMethod && request.uri === '/sitemap.xml') {
      routeToGovernedArtifact(request, CHAIN_SITEMAP_ARTIFACT);
    } else {
      routeToOrigin(request, CHAIN_NATIVE_ORIGIN);
    }
    return request;
  }

  var uri = request.uri;
  if (uri.endsWith('/')) {
    request.uri += 'index.html';
  } else if (!uri.split('/').pop().includes('.')) {
    request.uri += '/index.html';
  }
  return request;
}
