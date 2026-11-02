'use client';

import { useParams } from 'next/navigation';
import { ObjectPage } from '@/components/pic/object';
import { Facts } from '@/components/pic/ui';
import { date, dateTime, inr } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { CountActions, CountDetail, CountEntry, scopeText, VarianceTable } from '../../_counts';
import { Flag, useRules } from '../../_shared';

const COUNTING = ['PLANNED', 'COUNTING', 'COUNTED'];

export default function CountPage() {
  const { ref } = useParams<{ ref: string }>();
  const number = decodeURIComponent(ref);
  const rules = useRules();
  const { data: c, isLoading, error } = useApi<CountDetail>(`/physical-inventories/${encodeURIComponent(number)}`);
  const me = rules.data?.me;
  const person = (u: CountDetail['createdBy'], at?: string | null) => (u ? `${u.name}${at ? ` · ${dateTime(at)}` : ''}` : '–');
  // The server decides what is revealed: `blind` is true for counters and for users without approval authority.
  const canEnter = !!c && !!me?.canCount && COUNTING.includes(c.status);
  return (
    <ObjectPage
      type="PHYSICAL_INVENTORY" docRef={c?.number ?? ''} eyebrow="INV-04 · Physical inventory" loading={isLoading} error={error}
      title={<>{c?.number} <span className="text-base font-normal text-slate-500">{c?.plant} / {c?.storageLocation}</span></>}
      status={c?.status}
      actions={c && <CountActions count={c} />}
      facts={c && (
        <div className="space-y-3">
          {c.blind && (
            <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
              <Flag tone="info">Blind count</Flag> Book quantities and differences are hidden from you; counters and users without approval authority never see them.
            </p>
          )}
          <Facts items={[
            ['Scope', scopeText(c.scope, c.materialGroup)], ['Description', c.description ?? '–'], ['Planned', date(c.plannedDate)], ['Book quantities frozen', dateTime(c.frozenAt)],
            ['Lines', String(c.lineCount)], ['Counted', `${c.progress.counted} of ${c.progress.lines}`], ['Accepted', String(c.progress.accepted)], ['Awaiting recount', String(c.progress.recountRequired)],
            ...(c.blind ? [] : ([['Gain', inr(c.gainMinor ?? 0)], ['Loss', inr(c.lossMinor ?? 0)], ['First-count accuracy', c.accuracyPct ? `${c.accuracyPct}%` : '–']] as [string, string][])),
            ['Created by', person(c.createdBy, c.createdAt)], ['Submitted by', person(c.submittedBy, c.submittedAt)], ['Approved by', person(c.approvedBy)],
            ['Posted by', person(c.postedBy, c.postedAt)], ['ERP document', c.erpDocument ?? '–'], ['Rule', c.rule ?? '–'],
            ...(c.decisionComment ? [['Decision comment', c.decisionComment] as [string, string]] : []),
          ]} />
        </div>
      )}
      lines={c && (c.blind ? <CountEntry count={c} editable={canEnter} /> : <VarianceTable count={c} />)}
    />
  );
}
