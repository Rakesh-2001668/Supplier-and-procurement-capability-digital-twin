'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, DataTable, Dialog, Facts, Field, Input, Loading, PageHeader, ProblemBox, Select, StatusChip, Textarea, type Column } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { useApi } from '@/lib/pic/hooks';
import { dateTime } from '@/lib/pic/format';

// Platform operator console: organisation registration requests (confirmed by the company's shared mailbox) are approved, which provisions
// the organisation and invites its first administrator, or rejected with a reason that is e-mailed to the company. Operators only.

type Row = {
  id: string; number: string; kind: string; status: string; companyName: string; country: string; organisationEmail: string; adminName: string;
  adminEmail: string; screeningOutcome: string | null; createdAt: string; verifiedAt: string | null; organisationCode: string | null;
};
type Detail = Row & {
  stateCode: string | null; industryTemplate: string; gstin: string | null; domain: string; adminPhone: string | null;
  authorisedByName: string | null; authorisedByDesignation: string | null; expectedUsers: number | null; proposedCode: string;
  decidedBy: string | null; decidedAt: string | null; decisionReason: string | null;
  screening: { outcome?: string; sanctionsHits?: string[]; similarOrganisations?: string[]; domainInUse?: boolean; otherRequests?: string[]; providerError?: string | null };
};

const FILTERS = [
  { value: 'PENDING_APPROVAL', label: 'Waiting for a decision' }, { value: 'PENDING_VERIFICATION', label: 'Mailbox not confirmed yet' },
  { value: 'APPROVED', label: 'Approved' }, { value: 'REJECTED', label: 'Rejected' }, { value: 'EXPIRED', label: 'Expired' }, { value: '', label: 'All' },
];

export default function RegistrationsPage() {
  const [filter, setFilter] = useState('PENDING_APPROVAL');
  const [openId, setOpenId] = useState<string | null>(null);
  const list = useApi<Row[]>(`/platform/registrations${filter ? `?status=${filter}` : ''}`);
  const columns: Column<Row>[] = [
    { key: 'number', header: 'Request', render: (r) => (
      <button type="button" onClick={() => setOpenId(r.id)} className="font-mono text-[#1A56DB] hover:underline">{r.number}</button>
    ) },
    { key: 'companyName', header: 'Company', render: (r) => <span>{r.companyName}<span className="block text-xs text-slate-500">{r.kind.toLowerCase()} · {r.country}</span></span> },
    { key: 'organisationEmail', header: 'Shared mailbox' },
    { key: 'adminEmail', header: 'First administrator', render: (r) => <span>{r.adminName}<span className="block text-xs text-slate-500">{r.adminEmail}</span></span> },
    { key: 'screeningOutcome', header: 'Screening', render: (r) => r.screeningOutcome ? <StatusChip status={r.screeningOutcome} /> : '–' },
    { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
    { key: 'createdAt', header: 'Received', render: (r) => dateTime(r.createdAt) },
  ];
  return (
    <div>
      <PageHeader eyebrow="Platform" title="Organisation registrations"
        subtitle="Approve to create the organisation and invite its first administrator; reject with a reason that is sent to the company." />
      <Card actions={
        <label className="flex items-center gap-2 text-sm text-slate-600">Show
          <Select value={filter} onChange={(e) => setFilter(e.target.value)} options={FILTERS} className="w-auto" />
        </label>
      }>
        <DataTable columns={columns} rows={list.data ?? []} loading={list.isLoading} error={list.error} empty="No registration requests" />
      </Card>
      {openId && <Decision id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function Decision({ id, onClose }: { id: string; onClose: () => void }) {
  const client = useQueryClient();
  const detail = useApi<Detail>(`/platform/registrations/${id}`);
  const [code, setCode] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const d = detail.data;

  async function decide(kind: 'approve' | 'reject') {
    setBusy(kind);
    setError(null);
    try {
      if (kind === 'approve') {
        const r = await api.post<{ organisation: string; activationEmail: string }>(`/platform/registrations/${id}/approve`,
          { organisationCode: (code ?? d?.proposedCode ?? '').trim().toUpperCase(), note: note.trim() || null }, { idempotencyKey: false });
        setMessage(`Organisation ${r.organisation} created. Activation e-mail to the first administrator: ${r.activationEmail}.`);
      } else {
        await api.post(`/platform/registrations/${id}/reject`, { reason: reason.trim() }, { idempotencyKey: false });
        setMessage('Rejected. The reason was e-mailed to the shared mailbox.');
      }
      await client.invalidateQueries();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(null);
    }
  }

  const s = d?.screening ?? {};
  const open = d?.status === 'PENDING_APPROVAL';
  return (
    <Dialog open title={d ? `${d.number} · ${d.companyName}` : 'Registration'} onClose={onClose} wide>
      {detail.isLoading || !d ? <Loading /> : (
        <div className="space-y-4">
          <Facts items={[
            ['Type', d.kind === 'BUYER' ? 'Buyer organisation' : 'Supplier organisation'], ['Status', <StatusChip key="s" status={d.status} />],
            ['Country / state', `${d.country}${d.stateCode ? ` / ${d.stateCode}` : ''}`], ['GSTIN', d.gstin ?? '–'], ['Industry', d.industryTemplate],
            ['Shared mailbox', d.organisationEmail], ['Domain', d.domain], ['First administrator', `${d.adminName} · ${d.adminEmail}${d.adminPhone ? ` · ${d.adminPhone}` : ''}`],
            ['Authorised by', d.authorisedByName ? `${d.authorisedByName}, ${d.authorisedByDesignation}` : '–'], ['Expected users', d.expectedUsers ?? '–'],
            ['Mailbox confirmed', d.verifiedAt ? dateTime(d.verifiedAt) : 'not yet'],
          ]} />
          <section className="rounded-lg border border-slate-200 p-3 text-sm">
            <p className="font-medium">Screening {s.outcome ? <StatusChip status={s.outcome} /> : '–'}</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-700">
              <li>Sanctions: {s.sanctionsHits?.length ? s.sanctionsHits.join(', ') : 'no match'}</li>
              <li>Similar organisations already on the platform: {s.similarOrganisations?.length ? s.similarOrganisations.join(', ') : 'none'}</li>
              <li>Domain already used by an organisation: {s.domainInUse ? 'yes' : 'no'}</li>
              <li>Other requests for the domain or GSTIN: {s.otherRequests?.length ? s.otherRequests.join(', ') : 'none'}</li>
              {s.providerError && <li>Sanctions provider not reachable: {s.providerError}</li>}
            </ul>
          </section>
          {d.decidedAt && (
            <p className="text-sm text-slate-700">Decided by {d.decidedBy} on {dateTime(d.decidedAt)}{d.decisionReason ? `: ${d.decisionReason}` : ''}
              {d.organisationCode ? ` · organisation ${d.organisationCode}` : ''}</p>
          )}
          {message && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">{message}</p>}
          <ProblemBox error={error} />
          {open && !message && (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2 rounded-lg border border-slate-200 p-3">
                <p className="font-medium">Approve</p>
                <Field label="Organisation code" hint="2-20 capital letters and digits; users see it in the header">{(fid, hint) => (
                  <Input id={fid} aria-describedby={hint} value={code ?? d.proposedCode} onChange={(e) => setCode(e.target.value.toUpperCase())} className="font-mono" />
                )}</Field>
                <Field label={s.outcome === 'HIT' ? 'Reason for approving despite the sanctions match (required)' : 'Note (optional)'}>{(fid) => (
                  <Textarea id={fid} value={note} onChange={(e) => setNote(e.target.value)} />
                )}</Field>
                <Button variant="primary" busy={busy === 'approve'} disabled={busy !== null} onClick={() => decide('approve')}>Approve and create organisation</Button>
              </div>
              <div className="space-y-2 rounded-lg border border-slate-200 p-3">
                <p className="font-medium">Reject</p>
                <Field label="Reason (sent to the company)" required>{(fid) => (
                  <Textarea id={fid} value={reason} onChange={(e) => setReason(e.target.value)} />
                )}</Field>
                <Button busy={busy === 'reject'} disabled={busy !== null || reason.trim().length < 10} onClick={() => decide('reject')}>Reject</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}
