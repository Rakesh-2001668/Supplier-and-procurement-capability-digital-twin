'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  CheckCircle2, XCircle, AlertTriangle, ShieldAlert, ShieldCheck, 
  Clock, Filter, Search, UserCheck, ArrowRight, RefreshCw, 
  Layers, FileText, ChevronRight, Check, X, Shield, Building2,
  ExternalLink, UserX, AlertOctagon, Sparkles, Send, UserPlus
} from 'lucide-react';
import axios from 'axios';

interface ApprovalItem {
  id: string;
  document_type: string;
  document_ref: string;
  title: string;
  category: string;
  currency: string;
  total_amount: number;
  amount_display: string;
  tier: string;
  tier_level: number;
  sla_hours: number;
  submitted_at: string;
  expires_at: string;
  creator: string;
  creator_role: string;
  current_approvers: string[];
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'RETURNED' | 'DELEGATED';
  sod_rule: string;
  sod_risk: 'Critical' | 'High' | 'Medium' | 'Low';
  sod_description: string;
  commercial_summary: {
    awarded_supplier: string;
    benchmark_should_cost: string;
    awarded_unit_rate: string;
    annual_savings: string;
    non_lowest_justification?: string;
  };
  approval_chain: Array<{
    tier: string;
    role: string;
    assignee: string;
    status: string;
    timestamp?: string | null;
    notes?: string;
  }>;
}

interface SodViolationRecord {
  rule_id: string;
  risk: string;
  message: string;
  conflicting_action: string;
  attempted_action: string;
  actor: string;
  target_object: string;
  blocked_at: string;
  enforcement: string;
}

export default function UnifiedApprovalsPage() {
  const [activeTab, setActiveTab] = useState<'INBOX' | 'SOD_MATRIX' | 'DELEGATIONS'>('INBOX');
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<ApprovalItem | null>(null);
  const [metrics, setMetrics] = useState<any>({});
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Filters
  const [docTypeFilter, setDocTypeFilter] = useState<string>('ALL');
  const [tierFilter, setTierFilter] = useState<string>('ALL');
  const [statusFilter, setStatusFilter] = useState<string>('PENDING');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Simulated Active User Persona (to test SoD blocks vs valid approvals)
  const [currentActor, setCurrentActor] = useState<string>('cpo@alphahelion.com');

  // Drawer / Modal states
  const [rejectModalOpen, setRejectModalOpen] = useState<boolean>(false);
  const [rejectRationale, setRejectRationale] = useState<string>('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [sodPrecheck, setSodPrecheck] = useState<{ can_approve: boolean; conflict_reason?: string; rule_id?: string } | null>(null);
  const [toastMessage, setToastMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // SoD Tab Data
  const [sodMatrixData, setSodMatrixData] = useState<any>(null);
  const [sodViolations, setSodViolations] = useState<SodViolationRecord[]>([]);
  const [delegations, setDelegations] = useState<any[]>([]);

  // New Delegation Modal
  const [delegationModalOpen, setDelegationModalOpen] = useState<boolean>(false);
  const [newDelegator, setNewDelegator] = useState<string>('cpo@alphahelion.com');
  const [newDelegatee, setNewDelegatee] = useState<string>('deputy.cpo@alphahelion.com');
  const [newReason, setNewReason] = useState<string>('Executive Offsite');

  const showToast = (text: string, type: 'success' | 'error') => {
    setToastMessage({ text, type });
    setTimeout(() => setToastMessage(null), 5000);
  };

  const fetchInbox = async () => {
    setIsLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8080/api/v1/approvals/inbox', {
        params: {
          document_type: docTypeFilter,
          tier: tierFilter,
          status: statusFilter
        }
      });
      if (res.data && res.data.items) {
        setItems(res.data.items);
        setMetrics(res.data.metrics || {});
        if (!selectedItem && res.data.items.length > 0) {
          setSelectedItem(res.data.items[0]);
        }
      }
    } catch (err) {
      console.error('Failed to fetch approvals:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchSodAndDelegations = async () => {
    try {
      const [mRes, vRes, dRes] = await Promise.all([
        axios.get('http://127.0.0.1:8080/api/v1/approvals/sod/matrix'),
        axios.get('http://127.0.0.1:8080/api/v1/approvals/sod/violations'),
        axios.get('http://127.0.0.1:8080/api/v1/approvals/delegations')
      ]);
      setSodMatrixData(mRes.data);
      setSodViolations(vRes.data.violations || []);
      setDelegations(dRes.data.delegations || []);
    } catch (err) {
      console.error('Failed to load SoD matrix data:', err);
    }
  };

  useEffect(() => {
    fetchInbox();
  }, [docTypeFilter, tierFilter, statusFilter]);

  useEffect(() => {
    fetchSodAndDelegations();
  }, [activeTab]);

  // When selectedItem or currentActor changes, run SoD pre-check
  useEffect(() => {
    if (!selectedItem) return;
    async function checkSoD() {
      try {
        const res = await axios.get(`http://127.0.0.1:8080/api/v1/approvals/inbox/${selectedItem?.id}`, {
          params: { actor: currentActor }
        });
        setSodPrecheck(res.data.sod_precheck);
      } catch (err) {
        setSodPrecheck(null);
      }
    }
    checkSoD();
  }, [selectedItem, currentActor]);

  const handleApprove = async (item: ApprovalItem) => {
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/approvals/inbox/${item.id}/action`, {
        action: 'APPROVE',
        actor: currentActor
      });
      showToast(res.data.message, 'success');
      fetchInbox();
      fetchSodAndDelegations();
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 403 && detail?.error === 'SEGREGATION_OF_DUTIES_VIOLATION') {
        showToast(`BLOCKED BY ${detail.rule_id}: ${detail.message}`, 'error');
      } else {
        showToast(detail?.message || 'Approval failed due to policy violation.', 'error');
      }
      fetchSodAndDelegations();
    }
  };

  const handleRejectSubmit = async () => {
    if (!selectedItem) return;
    if (rejectRationale.trim().length < 15) {
      showToast('Rejection requires a mandatory written rationale of at least 15 characters.', 'error');
      return;
    }
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/approvals/inbox/${selectedItem.id}/action`, {
        action: 'REJECT',
        actor: currentActor,
        rationale: rejectRationale
      });
      showToast(res.data.message, 'success');
      setRejectModalOpen(false);
      setRejectRationale('');
      fetchInbox();
    } catch (err: any) {
      showToast(err.response?.data?.detail || 'Rejection failed.', 'error');
    }
  };

  const handleBulkApprove = async () => {
    if (selectedIds.length === 0) return;
    try {
      const res = await axios.post('http://127.0.0.1:8080/api/v1/approvals/inbox/bulk-action', {
        approval_ids: selectedIds,
        actor: currentActor
      });
      if (res.data.blocked_count > 0) {
        showToast(`Approved ${res.data.approved_count} items. ${res.data.blocked_count} blocked by SoD conflicts!`, 'error');
      } else {
        showToast(`Successfully bulk-approved ${res.data.approved_count} items.`, 'success');
      }
      setSelectedIds([]);
      fetchInbox();
      fetchSodAndDelegations();
    } catch (err: any) {
      showToast('Bulk approval encountered an error.', 'error');
    }
  };

  const handleCreateDelegation = async () => {
    try {
      const res = await axios.post('http://127.0.0.1:8080/api/v1/approvals/delegations', {
        delegator: newDelegator,
        delegatee: newDelegatee,
        scope: 'ALL_DOCUMENTS',
        valid_from: new Date().toISOString(),
        valid_until: new Date(Date.now() + 7 * 86400000).toISOString(),
        reason: newReason
      });
      showToast(res.data.message, 'success');
      setDelegationModalOpen(false);
      fetchSodAndDelegations();
    } catch (err: any) {
      showToast('Failed to create delegation rule.', 'error');
    }
  };

  const filteredItems = items.filter(item => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      item.id.toLowerCase().includes(q) ||
      item.title.toLowerCase().includes(q) ||
      item.document_ref.toLowerCase().includes(q) ||
      item.creator.toLowerCase().includes(q)
    );
  });

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 space-y-6">
      {/* Toast Notification */}
      {toastMessage && (
        <div className={`fixed top-4 right-4 z-50 flex items-center gap-3 px-4 py-3 rounded-xl border shadow-2xl backdrop-blur-md transition-all animate-bounce ${
          toastMessage.type === 'success' 
            ? 'bg-emerald-950/90 border-emerald-500/80 text-emerald-200' 
            : 'bg-rose-950/90 border-rose-500/80 text-rose-200'
        }`}>
          {toastMessage.type === 'success' ? <CheckCircle2 className="w-5 h-5 text-emerald-400" /> : <AlertOctagon className="w-5 h-5 text-rose-400" />}
          <span className="text-xs font-semibold">{toastMessage.text}</span>
        </div>
      )}

      {/* Page Title & Standards Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono text-cyan-400 font-semibold tracking-wider uppercase bg-cyan-950/60 px-2.5 py-0.5 rounded border border-cyan-800/40">
              Module REQ-03 & Sourcing Governance
            </span>
            <span className="text-xs font-mono text-slate-400">
              DMN-01 4-Tier Spend Matrix & SoD Sentinel (P09)
            </span>
          </div>
          <h1 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight flex items-center gap-3">
            <ShieldCheck className="w-8 h-8 text-cyan-400" />
            Unified Multi-Tier Approval Inbox & SoD Matrix Sentinel
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-3xl">
            Governed authorization engine for RFQ Sourcing Awards, Requisitions, Purchase Orders, and Banking details.
            Enforces strict 4-tier spend thresholds (<span className="text-cyan-300 font-mono">DMN-01</span>) and blocks conflicting self-approvals (<span className="text-rose-400 font-mono">SOD-01..07</span>) at command time.
          </p>
        </div>

        {/* Actor Persona Selector & Quick Actions */}
        <div className="flex items-center gap-3">
          <div className="bg-slate-900 border border-slate-700/80 rounded-lg p-1.5 flex items-center gap-2">
            <span className="text-[11px] text-slate-400 font-mono pl-1">Sign-off Actor:</span>
            <select
              value={currentActor}
              onChange={(e) => setCurrentActor(e.target.value)}
              className="bg-[#0A101D] text-xs font-mono font-bold text-cyan-300 border border-slate-700 rounded px-2 py-1 outline-none focus:border-cyan-500"
            >
              <option value="cpo@alphahelion.com">cpo@alphahelion.com (Independent CPO)</option>
              <option value="amit.verma@alphahelion.com">amit.verma@alphahelion.com (RFQ Creator - SOD-05)</option>
              <option value="priya.sharma@alphahelion.com">priya.sharma@alphahelion.com (PR Requester - SOD-01)</option>
              <option value="category.lead@alphahelion.com">category.lead@alphahelion.com (Category Lead)</option>
              <option value="controller2@alphahelion.com">controller2@alphahelion.com (Dual Finance Signatory)</option>
            </select>
          </div>

          <Link
            href="/bpmn-flows"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 hover:border-cyan-500 text-xs font-semibold text-slate-200 transition-all shadow"
          >
            <Layers className="w-4 h-4 text-cyan-400" />
            BPMN Flows
          </Link>
        </div>
      </div>

      {/* KPI Stats Architecture Ribbon */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center gap-3 shadow-sm">
          <div className="p-3 bg-cyan-500/10 border border-cyan-500/30 rounded-lg text-cyan-400">
            <Clock className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xl font-bold text-white">{metrics.total_pending_count || 0} Pending</div>
            <div className="text-xs text-slate-400">Multi-Tier Approvals</div>
          </div>
        </div>

        <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center gap-3 shadow-sm">
          <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xl font-bold text-white">{metrics.total_rfq_pending_count || 0} RFQ Awards</div>
            <div className="text-xs text-slate-400">Sourcing Waves Requiring Sign-off</div>
          </div>
        </div>

        <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center gap-3 shadow-sm">
          <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400">
            <Building2 className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xl font-bold text-white font-mono">
              ₹{(metrics.total_pending_value_inr || 0).toLocaleString('en-IN')}
            </div>
            <div className="text-xs text-slate-400">Total Spend Under Governance</div>
          </div>
        </div>

        <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center gap-3 shadow-sm">
          <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-lg text-rose-400">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xl font-bold text-rose-300 font-mono">
              {metrics.sod_violations_prevented_today || 0} Violations Blocked
            </div>
            <div className="text-xs text-slate-400">Command-Time SoD Hard Blocks</div>
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex border-b border-slate-800 gap-4">
        <button
          onClick={() => setActiveTab('INBOX')}
          className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'INBOX'
              ? 'border-cyan-400 text-cyan-300 font-bold'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <FileText className="w-4 h-4" />
          Approval Inbox
          <span className="px-1.5 py-0.2 rounded-full text-xs font-mono bg-cyan-950 text-cyan-300 border border-cyan-800">
            {metrics.total_pending_count || items.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('SOD_MATRIX')}
          className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'SOD_MATRIX'
              ? 'border-cyan-400 text-cyan-300 font-bold'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <ShieldAlert className="w-4 h-4 text-rose-400" />
          SoD Conflict Matrix & Sentinel
          <span className="px-1.5 py-0.2 rounded-full text-xs font-mono bg-rose-950 text-rose-300 border border-rose-800">
            7 Rules
          </span>
        </button>

        <button
          onClick={() => setActiveTab('DELEGATIONS')}
          className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'DELEGATIONS'
              ? 'border-cyan-400 text-cyan-300 font-bold'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <UserCheck className="w-4 h-4" />
          Delegation & Out-of-Office Registry
        </button>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: APPROVAL INBOX */}
      {/* ========================================================================= */}
      {activeTab === 'INBOX' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Side: Filterable Inbox List (7 cols) */}
          <div className="lg:col-span-7 space-y-4">
            {/* Filter Toolbar */}
            <div className="p-3 bg-slate-900/80 border border-slate-800 rounded-xl space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                {/* Search */}
                <div className="relative flex-1 min-w-[200px]">
                  <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    placeholder="Search by ID, Title, Creator, or Ref..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-9 pr-3 py-1.5 bg-[#070D18] border border-slate-700/80 rounded-lg text-xs text-white placeholder-slate-500 outline-none focus:border-cyan-500"
                  />
                </div>

                {/* Bulk Actions Button */}
                {selectedIds.length > 0 && (
                  <button
                    onClick={handleBulkApprove}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-bold shadow-md transition-all"
                  >
                    <Check className="w-3.5 h-3.5 stroke-[3]" />
                    Bulk Approve ({selectedIds.length})
                  </button>
                )}
              </div>

              {/* Pills Filters */}
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-slate-500 font-mono text-[11px] mr-1">Doc Type:</span>
                {[
                  { id: 'ALL', label: 'All Docs' },
                  { id: 'RFQ_SOURCING_AWARD', label: 'RFQ Awards' },
                  { id: 'PURCHASE_REQUISITION', label: 'Requisitions' },
                  { id: 'PURCHASE_ORDER', label: 'Purchase Orders' },
                  { id: 'SUPPLIER_BANK_CHANGE', label: 'Vendor Banking' }
                ].map(f => (
                  <button
                    key={f.id}
                    onClick={() => setDocTypeFilter(f.id)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all ${
                      docTypeFilter === f.id
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm'
                        : 'bg-slate-800/60 text-slate-400 hover:bg-slate-700 hover:text-slate-200 border border-slate-700/60'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}

                <div className="h-4 w-px bg-slate-800 mx-1" />

                {/* Tier Filter */}
                <select
                  value={tierFilter}
                  onChange={(e) => setTierFilter(e.target.value)}
                  className="bg-[#0A101D] border border-slate-700 rounded px-2 py-1 text-[11px] font-mono text-slate-300 outline-none"
                >
                  <option value="ALL">All Tiers</option>
                  <option value="Tier 1">Tier 1 (&lt;₹1L)</option>
                  <option value="Tier 2">Tier 2 (₹1L-₹10L)</option>
                  <option value="Tier 3">Tier 3 (₹10L-₹50L)</option>
                  <option value="Tier 4">Tier 4 (&gt;₹50L)</option>
                </select>
              </div>
            </div>

            {/* Inbox Document Cards */}
            <div className="space-y-3">
              {isLoading ? (
                <div className="flex items-center justify-center p-12 text-slate-400">
                  <RefreshCw className="w-6 h-6 animate-spin text-cyan-400 mr-2" />
                  Loading Governed Inbox...
                </div>
              ) : filteredItems.length === 0 ? (
                <div className="p-8 text-center bg-slate-900/40 border border-slate-800 rounded-xl text-slate-400">
                  No documents matching filter criteria.
                </div>
              ) : (
                filteredItems.map(item => {
                  const isSelected = selectedItem?.id === item.id;
                  const isPending = item.status === 'PENDING';
                  const isChecked = selectedIds.includes(item.id);

                  return (
                    <div
                      key={item.id}
                      onClick={() => setSelectedItem(item)}
                      className={`p-4 rounded-xl border transition-all cursor-pointer relative ${
                        isSelected
                          ? 'bg-slate-900/95 border-cyan-500/80 shadow-lg shadow-cyan-500/10 ring-1 ring-cyan-500/30'
                          : 'bg-slate-900/50 hover:bg-slate-850/80 border-slate-800'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3">
                          {/* Checkbox for Bulk Actions */}
                          {isPending && (
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => {
                                if (e.target.checked) setSelectedIds([...selectedIds, item.id]);
                                else setSelectedIds(selectedIds.filter(id => id !== item.id));
                              }}
                              className="mt-1 rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0 cursor-pointer"
                            />
                          )}

                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-mono font-bold text-cyan-300">
                                {item.document_ref}
                              </span>
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                                {item.document_type.replace('_', ' ')}
                              </span>
                              <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                                item.tier_level === 4 
                                  ? 'bg-purple-950 text-purple-300 border border-purple-800' 
                                  : item.tier_level === 3 
                                  ? 'bg-indigo-950 text-indigo-300 border border-indigo-800'
                                  : 'bg-slate-800 text-slate-300'
                              }`}>
                                {item.tier}
                              </span>
                            </div>

                            <h3 className="text-sm font-bold text-white leading-snug line-clamp-1">
                              {item.title}
                            </h3>

                            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400 mt-2">
                              <span>By: <strong className="text-slate-300">{item.creator}</strong></span>
                              <span>•</span>
                              <span>Category: <strong className="text-slate-300">{item.category}</strong></span>
                            </div>
                          </div>
                        </div>

                        {/* Amount & Status Badge */}
                        <div className="text-right shrink-0">
                          <div className="text-base font-extrabold text-white font-mono">
                            {item.amount_display}
                          </div>
                          <span className={`inline-block mt-1 text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                            item.status === 'APPROVED' 
                              ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' 
                              : item.status === 'REJECTED' 
                              ? 'bg-rose-950 text-rose-300 border border-rose-800'
                              : 'bg-amber-950 text-amber-300 border border-amber-800'
                          }`}>
                            {item.status}
                          </span>
                        </div>
                      </div>

                      {/* Bottom Alert / SoD Badge */}
                      <div className="mt-3 pt-2.5 border-t border-slate-800/70 flex items-center justify-between text-xs">
                        <div className="flex items-center gap-1.5 text-slate-400">
                          <Shield className="w-3.5 h-3.5 text-cyan-400" />
                          <span className="font-mono text-[11px] text-slate-300">
                            {item.sod_rule} Conflict Guard Active
                          </span>
                        </div>

                        <div className="flex items-center gap-1.5 text-[11px] font-mono text-amber-400">
                          <Clock className="w-3 h-3" />
                          <span>SLA: {item.sla_hours}h Policy Limit</span>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Right Side: Detailed Inspection & SoD Sign-Off Drawer (5 cols) */}
          <div className="lg:col-span-5">
            {selectedItem ? (
              <div className="sticky top-6 p-6 bg-[#0A101E] border border-slate-800 rounded-xl space-y-6 shadow-2xl">
                {/* Header */}
                <div className="border-b border-slate-800 pb-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono font-bold text-cyan-400">
                      {selectedItem.id}
                    </span>
                    <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                      selectedItem.status === 'APPROVED' ? 'bg-emerald-950 text-emerald-300' : 'bg-amber-950 text-amber-300'
                    }`}>
                      {selectedItem.status}
                    </span>
                  </div>
                  <h2 className="text-lg font-bold text-white mt-1 leading-snug">
                    {selectedItem.title}
                  </h2>
                  <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
                    <span>Document: <strong className="text-slate-200">{selectedItem.document_ref}</strong></span>
                    <span>•</span>
                    <span>Spend: <strong className="text-cyan-300 font-mono">{selectedItem.amount_display}</strong></span>
                  </div>
                </div>

                {/* Commercial Summary Card */}
                <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-lg space-y-2 text-xs">
                  <div className="font-bold text-slate-200 flex items-center justify-between">
                    <span>Commercial & Award Terms</span>
                    <span className="text-[10px] font-mono text-cyan-400">DMN-01 Governed</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-slate-400 pt-1">
                    <div>Supplier: <strong className="text-white block">{selectedItem.commercial_summary.awarded_supplier}</strong></div>
                    <div>Unit Rate: <strong className="text-white block">{selectedItem.commercial_summary.awarded_unit_rate}</strong></div>
                    <div>Benchmark Cost: <strong className="text-slate-300 block">{selectedItem.commercial_summary.benchmark_should_cost}</strong></div>
                    <div>Savings: <strong className="text-emerald-400 block">{selectedItem.commercial_summary.annual_savings}</strong></div>
                  </div>
                  {selectedItem.commercial_summary.non_lowest_justification && (
                    <div className="mt-2 p-2 bg-amber-950/40 border border-amber-800/40 rounded text-[11px] text-amber-300 leading-relaxed">
                      <strong>Non-Lowest Award Justification:</strong> {selectedItem.commercial_summary.non_lowest_justification}
                    </div>
                  )}
                </div>

                {/* Multi-Tier Approval Chain Visual Stepper */}
                <div className="space-y-2">
                  <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider font-mono">
                    Multi-Tier Approval Chain (DMN-01)
                  </h4>
                  <div className="space-y-2">
                    {selectedItem.approval_chain.map((step, idx) => {
                      const isStepApproved = step.status === 'APPROVED';
                      const isStepPending = step.status === 'PENDING';
                      return (
                        <div key={idx} className="flex items-center justify-between p-2.5 bg-slate-900/60 border border-slate-800 rounded-lg text-xs">
                          <div className="flex items-center gap-2.5">
                            <div className={`w-6 h-6 rounded-full flex items-center justify-center font-mono text-[10px] font-bold ${
                              isStepApproved ? 'bg-emerald-500 text-slate-950' : isStepPending ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/50' : 'bg-slate-800 text-slate-400'
                            }`}>
                              {isStepApproved ? <Check className="w-3.5 h-3.5 stroke-[3]" /> : idx + 1}
                            </div>
                            <div>
                              <div className="font-semibold text-white">{step.role} ({step.tier})</div>
                              <div className="text-[11px] text-slate-400 font-mono">{step.assignee}</div>
                            </div>
                          </div>
                          <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                            isStepApproved ? 'bg-emerald-950 text-emerald-300' : isStepPending ? 'bg-amber-950 text-amber-300 animate-pulse' : 'bg-slate-800 text-slate-400'
                          }`}>
                            {step.status}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Live SoD Pre-Check Sentinel Banner */}
                {sodPrecheck && (
                  <div className={`p-3.5 rounded-lg border text-xs leading-relaxed ${
                    sodPrecheck.can_approve
                      ? 'bg-emerald-950/30 border-emerald-500/40 text-emerald-300'
                      : 'bg-rose-950/40 border-rose-500/60 text-rose-300'
                  }`}>
                    <div className="flex items-center gap-2 font-bold mb-1">
                      {sodPrecheck.can_approve ? (
                        <>
                          <ShieldCheck className="w-4 h-4 text-emerald-400" />
                          <span>SoD Validation Passed — Authorized to Sign Off</span>
                        </>
                      ) : (
                        <>
                          <ShieldAlert className="w-4 h-4 text-rose-400" />
                          <span>SoD Hard Block ({sodPrecheck.rule_id}) — Action Prohibited</span>
                        </>
                      )}
                    </div>
                    <p className="text-[11px] text-slate-300">
                      {sodPrecheck.can_approve
                        ? `Actor '${currentActor}' holds independent authority for ${selectedItem.tier} and has no historical creation conflict.`
                        : sodPrecheck.conflict_reason}
                    </p>
                  </div>
                )}

                {/* Action Buttons */}
                {selectedItem.status === 'PENDING' && (
                  <div className="pt-2 border-t border-slate-800 space-y-2">
                    <div className="grid grid-cols-2 gap-3">
                      <button
                        onClick={() => handleApprove(selectedItem)}
                        className="flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shadow-lg shadow-emerald-500/20 transition-all"
                      >
                        <Check className="w-4 h-4 stroke-[2.5]" />
                        Approve Document
                      </button>

                      <button
                        onClick={() => setRejectModalOpen(true)}
                        className="flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/50 text-rose-300 font-bold text-xs transition-all"
                      >
                        <X className="w-4 h-4 stroke-[2.5]" />
                        Reject with Rationale
                      </button>
                    </div>

                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          axios.post(`http://127.0.0.1:8080/api/v1/approvals/inbox/${selectedItem.id}/action`, {
                            action: 'RETURN',
                            actor: currentActor
                          }).then(() => {
                            showToast('Returned document to creator for revision.', 'success');
                            fetchInbox();
                          });
                        }}
                        className="flex-1 py-1.5 rounded bg-slate-900 border border-slate-700 hover:bg-slate-800 text-[11px] font-semibold text-slate-300"
                      >
                        Return for Correction
                      </button>

                      <button
                        onClick={() => {
                          const target = prompt('Enter email address to delegate this document to:');
                          if (target) {
                            axios.post(`http://127.0.0.1:8080/api/v1/approvals/inbox/${selectedItem.id}/action`, {
                              action: 'DELEGATE',
                              actor: currentActor,
                              delegate_to: target
                            }).then(() => {
                              showToast(`Delegated document to ${target}`, 'success');
                              fetchInbox();
                            });
                          }
                        }}
                        className="flex-1 py-1.5 rounded bg-slate-900 border border-slate-700 hover:bg-slate-800 text-[11px] font-semibold text-cyan-300"
                      >
                        Delegate Sign-off
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: SOD CONFLICT MATRIX & SENTINEL */}
      {/* ========================================================================= */}
      {activeTab === 'SOD_MATRIX' && sodMatrixData && (
        <div className="space-y-6">
          {/* Rules Catalog */}
          <div className="p-6 bg-slate-900/70 border border-slate-800 rounded-xl space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-emerald-400" />
                  Segregation of Duties (SoD) Active Catalog (Table 4)
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Principle P09: Command-time enforcement across both humans and autonomous AI agents.
                </p>
              </div>
              <span className="text-xs font-mono px-2.5 py-1 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                Mode: HARD_BLOCK Active
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {sodMatrixData.rules.map((rule: any) => (
                <div key={rule.id} className="p-4 bg-[#090F1C] border border-slate-800 rounded-xl space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono font-bold text-cyan-400">{rule.id}</span>
                    <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                      rule.risk === 'Critical' ? 'bg-rose-950 text-rose-300 border border-rose-800' : 'bg-amber-950 text-amber-300 border border-amber-800'
                    }`}>
                      {rule.risk} Risk
                    </span>
                  </div>
                  <h4 className="text-xs font-bold text-white">{rule.title}</h4>
                  <p className="text-[11px] text-slate-400 leading-relaxed">{rule.description}</p>
                  <div className="mt-2 pt-2 border-t border-slate-800/60 text-[10px] text-slate-300">
                    <strong className="text-slate-400">Mitigation:</strong> {rule.mitigation}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Role Conflict Grid */}
          <div className="p-6 bg-slate-900/70 border border-slate-800 rounded-xl space-y-4">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Layers className="w-5 h-5 text-cyan-400" />
              Role vs Role Segregation of Duties Conflict Grid
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border border-slate-800">
                <thead className="bg-[#0A101D] text-slate-400 font-mono uppercase text-[11px] border-b border-slate-800">
                  <tr>
                    <th className="py-2.5 px-3">Primary Action Role</th>
                    <th className="py-2.5 px-3">Conflicting Target Role</th>
                    <th className="py-2.5 px-3">Governed Rule</th>
                    <th className="py-2.5 px-3">Enforcement Description</th>
                    <th className="py-2.5 px-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-slate-300">
                  {sodMatrixData.conflict_grid.map((c: any, idx: number) => (
                    <tr key={idx} className="hover:bg-slate-850/50">
                      <td className="py-2.5 px-3 font-semibold text-white">{c.role_a}</td>
                      <td className="py-2.5 px-3 font-semibold text-rose-300">{c.role_b}</td>
                      <td className="py-2.5 px-3 font-mono font-bold text-cyan-400">{c.rule}</td>
                      <td className="py-2.5 px-3 text-slate-400">{c.description}</td>
                      <td className="py-2.5 px-3 font-mono text-emerald-400 font-bold">BLOCKED</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Live SoD Violation Sentinel Log */}
          <div className="p-6 bg-slate-900/70 border border-slate-800 rounded-xl space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <ShieldAlert className="w-5 h-5 text-rose-400" />
                  Live SoD Violation Sentinel Ledger (Real-Time Block Log)
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Complete audit trail of unauthorized self-approval attempts blocked by the engine.
                </p>
              </div>
              <span className="text-xs font-mono text-slate-400">
                {sodViolations.length} Violations Logged
              </span>
            </div>

            <div className="space-y-2">
              {sodViolations.map((v, idx) => (
                <div key={idx} className="p-3 bg-rose-950/20 border border-rose-900/40 rounded-lg flex items-center justify-between gap-4 text-xs">
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">
                      {v.rule_id}
                    </span>
                    <div>
                      <div className="font-semibold text-white">{v.message}</div>
                      <div className="text-[11px] font-mono text-slate-400 mt-0.5">
                        Actor: <strong className="text-rose-300">{v.actor}</strong> | Target: {v.target_object}
                      </div>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold border border-rose-500/40">
                      HARD_BLOCK
                    </span>
                    <div className="text-[10px] text-slate-500 font-mono mt-1">{v.blocked_at}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: DELEGATIONS REGISTRY */}
      {/* ========================================================================= */}
      {activeTab === 'DELEGATIONS' && (
        <div className="p-6 bg-slate-900/70 border border-slate-800 rounded-xl space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <UserCheck className="w-5 h-5 text-cyan-400" />
                Active Out-of-Office & Role Delegation Registry
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Authorized proxy routing when primary sign-off authorities are on leave or traveling.
              </p>
            </div>

            <button
              onClick={() => setDelegationModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-bold shadow transition-all"
            >
              <UserPlus className="w-4 h-4" />
              Register New Delegation
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {delegations.map(del => (
              <div key={del.id} className="p-4 bg-[#090F1C] border border-slate-800 rounded-xl space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-bold text-cyan-300">{del.id}</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                    Active
                  </span>
                </div>
                <div className="text-xs text-slate-300">
                  Delegator: <strong className="text-white block">{del.delegator}</strong>
                </div>
                <div className="text-xs text-slate-300">
                  Delegatee: <strong className="text-cyan-300 block">{del.delegatee}</strong>
                </div>
                <div className="text-[11px] text-slate-400">
                  Scope: <strong className="text-slate-200">{del.scope}</strong>
                </div>
                <div className="text-[11px] text-slate-400 italic">
                  "{del.reason}"
                </div>
                <div className="mt-2 pt-2 border-t border-slate-800/60 text-[10px] font-mono text-slate-500">
                  Valid Until: {del.valid_until}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Reject Rationale Modal */}
      {rejectModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0B1322] border border-slate-700 rounded-xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-2 text-rose-400 font-bold">
              <XCircle className="w-5 h-5" />
              <span>Mandatory Rejection Rationale (Blueprint Governance)</span>
            </div>
            <p className="text-xs text-slate-400">
              Rejections require a minimum 15-character technical/commercial justification that will be permanently stored on the audit ledger and returned to the creator.
            </p>
            <textarea
              rows={4}
              value={rejectRationale}
              onChange={(e) => setRejectRationale(e.target.value)}
              placeholder="e.g., Quotation unit rate exceeds budget limit by 12%; request category manager renegotiate volume tier."
              className="w-full p-3 bg-[#060A12] border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 outline-none focus:border-rose-500"
            />
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{rejectRationale.length} characters (min 15 required)</span>
              <div className="flex gap-2">
                <button
                  onClick={() => setRejectModalOpen(false)}
                  className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                >
                  Cancel
                </button>
                <button
                  onClick={handleRejectSubmit}
                  disabled={rejectRationale.trim().length < 15}
                  className="px-4 py-1.5 rounded bg-rose-500 hover:bg-rose-400 disabled:opacity-40 text-white font-bold"
                >
                  Submit Rejection
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* New Delegation Modal */}
      {delegationModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0B1322] border border-slate-700 rounded-xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <h3 className="font-bold text-white text-base flex items-center gap-2">
              <UserPlus className="w-5 h-5 text-cyan-400" />
              Register Out-of-Office Delegation
            </h3>
            <div className="space-y-3 text-xs">
              <div>
                <label className="text-slate-400 block mb-1">Delegating Authority (From):</label>
                <input
                  type="text"
                  value={newDelegator}
                  onChange={(e) => setNewDelegator(e.target.value)}
                  className="w-full p-2 bg-[#060A12] border border-slate-700 rounded text-white"
                />
              </div>
              <div>
                <label className="text-slate-400 block mb-1">Proxy Signatory (To):</label>
                <input
                  type="text"
                  value={newDelegatee}
                  onChange={(e) => setNewDelegatee(e.target.value)}
                  className="w-full p-2 bg-[#060A12] border border-slate-700 rounded text-white"
                />
              </div>
              <div>
                <label className="text-slate-400 block mb-1">Reason:</label>
                <input
                  type="text"
                  value={newReason}
                  onChange={(e) => setNewReason(e.target.value)}
                  className="w-full p-2 bg-[#060A12] border border-slate-700 rounded text-white"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setDelegationModalOpen(false)}
                className="px-3 py-1.5 rounded bg-slate-800 text-slate-300 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateDelegation}
                className="px-4 py-1.5 rounded bg-cyan-500 text-slate-950 font-bold text-xs"
              >
                Save Delegation
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
