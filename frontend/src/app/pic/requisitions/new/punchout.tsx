'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Field, Input, ProblemBox, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr, label, qty as fmtQty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import type { Requisition } from '../_components';

// M04 punch-out: shop in the supplier's own catalogue (cXML / OCI); the returned cart becomes catalogue PR lines.

type PunchoutSupplier = { code: string; name: string; status: string; protocol: string; builtin: boolean };
type CartItem = {
  lineNo: number; supplierPartNo: string | null; description: string | null; qty: string; uom: string; unitPriceMinor: number;
  currency: string; unspsc: string | null; classification: Record<string, string> | null;
};
type PunchoutSession = {
  id: string; buyer_cookie: string; protocol: string; status: string; number: string | null; expires_at: string; start_url: string | null;
  supplier: { code: string; name: string }; cart: CartItem[]; totalMinor: number; requisition: string | null;
  startUrl?: string; method?: 'GET' | 'POST'; formFields?: Record<string, string>;
};
type Converted = Requisition & { punchoutSession: PunchoutSession };

const ERRORS: Record<string, string> = {
  PUNCHOUT_SESSION_EXPIRED: 'The punch-out session expired before the cart came back. Start shopping again.',
  PUNCHOUT_SESSION_CLOSED: 'This cart was already received. Start a new punch-out session to shop again.',
  PUNCHOUT_SESSION_NOT_FOUND: 'The supplier returned a cart for an unknown session.',
  EMPTY_CART: 'The supplier returned an empty cart.',
  INVALID_CXML: 'The supplier returned a cart document that could not be read.',
  PROTOCOL_MISMATCH: 'The supplier returned the cart in a different protocol than the session.',
  API_UNAVAILABLE: 'The procurement API was not reachable when the cart came back.',
};

function inDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Send the browser to the supplier: cXML start page (GET) or the OCI form post with HOOK_URL. */
function leaveForSupplier(session: PunchoutSession) {
  const url = session.startUrl ?? session.start_url;
  if (!url) return;
  if (session.method === 'POST') {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = url;
    for (const [name, value] of Object.entries(session.formFields ?? {})) {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      input.value = value;
      form.appendChild(input);
    }
    document.body.appendChild(form);
    form.submit();
    return;
  }
  window.location.assign(url);
}

export function PunchOut({ plant, purposeCode, purposeText, draftLines, cookie, error, onConverted }: {
  plant: string; purposeCode: string; purposeText: string; draftLines: number; cookie: string | null; error: string | null;
  onConverted: (pr: Requisition) => void;
}) {
  const suppliers = useApi<PunchoutSupplier[]>('/punchout/suppliers');
  const session = useApi<PunchoutSession>(cookie ? `/punchout/sessions/${encodeURIComponent(cookie)}` : null);
  const [target, setTarget] = useState('');
  const [needDate, setNeedDate] = useState(inDays(14));
  const [hint, setHint] = useState<string | null>(null);
  const start = useCommand((code: string) => api.post<PunchoutSession>('/punchout/sessions', { supplier: code }, { idempotencyKey: false }), {
    onSuccess: leaveForSupplier,
  });
  const convert = useCommand(() => api.post<Converted>(`/punchout/sessions/${encodeURIComponent(cookie ?? '')}/convert`, {
    requisition: target.trim() || undefined, plant, purposeCode: purposeCode || undefined, purposeText: purposeText || undefined, needDate,
  }), { success: (r) => `${r.lines?.length ?? 0} punch-out line(s) on ${r.number}`, onSuccess: onConverted });

  const list = suppliers.data ?? [];
  const cart = session.data;
  if (!cookie && !error && !list.length && !suppliers.error) return null;

  const add = () => {
    if (!target.trim() && !purposeCode) {
      setHint('Enter the purpose code in the header first (P01), or give an existing draft requisition number.');
      return;
    }
    setHint(null);
    convert.mutate();
  };

  return (
    <Card title="Shop at supplier (punch-out)">
      {error && (
        <div role="alert" className="mb-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {ERRORS[error] ?? `The cart could not be received (${label(error)}).`}
        </div>
      )}
      {cookie && session.error && <div className="mb-3"><ProblemBox error={session.error} /></div>}
      {cart && (
        <div className="mb-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold">Cart from {cart.supplier.name}</span>
            <StatusChip status={cart.status} />
            <span className="text-slate-500">{cart.number} · {cart.protocol} · {cart.cart.length} item(s) · {inr(cart.totalMinor)}</span>
          </div>
          <DataTable<CartItem> rows={cart.cart} empty="The cart is empty" columns={[
            { key: 'supplierPartNo', header: 'Supplier part', render: (i) => <span className="font-mono text-xs">{i.supplierPartNo ?? '–'}</span> },
            { key: 'description', header: 'Description', render: (i) => i.description ?? '–' },
            { key: 'qty', header: 'Quantity', align: 'right', render: (i) => fmtQty(i.qty, i.uom) },
            { key: 'unitPriceMinor', header: 'Unit price', align: 'right', render: (i) => `${inr(i.unitPriceMinor)}${i.currency !== 'INR' ? ` ${i.currency}` : ''}` },
            { key: 'value', header: 'Value', align: 'right', render: (i) => inr(Math.round(Number(i.qty) * i.unitPriceMinor)) },
            { key: 'unspsc', header: 'Classification', render: (i) => Object.entries(i.classification ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ') || '–' },
          ]} />
          {cart.status === 'RETURNED' && (
            <div className="grid gap-3 md:grid-cols-4 md:items-end">
              <Field label="Need date">{(id) => <Input id={id} type="date" value={needDate} onChange={(e) => setNeedDate(e.target.value)} />}</Field>
              <Field label="Existing draft requisition (optional)" hint="Leave empty to create a new catalogue requisition from the header">{(id) => (
                <Input id={id} value={target} onChange={(e) => setTarget(e.target.value.toUpperCase())} placeholder="e.g. REQ-2320" />
              )}</Field>
              <div className="md:col-span-2 flex justify-end">
                <Button type="button" variant="primary" busy={convert.isPending} onClick={add}>Add to requisition</Button>
              </div>
            </div>
          )}
          {cart.status === 'CONVERTED' && cart.requisition && (
            <p className="text-sm">Added to <Link href={`/pic/requisitions/${cart.requisition}`} className="font-medium text-[#1A56DB] hover:underline">{cart.requisition}</Link>.</p>
          )}
          {cart.status === 'OPEN' && <p className="text-sm text-slate-600">Waiting for the supplier to return the cart (session ends {dateTime(cart.expires_at)}).</p>}
          {hint && <p role="alert" className="text-sm text-amber-800">{hint}</p>}
          {convert.error && <ProblemBox error={convert.error} />}
          <p className="text-xs text-slate-500">Lines are added as catalogue lines with the supplier part number, the supplier as preferred source and the returned price.
            Policy, budget and the approval route (DMN-01) are checked when you submit.</p>
        </div>
      )}
      {suppliers.error && <ProblemBox error={suppliers.error} />}
      {list.length > 0 && (
        <div>
          <p className="mb-2 text-sm text-slate-600">Open a supplier&apos;s own web shop; when you transfer the cart it comes back here.
            {draftLines > 0 && <span className="font-medium text-amber-800"> Lines added on this page are not kept while you are away — create the requisition first, then add the cart to it.</span>}</p>
          <ul className="flex flex-wrap gap-2">
            {list.map((s) => (
              <li key={s.code}>
                <Button type="button" busy={start.isPending && start.variables === s.code} onClick={() => start.mutate(s.code)}>
                  Shop at {s.name} <span className="text-xs text-slate-500">({s.protocol}{s.builtin ? ' · test catalogue' : ''})</span>
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
