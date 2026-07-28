# JUNCA Protocol Observability Baseline

## Position

This stack is a development and acceptance-evidence environment. It does not
publish production status and does not modify validator, Public Testnet or
Mainnet state.

## Prerequisite

Start the canonical local validator network first:

```bash
make local-network-up
```

## Start observability

```bash
docker compose -f docker/observability/compose.yaml up -d --build
```

Local access:

- Metrics exporter: `http://127.0.0.1:19108/metrics`
- OpenTelemetry Prometheus export: `http://127.0.0.1:19464/metrics`
- Prometheus: `http://127.0.0.1:19090/`
- Grafana OSS: `http://127.0.0.1:13000/`

## Evidence model

The exporter reads the existing validator `/health` evidence endpoints. It does
not create or estimate chain values. It emits:

- validator availability;
- finalized height per validator;
- peer count;
- authenticated and required vote counts;
- recovery-required state;
- network height divergence;
- finality-certificate convergence;
- explicit Mainnet, asset and bridge safety boundaries.

Missing, malformed or unavailable validator evidence causes the metrics endpoint
to return HTTP 503. Prometheus alerts treat missing, stale and divergent evidence
as fail-closed conditions.

## Boundaries

- Development and acceptance evidence only
- No validator mutation
- No transaction submission
- No hosted observability dependency
- No public-site update
- Mainnet Changed: false
- Assets Moved: false
- Bridge Activated: false
