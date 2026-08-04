import cf from 'cloudfront';

const GOVERNED_ORIGIN = 'docs.jaios-governance.org';
const ROOT_ARTIFACT = '/jaios-root-news/index.html';
const BROWSER_APP_ARTIFACT = '/jaios-browser-app/index.html';

function routeToGovernedOrigin(request, artifact) {
  request.uri = artifact;
  cf.updateRequestOrigin({
    domainName: GOVERNED_ORIGIN,
    hostHeader: GOVERNED_ORIGIN,
    sni: GOVERNED_ORIGIN,
    allowedCertificateNames: [GOVERNED_ORIGIN]
  });
}

function handler(event) {
  const request = event.request;
  const method = request.method;
  const isReadable = method === 'GET' || method === 'HEAD';
  const isRoot = request.uri === '/' || request.uri === '/index.html';
  const isBrowserApp = request.uri === '/browser/app' || request.uri === '/browser/app/';

  if (isReadable && isRoot) {
    routeToGovernedOrigin(request, ROOT_ARTIFACT);
  } else if (isReadable && isBrowserApp) {
    routeToGovernedOrigin(request, BROWSER_APP_ARTIFACT);
  }

  return request;
}
