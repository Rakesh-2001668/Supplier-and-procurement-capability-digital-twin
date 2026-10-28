'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { 
  History as HistoryIcon, ShieldCheck, CheckCircle2, AlertTriangle, Clock, 
  ExternalLink, RefreshCw, Search, Filter, Sparkles, 
  Layers, Lock, Database, Check, X, ArrowUpRight,
  FileCheck, AlertOctagon, FileText, Download, Code,
  Building2, Hash, Terminal, UserCheck, Shield
} from 'lucide-react';

interface AuditEvent {
  id: string;
  timestamp: string;
  event_type: string;
  document_id: string;
  document_name: string;
  supplier_id: string;
  supplier_name: string;
  actor: string;
  details: string;
  status: 'SUCCESS' | 'WARNING';
  ip_address: string;
  rules_applied: string[];
}

interface AuditKPIs {
  total_audit_events: number;
  document_events: number;
  verification_events: number;
  user_actions: number;
  policy_violations: number;
}

export default function EvidenceAuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [kpis, setKpis] = useState<AuditKPIs>({
    total_audit_events: 0,
    document_events: 0,
    verification_events: 0,
    user_actions: 0,
    policy_violations: 0
  });
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('All Events');
  const [supplierFilter, setSupplierFilter] = useState<string>('All Suppliers');
  const [statusFilter, setStatusFilter] = useState<string>('All Statuses');
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [drawerTab, setDrawerTab] = useState<'details' | 'json' | 'rules'>('details');

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const fetchAuditTrail = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/evidence/audit-trail');
      if (res.ok) {
        const data = await res.json();
        setEvents(data.events || []);
        if (data.kpis) {
          setKpis(data.kpis);
        }
        if (data.events && data.events.length > 0 && !selectedEventId) {
          setSelectedEventId(data.events[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to load audit trail:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAuditTrail();
  }, []);

  const selectedEvent = useMemo(() => {
    return events.find(e => e.id === selectedEventId) || null;
  }, [events, selectedEventId]);

  // Unique types and suppliers
  const uniqueEventTypes = useMemo(() => {
    return Array.from(new Set(events.map(e => e.event_type))).filter(Boolean);
  }, [events]);

  const uniqueSuppliers = useMemo(() => {
    return Array.from(new Set(events.map(e => e.supplier_name))).filter(Boolean);
  }, [events]);

  // Filtered events
  const filteredEvents = useMemo(() => {
    return events.filter(e => {
      if (eventTypeFilter !== 'All Events' && e.event_type !== eventTypeFilter) return false;
      if (supplierFilter !== 'All Suppliers' && e.supplier_name !== supplierFilter) return false;
      if (statusFilter !== 'All Statuses' && e.status !== statusFilter) return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchDoc = e.document_name.toLowerCase().includes(q);
        const matchSup = e.supplier_name.toLowerCase().includes(q);
        const matchActor = e.actor.toLowerCase().includes(q);
        const matchDet = e.details.toLowerCase().includes(q);
        const matchId = e.id.toLowerCase().includes(q);
        if (!matchDoc && !matchSup && !matchActor && !matchDet && !matchId) return false;
      }

      return true;
    });
  }, [events, eventTypeFilter, supplierFilter, statusFilter, searchQuery]);

  // Export full audit log
  const handleExportAuditLog = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(events, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `evidence_audit_ledger_${new Date().toISOString().split('T')[0]}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    showToast('Exported complete cryptographic audit ledger.');
  };

  const getEventBadge = (type: string) => {
    if (type.includes('VERIFIED')) {
      return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">{type}</span>;
    }
    if (type.includes('CONFLICT') || type.includes('FLAGGED') || type.includes('REJECTED')) {
      return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20">{type}</span>;
    }
    if (type.includes('SCAN') || type.includes('OCR')) {
      return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20">{type}</span>;
    }
    return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-500/10 text-purple-400 border border-purple-500/20">{type}</span>;
  };

  return (
    <div className="flex flex-col h-full bg-[#070B14] text-slate-100 min-h-screen">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0F172A] border border-blue-500/60 text-white px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3 backdrop-blur-md animate-slide-up">
          <Sparkles className="w-5 h-5 text-blue-400 animate-spin" />
          <span className="text-sm font-semibold">{toastMessage}</span>
          <button onClick={() => setToastMessage(null)} className="ml-2 text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Header Area */}
      <div className="border-b border-slate-800/80 bg-[#0B1528] px-8 py-5 shrink-0">
        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
          <div>
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-purple-600 to-indigo-600 text-white flex items-center justify-center shadow-lg shadow-purple-500/20">
                <HistoryIcon className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-extrabold text-purple-400 uppercase tracking-widest">
                  IMMUTABLE DEFENSE LEDGER
                </div>
                <h1 className="text-2xl font-black text-white tracking-tight">Evidence Audit Trail Sentinel</h1>
              </div>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Complete chronological audit trail of all credential uploads, automated OCR validations, manual auditor verifications, and conflict reconciliations.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => fetchAuditTrail()}
              className="px-3.5 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-xs font-bold text-slate-300 hover:text-white transition-all flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-purple-400' : ''}`} />
              Refresh Trail
            </button>
            <button
              onClick={handleExportAuditLog}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-purple-500/20 transition-all flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Export Cryptographic Ledger
            </button>
          </div>
        </div>
      </div>

      {/* Subnav Navigation Bar */}
      <div className="border-b border-slate-800/80 bg-slate-900/40 px-8 flex items-center gap-6 text-xs font-bold shrink-0 overflow-x-auto">
        <Link href="/evidence" className="py-3 text-slate-400 hover:text-slate-200 transition-colors">
          Overview
        </Link>
        <Link href="/evidence/vault" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <Database className="w-3.5 h-3.5" />
          Document Vault
        </Link>
        <Link href="/evidence/verification-queue" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <FileCheck className="w-3.5 h-3.5" />
          Verification Queue
        </Link>
        <Link href="/evidence/conflicts" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
          Conflict Discrepancies
        </Link>
        <Link href="/evidence/integrity" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <Shield className="w-3.5 h-3.5 text-emerald-400" />
          Integrity & Cryptographic Check
        </Link>
        <Link href="/evidence/audit" className="py-3 text-purple-400 border-b-2 border-purple-500 transition-colors flex items-center gap-1.5">
          <HistoryIcon className="w-3.5 h-3.5 text-purple-400" />
          Audit Trail Sentinel
        </Link>
      </div>

      {/* KPI Ribbon */}
      <div className="px-8 py-4 border-b border-slate-800/80 bg-[#0B1528]/40 grid grid-cols-2 md:grid-cols-5 gap-4 shrink-0">
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center font-bold">
            <HistoryIcon className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">Total Audit Events</div>
            <div className="text-xl font-black text-white">{kpis.total_audit_events.toLocaleString()}</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-purple-500/10 text-purple-400 flex items-center justify-center font-bold">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">Document Ingests</div>
            <div className="text-xl font-black text-purple-400">{kpis.document_events.toLocaleString()}</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center font-bold">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">Verifications</div>
            <div className="text-xl font-black text-emerald-400">{kpis.verification_events.toLocaleString()}</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-500/10 text-cyan-400 flex items-center justify-center font-bold">
            <UserCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">User Signoffs</div>
            <div className="text-xl font-black text-cyan-400">{kpis.user_actions.toLocaleString()}</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-rose-500/10 text-rose-400 flex items-center justify-center font-bold">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">Policy Flags</div>
            <div className="text-xl font-black text-rose-400">{kpis.policy_violations.toLocaleString()}</div>
          </div>
        </div>
      </div>

      {/* Main Split Layout: Left Table + Right Drawer */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Table */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden border-r border-slate-800/80">
          
          {/* Filters Bar */}
          <div className="p-4 border-b border-slate-800/80 bg-slate-900/30 flex flex-wrap items-center gap-3 shrink-0">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search audit trail by actor, document, ID, or details..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-purple-500"
              />
            </div>

            <select
              value={eventTypeFilter}
              onChange={(e) => setEventTypeFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-purple-500 font-medium max-w-[180px] truncate"
            >
              <option>All Events</option>
              {uniqueEventTypes.map(t => <option key={t}>{t}</option>)}
            </select>

            <select
              value={supplierFilter}
              onChange={(e) => setSupplierFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-purple-500 font-medium max-w-[180px] truncate"
            >
              <option>All Suppliers</option>
              {uniqueSuppliers.map(s => <option key={s}>{s}</option>)}
            </select>

            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-purple-500 font-medium"
            >
              <option>All Statuses</option>
              <option value="SUCCESS">SUCCESS</option>
              <option value="WARNING">WARNING</option>
            </select>
          </div>

          {/* Table */}
          <div className="flex-1 overflow-y-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="sticky top-0 bg-[#0B1528] text-slate-400 text-[10px] uppercase font-bold tracking-wider border-b border-slate-800 z-10">
                <tr>
                  <th className="py-3 px-4">Event ID / Timestamp</th>
                  <th className="py-3 px-4">Event Type</th>
                  <th className="py-3 px-4">Document</th>
                  <th className="py-3 px-4">Supplier</th>
                  <th className="py-3 px-4">Actor / System</th>
                  <th className="py-3 px-4">Details</th>
                  <th className="py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-medium text-slate-300">
                {filteredEvents.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-500">
                      No audit events found matching filter criteria.
                    </td>
                  </tr>
                ) : (
                  filteredEvents.map((evt) => {
                    const isSelected = selectedEventId === evt.id;
                    return (
                      <tr
                        key={evt.id}
                        onClick={() => setSelectedEventId(evt.id)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-purple-500/10 border-l-2 border-l-purple-500'
                            : 'hover:bg-slate-800/40'
                        }`}
                      >
                        <td className="py-3 px-4">
                          <div className="font-mono text-purple-300 font-bold text-[11px]">{evt.id}</div>
                          <div className="text-[10px] text-slate-500 font-mono mt-0.5">{evt.timestamp.replace('T', ' ').replace('Z', '')}</div>
                        </td>

                        <td className="py-3 px-4">
                          {getEventBadge(evt.event_type)}
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-bold text-white leading-tight max-w-[220px] truncate">{evt.document_name}</div>
                          <div className="text-[10px] text-slate-500 font-mono">{evt.document_id}</div>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-semibold text-slate-200">{evt.supplier_name}</div>
                          <div className="text-[10px] text-slate-500">{evt.supplier_id}</div>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-semibold text-slate-300">{evt.actor}</div>
                          <div className="text-[10px] text-slate-500 font-mono truncate max-w-[140px]">{evt.ip_address}</div>
                        </td>

                        <td className="py-3 px-4 text-slate-400 max-w-[240px] truncate text-[11px]">
                          {evt.details}
                        </td>

                        <td className="py-3 px-4">
                          {evt.status === 'SUCCESS' ? (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                              Success
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                              Warning
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Footer Bar */}
          <div className="px-6 py-2.5 border-t border-slate-800/80 bg-slate-900/60 flex justify-between items-center text-xs text-slate-400 shrink-0">
            <div>
              Showing <span className="text-white font-bold">{filteredEvents.length}</span> of {events.length} chronological audit entries
            </div>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-400"></span> Cryptographic Seal Verified
              </span>
            </div>
          </div>
        </div>

        {/* Right Drawer: Event Inspector */}
        {selectedEvent ? (
          <div className="w-[450px] shrink-0 bg-[#0B1528] border-l border-slate-800 flex flex-col h-full overflow-hidden animate-fade-in">
            {/* Header */}
            <div className="p-5 border-b border-slate-800 bg-slate-900/50 shrink-0">
              <div className="flex justify-between items-start mb-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                  {selectedEvent.id}
                </span>
                {getEventBadge(selectedEvent.event_type)}
              </div>
              <h2 className="text-base font-black text-white leading-snug">{selectedEvent.event_type.replace(/_/g, ' ')}</h2>
              <p className="text-xs text-slate-400 font-mono mt-0.5">{selectedEvent.timestamp}</p>

              {/* Drawer Tabs */}
              <div className="flex gap-4 border-b border-slate-800 mt-4 text-xs font-bold">
                <button
                  onClick={() => setDrawerTab('details')}
                  className={`pb-2 border-b-2 transition-colors ${drawerTab === 'details' ? 'border-purple-500 text-purple-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                >
                  Event Details
                </button>
                <button
                  onClick={() => setDrawerTab('rules')}
                  className={`pb-2 border-b-2 transition-colors ${drawerTab === 'rules' ? 'border-purple-500 text-purple-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                >
                  Rules Applied ({selectedEvent.rules_applied?.length || 0})
                </button>
                <button
                  onClick={() => setDrawerTab('json')}
                  className={`pb-2 border-b-2 transition-colors ${drawerTab === 'json' ? 'border-purple-500 text-purple-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                >
                  Raw JSON Payload
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {drawerTab === 'details' && (
                <>
                  {/* Summary Callout */}
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 space-y-2">
                    <div className="text-[10px] uppercase font-bold text-slate-500">Event Action Log</div>
                    <p className="text-xs text-white leading-relaxed font-sans">{selectedEvent.details}</p>
                  </div>

                  {/* Document & Supplier Link */}
                  <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-3">
                    <div className="flex justify-between items-start">
                      <div>
                        <div className="text-[10px] uppercase font-bold text-slate-500">Target Document</div>
                        <div className="text-xs font-bold text-white mt-0.5">{selectedEvent.document_name}</div>
                        <div className="text-[10px] text-slate-500 font-mono">{selectedEvent.document_id}</div>
                      </div>
                      <Link
                        href={`/evidence/vault`}
                        className="p-1 rounded text-slate-400 hover:text-purple-400 transition-colors"
                        title="View Document in Vault"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </Link>
                    </div>

                    <div className="pt-2 border-t border-slate-800/80">
                      <div className="text-[10px] uppercase font-bold text-slate-500">Supplier Entity</div>
                      <div className="text-xs font-semibold text-slate-200 mt-0.5">{selectedEvent.supplier_name}</div>
                      <div className="text-[10px] text-slate-500 font-mono">{selectedEvent.supplier_id}</div>
                    </div>
                  </div>

                  {/* Execution Actor & Security Origin */}
                  <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 space-y-2.5 text-xs">
                    <div className="flex justify-between py-1 border-b border-slate-800">
                      <span className="text-slate-400">Actor / Initiator</span>
                      <span className="text-white font-bold">{selectedEvent.actor}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-800">
                      <span className="text-slate-400">Security Enclave Origin</span>
                      <span className="font-mono text-purple-300">{selectedEvent.ip_address}</span>
                    </div>
                    <div className="flex justify-between py-1">
                      <span className="text-slate-400">Audit Status</span>
                      <span className="font-bold text-emerald-400">{selectedEvent.status}</span>
                    </div>
                  </div>
                </>
              )}

              {drawerTab === 'rules' && (
                <div className="space-y-3">
                  <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                    Automated Compliance Assertions
                  </div>
                  {selectedEvent.rules_applied && selectedEvent.rules_applied.length > 0 ? (
                    selectedEvent.rules_applied.map((rule, idx) => (
                      <div key={idx} className="bg-slate-900/80 border border-slate-800 p-3 rounded-xl flex items-center gap-3">
                        <div className="w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-400 flex items-center justify-center font-bold text-xs">
                          ✓
                        </div>
                        <div className="text-xs font-bold text-white">{rule}</div>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-slate-500">No rule assertions recorded for this action.</p>
                  )}
                </div>
              )}

              {drawerTab === 'json' && (
                <div className="bg-slate-950 border border-slate-800 rounded-xl p-3 font-mono text-[11px] text-purple-300 overflow-x-auto">
                  <pre>{JSON.stringify(selectedEvent, null, 2)}</pre>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-slate-800 bg-slate-900/80 shrink-0">
              <button
                onClick={() => {
                  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(selectedEvent, null, 2));
                  const downloadAnchor = document.createElement('a');
                  downloadAnchor.setAttribute("href", dataStr);
                  downloadAnchor.setAttribute("download", `${selectedEvent.id}_receipt.json`);
                  document.body.appendChild(downloadAnchor);
                  downloadAnchor.click();
                  downloadAnchor.remove();
                  showToast(`Downloaded event receipt for ${selectedEvent.id}`);
                }}
                className="w-full py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white font-bold text-xs flex items-center justify-center gap-2 transition-all"
              >
                <Download className="w-3.5 h-3.5 text-purple-400" />
                Export Event Cryptographic Receipt
              </button>
            </div>
          </div>
        ) : (
          <div className="w-[450px] shrink-0 bg-[#0B1528] border-l border-slate-800 flex items-center justify-center text-slate-500 text-xs p-6 text-center">
            Select an event from the audit ledger to inspect its cryptographic receipt and rule assertions.
          </div>
        )}
      </div>
    </div>
  );
}
