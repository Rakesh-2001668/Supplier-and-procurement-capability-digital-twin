'use client';

// Browser client for the PIC API. Calls go to the same-origin /api/pic route, which adds the session token.

export type Problem = {
  status: number;
  code: string;
  title?: string;
  detail?: string;
  ruleRef?: string;
  traceId?: string;
  [key: string]: unknown;
};

export class ApiError extends Error {
  readonly problem: Problem;
  constructor(problem: Problem) {
    super(problem.detail ?? problem.title ?? problem.code);
    this.problem = problem;
  }
  get status() {
    return this.problem.status;
  }
}

export type Paged<T> = { items: T[]; nextCursor: string | null };

type Options = { idempotencyKey?: string | false; ifMatch?: string };

function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function request<T>(method: string, path: string, body?: unknown, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json' };
  if (body !== undefined) headers['content-type'] = 'application/json';
  if (method === 'POST' && options.idempotencyKey !== false) headers['idempotency-key'] = options.idempotencyKey || newKey();
  if (options.ifMatch) headers['if-match'] = options.ifMatch;
  const response = await fetch(`/api/pic/v1${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  });
  if (response.status === 401 && typeof window !== 'undefined' && !window.location.pathname.startsWith('/pic/login')) {
    window.location.href = `/pic/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
  }
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError({ status: response.status, code: data?.code ?? 'ERROR', ...(data ?? {}) });
  }
  return data as T;
}

export const api = {
  get: <T,>(path: string) => request<T>('GET', path),
  post: <T,>(path: string, body?: unknown, options?: Options) => request<T>('POST', path, body ?? {}, options),
  patch: <T,>(path: string, body: unknown, options?: Options) => request<T>('PATCH', path, body, options),
  put: <T,>(path: string, body: unknown, options?: Options) => request<T>('PUT', path, body, options),
};

export async function signIn(tenant: string, email: string, password: string) {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tenant, email, password }),
  });
  const data = await response.json();
  if (!response.ok) throw new ApiError({ status: response.status, code: data?.code ?? 'ERROR', ...data });
  return data.user as SessionUser;
}

export async function signOut() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/pic/login';
}

export type SessionUser = { id: string; name: string; email: string; tenant: string; roles: string[]; supplierId: string | null };

export function readSessionUser(): SessionUser | null {
  if (typeof document === 'undefined') return null;
  const raw = document.cookie.split('; ').find((c) => c.startsWith('pic_user='));
  if (!raw) return null;
  // The value is URI-encoded by us and again by the cookie serialiser: decode until it is JSON.
  let value = raw.slice('pic_user='.length);
  for (let i = 0; i < 3 && !value.startsWith('{'); i++) {
    try {
      value = decodeURIComponent(value);
    } catch {
      return null;
    }
  }
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}
