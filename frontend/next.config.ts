import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV !== 'production';

// Content Security Policy. Next.js App Router injects inline bootstrap scripts, so script-src needs 'unsafe-inline' unless a
// per-request nonce is generated in the proxy (which forces every page to render dynamically). Dev additionally needs
// 'unsafe-eval' (React Refresh) and websocket connections for HMR. All API calls go to the same origin (/api/pic), so
// connect-src stays 'self'. form-action allows https: because an OCI punch-out posts a form to the supplier's catalogue.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ''}`,
  "style-src 'self' 'unsafe-inline'",
  // Legacy demo screens use a world-map SVG from Wikimedia; it is harmless as an image source.
  "img-src 'self' data: blob: https://upload.wikimedia.org",
  "font-src 'self' data:",
  `connect-src 'self'${isDev ? ' ws: wss:' : ''}`,
  "frame-src 'none'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self' https:",
  "manifest-src 'self'",
  "worker-src 'self' blob:",
].join('; ');

const securityHeaders = [
  { key: 'Content-Security-Policy', value: csp },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
  { key: 'Cross-Origin-Resource-Policy', value: 'same-origin' },
  {
    key: 'Permissions-Policy',
    value: 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), magnetometer=(), gyroscope=(), accelerometer=(), browsing-topics=()',
  },
  // Browsers ignore HSTS on plain-HTTP responses, so this is safe for `next start` on localhost; it applies behind TLS.
  ...(isDev ? [] : [{ key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains' }]),
];

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (node server.js).
  output: 'standalone',
  poweredByHeader: false,
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }];
  },
};

export default nextConfig;
