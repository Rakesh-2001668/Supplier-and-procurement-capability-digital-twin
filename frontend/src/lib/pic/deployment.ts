// Deployment flags shared by the proxy (server) and the workspace shell (browser).
//
// NEXT_PUBLIC_* values are inlined at build time (docker build --build-arg NEXT_PUBLIC_PIC_ENV=production), so the browser can
// read them. The proxy also honours the runtime variables PIC_ENV / PIC_ENABLE_LEGACY_DEMO (same names as the API), so one image
// can be promoted between environments and the legacy screens stay closed even if the build-time flag was forgotten.

function flag(value: string | undefined): boolean | undefined {
  if (value === undefined || value === '') return undefined;
  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
}

function isProduction(env: string | undefined): boolean {
  return ['production', 'prod'].includes((env ?? '').toLowerCase());
}

/** Build-time view (safe in client components): hide links to the legacy prototype screens when false. */
export const legacyDemoEnabled: boolean =
  flag(process.env.NEXT_PUBLIC_PIC_LEGACY_DEMO) ?? !isProduction(process.env.NEXT_PUBLIC_PIC_ENV);

/** Server-side view used by the proxy: runtime variables first, then the build-time ones. Production wins when either says so. */
export function legacyDemoAllowed(): boolean {
  const runtimeProduction = isProduction(process.env.PIC_ENV) || isProduction(process.env.NEXT_PUBLIC_PIC_ENV);
  const explicit = flag(process.env.PIC_ENABLE_LEGACY_DEMO) ?? flag(process.env.NEXT_PUBLIC_PIC_LEGACY_DEMO);
  return explicit ?? !runtimeProduction;
}
