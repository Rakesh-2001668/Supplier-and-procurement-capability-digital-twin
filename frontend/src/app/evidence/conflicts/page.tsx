'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { 
  AlertOctagon, AlertTriangle, CheckCircle2, Clock, 
  ExternalLink, RefreshCw, Search, Filter, Sparkles, 
  Layers, Lock, Database, Check, X, ArrowUpRight,
  FileCheck, Shield, History as HistoryIcon, ArrowRightLeft, UserCheck,
  Building2, Hash, FileText, Plus, Send
} from 'lucide-react';

interface ConflictCase {
  id: string;
  conflict_type: string;
  field: string;
  supplier_id: string;
  supplier_name: string;
  val1: string;
  val2: string;
  doc1_title: string;
  doc1_id?: string;
  doc1_source: string;
  doc2_title: string;
  doc2_id?: string;
  doc2_source: string;
  risk_level: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  status: 'OPEN' | 'IN_REVIEW' | 'RESOLVED' | 'ESCALATED';
  detected_at: string;
  ai_confidence: number;
  ai_analysis: string;
  resolution_history?: Array<{
    timestamp: string;
    action: string;
    actor: string;
    resolution_action?: string;
    notes?: string;
    escalated_to?: string;
  }>;
}

interface ConflictStats {
  total_conflicts: number;
  open_count: number;
  in_review_count: number;
  resolved_count: number;
  escalated_count: number;
  high_risk_count: number;
}

export default function EvidenceConflictsPage() {
  const [conflicts, setConflicts] = useState<ConflictCase[]>([]);
  const [stats, setStats] = useState<ConflictStats>({
    total_conflicts: 0,
    open_count: 0,
    in_review_count: 0,
    resolved_count: 0,
    escalated_count: 0,
    high_risk_count: 0
  });
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('All Statuses');
  const [riskFilter, setRiskFilter] = useState<string>('All Levels');
  const [typeFilter, setTypeFilter] = useState<string>('All Types');
  const [supplierFilter, setSupplierFilter] = useState<string>('All Suppliers');
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Resolution Form
  const [resolutionAction, setResolutionAction] = useState<string>('ACCEPT_DOCUMENT_VALUE');
  const [resolutionNotes, setResolutionNotes] = useState<string>('');

  // Create Conflict Modal
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [newConflictForm, setNewConflictForm] = useState({
    conflict_type: 'Entity Legal Name Mismatch',
    field: 'Company Legal Entity Name',
    supplier_id: 'TWIN-APEX-001',
    supplier_name: 'Apex Precision Machining Ltd',
    val1: '',
    val2: '',
    doc1_title: 'AS9100D Certificate',
    doc2_title: 'Official Commercial Registry',
    risk_level: 'HIGH',
    ai_analysis: ''
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const fetchConflicts = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/evidence/conflicts');
      if (res.ok) {
        const data = await res.json();
        setConflicts(data.conflicts || []);
        setStats({
          total_conflicts: data.total_conflicts,
          open_count: data.open_count,
          in_review_count: data.in_review_count,
          resolved_count: data.resolved_count,
          escalated_count: data.escalated_count,
          high_risk_count: data.high_risk_count
        });
        if (data.conflicts && data.conflicts.length > 0 && !selectedConflictId) {
          setSelectedConflictId(data.conflicts[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to load conflicts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConflicts();
  }, []);

  const selectedConflict = useMemo(() => {
    return conflicts.find(c => c.id === selectedConflictId) || null;
  }, [conflicts, selectedConflictId]);

  // Unique filter sets
  const uniqueTypes = useMemo(() => {
    return Array.from(new Set(conflicts.map(c => c.conflict_type))).filter(Boolean);
  }, [conflicts]);

  const uniqueSuppliers = useMemo(() => {
    return Array.from(new Set(conflicts.map(c => c.supplier_name))).filter(Boolean);
  }, [conflicts]);

  // Filtered conflicts
  const filteredConflicts = useMemo(() => {
    return conflicts.filter(c => {
      if (statusFilter !== 'All Statuses' && c.status !== statusFilter) return false;
      if (riskFilter !== 'All Levels' && c.risk_level !== riskFilter) return false;
      if (typeFilter !== 'All Types' && c.conflict_type !== typeFilter) return false;
      if (supplierFilter !== 'All Suppliers' && c.supplier_name !== supplierFilter) return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchId = c.id.toLowerCase().includes(q);
        const matchType = c.conflict_type.toLowerCase().includes(q);
        const matchField = c.field.toLowerCase().includes(q);
        const matchSupplier = c.supplier_name.toLowerCase().includes(q);
        const matchVal1 = c.val1.toLowerCase().includes(q);
        const matchVal2 = c.val2.toLowerCase().includes(q);
        if (!matchId && !matchType && !matchField && !matchSupplier && !matchVal1 && !matchVal2) return false;
      }

      return true;
    });
  }, [conflicts, statusFilter, riskFilter, typeFilter, supplierFilter, searchQuery]);

  // Actions
  const handleResolve = async (conflictId: string) => {
    try {
      setActionLoading('resolve');
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/conflicts/${conflictId}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resolution_action: resolutionAction,
          notes: resolutionNotes.trim() || `Discrepancy reconciled via ${resolutionAction.replace(/_/g, ' ')}.`,
          resolver_name: 'Lead Defense Compliance Auditor'
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`✓ Conflict ${conflictId} resolved successfully.`);
        setResolutionNotes('');
        await fetchConflicts();
      }
    } catch (err) {
      console.error(err);
      showToast('Resolution failed.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleEscalate = async (conflictId: string) => {
    try {
      setActionLoading('escalate');
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/conflicts/${conflictId}/escalate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: resolutionNotes.trim() || 'Escalated for senior legal oversight & Defense Trade Controls notice.',
          escalated_to: 'Defense & Aerospace Compliance Oversight Committee',
          escalator_name: 'Senior Risk Auditor'
        })
      });
      if (res.ok) {
        showToast(`Conflict ${conflictId} escalated to Defense Oversight Committee.`);
        setResolutionNotes('');
        await fetchConflicts();
      }
    } catch (err) {
      console.error(err);
      showToast('Escalation failed.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/evidence/conflicts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConflictForm)
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Conflict ${data.conflict.id} created.`);
        setShowCreateModal(false);
        await fetchConflicts();
        setSelectedConflictId(data.conflict.id);
      }
    } catch (err) {
      console.error(err);
      showToast('Failed to create conflict case.');
    }
  };

  const getRiskBadge = (risk: string) => {
    switch (risk) {
      case 'CRITICAL':
        return <span className="px-2 py-0.5 rounded text-[10px] font-extrabold bg-rose-500/20 text-rose-400 border border-rose-500/40">CRITICAL</span>;
      case 'HIGH':
        return <span className="px-2 py-0.5 rounded text-[10px] font-extrabold bg-rose-500/10 text-rose-400 border border-rose-500/30">HIGH</span>;
      case 'MEDIUM':
        return <span className="px-2 py-0.5 rounded text-[10px] font-extrabold bg-amber-500/10 text-amber-400 border border-amber-500/30">MEDIUM</span>;
      case 'LOW':
        return <span className="px-2 py-0.5 rounded text-[10px] font-extrabold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">LOW</span>;
      default:
        return <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300">{risk}</span>;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'OPEN':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-1 w-max"><AlertOctagon className="w-3 h-3" /> Open</span>;
      case 'IN_REVIEW':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/30 flex items-center gap-1 w-max"><Clock className="w-3 h-3" /> In Review</span>;
      case 'RESOLVED':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1 w-max"><CheckCircle2 className="w-3 h-3" /> Resolved</span>;
      case 'ESCALATED':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/10 text-purple-400 border border-purple-500/30 flex items-center gap-1 w-max"><AlertTriangle className="w-3 h-3" /> Escalated</span>;
      default:
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-slate-800 text-slate-400">{status}</span>;
    }
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

      {/* Create Conflict Case Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 animate-fade-in">
          <div className="bg-[#0B1528] border border-slate-700 rounded-2xl w-full max-w-xl p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-start">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-blue-500/20 text-blue-400 flex items-center justify-center">
                  <Plus className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">Log Evidence Discrepancy Case</h3>
                  <p className="text-xs text-slate-400">Record conflicting values across supplier credentials and external registers</p>
                </div>
              </div>
              <button onClick={() => setShowCreateModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Conflict Category</label>
                  <input
                    type="text"
                    value={newConflictForm.conflict_type}
                    onChange={(e) => setNewConflictForm({ ...newConflictForm, conflict_type: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500"
                    required
                  />
                </div>
                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Field / Attribute</label>
                  <input
                    type="text"
                    value={newConflictForm.field}
                    onChange={(e) => setNewConflictForm({ ...newConflictForm, field: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500"
                    required
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Supplier Name</label>
                  <input
                    type="text"
                    value={newConflictForm.supplier_name}
                    onChange={(e) => setNewConflictForm({ ...newConflictForm, supplier_name: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500"
                    required
                  />
                </div>
                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Risk Severity</label>
                  <select
                    value={newConflictForm.risk_level}
                    onChange={(e) => setNewConflictForm({ ...newConflictForm, risk_level: e.target.value })}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="CRITICAL">CRITICAL</option>
                    <option value="HIGH">HIGH</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="LOW">LOW</option>
                  </select>
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold block">Document / Certificate Value (Value 1)</label>
                <input
                  type="text"
                  value={newConflictForm.val1}
                  onChange={(e) => setNewConflictForm({ ...newConflictForm, val1: e.target.value })}
                  placeholder="e.g. Apex Precision Machining Ltd (Commercial Registry HRB 99281)"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500"
                  required
                />
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold block">External Registry Value (Value 2)</label>
                <input
                  type="text"
                  value={newConflictForm.val2}
                  onChange={(e) => setNewConflictForm({ ...newConflictForm, val2: e.target.value })}
                  placeholder="e.g. Apex Precision Machining GmbH & Co. KG"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500"
                  required
                />
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold block">Discrepancy Analysis Note</label>
                <textarea
                  value={newConflictForm.ai_analysis}
                  onChange={(e) => setNewConflictForm({ ...newConflictForm, ai_analysis: e.target.value })}
                  placeholder="Provide context on why this discrepancy exists and its operational impact..."
                  rows={3}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-bold shadow-lg shadow-blue-600/30"
                >
                  Create Case
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Header Area */}
      <div className="border-b border-slate-800/80 bg-[#0B1528] px-8 py-5 shrink-0">
        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
          <div>
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-rose-600 to-amber-600 text-white flex items-center justify-center shadow-lg shadow-rose-500/20">
                <AlertOctagon className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-extrabold text-rose-400 uppercase tracking-widest">
                  REGULATORY COMPLIANCE VAULT
                </div>
                <h1 className="text-2xl font-black text-white tracking-tight">Evidence Discrepancies & Conflict Resolution</h1>
              </div>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Automated multi-registry cross-referencing, side-by-side reconciliation, and legal escalation workbench.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => fetchConflicts()}
              className="px-3.5 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-xs font-bold text-slate-300 hover:text-white transition-all flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-blue-400' : ''}`} />
              Refresh Cases
            </button>
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-blue-500/20 transition-all flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              + Log Discrepancy Case
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
        <Link href="/evidence/conflicts" className="py-3 text-rose-400 border-b-2 border-rose-500 transition-colors flex items-center gap-1.5">
          <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
          Conflict Discrepancies ({stats.open_count})
        </Link>
        <Link href="/evidence/integrity" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <Shield className="w-3.5 h-3.5 text-emerald-400" />
          Integrity & Cryptographic Check
        </Link>
        <Link href="/evidence/audit" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <HistoryIcon className="w-3.5 h-3.5 text-purple-400" />
          Audit Trail Sentinel
        </Link>
      </div>

      {/* Quick KPI Strip */}
      <div className="px-8 py-4 border-b border-slate-800/80 bg-[#0B1528]/40 grid grid-cols-2 md:grid-cols-4 gap-4 shrink-0">
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-rose-500/10 text-rose-400 flex items-center justify-center font-bold">
            <AlertOctagon className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">Open Discrepancies</div>
            <div className="text-xl font-black text-rose-400">{stats.open_count}</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center font-bold">
            <Clock className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">In Auditor Review</div>
            <div className="text-xl font-black text-blue-400">{stats.in_review_count}</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center font-bold">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">Reconciled / Resolved</div>
            <div className="text-xl font-black text-emerald-400">{stats.resolved_count}</div>
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 text-amber-400 flex items-center justify-center font-bold">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-bold text-slate-500">High / Critical Severity</div>
            <div className="text-xl font-black text-amber-400">{stats.high_risk_count}</div>
          </div>
        </div>
      </div>

      {/* Main Split Layout: Left Table + Right Detail Drawer */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Table Panel */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden border-r border-slate-800/80">
          
          {/* Filters Bar */}
          <div className="p-4 border-b border-slate-800/80 bg-slate-900/30 flex flex-wrap items-center gap-3 shrink-0">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search conflicts by supplier, field, ID, or value..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-rose-500"
              />
            </div>

            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-rose-500 font-medium"
            >
              <option>All Statuses</option>
              <option value="OPEN">OPEN</option>
              <option value="IN_REVIEW">IN_REVIEW</option>
              <option value="RESOLVED">RESOLVED</option>
              <option value="ESCALATED">ESCALATED</option>
            </select>

            <select
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-rose-500 font-medium"
            >
              <option>All Levels</option>
              <option value="CRITICAL">CRITICAL</option>
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>

            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-rose-500 font-medium max-w-[180px] truncate"
            >
              <option>All Types</option>
              {uniqueTypes.map(t => <option key={t}>{t}</option>)}
            </select>

            <select
              value={supplierFilter}
              onChange={(e) => setSupplierFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-rose-500 font-medium max-w-[180px] truncate"
            >
              <option>All Suppliers</option>
              {uniqueSuppliers.map(s => <option key={s}>{s}</option>)}
            </select>
          </div>

          {/* Table */}
          <div className="flex-1 overflow-y-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="sticky top-0 bg-[#0B1528] text-slate-400 text-[10px] uppercase font-bold tracking-wider border-b border-slate-800 z-10">
                <tr>
                  <th className="py-3 px-4">Conflict / ID</th>
                  <th className="py-3 px-4">Supplier</th>
                  <th className="py-3 px-4">Attribute Mismatch</th>
                  <th className="py-3 px-4">Severity</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Detected</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-medium text-slate-300">
                {filteredConflicts.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-500">
                      No conflict discrepancies found matching filter criteria.
                    </td>
                  </tr>
                ) : (
                  filteredConflicts.map((c) => {
                    const isSelected = selectedConflictId === c.id;
                    return (
                      <tr
                        key={c.id}
                        onClick={() => setSelectedConflictId(c.id)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-rose-500/10 border-l-2 border-l-rose-500'
                            : 'hover:bg-slate-800/40'
                        }`}
                      >
                        <td className="py-3 px-4">
                          <div className="flex items-start gap-2.5">
                            <div className="p-1.5 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/20 shrink-0 mt-0.5">
                              <AlertOctagon className="w-3.5 h-3.5" />
                            </div>
                            <div>
                              <div className="font-bold text-white leading-tight">{c.conflict_type}</div>
                              <div className="text-[10px] text-slate-400 font-mono mt-0.5">{c.id}</div>
                            </div>
                          </div>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-semibold text-slate-200">{c.supplier_name}</div>
                          <div className="text-[10px] text-slate-500">{c.supplier_id}</div>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-semibold text-slate-300">{c.field}</div>
                          <div className="text-[10px] text-slate-500 truncate max-w-[200px]">
                            {c.val1} <span className="text-rose-400 font-bold">vs</span> {c.val2}
                          </div>
                        </td>

                        <td className="py-3 px-4">
                          {getRiskBadge(c.risk_level)}
                        </td>

                        <td className="py-3 px-4">
                          {getStatusBadge(c.status)}
                        </td>

                        <td className="py-3 px-4 text-slate-400 text-[11px] font-mono">
                          {c.detected_at.split('T')[0]}
                        </td>

                        <td className="py-3 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => setSelectedConflictId(c.id)}
                            className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-blue-400 hover:text-white text-[10px] font-bold border border-slate-700 transition-all inline-flex items-center gap-1"
                          >
                            Inspect
                          </button>
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
              Showing <span className="text-white font-bold">{filteredConflicts.length}</span> of {conflicts.length} active discrepancies
            </div>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-rose-400"></span> Multi-Registry Flagged
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-400"></span> Verified Resolvers
              </span>
            </div>
          </div>
        </div>

        {/* Right Conflict Detail & Resolution Drawer */}
        {selectedConflict ? (
          <div className="w-[480px] shrink-0 bg-[#0B1528] border-l border-slate-800 flex flex-col h-full overflow-hidden animate-fade-in">
            {/* Header */}
            <div className="p-5 border-b border-slate-800 bg-slate-900/50 shrink-0">
              <div className="flex justify-between items-start mb-2">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                    {selectedConflict.id}
                  </span>
                  {getRiskBadge(selectedConflict.risk_level)}
                  {getStatusBadge(selectedConflict.status)}
                </div>
              </div>

              <h2 className="text-base font-black text-white leading-snug">{selectedConflict.conflict_type}</h2>
              <div className="text-xs text-slate-400 mt-0.5 flex items-center gap-1.5">
                <Building2 className="w-3.5 h-3.5 text-blue-400" />
                <span>{selectedConflict.supplier_name}</span>
                <span className="text-slate-500">({selectedConflict.supplier_id})</span>
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              
              {/* Field being mismatched */}
              <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 flex justify-between items-center">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Target Attribute</span>
                <span className="text-xs font-black text-white">{selectedConflict.field}</span>
              </div>

              {/* Side-by-Side Comparison Cards */}
              <div className="space-y-3">
                <div className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                  <ArrowRightLeft className="w-3.5 h-3.5 text-rose-400" /> Conflicting Evidence Comparison
                </div>

                {/* Value 1: Uploaded Certificate / Document */}
                <div className="bg-slate-900/90 border border-blue-500/30 rounded-xl p-4 space-y-2 relative overflow-hidden">
                  <div className="absolute top-0 right-0 px-2 py-0.5 rounded-bl bg-blue-500/20 text-blue-300 text-[9px] font-bold">
                    Source 1 • Document Vault
                  </div>
                  <div className="text-[10px] font-bold text-slate-400 uppercase">{selectedConflict.doc1_title}</div>
                  <div className="text-xs font-mono font-bold text-white bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
                    "{selectedConflict.val1}"
                  </div>
                  <div className="text-[10px] text-slate-400 italic">
                    Provenance: {selectedConflict.doc1_source}
                  </div>
                </div>

                {/* Value 2: External Central Registry */}
                <div className="bg-slate-900/90 border border-amber-500/30 rounded-xl p-4 space-y-2 relative overflow-hidden">
                  <div className="absolute top-0 right-0 px-2 py-0.5 rounded-bl bg-amber-500/20 text-amber-300 text-[9px] font-bold">
                    Source 2 • Official Registry
                  </div>
                  <div className="text-[10px] font-bold text-slate-400 uppercase">{selectedConflict.doc2_title}</div>
                  <div className="text-xs font-mono font-bold text-amber-200 bg-slate-950 p-2.5 rounded-lg border border-slate-800/80">
                    "{selectedConflict.val2}"
                  </div>
                  <div className="text-[10px] text-slate-400 italic">
                    Provenance: {selectedConflict.doc2_source}
                  </div>
                </div>
              </div>

              {/* AI Discrepancy & Root Cause Analysis */}
              <div className="bg-slate-900/60 border border-purple-500/30 rounded-xl p-4 space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-xs font-bold text-purple-300 flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-purple-400" /> AI Root Cause Analysis
                  </span>
                  <span className="text-[11px] font-mono text-purple-400 font-bold">
                    Confidence: {selectedConflict.ai_confidence.toFixed(1)}%
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed font-sans">
                  {selectedConflict.ai_analysis}
                </p>
              </div>

              {/* Resolution Action Picker */}
              <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 space-y-3">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider">
                  Reconciliation Protocol
                </h3>
                
                <div className="space-y-2 text-xs">
                  <label className="flex items-start gap-2.5 p-2 rounded-lg bg-slate-950 hover:bg-slate-900 cursor-pointer border border-slate-800 transition-colors">
                    <input
                      type="radio"
                      name="res_action"
                      checked={resolutionAction === 'ACCEPT_DOCUMENT_VALUE'}
                      onChange={() => setResolutionAction('ACCEPT_DOCUMENT_VALUE')}
                      className="mt-0.5 accent-blue-500"
                    />
                    <div>
                      <div className="font-bold text-white">Accept Uploaded Document Value</div>
                      <div className="text-[10px] text-slate-400">Validate document provenance & confirm local aerospace division accuracy.</div>
                    </div>
                  </label>

                  <label className="flex items-start gap-2.5 p-2 rounded-lg bg-slate-950 hover:bg-slate-900 cursor-pointer border border-slate-800 transition-colors">
                    <input
                      type="radio"
                      name="res_action"
                      checked={resolutionAction === 'ACCEPT_REGISTRY_VALUE'}
                      onChange={() => setResolutionAction('ACCEPT_REGISTRY_VALUE')}
                      className="mt-0.5 accent-blue-500"
                    />
                    <div>
                      <div className="font-bold text-white">Reconcile to Official Registry Value</div>
                      <div className="text-[10px] text-slate-400">Standardize to OASIS / VIES / RMI official government directory.</div>
                    </div>
                  </label>

                  <label className="flex items-start gap-2.5 p-2 rounded-lg bg-slate-950 hover:bg-slate-900 cursor-pointer border border-slate-800 transition-colors">
                    <input
                      type="radio"
                      name="res_action"
                      checked={resolutionAction === 'UPDATE_MASTER_DATA'}
                      onChange={() => setResolutionAction('UPDATE_MASTER_DATA')}
                      className="mt-0.5 accent-blue-500"
                    />
                    <div>
                      <div className="font-bold text-white">Update ERP & Digital Twin Master Data</div>
                      <div className="text-[10px] text-slate-400">Propagate reconciled attribute to all procurement and simulation contracts.</div>
                    </div>
                  </label>

                  <label className="flex items-start gap-2.5 p-2 rounded-lg bg-slate-950 hover:bg-slate-900 cursor-pointer border border-slate-800 transition-colors">
                    <input
                      type="radio"
                      name="res_action"
                      checked={resolutionAction === 'REQUEST_RE_AUDIT'}
                      onChange={() => setResolutionAction('REQUEST_RE_AUDIT')}
                      className="mt-0.5 accent-blue-500"
                    />
                    <div>
                      <div className="font-bold text-white">Request Re-Audit / CAPA Clarification</div>
                      <div className="text-[10px] text-slate-400">Issue formal corrective action request to supplier compliance team.</div>
                    </div>
                  </label>
                </div>

                <div className="pt-1">
                  <label className="text-[10px] font-bold uppercase text-slate-400 block mb-1">
                    Auditor Resolution Notes
                  </label>
                  <textarea
                    value={resolutionNotes}
                    onChange={(e) => setResolutionNotes(e.target.value)}
                    placeholder="Enter compliance justification and cross-reference documentation..."
                    rows={2}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              {/* Resolution History Trail */}
              {selectedConflict.resolution_history && selectedConflict.resolution_history.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                    <HistoryIcon className="w-3.5 h-3.5 text-blue-400" /> Case History Log
                  </h3>
                  <div className="space-y-2">
                    {selectedConflict.resolution_history.map((h, i) => (
                      <div key={i} className="bg-slate-900/80 border border-slate-800 rounded-xl p-3 text-xs space-y-1">
                        <div className="flex justify-between items-center">
                          <span className="font-bold text-emerald-400">{h.action}</span>
                          <span className="text-[10px] text-slate-500 font-mono">{h.timestamp}</span>
                        </div>
                        <div className="text-[11px] text-slate-300">Auditor: {h.actor}</div>
                        {h.notes && <div className="text-[10px] text-slate-400 italic">"{h.notes}"</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Footer Buttons */}
            <div className="p-4 border-t border-slate-800 bg-slate-900/80 shrink-0 flex gap-2">
              <button
                onClick={() => handleEscalate(selectedConflict.id)}
                disabled={actionLoading === 'escalate' || selectedConflict.status === 'ESCALATED'}
                className="py-2.5 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-purple-400 hover:text-purple-300 font-bold text-xs flex items-center justify-center gap-1.5 transition-all flex-1"
              >
                {actionLoading === 'escalate' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                Escalate Case
              </button>

              <button
                onClick={() => handleResolve(selectedConflict.id)}
                disabled={actionLoading === 'resolve' || selectedConflict.status === 'RESOLVED'}
                className="py-2.5 px-3 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5 transition-all flex-1"
              >
                {actionLoading === 'resolve' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                Resolve Discrepancy
              </button>
            </div>
          </div>
        ) : (
          <div className="w-[480px] shrink-0 bg-[#0B1528] border-l border-slate-800 flex items-center justify-center text-slate-500 text-xs p-6 text-center">
            Select a discrepancy case from the table to view the side-by-side evidence analysis and resolve.
          </div>
        )}
      </div>
    </div>
  );
}
