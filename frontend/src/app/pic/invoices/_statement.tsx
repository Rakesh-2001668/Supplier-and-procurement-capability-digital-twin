'use client';

import { useState } from 'react';
import { Button, DataTable, Dialog, Field, ProblemBox, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, date, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- bank statement import (camt.053 / camt.052 / camt.054 / MT940)
export type StatementItem = { line: number; part?: number; batch?: boolean; returned?: boolean; amountMinor: number; bankRef: string; valueDate: string;
  payment: string | null; action: string | null; state: string; detail: string };
export type StatementResult = { statementId: string; format: string; account: string; entries: number; counts: Record<string, number>; items: StatementItem[];
  dryRun: boolean; alreadyImported?: boolean; replayed?: boolean; applied?: number; credited?: number; returned?: number };

const FORMAT_TEXT: Record<string, string> = { CAMT053: 'camt.053 statement', CAMT054: 'camt.054 notification', MT940: 'MT940 statement' };

/** What each state means for the person reading the analysis. */
const STATE_TEXT: Record<string, string> = {
  READY: 'will be recorded when you apply',
  UNCHANGED: 'already recorded, nothing to do',
  UNMATCHED: 'no payment number in the entry: left alone',
  AMBIGUOUS: 'names several payments whose amounts do not add up to the entry: left alone, split or correct it at the bank',
  AMOUNT_MISMATCH: 'the bank amount differs from the payment: left alone',
  NO_REFERENCE: 'a credit without a bank reference (UTR): left alone',
  FILE_NOT_SENT: 'the bank file of the run is not marked sent yet',
  CONFLICT: 'contradicts an earlier result: left alone',
  IGNORED: 'a credit that is not the return of a payment',
};

/** A batch booking is one bank entry that carries several payments: one row per payment (the same entry number), grouped under its entry. */
function grouped(items: StatementItem[]) {
  const out: { entry: number; batch: boolean; items: StatementItem[] }[] = [];
  for (const item of items) {
    const last = out[out.length - 1];
    if (last && last.entry === item.line) last.items.push(item);
    else out.push({ entry: item.line, batch: !!item.batch, items: [item] });
  }
  return out;
}

/** Upload a bank statement: the dry run shows what each entry would do to which payment, then it is applied (idempotent per statement id). */
export function StatementImport({ onDone }: { onDone?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<StatementResult | null>(null);
  const send = (dryRun: boolean) => {
    const form = new FormData();
    form.append('file', file as File);
    return api.upload<StatementResult>(`/bank-statements/import?dry_run=${dryRun}`, form);
  };
  const analyse = useCommand(() => send(true), { onSuccess: setResult });
  const apply = useCommand(() => send(false), {
    success: (r) => (r.replayed ? `Statement ${r.statementId} was imported before: nothing changed` : `${r.applied ?? 0} result(s) recorded from ${r.statementId}`),
    onSuccess: (r) => { setResult(r); onDone?.(); },
  });
  const ready = result?.counts?.READY ?? 0;
  const ambiguous = result?.counts?.AMBIGUOUS ?? 0;
  const left = result ? Object.entries(result.counts).filter(([k]) => !['READY', 'UNCHANGED', 'IGNORED'].includes(k)).reduce((n, [, v]) => n + v, 0) : 0;
  const groups = result ? grouped(result.items) : [];
  return (
    <div className="space-y-3">
      <Field label="Bank statement (camt.053, camt.052, camt.054 or MT940)"
        hint="Entries are matched to payments by payment number; a batch booking is split into its payments. A statement id is applied once.">
        {(id, d) => <input id={id} aria-describedby={d} type="file" accept=".xml,.sta,.mt940,.txt,text/xml,text/plain" className="block w-full text-sm"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }} />}
      </Field>
      <ProblemBox error={analyse.error ?? apply.error} />
      {result && (
        <div className="space-y-2" aria-label="Statement analysis">
          <p className="text-sm">
            {FORMAT_TEXT[result.format] ?? result.format} · statement <span className="font-mono">{result.statementId}</span>
            {result.account ? <> · account <span className="font-mono">{result.account}</span></> : null} · {result.entries} line{result.entries === 1 ? '' : 's'}
            {result.alreadyImported ? ' · already imported' : ''}
            {!result.dryRun && result.applied !== undefined ? ` · applied ${result.applied} (${result.credited ?? 0} credited, ${result.returned ?? 0} returned)` : ''}
          </p>
          <ul className="flex flex-wrap gap-2" aria-label="Result counts">
            {Object.entries(result.counts).map(([k, v]) => (
              <li key={k} className="flex items-center gap-1 text-xs"><StatusChip status={k} /><span className="tabular-nums">{v}</span></li>
            ))}
          </ul>
          {ambiguous > 0 && (
            <p role="alert" className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {ambiguous} entr{ambiguous === 1 ? 'y' : 'ies'} name{ambiguous === 1 ? 's' : ''} more than one payment but the payment amounts do not add up to the entry amount, so nothing is
              recorded for {ambiguous === 1 ? 'it' : 'them'} (the totals are in the State column). Ask the bank for the transaction detail or correct the entry.
            </p>
          )}
          {left > 0 && (ready > 0 || left > ambiguous) && (
            <p className="text-xs text-amber-800">
              {left} line{left === 1 ? '' : 's'} will be left alone (unmatched, mismatched or conflicting){ready > 0 ? '; the others are applied' : `: nothing is recorded${result?.dryRun ? ' by this statement' : ''}`}.
            </p>
          )}
          <div className="max-h-80 overflow-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 text-left uppercase tracking-wide text-slate-500">
                <tr><th scope="col" className="px-2 py-1.5">Line</th><th scope="col" className="px-2 py-1.5">Payment</th><th scope="col" className="px-2 py-1.5">Result</th>
                  <th scope="col" className="px-2 py-1.5 text-right">Amount</th><th scope="col" className="px-2 py-1.5">Value date</th>
                  <th scope="col" className="px-2 py-1.5">Bank ref.</th><th scope="col" className="px-2 py-1.5">State</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {groups.map((g) => g.items.map((i, n) => (
                  <tr key={`${i.line}-${i.part ?? 0}`} className={g.batch ? 'bg-blue-50/30' : undefined}>
                    <td className="px-2 py-1.5 align-top">{n === 0 ? i.line : ''}
                      {g.batch && <span className="block text-[10px] font-semibold text-blue-800">batch {i.part ?? n + 1}/{g.items.length}</span>}</td>
                    <td className="px-2 py-1.5 align-top font-mono">{i.payment ?? '–'}</td>
                    <td className="px-2 py-1.5 align-top">{i.action ? label(i.action) : i.returned ? 'Return' : '–'}</td>
                    <td className="px-2 py-1.5 text-right align-top tabular-nums">{inr(i.amountMinor)}</td>
                    <td className="px-2 py-1.5 align-top">{i.valueDate && i.valueDate !== '0001-01-01' ? date(i.valueDate) : '–'}</td>
                    <td className="px-2 py-1.5 align-top font-mono">{i.bankRef || '–'}</td>
                    <td className="px-2 py-1.5 align-top"><StatusChip status={i.state} />
                      <span className="ml-1 text-slate-600">{i.detail}</span>
                      {STATE_TEXT[i.state] && i.state !== 'READY' && i.state !== 'UNCHANGED' ? <span className="block text-[11px] text-slate-500">{STATE_TEXT[i.state]}</span> : null}</td>
                  </tr>
                )))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Button disabled={!file} busy={analyse.isPending} onClick={() => analyse.mutate()}>Analyse (dry run)</Button>
        <Button variant="primary" disabled={!file || !result || !result.dryRun || ready === 0} busy={apply.isPending} onClick={() => apply.mutate()}>
          Apply {ready ? `${ready} result${ready === 1 ? '' : 's'}` : ''}
        </Button>
      </div>
    </div>
  );
}

export function StatementDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog open title="Import bank statement" onClose={onClose} wide>
      <StatementImport />
      <div className="mt-4 flex justify-end"><Button onClick={onClose}>Close</Button></div>
    </Dialog>
  );
}

type Imported = { statementId: string; format: string; account: string | null; entries: number; credited: number; returned: number; importedAt: string };

/** The statements already applied (each id is applied once). */
export function ImportedStatements() {
  const { data, isLoading, error } = useApi<{ items: Imported[] }>('/bank-statements');
  return (
    <DataTable<Imported> rows={(data?.items ?? []).map((s) => ({ ...s, id: s.statementId }))} loading={isLoading} error={error} empty="No bank statement imported yet"
      caption="Imported bank statements" columns={[
        { key: 'statementId', header: 'Statement', render: (s) => <span className="font-mono text-xs">{s.statementId}</span> },
        { key: 'format', header: 'Format', render: (s) => FORMAT_TEXT[s.format] ?? s.format },
        { key: 'account', header: 'Account', render: (s) => s.account ?? '–' },
        { key: 'entries', header: 'Lines', align: 'right' },
        { key: 'credited', header: 'Credited', align: 'right' },
        { key: 'returned', header: 'Returned', align: 'right', render: (s) => (s.returned ? <span className="font-semibold text-amber-700">{s.returned}</span> : '0') },
        { key: 'importedAt', header: 'Imported', render: (s) => dateTime(s.importedAt) },
      ]} />
  );
}
