'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, LinkButton, PageHeader, ProblemBox, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { emailValid } from '../register/tax';
import { useSupplierManager } from './roles';

type Supplier = { id: string; code: string; legal_name: string; status: string; state_code: string; segment: string | null; risk_tier: string | null;
  payment_terms: string; incoterms: string | null; screening: { outcome?: string } | null; categories: Record<string, string> };
type Invitation = { id: string; email: string; legal_name: string; categories: string[]; status: string; expires_at: string; created_at: string;
  registered_at: string | null; supplier: string | null };
type Invited = Invitation & { token: string; registrationUrl: string; emailStatus: string };

export default function Suppliers() {
  const list = useList<Supplier>('/suppliers');
  const canRegister = useSupplierManager();
  const [inviting, setInviting] = useState(false);
  const categories = Array.from(new Set(list.items.flatMap((s) => Object.keys(s.categories ?? {})))).sort();
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="SLM-02 · Supplier lifecycle" title="Suppliers"
        subtitle="Status is held per category: a supplier can be Qualified for one category and only Registered for another. Only Qualified or Preferred suppliers can be invited to sourcing."
        actions={<>
          <LinkButton href="/pic/suppliers/risk">Risk monitor (SLM-04)</LinkButton>
          <LinkButton href="/pic/suppliers/performance">Performance (SLM-03)</LinkButton>
          {canRegister && <Button onClick={() => setInviting(true)}>Invite supplier</Button>}
          {canRegister && <LinkButton variant="primary" href="/pic/suppliers/new">Register supplier</LinkButton>}
        </>} />
      <Card title="Supplier base">
        <DataTable<Supplier>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/suppliers/${encodeURIComponent(r.code)}`} empty="No suppliers"
          columns={[
            { key: 'code', header: 'Code' },
            { key: 'legal_name', header: 'Legal name' },
            { key: 'status', header: 'Supplier status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'categories', header: 'Category status', render: (r) => {
              const entries = Object.entries(r.categories ?? {});
              return entries.length ? (
                <ul className="flex flex-wrap gap-1.5">
                  {entries.map(([cat, st]) => <li key={cat} className="flex items-center gap-1"><span className="font-mono text-[11px] text-slate-600">{cat}</span><StatusChip status={st} /></li>)}
                </ul>
              ) : '–';
            } },
            { key: 'screening', header: 'Screening', render: (r) => (r.screening?.outcome ? <StatusChip status={r.screening.outcome} /> : '–') },
            { key: 'state_code', header: 'State' },
            { key: 'payment_terms', header: 'Terms' },
            { key: 'segment', header: 'Segment', render: (r) => (r.segment ? label(r.segment) : '–') },
          ]}
        />
      </Card>
      {canRegister && <Invitations />}
      {inviting && <InviteDialog categories={categories} onClose={() => setInviting(false)} />}
    </div>
  );
}

function Invitations() {
  const { data, isLoading, error } = useApi<Invitation[]>('/supplier-invitations');
  const revoke = useCommand((id: string) => api.post(`/supplier-invitations/${id}/revoke`, { reason: 'Revoked by supplier manager' }),
    { success: 'Invitation revoked – the link no longer works' });
  if (!isLoading && !error && !data?.length) return null;
  return (
    <Card title="Invitations (F8-01)">
      <DataTable<Invitation> rows={data ?? []} loading={isLoading} error={error} empty="No invitations sent" columns={[
        { key: 'legal_name', header: 'Company' },
        { key: 'email', header: 'Invited e-mail' },
        { key: 'categories', header: 'Categories', render: (i) => i.categories.join(', ') },
        { key: 'status', header: 'Status', render: (i) => <StatusChip status={i.status} /> },
        { key: 'expires_at', header: 'Expires', render: (i) => dateTime(i.expires_at) },
        { key: 'supplier', header: 'Supplier', render: (i) => (i.supplier ? <Link href={`/pic/suppliers/${encodeURIComponent(i.supplier)}`} className="font-medium text-[#1A56DB] hover:underline">{i.supplier}</Link> : '–') },
        { key: 'actions', header: '', render: (i) => (i.status === 'SENT'
          ? <Button variant="danger" busy={revoke.isPending && revoke.variables === i.id} onClick={() => revoke.mutate(i.id)}>Revoke</Button> : null) },
      ]} />
    </Card>
  );
}

function InviteDialog({ categories, onClose }: { categories: string[]; onClose: () => void }) {
  const [email, setEmail] = useState('');
  const [legalName, setLegalName] = useState('');
  const [cats, setCats] = useState('');
  const [copied, setCopied] = useState(false);
  const chosen = cats.split(',').map((c) => c.trim().toUpperCase()).filter(Boolean);
  const valid = emailValid(email) && legalName.trim().length >= 3 && chosen.length > 0;
  const invite = useCommand(() => api.post<Invited>('/supplier-invitations', { email: email.trim(), legalName: legalName.trim(), categories: chosen },
    { idempotencyKey: false }), { success: (r) => `Invitation created for ${r.legal_name}` });
  const result = invite.data;

  const copy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.registrationUrl);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Dialog open title="Invite a supplier to self-register" onClose={onClose}>
      {result ? (
        <div className="space-y-3 text-sm">
          <div role="status" className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900">
            <p className="font-semibold">Copy the registration link now – it is shown only once.</p>
            <p className="text-xs">Only a hash of the token is stored. If the link is lost, revoke this invitation and send a new one.</p>
          </div>
          <Field label="Registration link">{(id) => <Input id={id} readOnly value={result.registrationUrl} onFocus={(e) => e.target.select()} className="font-mono text-xs" />}</Field>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" onClick={copy}>{copied ? 'Copied' : 'Copy link'}</Button>
            <span className="text-slate-600">E-mail to {result.email}: <StatusChip status={result.emailStatus} />
              {result.emailStatus === 'DISABLED' && <span className="ml-1 text-xs">(outbound e-mail is not configured – send the link yourself)</span>}
              {result.emailStatus === 'FAILED' && <span className="ml-1 text-xs">(delivery failed – send the link yourself)</span>}</span>
          </div>
          <p className="text-xs text-slate-500">Valid until {dateTime(result.expires_at)} for {result.categories.join(', ')}. Registration starts screening, the onboarding process and qualification for these categories.</p>
          <div className="flex justify-end"><Button onClick={onClose}>Done</Button></div>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="Company legal name *">{(id) => <Input id={id} value={legalName} onChange={(e) => setLegalName(e.target.value)} />}</Field>
          <Field label="Contact e-mail *" hint="The registration and the portal login are bound to this address">{(id) => (
            <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          )}</Field>
          <Field label="Categories *" hint="Comma-separated; qualification starts for each">{(id) => (
            <>
              <Input id={id} list="invite-cats" value={cats} onChange={(e) => setCats(e.target.value.toUpperCase())} placeholder="e.g. FASTENERS, MRO" />
              <datalist id="invite-cats">{categories.map((c) => <option key={c} value={c} />)}</datalist>
            </>
          )}</Field>
          <ProblemBox error={invite.error} />
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!valid} busy={invite.isPending} onClick={() => invite.mutate()}>Create invitation</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
