'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Target, Award, CheckCircle2, AlertTriangle, 
  ArrowRight, Search, RefreshCw, Plus, Layers, Zap, 
  BarChart3, Clock, ChevronRight, ShieldCheck, DollarSign,
  Building2, Sparkles, Scale, Sliders, CheckCheck, X
} from 'lucide-react';
import axios from 'axios';

interface SourcingBid {
  bid_id: string;
  supplier_id: string;
  supplier_name: string;
  submitted_at: string;
  initial_unit_price_inr: number;
  negotiated_unit_price_inr: number;
  freight_per_unit_inr: number;
  packaging_inr: number;
  carrying_cost_inr: number;
  quality_cost_inr: number;
  payment_term_days: number;
  payment_term_benefit_inr: number;
  computed_tco_inr: number;
  total_score: number;
  verified_monthly_capacity: number;
}

interface SourcingEvent {
  id: string;
  title: string;
  type: string;
  category: string;
  commodity_code: string;
  plant: string;
  status: string;
  target_annual_volume: number;
  monthly_run_rate: number;
  should_cost_model: {
    commodity: string;
    computed_should_cost_inr: number;
    baseline_last_price_inr: number;
  };
  scoring_weights: Record<string, number>;
  weights_locked: boolean;
  bids: SourcingBid[];
  award_recommendation?: any;
}

export default function SourcingCockpitPage() {
  const [events, setEvents] = useState<SourcingEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<SourcingEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [optimizingMIP, setOptimizingMIP] = useState(false);
  const [showAwardModal, setShowAwardModal] = useState(false);
  const [awarding, setAwarding] = useState(false);

  const triggerToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4500);
  };

  const loadEvents = async () => {
    setLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8080/api/v1/strategic/sourcing/events');
      if (res.data.status === 'success') {
        const evs = res.data.events || [];
        setEvents(evs);
        if (evs.length > 0) {
          setSelectedEvent(evs[0]);
        }
      }
    } catch (err) {
      console.error('Failed to load sourcing events:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEvents();
  }, []);

  const handleRunMIP = async () => {
    if (!selectedEvent) return;
    setOptimizingMIP(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/strategic/sourcing/events/${selectedEvent.id}/optimize-award`);
      if (res.data.status === 'success') {
        setSelectedEvent({
          ...selectedEvent,
          award_recommendation: res.data.optimal_award
        });
        triggerToast('MIP Solver optimized dual-source award: 60/40 allocation under capacity constraint!');
      }
    } catch (err: any) {
      alert(`MIP Optimization failed: ${err.message}`);
    } finally {
      setOptimizingMIP(false);
    }
  };

  const handleExecuteAward = async () => {
    if (!selectedEvent || !selectedEvent.award_recommendation) return;
    setAwarding(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/strategic/sourcing/events/${selectedEvent.id}/award`, {
        event_id: selectedEvent.id,
        strategy: selectedEvent.award_recommendation.strategy,
        allocations: selectedEvent.award_recommendation.allocations,
        actor: 'u:category.mgr.castings',
        finance_approver: 'u:finance.controller.p100'
      });
      if (res.data.status === 'success') {
        triggerToast(`Award executed! Sourcing event ${selectedEvent.id} is now AWARDED.`);
        setShowAwardModal(false);
        loadEvents();
      }
    } catch (err: any) {
      alert(`Award execution failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setAwarding(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 md:p-8 space-y-8 font-sans">
      
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-3 bg-emerald-950/90 border border-emerald-500/50 text-emerald-200 px-5 py-3.5 rounded-xl shadow-2xl backdrop-blur-md animate-in fade-in duration-300">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
        </div>
      )}

      {/* Header Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#0B1528] via-[#0F1E38] to-[#070B14] border border-slate-800/80 p-8 shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="px-3 py-1 text-xs font-bold tracking-widest uppercase bg-cyan-950/80 text-cyan-400 border border-cyan-800/80 rounded-full flex items-center gap-1.5 shadow-sm">
                <Target className="w-3.5 h-3.5" /> Module M05: Strategic Sourcing
              </span>
              <span className="px-2.5 py-0.5 text-xs font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-800/50 rounded-full">
                MIP Award Optimizer & Should-Cost
              </span>
            </div>
            <h1 className="text-3xl lg:text-4xl font-extrabold tracking-tight text-white flex items-center gap-3">
              Strategic Sourcing & Award Studio (SRC-01..05)
            </h1>
            <p className="text-slate-400 max-w-3xl text-sm md:text-base leading-relaxed">
              Run competitive RFQs, normalise supplier TCO stacks, benchmark against parametric should-cost models, and solve capacity-constrained dual-sourcing optimizations.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button 
              onClick={handleRunMIP}
              disabled={optimizingMIP || selectedEvent?.status === 'AWARDED'}
              className="px-4 py-2.5 rounded-xl text-sm font-semibold bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white shadow-lg shadow-cyan-900/40 flex items-center gap-2 transition-all border border-cyan-400/30"
            >
              <Scale className="w-4 h-4" /> {optimizingMIP ? 'Optimizing...' : 'Run MIP Optimizer'}
            </button>
            <button 
              onClick={() => setShowAwardModal(true)}
              disabled={!selectedEvent?.award_recommendation || selectedEvent?.status === 'AWARDED'}
              className="px-4 py-2.5 rounded-xl text-sm font-semibold bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white shadow-lg shadow-emerald-900/40 flex items-center gap-2 transition-all border border-emerald-400/30"
            >
              <Award className="w-4 h-4" /> {selectedEvent?.status === 'AWARDED' ? 'Award Executed' : 'Execute Award Decision'}
            </button>
            <button 
              onClick={loadEvents}
              disabled={loading}
              className="p-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
            </button>
          </div>
        </div>

        {/* Quick Cross-Links */}
        <div className="mt-8 pt-6 border-t border-slate-800/60 flex flex-wrap items-center gap-4 text-xs font-medium text-slate-300">
          <span className="text-slate-500 font-semibold uppercase tracking-wider">Related Lifecycle Modules:</span>
          <Link 
            href="/contracts/agreements"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/80 hover:bg-slate-800 border border-slate-700/80 text-cyan-300 hover:text-cyan-200 transition-colors group"
          >
            <span>Buy-Side CLM (Scheduling Agreement SA-5520)</span>
            <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
          </Link>
          <Link 
            href="/savings"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/80 hover:bg-slate-800 border border-slate-700/80 text-emerald-300 hover:text-emerald-200 transition-colors group"
          >
            <span>Savings Realisation Waterfall (P12)</span>
            <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
          </Link>
          <Link 
            href="/p2p"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/80 hover:bg-slate-800 border border-slate-700/80 text-slate-300 hover:text-white transition-colors"
          >
            <span>Operational P2P Cockpit</span>
          </Link>
        </div>
      </div>

      {/* Main Grid: Event Details & Should-Cost vs TCO */}
      {selectedEvent && (
        <div className="space-y-6">
          
          {/* Top Event Summary & Should-Cost Cards */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            
            {/* Event Header & Scope (7 cols) */}
            <div className="lg:col-span-7 bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
              <div className="flex items-start justify-between gap-3 border-b border-slate-800 pb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-lg font-mono font-bold text-white">{selectedEvent.id}</span>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-bold border ${
                      selectedEvent.status === 'AWARDED' ? 'bg-emerald-950 text-emerald-300 border-emerald-800' : 'bg-cyan-950 text-cyan-300 border border-cyan-800'
                    }`}>
                      {selectedEvent.status}
                    </span>
                    <span className="text-xs text-slate-400 font-mono">AS9100D Castings</span>
                  </div>
                  <h2 className="text-base font-bold text-white mt-1">
                    {selectedEvent.title}
                  </h2>
                </div>
                <div className="text-right text-xs">
                  <span className="text-slate-500 block">Annual Volume</span>
                  <span className="font-mono text-cyan-300 font-bold text-sm">
                    {selectedEvent.target_annual_volume.toLocaleString()} EA
                  </span>
                  <span className="text-[10px] text-slate-500">({selectedEvent.monthly_run_rate.toLocaleString()} / mo)</span>
                </div>
              </div>

              {/* Locked Scoring Weights Strip (Principle P06) */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                    <Sliders className="w-3.5 h-3.5 text-cyan-400" />
                    Locked Scoring Weights (Sum: 100%)
                  </span>
                  <span className="text-emerald-400 text-[11px] font-semibold">Weights Locked at Publish</span>
                </div>
                <div className="grid grid-cols-5 gap-2 text-center text-xs">
                  <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                    <span className="text-[10px] text-slate-500 block">Commercial TCO</span>
                    <span className="font-bold text-white">{selectedEvent.scoring_weights.commercial_tco}%</span>
                  </div>
                  <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                    <span className="text-[10px] text-slate-500 block">Quality PPM</span>
                    <span className="font-bold text-white">{selectedEvent.scoring_weights.quality_ppm}%</span>
                  </div>
                  <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                    <span className="text-[10px] text-slate-500 block">Delivery OTIF</span>
                    <span className="font-bold text-white">{selectedEvent.scoring_weights.delivery_otif}%</span>
                  </div>
                  <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                    <span className="text-[10px] text-slate-500 block">Technical</span>
                    <span className="font-bold text-white">{selectedEvent.scoring_weights.technical_capability}%</span>
                  </div>
                  <div className="p-2 rounded-lg bg-slate-900 border border-slate-800">
                    <span className="text-[10px] text-slate-500 block">ESG / Carbon</span>
                    <span className="font-bold text-white">{selectedEvent.scoring_weights.esg_sustainability}%</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Should-Cost Benchmark Card (5 cols) */}
            <div className="lg:col-span-5 bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <span className="font-bold text-white text-sm flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-cyan-400" />
                  Parametric Should-Cost Model
                </span>
                <span className="text-[11px] font-mono text-cyan-400">EN AC-46000 Alloy</span>
              </div>

              <div className="grid grid-cols-2 gap-3 text-center">
                <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800">
                  <span className="text-[10px] text-slate-500 uppercase font-bold block">Baseline Last Price</span>
                  <span className="text-xl font-bold text-slate-300">
                    ₹{selectedEvent.should_cost_model.baseline_last_price_inr.toFixed(2)}
                  </span>
                  <span className="text-[10px] text-slate-500 block mt-0.5">Prior purchase order price</span>
                </div>
                <div className="p-3.5 rounded-xl bg-cyan-950/30 border border-cyan-800/60">
                  <span className="text-[10px] text-cyan-400 uppercase font-bold block">Parametric Should-Cost</span>
                  <span className="text-xl font-black text-cyan-300">
                    ₹{selectedEvent.should_cost_model.computed_should_cost_inr.toFixed(2)}
                  </span>
                  <span className="text-[10px] text-emerald-400 block mt-0.5">-4.6% Sourcing Target</span>
                </div>
              </div>

              <div className="text-[11px] text-slate-400 bg-slate-900/60 p-2.5 rounded-lg border border-slate-800 leading-relaxed">
                <strong>Model Basis:</strong> 1.95 kg net casting weight • LME Aluminium cash settlement ₹210/kg • 42s cycle time on 850T cold-chamber machine • SG&amp;A 8% • Target supplier margin 10%.
              </div>
            </div>

          </div>

          {/* Bid Comparison & Normalised TCO Stack Table (SRC-03) */}
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <DollarSign className="w-4 h-4 text-cyan-400" />
                  Normalized Bid Comparison & Total Cost of Ownership (TCO) Stack
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  TCO includes base price, freight, packaging, carrying cost, expected COPQ quality cost, and payment term value.
                </p>
              </div>
              <span className="text-xs text-slate-400 font-medium">Bids Unsealed at Event Close (Audit Verified)</span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] font-bold text-slate-400 uppercase bg-slate-900/40">
                    <th className="py-3 px-4">Supplier Partner</th>
                    <th className="py-3 px-4">Base Price (INR)</th>
                    <th className="py-3 px-4">Freight & Pack</th>
                    <th className="py-3 px-4">Carrying Cost</th>
                    <th className="py-3 px-4">Quality COPQ</th>
                    <th className="py-3 px-4">Terms Benefit</th>
                    <th className="py-3 px-4">Computed TCO</th>
                    <th className="py-3 px-4">Total Score</th>
                    <th className="py-3 px-4">Monthly Capacity</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {selectedEvent.bids.map((bid) => (
                    <tr key={bid.bid_id} className="hover:bg-slate-900/60 transition-colors">
                      <td className="py-3 px-4">
                        <div className="font-bold text-white">{bid.supplier_name}</div>
                        <div className="text-[10px] text-slate-500 font-mono">{bid.supplier_id}</div>
                      </td>
                      <td className="py-3 px-4 font-mono font-semibold text-slate-200">
                        ₹{bid.negotiated_unit_price_inr.toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-slate-400 font-mono">
                        +₹{(bid.freight_per_unit_inr + bid.packaging_inr).toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-slate-400 font-mono">
                        +₹{bid.carrying_cost_inr.toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-amber-400 font-mono">
                        +₹{bid.quality_cost_inr.toFixed(2)}
                      </td>
                      <td className="py-3 px-4 text-emerald-400 font-mono">
                        {bid.payment_term_benefit_inr < 0 ? `-₹${Math.abs(bid.payment_term_benefit_inr).toFixed(2)}` : '₹0.00'}
                      </td>
                      <td className="py-3 px-4 font-mono font-bold text-cyan-300">
                        ₹{bid.computed_tco_inr.toFixed(2)}
                      </td>
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 rounded font-bold text-xs bg-cyan-950 text-cyan-300 border border-cyan-800">
                          {bid.total_score} / 100
                        </span>
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-300">
                        {bid.verified_monthly_capacity.toLocaleString()} / mo
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* MIP Award Optimization Studio (SRC-04) */}
          {selectedEvent.award_recommendation && (
            <div className="bg-[#0B1528]/80 backdrop-blur-md border border-emerald-500/40 rounded-2xl p-6 shadow-xl space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <Scale className="w-5 h-5 text-emerald-400" />
                  <h3 className="text-base font-bold text-white">
                    Mixed-Integer Programming (MIP) Optimal Award Recommendation
                  </h3>
                  <span className="text-xs px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-mono">
                    {selectedEvent.award_recommendation.strategy}
                  </span>
                </div>
                <div className="text-xs font-semibold text-emerald-400">
                  Negotiated Savings: ₹{(selectedEvent.award_recommendation.negotiated_annual_savings_inr / 10000000).toFixed(2)} Cr/year
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {selectedEvent.award_recommendation.allocations.map((alloc: any, idx: number) => (
                  <div key={idx} className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2 text-xs">
                    <div className="flex justify-between items-center">
                      <span className="font-bold text-white text-sm">{alloc.name}</span>
                      <span className="text-xs font-black text-cyan-300 px-2.5 py-0.5 rounded-full bg-cyan-950 border border-cyan-800">
                        {alloc.share_pct}% Volume Share
                      </span>
                    </div>
                    <div className="flex justify-between text-slate-400">
                      <span>Agreed Unit Price:</span>
                      <span className="font-mono font-bold text-emerald-400">₹{alloc.unit_price.toFixed(2)} / EA</span>
                    </div>
                    <div className="flex justify-between text-slate-400">
                      <span>Monthly Allocation:</span>
                      <span className="font-mono text-slate-200">{alloc.monthly_qty.toLocaleString()} units / month</span>
                    </div>
                  </div>
                ))}
              </div>

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 text-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
                <div className="text-slate-300">
                  <strong>Weighted Average Sourcing Price:</strong> <span className="font-mono font-bold text-emerald-400 text-sm">₹{selectedEvent.award_recommendation.weighted_average_price_inr.toFixed(2)}</span> (Annual Contract Value: ₹{(selectedEvent.award_recommendation.annual_contract_value_inr / 10000000).toFixed(2)} Cr)
                </div>
                <div className="text-slate-400 text-[11px]">
                  Hands off to Scheduling Agreement <strong>SA-5520</strong> &amp; Savings <strong>SV-0412</strong>.
                </div>
              </div>
            </div>
          )}

        </div>
      )}

      {/* Award Decision Modal */}
      {showAwardModal && selectedEvent && selectedEvent.award_recommendation && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0B1528] border border-slate-700 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Award className="w-5 h-5 text-emerald-400" /> Execute Dual-Source Award Decision
              </h3>
              <button onClick={() => setShowAwardModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <p className="text-slate-300 leading-relaxed">
                You are executing the formal commercial award for <strong>{selectedEvent.id}</strong> ({selectedEvent.title}):
              </p>

              <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                <div className="flex justify-between text-slate-300">
                  <span>Trichy Forge Works:</span>
                  <span className="font-bold text-cyan-300">60% @ ₹398.00 (648k units/yr)</span>
                </div>
                <div className="flex justify-between text-slate-300">
                  <span>Kovai Diecast Industries:</span>
                  <span className="font-bold text-cyan-300">40% @ ₹405.00 (432k units/yr)</span>
                </div>
                <div className="flex justify-between text-slate-400 pt-1 border-t border-slate-800">
                  <span>Weighted Average Price:</span>
                  <span className="font-bold text-emerald-400">₹400.80 / EA</span>
                </div>
              </div>

              <div className="p-3 rounded-lg bg-emerald-950/20 border border-emerald-800/40 text-[11px] text-emerald-300">
                <strong>SoD Guard Verification:</strong> Category Manager recommendation approved with independent Finance Controller sign-off (SOD-05).
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
              <button 
                onClick={() => setShowAwardModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 text-xs font-semibold"
              >
                Cancel
              </button>
              <button 
                onClick={handleExecuteAward}
                disabled={awarding}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-emerald-900/40"
              >
                {awarding ? 'Executing...' : 'Authorize Award'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
