'use client';

// BPMN viewer (bpmn-js) for workflow definitions: the admin workflow designer and the process tab of every object page.
// The API renders a definition version as BPMN 2.0 XML with layout (GET /process-definitions/{key}/versions/{n}/bpmn); the
// process instance's path colours the steps: passed (green) and the token's current step (amber, pulsing).

import { useEffect, useRef, useState } from 'react';
import 'bpmn-js/dist/assets/diagram-js.css';
import 'bpmn-js/dist/assets/bpmn-js.css';
import { Loading, ProblemBox } from './ui';
import { useApi } from '@/lib/pic/hooks';

type Bpmn = { key: string; version: number; status: string; name: string; xml: string };

type ViewerLike = {
  importXML: (xml: string) => Promise<unknown>;
  get: (name: string) => { zoom: (value: string) => void; addMarker: (id: string, cls: string) => void; removeMarker: (id: string, cls: string) => void };
  destroy: () => void;
};

const STYLE = `
.pic-bpmn .djs-container .pic-done .djs-visual > :first-child { stroke: #059669 !important; stroke-width: 3px !important; fill: #ecfdf5 !important; }
.pic-bpmn .djs-container .pic-active .djs-visual > :first-child { stroke: #d97706 !important; stroke-width: 4px !important; fill: #fffbeb !important; }
.pic-bpmn .djs-container .pic-selected .djs-visual > :first-child { stroke: #1A56DB !important; stroke-width: 3px !important; }
.pic-bpmn .bjs-powered-by { display: none; }
`;

/** Draws BPMN XML read-only. `done` and `active` are step ids; `selected` highlights one step (designer). */
export function BpmnDiagram({ xml, done = [], active = null, selected = null, onSelect, height = 380 }: {
  xml: string; done?: string[]; active?: string | null; selected?: string | null; onSelect?: (id: string) => void; height?: number;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  const viewer = useRef<ViewerLike | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [ready, setReady] = useState(0);
  const onSelectRef = useRef(onSelect);
  useEffect(() => { onSelectRef.current = onSelect; }, [onSelect]);

  useEffect(() => {
    let cancelled = false;
    let created: ViewerLike | null = null;
    (async () => {
      try {
        const { default: NavigatedViewer } = await import('bpmn-js/lib/NavigatedViewer');
        if (cancelled || !host.current) return;
        created = new NavigatedViewer({ container: host.current }) as unknown as ViewerLike;
        viewer.current = created;
        await created.importXML(xml);
        if (cancelled) return;
        created.get('canvas').zoom('fit-viewport');
        const bus = created.get('eventBus') as unknown as { on: (event: string, fn: (e: { element: { id: string } }) => void) => void };
        bus.on('element.click', (e) => onSelectRef.current?.(e.element.id));
        setFailure(null);
        setReady((n) => n + 1);
      } catch (error) {
        if (!cancelled) setFailure((error as Error).message);
      }
    })();
    return () => { cancelled = true; created?.destroy(); viewer.current = null; };
  }, [xml]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || ready === 0) return;
    const canvas = v.get('canvas');
    const marked: [string, string][] = [];
    const mark = (id: string, cls: string) => { try { canvas.addMarker(id, cls); marked.push([id, cls]); } catch { /* step not in this version */ } };
    done.forEach((id) => mark(id, 'pic-done'));
    if (active) mark(active, 'pic-active');
    if (selected) mark(selected, 'pic-selected');
    return () => marked.forEach(([id, cls]) => { try { canvas.removeMarker(id, cls); } catch { /* diagram replaced */ } });
  }, [ready, done, active, selected]);

  return (
    <div className="pic-bpmn">
      <style>{STYLE}</style>
      {failure && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">The diagram could not be drawn: {failure}</p>}
      <div ref={host} style={{ height }} className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white" aria-label="Process diagram" role="img" />
      <ul className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-600">
        <li><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-emerald-500" aria-hidden />Passed</li>
        <li><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full bg-amber-500" aria-hidden />Token is here</li>
      </ul>
    </div>
  );
}

/** Loads the BPMN of one definition version and draws it with the instance's token. */
export function ProcessDiagram({ processKey, version, done, active, selected, onSelect, height }: {
  processKey: string; version: number; done?: string[]; active?: string | null; selected?: string | null; onSelect?: (id: string) => void; height?: number;
}) {
  const { data, isLoading, error } = useApi<Bpmn>(`/process-definitions/${processKey}/versions/${version}/bpmn`);
  if (isLoading) return <Loading text="Loading the diagram…" />;
  if (error || !data) return <ProblemBox error={error} />;
  return <BpmnDiagram xml={data.xml} done={done} active={active} selected={selected} onSelect={onSelect} height={height} />;
}
