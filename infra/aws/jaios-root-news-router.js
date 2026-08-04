import cf from 'cloudfront';

const JAIOS_HOST = 'jaios-governance.org';
const ROOT_ORIGIN = 'docs.jaios-governance.org';
const ROOT_ARTIFACT = '/jaios-root-news/index.html';

function handler(event) {
  var request = event.request;
  var hostHeader = request.headers && request.headers.host;
  var host = hostHeader && hostHeader.value ? hostHeader.value.toLowerCase() : '';
  var isRoot = request.uri === '/' || request.uri === '/index.html';
  var isReadableMethod = request.method === 'GET' || request.method === 'HEAD';

  if (host === JAIOS_HOST) {
    if (isRoot && isReadableMethod) {
      request.uri = ROOT_ARTIFACT;
      cf.updateRequestOrigin({
        domainName: ROOT_ORIGIN,
        hostHeader: ROOT_ORIGIN,
        sni: ROOT_ORIGIN,
        allowedCertificateNames: [ROOT_ORIGIN]
      });
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
