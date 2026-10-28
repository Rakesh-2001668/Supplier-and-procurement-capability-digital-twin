// Server-only helpers for the backend-for-frontend routes.
// The access token lives in an httpOnly cookie and is attached here, so page scripts never see it.

export const SESSION_COOKIE = 'pic_session';
export const USER_COOKIE = 'pic_user';
export const SESSION_MAX_AGE = 8 * 60 * 60; // matches PIC_JWT_TTL_MINUTES (480)

export function apiBase(): string {
  return (process.env.PIC_API_URL ?? 'http://127.0.0.1:8080').replace(/\/$/, '');
}

export function clientIp(headers: Headers): string | null {
  return headers.get('x-forwarded-for') ?? headers.get('x-real-ip');
}
