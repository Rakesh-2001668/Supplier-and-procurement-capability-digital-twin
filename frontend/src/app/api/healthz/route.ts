// Liveness / readiness of the web server itself (container healthcheck, Kubernetes probes, load-balancer health check).
// It deliberately does not call the API: an API outage must not restart or drain the web tier.
export const dynamic = 'force-dynamic';

export function GET() {
  return Response.json({ status: 'ok' }, { headers: { 'cache-control': 'no-store' } });
}
