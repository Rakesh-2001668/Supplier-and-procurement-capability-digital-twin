# syntax=docker/dockerfile:1.7
# PIC web workspace (Next.js standalone server).
#   docker build -t pic-web frontend                                        # production build: legacy screens redirect to /pic
#   docker build --build-arg NEXT_PUBLIC_PIC_ENV=dev -t pic-web frontend    # local demo build with the legacy screens
# Runtime: PIC_API_URL (server-side API address, default http://127.0.0.1:8080), PIC_ENV / PIC_ENABLE_LEGACY_DEMO (legacy gate).

ARG NODE_IMAGE=node:22-alpine

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ARG NEXT_PUBLIC_PIC_ENV=production
ARG NEXT_PUBLIC_PIC_LEGACY_DEMO=
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_PIC_ENV=${NEXT_PUBLIC_PIC_ENV} NEXT_PUBLIC_PIC_LEGACY_DEMO=${NEXT_PUBLIC_PIC_LEGACY_DEMO}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM ${NODE_IMAGE} AS run
LABEL org.opencontainers.image.title="pic-web" \
      org.opencontainers.image.description="AlphaHelion Purchasing Intelligence Cloud web workspace" \
      org.opencontainers.image.source="https://github.com/OWNER/supplier-capability-twin"
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0 PIC_ENV=production
RUN apk upgrade --no-cache && addgroup -S -g 10001 web && adduser -S -u 10001 -G web -H -h /app web \
 && mkdir -p /app/.next/cache && chown 10001:10001 /app/.next/cache
# Application files stay root-owned (read-only for the server); only the image cache directory is writable.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER 10001:10001
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/api/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
