import cf from 'cloudfront';

const ROOT_ORIGIN = 'docs.jaios-governance.org';
const ROOT_ARTIFACT = '/jaios-root-news/index.html';

function handler(event) {
  const request = event.request;
  const method = request.method;
  const isRoot = request.uri === '/' || request.uri === '/index.html';

  if (isRoot && (method === 'GET' || method === 'HEAD')) {
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
