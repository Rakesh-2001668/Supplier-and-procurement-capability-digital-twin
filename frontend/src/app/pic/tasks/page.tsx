'use client';

import Link from 'next/link';
import { TaskDecision } from '@/components/pic/object';
import { Card, Empty, Loading, PageHeader, ProblemBox } from '@/components/pic/ui';
import { useApi } from '@/lib/pic/hooks';
import { docHref } from '@/lib/pic/links';

type Task = { id: string; name: string; kind: string; object_type: string; object_id: string; object_ref: string; candidate_role: string;
  due_at: string | null; escalation_level: number; evidence: Record<string, unknown> };

export default function TaskInbox() {
  const { data, isLoading, error } = useApi<Task[]>('/tasks');
  return (
    <div>
      <PageHeader eyebrow="REQ-03 · Approval inbox" title="Task inbox"
        subtitle="Approvals, steward decisions and reviews waiting for you. You never see tasks on documents you started or already approved (four-eyes)." />
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data?.length ? (
        <Empty title="You're all caught up" hint="New tasks appear here immediately when a document reaches your step." />
      ) : (
        <div className="space-y-4">
          {data.map((t) => {
            const href = docHref(t.object_type, t.object_ref, t.object_id);
            return (
              <Card key={t.id} title={<span>{t.object_type.replace(/_/g, ' ').toLowerCase()} · {href ? <Link className="text-[#1A56DB] hover:underline" href={href}>{t.object_ref}</Link> : t.object_ref}</span>}>
                <TaskDecision task={t} />
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
