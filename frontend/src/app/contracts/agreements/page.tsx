'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  FileText, CheckCircle2, AlertTriangle, ArrowRight, 
  Search, RefreshCw, Layers, ShieldCheck, DollarSign,
  Building2, Sparkles, Scale, Sliders, Calendar, Clock,
  ExternalLink, TrendingUp, TrendingDown, ShieldAlert,
  ChevronRight, Award, Box, Zap
} from 'lucide-react';
import axios from 'axios';

interface ContractLine {
  line_no: number;
  material_id: string;
  description: string;
  agreed_base_price_inr: number;
  current_effective_price_inr: number;
  uom: string;
  over_delivery_tol_pct: number;
  under_delivery_tol_pct: number;
}

interface IndexationClause {
  benchmark_index: string;
  baseline_index_value: number;
  current_index_value: number;
  deadband_tolerance_pct: number;
  reset_frequency: string;
  next_reset_date: string;
  cost_pass_through_factor: number;
  status: string;
}

interface Obligation {
  id: string;
  type: string;
  title: string;
  due_rule: string;
  status: string;
}

interface ContractAgreement {
  id: string;
  tenant_id: string;
  title: string;
  contract_type: string;
  supplier_id: string;
  supplier_name: string;
  plant: string;
  company_code: string;
  status: string;
  sourcing_event_ref: string;
  valid_from: string;
  valid_to: string;
  target_quantity: number;
  released_quantity: number;
  remaining_quantity: number;
  target_value_inr: number;
  released_value_inr: number;
  consumption_pct: number;
  payment_terms: string;
  incoterms: string;
  lines: ContractLine[];
  indexation_clause: IndexationClause;
  obligations: Obligation[];
}

export default function ContractAgreementsPage() {
  const [contracts, setContracts] = useState<ContractAgreement[]>([]);
  const [selectedContract, setSelectedContract] = useState<ContractAgreement | null>(null);
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Indexation Reset Modal State
  const [showIndexationModal, setShowIndexationModal] = useState(false);
  const [newLmeValue, setNewLmeValue] = useState<number>(2600.0);
  const [resettingIndex, setResettingIndex] = useState(false);
  const [indexationResult, setIndexationResult] = useState<any>(null);

  const fetchContracts = async () => {
    setLoading(true);
    try {
      const res = await axios.get('http://localhost:8080/api/v1/strategic/contracts/agreements');
      if (res.data && res.data.status === 'success') {
        setContracts(res.data.contracts || []);
        if (res.data.contracts?.length > 0) {
          setSelectedContract(res.data.contracts[0]);
        }
      }
    } catch (err) {
      console.error('Failed to load contracts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContracts();
  }, []);

  const handleIndexationReset = async () => {
    if (!selectedContract) return;
    setResettingIndex(true);
    try {
      const res = await axios.post(
        `http://localhost:8080/api/v1/strategic/contracts/agreements/${selectedContract.id}/indexation-reset`,
        {
          new_lme_index_value: Number(newLmeValue),
          effective_date: new Date().toISOString().split('T')[0],
          actor: 'u:category.mgr.castings'
        }
      );

      if (res.data && res.data.status === 'success') {
        setIndexationResult(res.data);
        setToastMessage(`Indexation evaluated: ${res.data.message}`);
        // Refresh contract state
        const refRes = await axios.get(`http://localhost:8080/api/v1/strategic/contracts/agreements/${selectedContract.id}`);
        if (refRes.data && refRes.data.contract) {
          setSelectedContract(refRes.data.contract);
          setContracts(prev => prev.map(c => c.id === selectedContract.id ? refRes.data.contract : c));
        }
      }
    } catch (err: any) {
      console.error('Indexation error:', err);
      setToastMessage(err.response?.data?.detail || 'Failed to evaluate indexation');
    } finally {
      setResettingIndex(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 space-y-6">
      {/* Toast Banner */}
      {toastMessage && (
        <div className="p-4 rounded-xl bg-cyan-950/80 border border-cyan-500/50 text-cyan-200 flex items-center justify-between shadow-xl shadow-cyan-950/30 animate-in fade-in duration-200">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            <span className="font-medium text-sm">{toastMessage}</span>
          </div>
          <button 
            onClick={() => setToastMessage(null)} 
            className="text-xs px-2.5 py-1 rounded-md bg-cyan-900/60 hover:bg-cyan-800 text-cyan-300"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold tracking-wider uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              Module M07 • CLM-01..04
            </span>
            <span className="text-xs text-slate-400 font-mono">Governed Scheduling Agreements</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Buy-Side Contract Repository & Rate Indexation
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Target consumption tracking, dynamic quarterly LME metal indexation clauses, and automated release order inheritances.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchContracts}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-slate-700/60 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <Link
            href="/sourcing"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-xs font-semibold text-white shadow-lg shadow-blue-600/20 transition"
          >
            <Award className="w-3.5 h-3.5" />
            Sourcing Cockpit
          </Link>
          <Link
            href="/p2p"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-xs font-semibold text-white shadow-lg shadow-cyan-600/20 transition"
          >
            <Box className="w-3.5 h-3.5" />
            P2P Releases
          </Link>
        </div>
      </div>

      {/* Main Grid: Contracts List + Detail Cockpit */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Agreement Selector (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Active Master Agreements ({contracts.length})
            </h3>
            <span className="text-[11px] text-cyan-400 font-mono">Principle P03 (Contract Reuse)</span>
          </div>

          <div className="space-y-3">
            {contracts.map(c => {
              const isSelected = selectedContract?.id === c.id;
              const isLme = !!c.indexation_clause;
              return (
                <div 
                  key={c.id}
                  onClick={() => { setSelectedContract(c); setIndexationResult(null); }}
                  className={`p-4 rounded-xl border cursor-pointer transition relative ${
                    isSelected 
                      ? 'bg-[#0E1A30] border-cyan-500/60 shadow-lg shadow-cyan-950/40 ring-1 ring-cyan-500/40' 
                      : 'bg-[#0B1528]/80 border-slate-800/80 hover:border-slate-700/80 hover:bg-[#0B1528]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-500/30">
                        {c.id}
                      </span>
                      <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                        {c.status}
                      </span>
                    </div>
                    <span className="text-[11px] font-mono text-slate-400">
                      {c.plant}
                    </span>
                  </div>

                  <h4 className="text-sm font-semibold text-white leading-snug line-clamp-1 mb-1">
                    {c.title}
                  </h4>

                  <div className="flex items-center gap-2 text-xs text-slate-400 mb-3">
                    <Building2 className="w-3.5 h-3.5 text-slate-500" />
                    <span>{c.supplier_name}</span>
                  </div>

                  {/* Consumption Progress Bar */}
                  <div className="space-y-1.5 pt-2 border-t border-slate-800/60">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-slate-400">Target Value</span>
                      <span className="font-mono text-slate-200">₹{(c.target_value_inr / 10000000).toFixed(2)} Cr</span>
                    </div>
                    <div className="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden">
                      <div 
                        className="bg-gradient-to-r from-cyan-500 to-emerald-500 h-1.5 rounded-full"
                        style={{ width: `${Math.min(100, c.consumption_pct * 10)}%` }}
                      />
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono">
                      <span>Consumed: {c.consumption_pct}%</span>
                      <span>Target: {c.target_quantity.toLocaleString()} {c.lines[0]?.uom || 'EA'}</span>
                    </div>
                  </div>

                  {isLme && (
                    <div className="mt-3 flex items-center justify-between text-[11px] px-2 py-1 rounded bg-amber-500/10 border border-amber-500/20 text-amber-300">
                      <span className="flex items-center gap-1 font-mono">
                        <Scale className="w-3 h-3 text-amber-400" />
                        LME Index Linked
                      </span>
                      <span className="text-[10px] font-semibold">{c.indexation_clause.status}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Detailed Agreement Cockpit (8 cols) */}
        {selectedContract ? (
          <div className="lg:col-span-8 space-y-6">
            {/* Top Agreement Card */}
            <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
                <div>
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm font-bold text-cyan-300 bg-cyan-950/80 px-2.5 py-1 rounded border border-cyan-500/40">
                      {selectedContract.id}
                    </span>
                    <span className="text-xs font-semibold px-2.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                      {selectedContract.contract_type}
                    </span>
                    <span className="text-xs text-slate-400 font-mono">
                      Ref: {selectedContract.sourcing_event_ref}
                    </span>
                  </div>
                  <h2 className="text-lg font-bold text-white mt-2">
                    {selectedContract.title}
                  </h2>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowIndexationModal(true)}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-medium transition"
                  >
                    <Scale className="w-3.5 h-3.5 text-amber-400" />
                    Reset LME Indexation
                  </button>
                </div>
              </div>

              {/* Key Metrics Row */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
                  <span className="text-[11px] text-slate-400 uppercase font-semibold">Total Commitment</span>
                  <div className="text-lg font-bold text-white font-mono mt-0.5">
                    ₹{(selectedContract.target_value_inr / 10000000).toFixed(2)} Cr
                  </div>
                  <span className="text-[10px] text-slate-400 font-mono">
                    {selectedContract.target_quantity.toLocaleString()} units
                  </span>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
                  <span className="text-[11px] text-slate-400 uppercase font-semibold">Released / Drawn</span>
                  <div className="text-lg font-bold text-emerald-400 font-mono mt-0.5">
                    ₹{(selectedContract.released_value_inr / 100000).toFixed(2)} L
                  </div>
                  <span className="text-[10px] text-emerald-400/80 font-mono">
                    {selectedContract.released_quantity.toLocaleString()} units ({selectedContract.consumption_pct}%)
                  </span>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
                  <span className="text-[11px] text-slate-400 uppercase font-semibold">Effective Unit Price</span>
                  <div className="text-lg font-bold text-cyan-400 font-mono mt-0.5">
                    ₹{selectedContract.lines[0]?.current_effective_price_inr.toFixed(2)}
                  </div>
                  <span className="text-[10px] text-slate-400 font-mono">
                    Base: ₹{selectedContract.lines[0]?.agreed_base_price_inr.toFixed(2)}
                  </span>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
                  <span className="text-[11px] text-slate-400 uppercase font-semibold">Terms & Plant</span>
                  <div className="text-sm font-bold text-white font-mono mt-1">
                    {selectedContract.payment_terms} • {selectedContract.incoterms}
                  </div>
                  <span className="text-[10px] text-slate-400 font-mono">
                    {selectedContract.plant}
                  </span>
                </div>
              </div>

              {/* Dynamic Indexation Clause Visualizer */}
              {selectedContract.indexation_clause && (
                <div className="p-5 rounded-xl bg-gradient-to-br from-amber-950/20 via-slate-900/40 to-slate-900/80 border border-amber-500/30 space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <Scale className="w-5 h-5 text-amber-400" />
                      <div>
                        <h4 className="text-sm font-bold text-amber-200">
                          Automated Metal Indexation Clause (Principle P14)
                        </h4>
                        <p className="text-xs text-amber-300/70">
                          {selectedContract.indexation_clause.benchmark_index} with ±{selectedContract.indexation_clause.deadband_tolerance_pct}% Deadband
                        </p>
                      </div>
                    </div>
                    <span className="text-xs px-2.5 py-1 rounded bg-amber-500/20 text-amber-300 font-mono font-bold border border-amber-500/30">
                      {selectedContract.indexation_clause.status}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-2 text-xs">
                    <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/80">
                      <span className="text-slate-400 text-[10px]">Baseline LME Index</span>
                      <div className="text-slate-200 font-mono font-bold mt-0.5">
                        ${selectedContract.indexation_clause.baseline_index_value.toFixed(1)} / MT
                      </div>
                    </div>
                    <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/80">
                      <span className="text-slate-400 text-[10px]">Current LME Index</span>
                      <div className="text-amber-400 font-mono font-bold mt-0.5">
                        ${selectedContract.indexation_clause.current_index_value.toFixed(1)} / MT
                      </div>
                    </div>
                    <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/80">
                      <span className="text-slate-400 text-[10px]">Pass-Through Factor</span>
                      <div className="text-cyan-400 font-mono font-bold mt-0.5">
                        {(selectedContract.indexation_clause.cost_pass_through_factor * 100).toFixed(0)}% Pass-Through
                      </div>
                    </div>
                    <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/80">
                      <span className="text-slate-400 text-[10px]">Next Reset Date</span>
                      <div className="text-slate-200 font-mono font-bold mt-0.5">
                        {selectedContract.indexation_clause.next_reset_date}
                      </div>
                    </div>
                  </div>

                  {/* Indexation status bar */}
                  <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800 text-xs text-slate-300 flex items-center justify-between">
                    <span className="text-slate-400">
                      LME Delta: {(((selectedContract.indexation_clause.current_index_value - selectedContract.indexation_clause.baseline_index_value) / selectedContract.indexation_clause.baseline_index_value) * 100).toFixed(2)}%
                    </span>
                    <span className="text-amber-300 font-mono">
                      Deadband: ±{selectedContract.indexation_clause.deadband_tolerance_pct}% ({`$${(selectedContract.indexation_clause.baseline_index_value * 0.97).toFixed(0)} to $${(selectedContract.indexation_clause.baseline_index_value * 1.03).toFixed(0)}`})
                    </span>
                  </div>
                </div>
              )}

              {/* Line Items Table */}
              <div className="space-y-3">
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Contract Line Items & Delivery Tolerances
                </h4>
                <div className="overflow-x-auto rounded-xl border border-slate-800/80">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900/80 text-slate-400 font-medium border-b border-slate-800">
                      <tr>
                        <th className="py-2.5 px-3">Item</th>
                        <th className="py-2.5 px-3">Material ID</th>
                        <th className="py-2.5 px-3">Description</th>
                        <th className="py-2.5 px-3">Agreed Base</th>
                        <th className="py-2.5 px-3">Effective Price</th>
                        <th className="py-2.5 px-3">Tolerances</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono">
                      {selectedContract.lines.map((l) => (
                        <tr key={l.line_no} className="hover:bg-slate-800/30">
                          <td className="py-3 px-3 text-slate-400">{l.line_no}</td>
                          <td className="py-3 px-3 font-bold text-cyan-400">{l.material_id}</td>
                          <td className="py-3 px-3 text-slate-200 font-sans">{l.description}</td>
                          <td className="py-3 px-3 text-slate-400">₹{l.agreed_base_price_inr.toFixed(2)}</td>
                          <td className="py-3 px-3 font-bold text-emerald-400">₹{l.current_effective_price_inr.toFixed(2)}</td>
                          <td className="py-3 px-3 text-[11px] text-slate-400 font-sans">
                            +{l.over_delivery_tol_pct}% / -{l.under_delivery_tol_pct}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Two-Sided Obligations Tracker */}
              <div className="space-y-3">
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Governed Obligations & SLA Commitments
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {selectedContract.obligations.map((obl) => (
                    <div 
                      key={obl.id}
                      className="p-3.5 rounded-xl bg-slate-900/50 border border-slate-800/80 flex items-start gap-3"
                    >
                      <div className="mt-0.5">
                        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-[10px] text-cyan-400 font-bold bg-cyan-950/60 px-1.5 py-0.5 rounded">
                            {obl.id}
                          </span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                            {obl.due_rule}
                          </span>
                        </div>
                        <p className="text-xs text-slate-200 mt-1 font-medium leading-relaxed">
                          {obl.title}
                        </p>
                        <div className="mt-1.5 flex items-center justify-between text-[10px] text-slate-400">
                          <span>Party: <strong className="text-slate-300">{obl.type}</strong></span>
                          <span className="text-emerald-400 font-semibold">{obl.status}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* P10 Audit & Lineage Breadcrumb */}
              <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-slate-400">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-cyan-400" />
                  <span>Lineage (P10): Sourced via <strong className="text-slate-200 font-mono">{selectedContract.sourcing_event_ref}</strong> • Governs PO releases under plant <strong className="text-slate-200 font-mono">{selectedContract.plant}</strong></span>
                </div>
                <Link
                  href="/p2p"
                  className="inline-flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300 font-semibold transition"
                >
                  View Release PO-77410
                  <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            </div>
          </div>
        ) : (
          <div className="lg:col-span-8 flex items-center justify-center p-12 rounded-2xl bg-[#0B1528] border border-slate-800 text-slate-400">
            Select a contract from the left to view details.
          </div>
        )}
      </div>

      {/* Indexation Reset Modal */}
      {showIndexationModal && selectedContract && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-lg bg-[#0B1528] border border-slate-700 rounded-2xl shadow-2xl p-6 space-y-5 text-slate-100">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3">
              <div>
                <span className="text-xs font-mono text-amber-400 font-semibold">Principle P14 • Formula Reset</span>
                <h3 className="text-lg font-bold text-white mt-0.5">Quarterly LME Indexation Reset</h3>
              </div>
              <button 
                onClick={() => { setShowIndexationModal(false); setIndexationResult(null); }}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              Evaluate current London Metal Exchange (LME) Aluminium Cash Settlement index against contract baseline (${selectedContract.indexation_clause.baseline_index_value}/MT). 
              If the movement exceeds the ±{selectedContract.indexation_clause.deadband_tolerance_pct}% deadband, the current effective unit price will be automatically updated with the {(selectedContract.indexation_clause.cost_pass_through_factor * 100).toFixed(0)}% pass-through rule.
            </p>

            <div className="space-y-3">
              <label className="block text-xs font-semibold text-slate-300">
                New LME Aluminium Cash Settlement Price ($/MT)
              </label>
              <input
                type="number"
                step="5.0"
                value={newLmeValue}
                onChange={(e) => setNewLmeValue(parseFloat(e.target.value))}
                className="w-full px-3.5 py-2.5 bg-slate-900 border border-slate-700 rounded-xl font-mono text-cyan-300 text-sm focus:outline-none focus:border-cyan-500"
              />
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span>Baseline: ${selectedContract.indexation_clause.baseline_index_value}</span>
                <span>Deadband threshold: ${(selectedContract.indexation_clause.baseline_index_value * 1.03).toFixed(1)} (+3%)</span>
              </div>
            </div>

            {indexationResult && (
              <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Evaluation Result:</span>
                  <span className="font-mono font-bold text-amber-300">{indexationResult.indexation?.status}</span>
                </div>
                <p className="text-slate-200">{indexationResult.message}</p>
                <div className="pt-2 border-t border-slate-800 flex items-center justify-between font-mono">
                  <span className="text-slate-400">New Effective Price:</span>
                  <span className="text-emerald-400 font-bold text-sm">₹{indexationResult.effective_unit_price?.toFixed(2)}</span>
                </div>
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                onClick={() => { setShowIndexationModal(false); setIndexationResult(null); }}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300"
              >
                Close
              </button>
              <button
                onClick={handleIndexationReset}
                disabled={resettingIndex}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-xs font-bold text-white shadow-lg shadow-amber-600/20 disabled:opacity-50 transition"
              >
                {resettingIndex ? 'Evaluating Index...' : 'Evaluate & Recalibrate'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
