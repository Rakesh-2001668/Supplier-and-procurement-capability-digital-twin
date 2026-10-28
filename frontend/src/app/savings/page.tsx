'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  DollarSign, TrendingUp, ShieldCheck, AlertTriangle, 
  ArrowRight, RefreshCw, BarChart3, Layers, CheckCircle2,
  PieChart, Sparkles, Filter, ChevronRight, Lock, 
  Building2, Scale, ArrowDownRight, Award, Box
} from 'lucide-react';
import axios from 'axios';

interface SavingsInitiative {
  id: string;
  tenant_id: string;
  title: string;
  sourcing_event_ref: string;
  contract_ref: string;
  category: string;
  owner: string;
  baseline_method: string;
  baseline_price_inr: number;
  negotiated_weighted_price_inr: number;
  annual_volume: number;
  negotiated_savings_annual_inr: number;
  cost_avoidance_annual_inr: number;
  realised_savings_ytd_inr: number;
  status: string;
  finance_validated: boolean;
  finance_validator?: string;
  created_at: string;
}

interface WaterfallData {
  portfolio_spend_under_management_cr: number;
  negotiated_savings_cr: number;
  contracted_savings_cr: number;
  leakage_total_cr: number;
  leakage_breakdown: {
    off_contract_buys_cr: number;
    volume_shortfall_cr: number;
    price_drift_cr: number;
  };
  realised_savings_pnl_cr: number;
  cost_avoidance_cr: number;
}

export default function SavingsRealisationPage() {
  const [initiatives, setInitiatives] = useState<SavingsInitiative[]>([]);
  const [waterfall, setWaterfall] = useState<WaterfallData | null>(null);
  const [p12Note, setP12Note] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // SOD-07 Finance Sign-Off Modal State
  const [showSignOffModal, setShowSignOffModal] = useState(false);
  const [selectedInit, setSelectedInit] = useState<SavingsInitiative | null>(null);
  const [financeValidator, setFinanceValidator] = useState('u:finance.controller.p100');
  const [comments, setComments] = useState('Audited against ERP invoice Doc 5100004421 and contract SA-5520 terms.');
  const [validating, setValidating] = useState(false);

  const fetchSavingsData = async () => {
    setLoading(true);
    try {
      const [initRes, waterRes] = await Promise.all([
        axios.get('http://localhost:8080/api/v1/strategic/savings/initiatives'),
        axios.get('http://localhost:8080/api/v1/strategic/savings/waterfall')
      ]);

      if (initRes.data && initRes.data.status === 'success') {
        setInitiatives(initRes.data.initiatives || []);
      }
      if (waterRes.data && waterRes.data.status === 'success') {
        setWaterfall(waterRes.data.waterfall);
        setP12Note(waterRes.data.principle_p12_enforcement || '');
      }
    } catch (err) {
      console.error('Failed to load savings data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSavingsData();
  }, []);

  const handleValidateInitiative = async () => {
    if (!selectedInit) return;
    setValidating(true);
    try {
      const res = await axios.post(
        `http://localhost:8080/api/v1/strategic/savings/initiatives/${selectedInit.id}/validate`,
        {
          validator: financeValidator,
          comments: comments
        }
      );

      if (res.data && res.data.status === 'success') {
        setToastMessage(`Finance sign-off recorded for ${selectedInit.id} (SOD-07 Enforced).`);
        setShowSignOffModal(false);
        fetchSavingsData();
      }
    } catch (err: any) {
      console.error('Validation error:', err);
      setToastMessage(err.response?.data?.detail || 'Finance validation failed');
    } finally {
      setValidating(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 space-y-6">
      {/* Toast Alert */}
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
            <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold tracking-wider uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Module M11 • SAV-01..02
            </span>
            <span className="text-xs text-slate-400 font-mono">Governed Value Realisation</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Savings Realisation & Value Waterfall Cockpit
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Strict Principle P12 multi-tier accounting: Negotiated vs Cost Avoidance vs Realised from posted SAP invoices.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchSavingsData}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-slate-700/60 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <Link
            href="/contracts/agreements"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-cyan-400 border border-cyan-500/30 transition"
          >
            <Scale className="w-3.5 h-3.5" />
            Contract Agreements
          </Link>
          <Link
            href="/p2p"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-xs font-semibold text-white shadow-lg shadow-emerald-600/20 transition"
          >
            <Box className="w-3.5 h-3.5" />
            P2P Invoices
          </Link>
        </div>
      </div>

      {/* Principle P12 Compliance Banner */}
      <div className="p-4 rounded-xl bg-gradient-to-r from-cyan-950/40 via-slate-900/60 to-slate-900/40 border border-cyan-500/30 flex items-start gap-3.5">
        <ShieldCheck className="w-5 h-5 text-cyan-400 mt-0.5 shrink-0" />
        <div className="space-y-0.5 text-xs">
          <h4 className="font-bold text-cyan-300">
            Mandatory Business Principle P12: Three Kinds of Savings Enforced
          </h4>
          <p className="text-slate-300 leading-relaxed">
            {p12Note || "Cost avoidance (e.g. absorbing market index increases) is strictly tracked separately and NEVER reduces operating budgets. Realised savings are recognized ONLY when three-way matched invoices are posted to the ERP general ledger."}
          </p>
        </div>
      </div>

      {/* Top Level Metric Cards */}
      {waterfall && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-5 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-2">
            <span className="text-xs text-slate-400 uppercase font-semibold flex items-center justify-between">
              Spend Under Management
              <BarChart3 className="w-4 h-4 text-cyan-400" />
            </span>
            <div className="text-2xl font-bold text-white font-mono">
              ₹{waterfall.portfolio_spend_under_management_cr.toFixed(1)} Cr
            </div>
            <span className="text-[11px] text-slate-400">Total audited annual addressable spend</span>
          </div>

          <div className="p-5 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-2">
            <span className="text-xs text-slate-400 uppercase font-semibold flex items-center justify-between">
              Negotiated Savings
              <TrendingUp className="w-4 h-4 text-blue-400" />
            </span>
            <div className="text-2xl font-bold text-blue-400 font-mono">
              ₹{waterfall.negotiated_savings_cr.toFixed(2)} Cr
            </div>
            <span className="text-[11px] text-slate-400">Contracted price deltas vs Last Price Paid</span>
          </div>

          <div className="p-5 rounded-2xl bg-[#0B1528] border border-emerald-500/30 shadow-xl space-y-2 ring-1 ring-emerald-500/20">
            <span className="text-xs text-emerald-400 uppercase font-semibold flex items-center justify-between">
              Realised into P&L
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            </span>
            <div className="text-2xl font-bold text-emerald-400 font-mono">
              ₹{waterfall.realised_savings_pnl_cr.toFixed(2)} Cr
            </div>
            <span className="text-[11px] text-emerald-400/80">From posted SAP Invoices (Doc 5100004421)</span>
          </div>

          <div className="p-5 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-2">
            <span className="text-xs text-slate-400 uppercase font-semibold flex items-center justify-between">
              Cost Avoidance
              <ShieldCheck className="w-4 h-4 text-amber-400" />
            </span>
            <div className="text-2xl font-bold text-amber-400 font-mono">
              ₹{waterfall.cost_avoidance_cr.toFixed(2)} Cr
            </div>
            <span className="text-[11px] text-amber-400/80">Absorbed inflation / index mitigation</span>
          </div>
        </div>
      )}

      {/* Realisation Waterfall & Leakage Breakdown (SAV-02) */}
      {waterfall && (
        <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Layers className="w-5 h-5 text-cyan-400" />
                Value Realisation Waterfall & Leakage Analysis (SAV-02)
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Full bridge from negotiated baseline to final cash-in-bank realized savings.
              </p>
            </div>
            <span className="text-xs font-mono px-2.5 py-1 rounded bg-slate-900 text-slate-300 border border-slate-700">
              FY 2026-27 YTD
            </span>
          </div>

          {/* Waterfall Stages Horizontal Flow */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
            {/* Step 1: Negotiated */}
            <div className="p-4 rounded-xl bg-blue-950/20 border border-blue-500/30 flex flex-col justify-between">
              <div>
                <span className="text-[10px] font-semibold text-blue-400 uppercase tracking-wider">Step 1 • Sourcing</span>
                <h5 className="text-xs font-bold text-slate-200 mt-1">Negotiated Savings</h5>
              </div>
              <div className="mt-4">
                <div className="text-xl font-bold font-mono text-blue-400">+₹{waterfall.negotiated_savings_cr.toFixed(2)} Cr</div>
                <span className="text-[10px] text-slate-400">Awarded via RFQ-2231</span>
              </div>
            </div>

            {/* Step 2: Contracted */}
            <div className="p-4 rounded-xl bg-indigo-950/20 border border-indigo-500/30 flex flex-col justify-between">
              <div>
                <span className="text-[10px] font-semibold text-indigo-400 uppercase tracking-wider">Step 2 • CLM</span>
                <h5 className="text-xs font-bold text-slate-200 mt-1">Contracted Frame</h5>
              </div>
              <div className="mt-4">
                <div className="text-xl font-bold font-mono text-indigo-400">₹{waterfall.contracted_savings_cr.toFixed(2)} Cr</div>
                <span className="text-[10px] text-slate-400">Scheduling SA-5520</span>
              </div>
            </div>

            {/* Step 3: Leakage Deduction */}
            <div className="p-4 rounded-xl bg-rose-950/20 border border-rose-500/30 flex flex-col justify-between">
              <div>
                <span className="text-[10px] font-semibold text-rose-400 uppercase tracking-wider">Step 3 • Friction</span>
                <h5 className="text-xs font-bold text-rose-300 mt-1">Leakage Friction</h5>
              </div>
              <div className="mt-4">
                <div className="text-xl font-bold font-mono text-rose-400">-₹{waterfall.leakage_total_cr.toFixed(2)} Cr</div>
                <span className="text-[10px] text-rose-300/80">3 Identified Root Causes</span>
              </div>
            </div>

            {/* Step 4: Realised P&L */}
            <div className="p-4 rounded-xl bg-emerald-950/30 border border-emerald-500/40 flex flex-col justify-between ring-1 ring-emerald-500/20">
              <div>
                <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider">Step 4 • P2P Invoices</span>
                <h5 className="text-xs font-bold text-emerald-200 mt-1">Realised P&L Savings</h5>
              </div>
              <div className="mt-4">
                <div className="text-xl font-bold font-mono text-emerald-400">₹{waterfall.realised_savings_pnl_cr.toFixed(2)} Cr</div>
                <span className="text-[10px] text-emerald-400/80">Posted to GL via 3-way</span>
              </div>
            </div>

            {/* Step 5: Cost Avoidance */}
            <div className="p-4 rounded-xl bg-amber-950/20 border border-amber-500/30 flex flex-col justify-between">
              <div>
                <span className="text-[10px] font-semibold text-amber-400 uppercase tracking-wider">Separate • Ringfenced</span>
                <h5 className="text-xs font-bold text-amber-200 mt-1">Cost Avoidance</h5>
              </div>
              <div className="mt-4">
                <div className="text-xl font-bold font-mono text-amber-400">₹{waterfall.cost_avoidance_cr.toFixed(2)} Cr</div>
                <span className="text-[10px] text-amber-400/80">Non-Budgetary Benefit</span>
              </div>
            </div>
          </div>

          {/* Leakage Root-Cause Breakdown */}
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-3">
            <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
              <ArrowDownRight className="w-4 h-4 text-rose-400" />
              Identified Leakage Friction Decomposition (₹{waterfall.leakage_total_cr} Cr)
            </h4>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80 space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">Off-Contract Maverick Buys</span>
                  <span className="font-mono text-rose-400 font-bold">₹{waterfall.leakage_breakdown.off_contract_buys_cr} Cr</span>
                </div>
                <p className="text-[11px] text-slate-500">Non-catalog purchases outside SA-5520 terms.</p>
              </div>

              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80 space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">Volume Shortfall (Tier Miss)</span>
                  <span className="font-mono text-rose-400 font-bold">₹{waterfall.leakage_breakdown.volume_shortfall_cr} Cr</span>
                </div>
                <p className="text-[11px] text-slate-500">Unfulfilled volume commitments pushing tier rebate out.</p>
              </div>

              <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80 space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">Price Drift & Index Variance</span>
                  <span className="font-mono text-rose-400 font-bold">₹{waterfall.leakage_breakdown.price_drift_cr} Cr</span>
                </div>
                <p className="text-[11px] text-slate-500">Unhedged spot commodity price adjustments.</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Savings Initiatives Register (SAV-01) */}
      <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
          <div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-emerald-400" />
              Governed Savings Initiatives Register (SAV-01)
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Audited line-by-line projects tied to Sourcing Events, Scheduling Contracts and General Ledger entries.
            </p>
          </div>
          <span className="text-xs text-slate-400 font-mono">
            {initiatives.length} Tracked Project{initiatives.length !== 1 ? 's' : ''}
          </span>
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-800/80">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-900/80 text-slate-400 font-medium border-b border-slate-800">
              <tr>
                <th className="py-3 px-3.5">ID / Project</th>
                <th className="py-3 px-3.5">Refs (P10)</th>
                <th className="py-3 px-3.5">Baseline vs Neg</th>
                <th className="py-3 px-3.5">Negotiated Savings</th>
                <th className="py-3 px-3.5">Cost Avoidance</th>
                <th className="py-3 px-3.5">Realised (P&L)</th>
                <th className="py-3 px-3.5">Finance Status</th>
                <th className="py-3 px-3.5 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {initiatives.map((init) => (
                <tr key={init.id} className="hover:bg-slate-800/30">
                  <td className="py-3.5 px-3.5">
                    <span className="font-bold text-cyan-400">{init.id}</span>
                    <div className="text-xs font-sans text-slate-200 mt-0.5 font-medium">{init.title}</div>
                    <span className="text-[10px] text-slate-400 font-mono">Owner: {init.owner}</span>
                  </td>
                  <td className="py-3.5 px-3.5 text-[11px] text-slate-400">
                    <div>SRC: <strong className="text-slate-300">{init.sourcing_event_ref}</strong></div>
                    <div>CLM: <strong className="text-slate-300">{init.contract_ref}</strong></div>
                  </td>
                  <td className="py-3.5 px-3.5 text-slate-300">
                    <div>Base: ₹{init.baseline_price_inr.toFixed(2)}</div>
                    <div className="text-emerald-400 font-bold">Neg: ₹{init.negotiated_weighted_price_inr.toFixed(2)}</div>
                  </td>
                  <td className="py-3.5 px-3.5 font-bold text-blue-400">
                    ₹{(init.negotiated_savings_annual_inr / 10000000).toFixed(2)} Cr/yr
                  </td>
                  <td className="py-3.5 px-3.5 text-amber-400 font-bold">
                    ₹{(init.cost_avoidance_annual_inr / 100000).toFixed(2)} L
                  </td>
                  <td className="py-3.5 px-3.5 font-bold text-emerald-400">
                    ₹{(init.realised_savings_ytd_inr / 100000).toFixed(2)} L
                  </td>
                  <td className="py-3.5 px-3.5">
                    {init.finance_validated ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                        <ShieldCheck className="w-3 h-3" />
                        VALIDATED
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                        PENDING AUDIT
                      </span>
                    )}
                    {init.finance_validator && (
                      <div className="text-[10px] text-slate-500 font-mono mt-1">
                        By: {init.finance_validator}
                      </div>
                    )}
                  </td>
                  <td className="py-3.5 px-3.5 text-right font-sans">
                    {!init.finance_validated ? (
                      <button
                        onClick={() => { setSelectedInit(init); setShowSignOffModal(true); }}
                        className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold text-white shadow-md shadow-emerald-600/20 transition"
                      >
                        Sign-off (SOD-07)
                      </button>
                    ) : (
                      <span className="text-xs text-slate-500 flex items-center justify-end gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                        Signed
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* SOD-07 Finance Sign-Off Modal */}
      {showSignOffModal && selectedInit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-lg bg-[#0B1528] border border-slate-700 rounded-2xl shadow-2xl p-6 space-y-5 text-slate-100">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3">
              <div>
                <span className="text-xs font-mono text-emerald-400 font-semibold">SOD-07 Enforced • Segregation of Duties</span>
                <h3 className="text-lg font-bold text-white mt-0.5">Finance Sign-Off on Realised Savings</h3>
              </div>
              <button 
                onClick={() => setShowSignOffModal(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 space-y-1.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Initiative ID:</span>
                <span className="font-mono font-bold text-cyan-400">{selectedInit.id}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Category Owner (Initiator):</span>
                <span className="font-mono text-slate-300">{selectedInit.owner}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Realised Savings to be Audited:</span>
                <span className="font-mono text-emerald-400 font-bold">₹{(selectedInit.realised_savings_ytd_inr / 100000).toFixed(2)} L</span>
              </div>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              In compliance with <strong>SOD-07</strong>, the finance controller validating realized savings must be distinct from the category manager who originated the initiative.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Finance Controller Actor ID (SOD-07 Validator)
                </label>
                <input
                  type="text"
                  value={financeValidator}
                  onChange={(e) => setFinanceValidator(e.target.value)}
                  className="w-full px-3.5 py-2 bg-slate-900 border border-slate-700 rounded-xl font-mono text-cyan-300 text-xs focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Audit Notes & General Ledger Voucher Reference
                </label>
                <textarea
                  rows={2}
                  value={comments}
                  onChange={(e) => setComments(e.target.value)}
                  className="w-full px-3.5 py-2 bg-slate-900 border border-slate-700 rounded-xl text-slate-200 text-xs focus:outline-none focus:border-cyan-500"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                onClick={() => setShowSignOffModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300"
              >
                Cancel
              </button>
              <button
                onClick={handleValidateInitiative}
                disabled={validating}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-xs font-bold text-white shadow-lg shadow-emerald-600/20 disabled:opacity-50 transition"
              >
                {validating ? 'Verifying SOD-07...' : 'Confirm Finance Sign-off'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
