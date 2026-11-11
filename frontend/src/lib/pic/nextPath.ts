/** A page of this platform to return to after sign-in (PIC or twin screen): a local path only, never another site, the API or a sign-in page. */
export function safeNext(next: string): boolean {
  if (!next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return false;
  const path = next.split(/[?#]/)[0];
  return !['/pic/login', '/login', '/register', '/pic/activate', '/pic/register'].includes(path) && !path.startsWith('/api/');
}
