import cf from 'cloudfront';

const JAIOS_HOST = 'jaios-governance.org';
const GOVERNED_ORIGIN = 'docs.jaios-governance.org';
const ROOT_ARTIFACT = '/jaios-root-news/index.html';
const BROWSER_APP_ARTIFACT = '/jaios-browser-app/index.html';

function routeToGovernedArtifact(request, artifact) {
  request.uri = artifact;
  cf.updateRequestOrigin({
    domainName: GOVERNED_ORIGIN,
    hostHeader: GOVERNED_ORIGIN,
    sni: GOVERNED_ORIGIN,
    allowedCertificateNames: [GOVERNED_ORIGIN]
  });
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

  var uri = request.uri;
  if (uri.endsWith('/')) {
    request.uri += 'index.html';
  } else if (!uri.split('/').pop().includes('.')) {
    request.uri += '/index.html';
  }
  return request;
}
