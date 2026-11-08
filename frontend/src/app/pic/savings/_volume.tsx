'use client';

import { Fragment, useState } from 'react';
import { Card } from '@/components/pic/ui';
import { date, inr, qty } from '@/lib/pic/format';

// ---------------------------------------------------------------- volume compliance (BP M11 leakage "volume shortfall")
export type VolumePeriod = { period: string; expectedQty: string; invoicedQty: string; cumulativeShortfallQty: string };
export type VolumeLine = {
  contract: string | null; line: number | null; validFrom: string; validTo: string; contractedQty: string; expectedToDateQty: string; invoicedQty: string;
  acceptedQty: string; shortfallQty: string; unitSavingMinor: number; shortfallMinor: number; basis: 'CONTRACT_LINE' | 'INITIATIVE_VOLUME' | string;
  periods: VolumePeriod[];
};
export type Volume = { asOf: string; shortfallMinor: number; method: string; lines: VolumeLine[] };

/** Contracted volume against what is actually bought: per contract line (or the initiative's annual volume when it has no contract line), the
 *  quantity expected by today, invoiced on posted invoices and accepted at receipt, and the savings lost to the shortfall; periods expand. */
export function VolumeCompliance({ volume }: { volume: Volume | undefined }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!volume) return null;
  return (
    <Card title="Volume compliance">
      <p className="mb-3 text-xs text-slate-500">
        As of {date(volume.asOf)}: {volume.method}. Savings lost to the volume shortfall: <span className="font-semibold text-slate-800">{inr(volume.shortfallMinor)}</span>.
      </p>
      {!volume.lines.length ? (
        <p className="text-xs text-slate-500">No contracted volume to compare yet (no contract line for this initiative and no negotiated annual volume in force).</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <caption className="sr-only">Contracted against invoiced volume per contract line</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-2 py-2">Contract line</th><th className="px-2 py-2">Period</th>
                <th className="px-2 py-2 text-right">Contracted</th><th className="px-2 py-2 text-right">Expected to date</th>
                <th className="px-2 py-2 text-right">Invoiced</th><th className="px-2 py-2 text-right">Accepted</th>
                <th className="px-2 py-2 text-right">Shortfall</th><th className="px-2 py-2 text-right">Leakage</th><th className="px-2 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {volume.lines.map((l) => {
                const id = `${l.contract ?? 'initiative'}-${l.line ?? 0}`;
                const short = Number(l.shortfallQty) > 0;
                return (
                  <Fragment key={id}>
                    <tr>
                      <td className="px-2 py-2 font-medium">{l.contract ? `${l.contract} / ${l.line}` : 'Initiative volume'}</td>
                      <td className="px-2 py-2 text-xs">{date(l.validFrom)} – {date(l.validTo)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{qty(l.contractedQty)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{qty(l.expectedToDateQty)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{qty(l.invoicedQty)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{qty(l.acceptedQty)}</td>
                      <td className={`px-2 py-2 text-right tabular-nums ${short ? 'font-semibold text-amber-700' : ''}`}>{qty(l.shortfallQty)}</td>
                      <td className="px-2 py-2 text-right tabular-nums" title={`${inr(l.unitSavingMinor)} saving per unit`}>{inr(l.shortfallMinor)}</td>
                      <td className="px-2 py-2 text-right">
                        {l.periods.length > 0 && (
                          <button type="button" className="text-xs text-[#1A56DB] hover:underline" aria-expanded={open === id}
                            onClick={() => setOpen(open === id ? null : id)}>{open === id ? 'Hide months' : 'Months'}</button>
                        )}
                      </td>
                    </tr>
                    {open === id && l.periods.map((p) => (
                      <tr key={`${id}-${p.period}`} className="bg-slate-50/60 text-xs text-slate-600">
                        <td className="px-2 py-1" />
                        <td className="px-2 py-1">{p.period}</td>
                        <td className="px-2 py-1" />
                        <td className="px-2 py-1 text-right tabular-nums">{qty(p.expectedQty)}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{qty(p.invoicedQty)}</td>
                        <td className="px-2 py-1" />
                        <td className="px-2 py-1 text-right tabular-nums">{qty(p.cumulativeShortfallQty)} cumulative</td>
                        <td className="px-2 py-1" colSpan={2} />
                      </tr>
                    ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
