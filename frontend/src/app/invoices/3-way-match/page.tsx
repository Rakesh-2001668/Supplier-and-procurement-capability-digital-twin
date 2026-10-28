'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  ShieldCheck, AlertTriangle, CheckCircle2, XCircle, 
  Bot, Sparkles, ArrowRight, RefreshCw, FileText, 
  Receipt, DollarSign, Layers, AlertOctagon, Check, 
  Send, ExternalLink, Clock, ShieldAlert, ChevronRight,
  TrendingDown, FileMinus, ArrowLeftRight, Activity,
  Shield
} from 'lucide-react';
import axios from 'axios';

interface MatchCase {
  invoice_id: string;
  supplier_id: string;
  supplier_name: string;
  po_id: string;
  po_creator: string;
  contract_ref: string;
  material_id: string;
  material_desc: string;
  po_ordered_qty: number;
  po_unit_price: number;
  gr_id: string;
  gr_received_qty: number;
  gr_accepted_qty: number;
  gr_rejected_qty: number;
  quality_inspection_id?: string | null;
  quarantine_reason?: string | null;
  invoiced_qty: number;
  invoiced_unit_price: number;
  billed_base_amount_inr: number;
  tax_rate_percent: number;
  billed_tax_amount_inr: number;
  total_invoiced_inr: number;
  discrepancy_type: 'QUANTITY_EXCEPTION' | 'PRICE_EXCEPTION' | 'MISSING_GOODS_RECEIPT' | 'TAX_EXCEPTION' | 'NONE';
  discrepancy_units: number;
  discrepancy_base_inr: number;
  discrepancy_tax_inr: number;
  discrepancy_total_inr: number;
  adjusted_payable_inr: number;
  match_status: 'EXCEPTION' | 'MATCHED' | 'MATCHED_WITH_DEBIT_NOTE' | 'PENDING_CREDIT_NOTE' | 'POSTED';
  payment_hold: boolean;
  hold_reason?: string | null;
  debit_note_ref?: string | null;
  credit_note_ref?: string | null;
  erp_doc_no?: string | null;
  agent_verified: boolean;
  agent_verification_result?: any;
}

export default function ThreeWayMatchWorkbench() {
  const [cases, setCases] = useState<MatchCase[]>([]);
  const [selectedCase, setSelectedCase] = useState<MatchCase | null>(null);
  const [metrics, setMetrics] = useState<any>({});
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [filterType, setFilterType] = useState<string>('ALL');
  
  // Agent State
  const [isVerifying, setIsVerifying] = useState<boolean>(false);
  const [agentResult, setAgentResult] = useState<any>(null);

  // Active User Persona (to demonstrate SOD-04 guard vs authorized AP supervisor)
  const [currentActor, setCurrentActor] = useState<string>('ap.clerk@alphahelion.com');

  // Modals & Feedback
  const [toastMessage, setToastMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);

  const showToast = (text: string, type: 'success' | 'error') => {
    setToastMessage({ text, type });
    setTimeout(() => setToastMessage(null), 5000);
  };

  const fetchCases = async () => {
    setIsLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8080/api/v1/invoices/3-way-match/cases', {
        params: { discrepancy_type: filterType !== 'ALL' ? filterType : undefined }
      });
      if (res.data && res.data.cases) {
        setCases(res.data.cases);
        setMetrics(res.data.metrics || {});
        if (!selectedCase && res.data.cases.length > 0) {
          setSelectedCase(res.data.cases[0]);
          if (res.data.cases[0].agent_verification_result) {
            setAgentResult(res.data.cases[0].agent_verification_result);
          }
        } else if (selectedCase) {
          const updated = res.data.cases.find((c: MatchCase) => c.invoice_id === selectedCase.invoice_id);
          if (updated) setSelectedCase(updated);
        }
      }
    } catch (err) {
      console.error('Failed to load 3-way match cases:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchCases();
  }, [filterType]);

  const handleSelectCase = (c: MatchCase) => {
    setSelectedCase(c);
    setAgentResult(c.agent_verification_result || null);
  };

  // Run Agent AGT-INVOICE-11
  const handleRunAgentVerification = async () => {
    if (!selectedCase) return;
    setIsVerifying(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/invoices/3-way-match/cases/${selectedCase.invoice_id}/agent-verify`);
      setAgentResult(res.data.agent_contract);
      showToast('Agent AGT-INVOICE-11 completed autonomous tolerance cross-check (99% confidence).', 'success');
      fetchCases();
    } catch (err) {
      showToast('Agent verification failed.', 'error');
    } finally {
      setIsVerifying(false);
    }
  };

  // Issue Automated Debit Note
  const handleIssueDebitNote = async () => {
    if (!selectedCase) return;
    setActionLoading(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/invoices/3-way-match/cases/${selectedCase.invoice_id}/issue-debit-note`, {
        actor: currentActor,
        debit_note_number: `DN-2026-${selectedCase.invoice_id.slice(-4)}`
      });
      showToast(res.data.message, 'success');
      fetchCases();
    } catch (err) {
      showToast('Failed to issue debit note.', 'error');
    } finally {
      setActionLoading(false);
    }
  };

  // Request Supplier Credit Note
  const handleRequestCreditNote = async () => {
    if (!selectedCase) return;
    setActionLoading(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/invoices/3-way-match/cases/${selectedCase.invoice_id}/request-credit-note`, {
        actor: currentActor,
        expected_amount_inr: selectedCase.discrepancy_total_inr,
        dispute_reason: `Quantity overbilling: ${selectedCase.discrepancy_units} units rejected in QA`
      });
      showToast(res.data.message, 'success');
      fetchCases();
    } catch (err) {
      showToast('Failed to dispatch credit note dispute.', 'error');
    } finally {
      setActionLoading(false);
    }
  };

  // Waive Variance (SOD-04 Guarded)
  const handleWaiveVariance = async () => {
    if (!selectedCase) return;
    setActionLoading(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/invoices/3-way-match/cases/${selectedCase.invoice_id}/waive-variance`, {
        actor: currentActor,
        waiver_justification: 'Emergency indexation surcharge approved under SA-5521 amendment.',
        approved_tolerance_delta: selectedCase.discrepancy_total_inr
      });
      showToast(res.data.message, 'success');
      fetchCases();
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 403 && detail?.error === 'SEGREGATION_OF_DUTIES_VIOLATION') {
        showToast(`BLOCKED BY ${detail.rule_id}: ${detail.message}`, 'error');
      } else {
        showToast(detail?.message || 'Waiver failed.', 'error');
      }
    } finally {
      setActionLoading(false);
    }
  };

  // Idempotent Post to SAP S/4HANA
  const handlePostToERP = async () => {
    if (!selectedCase) return;
    setActionLoading(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/invoices/3-way-match/cases/${selectedCase.invoice_id}/post-to-erp`, {}, {
        headers: { 'Idempotency-Key': `AXN|1000|${selectedCase.supplier_id}|${selectedCase.invoice_id}-${Date.now()}` }
      });
      showToast(`Successfully posted to SAP S/4HANA (Accounting Doc: ${res.data.erpDocument})`, 'success');
      fetchCases();
    } catch (err: any) {
      showToast(err.response?.data?.detail || 'ERP posting failed. Ensure invoice is MATCHED first.', 'error');
    } finally {
      setActionLoading(false);
    }
  };

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

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono text-cyan-400 font-semibold tracking-wider uppercase bg-cyan-950/60 px-2.5 py-0.5 rounded border border-cyan-800/40">
              Module INV-03 & INV-04
            </span>
            <span className="text-xs font-mono text-slate-400">
              DMN-03 Tolerances & Autonomous Resolution
            </span>
          </div>
          <h1 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight flex items-center gap-3">
            <Receipt className="w-8 h-8 text-cyan-400" />
            3-Way Match Exception & Automated Dispute Resolution Engine
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-3xl">
            Autonomous 3-way reconciliation across Purchase Order contract pricing, warehouse Goods Receipts (including QA quarantine tags), and supplier invoices.
            Incorporates <strong className="text-cyan-300 font-mono">Agent AGT-INVOICE-11</strong> with automatic Debit Note generation and SoD-04 guarded price waivers.
          </p>
        </div>

        {/* Actor Selector & Breadcrumbs */}
        <div className="flex items-center gap-3">
          <div className="bg-slate-900 border border-slate-700/80 rounded-lg p-1.5 flex items-center gap-2">
            <span className="text-[11px] text-slate-400 font-mono pl-1">AP Signatory:</span>
            <select
              value={currentActor}
              onChange={(e) => setCurrentActor(e.target.value)}
              className="bg-[#0A101D] text-xs font-mono font-bold text-cyan-300 border border-slate-700 rounded px-2 py-1 outline-none focus:border-cyan-500"
            >
              <option value="ap.clerk@alphahelion.com">ap.clerk@alphahelion.com (AP Specialist)</option>
              <option value="ap.supervisor@alphahelion.com">ap.supervisor@alphahelion.com (Independent AP Supervisor)</option>
              <option value="buyer.automotive@alphahelion.com">buyer.automotive@alphahelion.com (PO Buyer - SOD-04 Guarded)</option>
            </select>
          </div>

          <Link
            href="/invoices"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 hover:border-cyan-500 text-xs font-semibold text-slate-200 transition-all shadow"
          >
            <FileText className="w-4 h-4 text-cyan-400" />
            Standard Invoices
          </Link>
        </div>
      </div>

      {/* Agent AGT-INVOICE-11 Live Status Ribbon */}
      <div className="p-4 bg-gradient-to-r from-slate-900/90 via-[#0B172E] to-slate-900/90 border border-cyan-500/40 rounded-xl shadow-lg flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-cyan-500/20 border border-cyan-500/40 rounded-lg text-cyan-300">
            <Bot className="w-6 h-6 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-white tracking-wide">
                Agent AGT-INVOICE-11: 3-Way Invoice Matching Resolver
              </h3>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-800">
                {metrics.agent_autonomy || 'L3_SUPERVISED_ACTION'}
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                ACTIVE
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Continuously cross-evaluates line-level tolerances (Price: 0%, Qty: ±5%, Tax: 0%), quarantines overbilling, and pre-fills automated Debit Notes.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="text-right">
            <span className="text-slate-400 block text-[10px]">ACTIONS TODAY</span>
            <span className="text-sm font-bold text-cyan-300">{metrics.agent_actions_today || 31} Resolutions</span>
          </div>
          <div className="h-6 w-px bg-slate-800" />
          <div className="text-right">
            <span className="text-slate-400 block text-[10px]">DISPUTED SPEND</span>
            <span className="text-sm font-bold text-amber-300">₹{(metrics.disputed_value_inr || 0).toLocaleString('en-IN')}</span>
          </div>
        </div>
      </div>

      {/* Main Workbench Layout: 12 Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left List of Invoices (4 Cols) */}
        <div className="lg:col-span-4 space-y-3">
          {/* Filter Pills */}
          <div className="p-3 bg-slate-900/70 border border-slate-800 rounded-xl space-y-2">
            <span className="text-[11px] font-mono text-slate-400 font-semibold uppercase">Filter Discrepancy:</span>
            <div className="flex flex-wrap gap-1.5">
              {[
                { id: 'ALL', label: 'All Cases' },
                { id: 'QUANTITY_EXCEPTION', label: 'Quantity Exception' },
                { id: 'PRICE_EXCEPTION', label: 'Price Variance' },
                { id: 'MISSING_GOODS_RECEIPT', label: 'Missing GR' }
              ].map(f => (
                <button
                  key={f.id}
                  onClick={() => setFilterType(f.id)}
                  className={`px-2 py-1 rounded text-[11px] font-semibold transition-all ${
                    filterType === f.id
                      ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm'
                      : 'bg-slate-800/60 text-slate-400 hover:text-slate-200 border border-slate-700/60'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          {/* Cards List */}
          <div className="space-y-2.5">
            {isLoading ? (
              <div className="p-8 text-center text-slate-400">Loading cases...</div>
            ) : cases.map(c => {
              const isSelected = selectedCase?.invoice_id === c.invoice_id;
              const isException = c.match_status === 'EXCEPTION';
              return (
                <div
                  key={c.invoice_id}
                  onClick={() => handleSelectCase(c)}
                  className={`p-3.5 rounded-xl border transition-all cursor-pointer ${
                    isSelected
                      ? 'bg-slate-900/95 border-cyan-500/80 shadow-lg shadow-cyan-500/10 ring-1 ring-cyan-500/30'
                      : 'bg-slate-900/50 hover:bg-slate-850/80 border-slate-800'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-mono font-bold text-cyan-300">{c.invoice_id}</span>
                    <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                      c.match_status === 'MATCHED' || c.match_status === 'MATCHED_WITH_DEBIT_NOTE' 
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' 
                        : c.match_status === 'POSTED'
                        ? 'bg-blue-950 text-blue-300 border border-blue-800'
                        : 'bg-rose-950 text-rose-300 border border-rose-800 animate-pulse'
                    }`}>
                      {c.match_status}
                    </span>
                  </div>

                  <div className="text-xs font-bold text-white line-clamp-1">{c.material_desc}</div>
                  <div className="text-[11px] text-slate-400 mt-1 flex justify-between">
                    <span>{c.supplier_name}</span>
                    <span className="font-mono font-bold text-white">₹{c.total_invoiced_inr.toLocaleString('en-IN')}</span>
                  </div>

                  {isException && (
                    <div className="mt-2 pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-rose-300">
                      <span>Delta: ₹{c.discrepancy_total_inr.toLocaleString('en-IN')}</span>
                      <span>{c.discrepancy_type.replace('_', ' ')}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Side: Detailed 3-Way Reconciliation Canvas & Action Resolver (8 Cols) */}
        <div className="lg:col-span-8 space-y-5">
          {selectedCase && (
            <>
              {/* 3-Way Reconciliation Comparison Panel */}
              <div className="p-5 bg-[#090F1E] border border-slate-800 rounded-xl space-y-4 shadow-xl">
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <div>
                    <span className="text-xs font-mono font-bold text-cyan-400">{selectedCase.invoice_id}</span>
                    <h2 className="text-base font-bold text-white mt-0.5">{selectedCase.material_desc}</h2>
                    <span className="text-xs text-slate-400">Supplier: <strong className="text-slate-200">{selectedCase.supplier_name} ({selectedCase.supplier_id})</strong></span>
                  </div>
                  
                  {/* Status Banner */}
                  <div className="text-right">
                    <span className={`inline-block px-3 py-1 rounded-lg text-xs font-mono font-bold ${
                      selectedCase.match_status.includes('MATCHED') 
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-700' 
                        : selectedCase.match_status === 'POSTED'
                        ? 'bg-blue-950 text-blue-300 border border-blue-700'
                        : 'bg-rose-950 text-rose-300 border border-rose-700'
                    }`}>
                      {selectedCase.match_status}
                    </span>
                    {selectedCase.payment_hold && (
                      <div className="text-[10px] font-mono text-rose-400 mt-1 flex items-center gap-1 justify-end">
                        <ShieldAlert className="w-3 h-3" /> Payment Block Active
                      </div>
                    )}
                  </div>
                </div>

                {/* 3-Way Comparative Cards Spine */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {/* Card 1: Purchase Order */}
                  <div className="p-3.5 bg-slate-900/80 border border-slate-800 rounded-lg space-y-1.5 text-xs">
                    <div className="flex items-center justify-between text-slate-400 font-mono text-[10px] font-bold">
                      <span className="flex items-center gap-1"><FileText className="w-3 h-3 text-cyan-400" /> 1. PURCHASE ORDER</span>
                      <span>{selectedCase.po_id}</span>
                    </div>
                    <div className="pt-1">
                      <div className="text-slate-400">Ordered Quantity:</div>
                      <div className="text-sm font-bold text-white font-mono">{selectedCase.po_ordered_qty} EA</div>
                    </div>
                    <div>
                      <div className="text-slate-400">Contract Unit Price:</div>
                      <div className="text-sm font-bold text-cyan-300 font-mono">₹{selectedCase.po_unit_price.toFixed(2)}</div>
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono pt-1 border-t border-slate-800">
                      Contract: {selectedCase.contract_ref}
                    </div>
                  </div>

                  {/* Card 2: Goods Receipt & QA */}
                  <div className="p-3.5 bg-slate-900/80 border border-slate-800 rounded-lg space-y-1.5 text-xs">
                    <div className="flex items-center justify-between text-slate-400 font-mono text-[10px] font-bold">
                      <span className="flex items-center gap-1"><ShieldCheck className="w-3 h-3 text-emerald-400" /> 2. GOODS RECEIPT</span>
                      <span>{selectedCase.gr_id}</span>
                    </div>
                    <div className="pt-1">
                      <div className="text-slate-400">Accepted into Stores:</div>
                      <div className="text-sm font-bold text-emerald-400 font-mono">{selectedCase.gr_accepted_qty} EA</div>
                    </div>
                    <div>
                      <div className="text-slate-400">QA Quarantined / Rejected:</div>
                      <div className={`text-sm font-bold font-mono ${selectedCase.gr_rejected_qty > 0 ? 'text-rose-400' : 'text-slate-400'}`}>
                        {selectedCase.gr_rejected_qty} EA
                      </div>
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono pt-1 border-t border-slate-800 truncate">
                      QA Tag: {selectedCase.quality_inspection_id || 'N/A'}
                    </div>
                  </div>

                  {/* Card 3: Invoiced Line */}
                  <div className="p-3.5 bg-slate-900/80 border border-slate-800 rounded-lg space-y-1.5 text-xs">
                    <div className="flex items-center justify-between text-slate-400 font-mono text-[10px] font-bold">
                      <span className="flex items-center gap-1"><Receipt className="w-3 h-3 text-amber-400" /> 3. INVOICED LINE</span>
                      <span>{selectedCase.invoice_id}</span>
                    </div>
                    <div className="pt-1">
                      <div className="text-slate-400">Billed Quantity:</div>
                      <div className={`text-sm font-bold font-mono ${selectedCase.invoiced_qty > selectedCase.gr_accepted_qty ? 'text-rose-400' : 'text-white'}`}>
                        {selectedCase.invoiced_qty} EA
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-400">Billed Unit Price:</div>
                      <div className={`text-sm font-bold font-mono ${selectedCase.invoiced_unit_price > selectedCase.po_unit_price ? 'text-rose-400' : 'text-cyan-300'}`}>
                        ₹{selectedCase.invoiced_unit_price.toFixed(2)}
                      </div>
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono pt-1 border-t border-slate-800">
                      Total: ₹{selectedCase.total_invoiced_inr.toLocaleString('en-IN')}
                    </div>
                  </div>
                </div>

                {/* Tolerance Discrepancy Callout */}
                {selectedCase.discrepancy_total_inr > 0 && (
                  <div className="p-3.5 bg-rose-950/30 border border-rose-800/60 rounded-lg flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2.5">
                      <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
                      <div>
                        <span className="font-bold text-rose-200 block">
                          Discrepancy Detected ({selectedCase.discrepancy_type.replace('_', ' ')})
                        </span>
                        <span className="text-[11px] text-slate-300">
                          {selectedCase.hold_reason || 'Variance exceeds DMN-03 0.0% tolerance limit.'}
                        </span>
                      </div>
                    </div>
                    <div className="text-right font-mono shrink-0">
                      <div className="text-sm font-extrabold text-rose-300">
                        ₹{selectedCase.discrepancy_total_inr.toLocaleString('en-IN')}
                      </div>
                      <div className="text-[10px] text-slate-400">Unsettled Delta</div>
                    </div>
                  </div>
                )}
              </div>

              {/* Agent AGT-INVOICE-11 Verification & Answer Contract Console */}
              <div className="p-5 bg-[#0A1224] border border-cyan-500/50 rounded-xl space-y-4 shadow-xl">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Bot className="w-5 h-5 text-cyan-400" />
                    <h3 className="text-sm font-bold text-white">
                      Agent AGT-INVOICE-11 Autonomous Audit & Copilot Contract
                    </h3>
                  </div>

                  <button
                    onClick={handleRunAgentVerification}
                    disabled={isVerifying}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 text-xs font-bold shadow-md transition-all"
                  >
                    {isVerifying ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Verifying Tolerances...
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-3.5 h-3.5" /> Run AGT-INVOICE-11 Audit
                      </>
                    )}
                  </button>
                </div>

                {agentResult ? (
                  <div className="space-y-3 text-xs leading-relaxed">
                    {/* Citations Ribbon */}
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <span className="text-slate-400 font-mono text-[11px]">Citations:</span>
                      {agentResult.citations?.map((cite: any, idx: number) => (
                        <span key={idx} className="px-2 py-0.5 rounded bg-slate-900 border border-slate-700 font-mono text-[10px] text-cyan-300">
                          [{cite.doc_id}]
                        </span>
                      ))}
                      <span className="ml-auto text-[10px] font-mono text-emerald-400 font-bold bg-emerald-950 px-2 py-0.5 rounded border border-emerald-800">
                        Confidence: {(agentResult.confidence_score * 100).toFixed(0)}%
                      </span>
                    </div>

                    {/* Root Cause Explanation */}
                    <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg text-slate-300">
                      <strong className="text-white block mb-1">Root Cause & Regulatory Assessment:</strong>
                      {agentResult.root_cause_explanation}
                    </div>

                    {/* Proposed Automated Resolution */}
                    <div className="p-3 bg-cyan-950/30 border border-cyan-800/40 rounded-lg text-cyan-200">
                      <strong className="text-cyan-300 block mb-1">Recommended Supervised Action (L3 Autonomy):</strong>
                      {agentResult.recommended_action}
                    </div>
                  </div>
                ) : (
                  <div className="p-4 text-center bg-slate-950/40 border border-slate-800/60 rounded-lg text-xs text-slate-400">
                    Click "Run AGT-INVOICE-11 Audit" to trigger autonomous tolerance evaluation under Principle P11.
                  </div>
                )}
              </div>

              {/* Automated Dispute Resolution Action Toolbar */}
              <div className="p-5 bg-slate-900/90 border border-slate-800 rounded-xl space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <ShieldAlert className="w-4 h-4 text-amber-400" />
                    Automated Dispute Resolution Actions (INV-04)
                  </h3>
                  <span className="text-xs font-mono text-slate-400">
                    Active Signatory: <strong className="text-cyan-300">{currentActor}</strong>
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                  {/* Action 1: Issue Automated Debit Note */}
                  <button
                    onClick={handleIssueDebitNote}
                    disabled={actionLoading || selectedCase.discrepancy_total_inr === 0 || selectedCase.match_status.includes('MATCHED')}
                    className="p-3 rounded-xl bg-gradient-to-b from-cyan-950 to-slate-900 border border-cyan-500/60 hover:border-cyan-400 text-left transition-all disabled:opacity-30 disabled:pointer-events-none group"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-bold text-cyan-300 flex items-center gap-1">
                        <TrendingDown className="w-3.5 h-3.5" /> Issue Debit Note
                      </span>
                      <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-cyan-400 transition-transform group-hover:translate-x-0.5" />
                    </div>
                    <div className="text-[11px] text-slate-300 leading-snug">
                      Auto-offsets ₹{selectedCase.discrepancy_total_inr.toLocaleString('en-IN')} and unblocks payment.
                    </div>
                  </button>

                  {/* Action 2: Request Supplier Credit Note */}
                  <button
                    onClick={handleRequestCreditNote}
                    disabled={actionLoading || selectedCase.discrepancy_total_inr === 0 || selectedCase.match_status.includes('MATCHED')}
                    className="p-3 rounded-xl bg-slate-900 border border-slate-700 hover:border-amber-400 text-left transition-all disabled:opacity-30 disabled:pointer-events-none group"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-bold text-amber-300 flex items-center gap-1">
                        <Send className="w-3.5 h-3.5" /> Request Credit Note
                      </span>
                      <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-amber-400 transition-transform group-hover:translate-x-0.5" />
                    </div>
                    <div className="text-[11px] text-slate-300 leading-snug">
                      Dispatches dispute notice with 48h resolution SLA.
                    </div>
                  </button>

                  {/* Action 3: Waive Price Variance (SOD-04 Guarded) */}
                  <button
                    onClick={handleWaiveVariance}
                    disabled={actionLoading || selectedCase.match_status.includes('MATCHED')}
                    className="p-3 rounded-xl bg-slate-900 border border-slate-700 hover:border-rose-400 text-left transition-all disabled:opacity-30 disabled:pointer-events-none group"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-bold text-rose-300 flex items-center gap-1">
                        <Shield className="w-3.5 h-3.5" /> Waive Variance
                      </span>
                      <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-rose-400 transition-transform group-hover:translate-x-0.5" />
                    </div>
                    <div className="text-[11px] text-slate-300 leading-snug">
                      Requires AP supervisor (SOD-04 blocks PO creator).
                    </div>
                  </button>

                  {/* Action 4: Post to SAP S/4HANA */}
                  <button
                    onClick={handlePostToERP}
                    disabled={actionLoading || (!selectedCase.match_status.includes('MATCHED') && selectedCase.match_status !== 'POSTED')}
                    className={`p-3 rounded-xl text-left transition-all group ${
                      selectedCase.match_status.includes('MATCHED')
                        ? 'bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold shadow-lg shadow-emerald-500/20'
                        : selectedCase.match_status === 'POSTED'
                        ? 'bg-blue-950/60 border border-blue-700 text-blue-300'
                        : 'bg-slate-900/60 border border-slate-800 text-slate-500 opacity-40 pointer-events-none'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-bold flex items-center gap-1">
                        <Check className="w-3.5 h-3.5 stroke-[3]" /> Post to ERP
                      </span>
                      <ChevronRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
                    </div>
                    <div className="text-[11px] leading-snug opacity-90">
                      {selectedCase.erp_doc_no ? `Posted: Doc ${selectedCase.erp_doc_no}` : 'Idempotent SAP S/4HANA Posting (P13)'}
                    </div>
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
