import { NextResponse } from 'next/server';
import { SESSION_COOKIE, USER_COOKIE } from '@/lib/pic/server';

export async function POST() {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(SESSION_COOKIE);
  response.cookies.delete(USER_COOKIE);
  return response;
}
