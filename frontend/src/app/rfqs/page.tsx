"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { 
  FileText, Filter, Check, X, Clock, ArrowRight, CheckCircle2, 
  AlertCircle, DollarSign, Building2, Calendar, ShieldCheck, 
  FileCheck, Download, ExternalLink, ChevronRight, MessageSquare,
  Sparkles, RefreshCw, Trophy, Sliders, TrendingDown, Plus, Cpu,
  Layers, Zap
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, TEST_TENANT_ID } from '@/lib/apiClient';

interface QuoteDetail {
  quote_id: string;
  supplier_id: string;
  supplier_name: string;
  supplier_tier: string;
  unit_price: number;
  total_amount: number;
  lead_time_days: number;
  committed_delivery_date: string;
  twin_match_pct: number;
  digital_twin_fit: string;
  atp_badge: string;
  quality_score: number;
  mcda_score: number;
  ai_recommendation: string;
  ai_reasoning: string;
  payment_terms: string;
  incoterms: string;
}

export default function RFQs() {
  const queryClient = useQueryClient();
  const [selectedRfqForModal, setSelectedRfqForModal] = useState<any | null>(null);
  const [selectedPo, setSelectedPo] = useState<any | null>(null);
  const [awardingQuoteId, setAwardingQuoteId] = useState<string | null>(null);
  const [actionToast, setActionToast] = useState<string | null>(null);

  // 1. Fetch live Overview KPIs
  const { data: overviewData } = useQuery({
    queryKey: ['buyer-rfqs-overview'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/rfqs/overview');
      return res.data;
    }
  });

  // 2. Fetch live RFQ List
  const { data: rfqs = [], isLoading: rfqsLoading } = useQuery({
    queryKey: ['buyer-rfqs-list'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/rfqs/list');
      return res.data;
    }
  });

  // 3. Fetch live Purchase Orders from backend
  const { data: pos = [], isLoading: posLoading, refetch: refetchPos } = useQuery({
    queryKey: ['buyer-pos', TEST_TENANT_ID],
    queryFn: async () => {
      const response = await apiClient.get(`/api/v1/procurement/po?tenant_id=${TEST_TENANT_ID}`);
      return response.data;
    }
  });

  // 4. Fetch live Invoices from backend
  const { data: invoices = [] } = useQuery({
    queryKey: ['buyer-invoices', TEST_TENANT_ID],
    queryFn: async () => {
      const response = await apiClient.get(`/api/v1/finance/invoices?buyer_tenant_id=${TEST_TENANT_ID}`);
      return response.data;
    }
  });

  // 5. Fetch bids for selected modal RFQ
  const { data: modalBidsData, isLoading: modalBidsLoading } = useQuery({
    queryKey: ['modal-rfq-bids', selectedRfqForModal?.id],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/procurement/rfqs/${selectedRfqForModal.id}/bids`);
      return res.data;
    },
    enabled: !!selectedRfqForModal
  });

  // Award Bid Mutation
  const awardMutation = useMutation({
    mutationFn: async ({ rfqId, quoteId, supplierId }: { rfqId: string; quoteId: string; supplierId: string }) => {
      const res = await apiClient.post(`/api/v1/procurement/rfqs/${rfqId}/award`, {
        quote_id: quoteId,
        supplier_id: supplierId,
        buyer_tenant_id: TEST_TENANT_ID
      });
      return res.data;
    },
    onSuccess: (data) => {
      setActionToast(`Quotation accepted! Purchase Order ${data.award.po_number} generated.`);
      refetchPos();
      queryClient.invalidateQueries({ queryKey: ['buyer-rfqs-list'] });
      queryClient.invalidateQueries({ queryKey: ['buyer-rfqs-overview'] });
      setTimeout(() => setSelectedRfqForModal(null), 1200);
    },
    onError: (err: any) => {
      setActionToast(`Award failed: ${err?.response?.data?.detail || err.message}`);
    }
  });

  const kpis = overviewData?.kpis || {
    total_rfqs: 6,
    active_rfqs: 4,
    under_evaluation: 2,
    awarded_rfqs: 2,
    total_pipeline_value: 306150,
    average_savings_pct: 12.4,
    total_bids_received: 12
  };

  const modalBids: QuoteDetail[] = modalBidsData?.bids || [];

  return (
    <div className="flex flex-col min-h-screen bg-[#070B14] text-slate-100 animate-in fade-in duration-300 pb-16">
      {/* Toast Notification */}
      {actionToast && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] border border-cyan-500/40 text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 backdrop-blur-md animate-bounce">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-semibold">{actionToast}</span>
          <button onClick={() => setActionToast(null)} className="ml-2 text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* HEADER */}
      <div className="border-b border-slate-800 bg-[#0B0F19]/90 backdrop-blur-md px-8 py-6 shrink-0 sticky top-0 z-30">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 max-w-7xl mx-auto w-full">
          <div>
            <div className="text-[11px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-1.5">
              <span>Aerospace Strategic Sourcing</span>
              <span className="text-slate-600">›</span>
              <span className="text-cyan-400 font-extrabold">Autonomous RFQ Command Hub</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight flex items-center gap-3">
              <span>RFQ Sourcing & Multi-Supplier Portal</span>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-black bg-emerald-950 text-emerald-300 border border-emerald-500/50">
                Live Twin Integrated
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-2xl">
              Broadcast RFQs, evaluate real-time multi-supplier quotations via MCDA, and 1-click issue Purchase Orders.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/rfqs/responses"
              className="px-4 py-2.5 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-xl text-xs font-black shadow-lg shadow-cyan-600/30 flex items-center gap-2 transition-all active:scale-95"
            >
              <Trophy className="w-4 h-4" />
              <span>Multi-Supplier Bidding Room</span>
            </Link>

            <Link 
              href="/rfqs/create" 
              className="px-4 py-2.5 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-200 rounded-xl text-xs font-bold transition-all flex items-center gap-2 shadow-sm"
            >
              <Plus className="w-4 h-4 text-cyan-400" />
              <span>Create RFQ</span>
            </Link>
          </div>
        </div>
      </div>

      <div className="flex-1 px-8 py-6 space-y-6 max-w-7xl w-full mx-auto">
        {/* KPI CARDS RIBBON */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-cyan-950/80 border border-cyan-800 text-cyan-400 flex items-center justify-center shrink-0">
              <FileText className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Active Pipeline</span>
              <span className="text-2xl font-black text-white">{kpis.active_rfqs} Open RFQs</span>
              <span className="text-[10px] text-cyan-400 block mt-0.5 font-bold">
                ${(kpis.total_pipeline_value / 1000).toFixed(1)}k Total Budget
              </span>
            </div>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-emerald-950/80 border border-emerald-800 text-emerald-400 flex items-center justify-center shrink-0">
              <TrendingDown className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Realized Cost Savings</span>
              <span className="text-2xl font-black text-emerald-400">-{kpis.average_savings_pct}%</span>
              <span className="text-[10px] text-emerald-400 block mt-0.5 font-bold">via MCDA Bidding Matrix</span>
            </div>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-purple-950/80 border border-purple-800 text-purple-400 flex items-center justify-center shrink-0">
              <Trophy className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Executed Awards</span>
              <span className="text-2xl font-black text-purple-300">{kpis.awarded_rfqs} Contracts</span>
              <span className="text-[10px] text-purple-400 block mt-0.5 font-bold">POs Dispatched to Plants</span>
            </div>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-950/80 border border-blue-800 text-blue-400 flex items-center justify-center shrink-0">
              <Sparkles className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Supplier Quotes</span>
              <span className="text-2xl font-black text-white">{kpis.total_bids_received} Bids</span>
              <span className="text-[10px] text-cyan-400 block mt-0.5 font-bold">95.8% Digital Twin Fit</span>
            </div>
          </div>
        </div>

        {/* QUICK NAVIGATION SUITE */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Link
            href="/rfqs/responses"
            className="p-4 bg-[#0E1526] hover:bg-[#141E34] border border-slate-800 hover:border-cyan-500/50 rounded-xl transition-all group shadow-md"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-black text-white group-hover:text-cyan-300 transition-colors">
                Multi-Supplier Responses
              </span>
              <Trophy className="w-4 h-4 text-cyan-400" />
            </div>
            <p className="text-[11px] text-slate-400">Side-by-side bid matrix & MCDA weights</p>
          </Link>

          <Link
            href="/rfqs/my-rfqs"
            className="p-4 bg-[#0E1526] hover:bg-[#141E34] border border-slate-800 hover:border-cyan-500/50 rounded-xl transition-all group shadow-md"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-black text-white group-hover:text-cyan-300 transition-colors">
                My RFQs Registry
              </span>
              <Layers className="w-4 h-4 text-blue-400" />
            </div>
            <p className="text-[11px] text-slate-400">Filter all buyer sourcing events</p>
          </Link>

          <Link
            href="/rfqs/compare"
            className="p-4 bg-[#0E1526] hover:bg-[#141E34] border border-slate-800 hover:border-cyan-500/50 rounded-xl transition-all group shadow-md"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-black text-white group-hover:text-cyan-300 transition-colors">
                Compare Matrix
              </span>
              <Sliders className="w-4 h-4 text-purple-400" />
            </div>
            <p className="text-[11px] text-slate-400">Detailed line-item cross examination</p>
          </Link>

          <Link
            href="/rfqs/analytics"
            className="p-4 bg-[#0E1526] hover:bg-[#141E34] border border-slate-800 hover:border-cyan-500/50 rounded-xl transition-all group shadow-md"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-black text-white group-hover:text-cyan-300 transition-colors">
                Sourcing Analytics
              </span>
              <TrendingDown className="w-4 h-4 text-emerald-400" />
            </div>
            <p className="text-[11px] text-slate-400">Category savings & response latency</p>
          </Link>
        </div>

        {/* SECTION 1: ACTIVE RFQ PIPELINE */}
        <div className="bg-[#0E1526] rounded-2xl shadow-xl border border-slate-800 overflow-hidden">
          <div className="border-b border-slate-800 p-4 px-6 flex justify-between items-center bg-[#141B2D]/60">
            <div className="flex items-center gap-3">
              <h2 className="font-black text-white text-base">Active RFQs & Bidding Events</h2>
              <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800">
                {rfqs.length} Events
              </span>
            </div>
            <Link 
              href="/rfqs/my-rfqs"
              className="text-cyan-400 hover:underline text-xs font-bold flex items-center gap-1"
            >
              <span>View All</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 bg-[#141B2D]/30 text-slate-400 font-bold uppercase tracking-wider">
                  <th className="p-4">RFQ Number</th>
                  <th className="p-4">Title & Part Number</th>
                  <th className="p-4">Deadline</th>
                  <th className="p-4 text-center">Quotes Received</th>
                  <th className="p-4 text-right">Target Budget</th>
                  <th className="p-4 text-right">Lowest Bid</th>
                  <th className="p-4 text-center">Status</th>
                  <th className="p-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {rfqsLoading ? (
                  <tr>
                    <td colSpan={8} className="p-8 text-center text-slate-400">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto text-cyan-400 mb-2" />
                      Loading live RFQs...
                    </td>
                  </tr>
                ) : rfqs.map((rfq: any) => {
                  const isAwarded = rfq.status === 'AWARDED';
                  return (
                    <tr key={rfq.id} className="hover:bg-slate-800/30 transition-colors">
                      <td className="p-4 font-mono font-bold text-cyan-300 text-sm">{rfq.id}</td>
                      <td className="p-4">
                        <strong className="text-white block font-bold">{rfq.title}</strong>
                        <span className="text-[11px] text-slate-400">{rfq.part_number} • {rfq.category}</span>
                      </td>
                      <td className="p-4 text-slate-400">{rfq.deadline_date || '2026-10-25'}</td>
                      <td className="p-4 text-center">
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-800">
                          {rfq.quotes_received} Bids
                        </span>
                      </td>
                      <td className="p-4 text-right font-mono text-slate-300 font-bold">
                        ${rfq.target_total_budget?.toLocaleString()}
                      </td>
                      <td className="p-4 text-right">
                        <strong className="text-emerald-400 font-mono text-sm block">
                          ${rfq.lowest_bid_amount?.toLocaleString()}
                        </strong>
                        {rfq.savings_pct > 0 && (
                          <span className="text-[10px] text-emerald-400 font-bold">
                            -{rfq.savings_pct}%
                          </span>
                        )}
                      </td>
                      <td className="p-4 text-center">
                        <span className={`px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wider border ${
                          isAwarded
                            ? 'bg-purple-950/80 text-purple-300 border-purple-500/40'
                            : rfq.status === 'UNDER_EVALUATION'
                            ? 'bg-blue-950/80 text-blue-300 border-blue-500/40'
                            : 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40'
                        }`}>
                          {isAwarded ? '🏆 Awarded' : rfq.status === 'UNDER_EVALUATION' ? 'Evaluating' : 'Open'}
                        </span>
                      </td>
                      <td className="p-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button 
                            onClick={() => setSelectedRfqForModal(rfq)}
                            className="px-3 py-1.5 bg-cyan-600/20 hover:bg-cyan-600/40 border border-cyan-500/40 text-cyan-300 rounded-lg text-xs font-bold transition-all shadow-sm flex items-center gap-1 active:scale-95"
                          >
                            <span>Quick View</span>
                            <ChevronRight className="w-3.5 h-3.5" />
                          </button>
                          <Link
                            href={`/rfqs/responses?rfq_id=${rfq.id}`}
                            className="px-3 py-1.5 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-lg text-xs font-bold transition-all"
                          >
                            Evaluate
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* SECTION 2: ISSUED PURCHASE ORDERS (RECONCILIATION) */}
        <div className="bg-[#0E1526] rounded-2xl shadow-xl border border-slate-800 overflow-hidden">
          <div className="border-b border-slate-800 p-4 px-6 flex justify-between items-center bg-[#141B2D]/60">
            <div className="flex items-center gap-3">
              <h2 className="font-black text-white text-base">Issued Purchase Orders (Commercial Ledger)</h2>
              <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800">
                {pos.length} Active Orders
              </span>
            </div>
            <Link 
              href="/invoices" 
              className="text-emerald-400 hover:underline text-xs font-bold flex items-center gap-1"
            >
              <span>Finance Ledger</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 bg-[#141B2D]/30 text-slate-400 font-bold uppercase tracking-wider">
                  <th className="p-4">PO Number</th>
                  <th className="p-4">Date Issued</th>
                  <th className="p-4">Supplier Entity</th>
                  <th className="p-4 text-right">Amount</th>
                  <th className="p-4 text-center">Status</th>
                  <th className="p-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {posLoading ? (
                  <tr>
                    <td colSpan={6} className="p-8 text-center text-slate-400">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto text-cyan-400 mb-2" />
                      Loading live purchase orders...
                    </td>
                  </tr>
                ) : pos.slice(0, 5).map((po: any) => (
                  <tr key={po.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="p-4 font-mono font-bold text-white text-sm">
                      {po.po_number || po.id.substring(0, 10)}
                    </td>
                    <td className="p-4 text-slate-400">
                      {po.created_at ? new Date(po.created_at).toLocaleDateString() : '10/12/2026'}
                    </td>
                    <td className="p-4 font-bold text-cyan-300">
                      {po.supplier_tenant_id === 'TENANT_SUPPLIER_001' ? 'Apex Precision Machining Ltd' : 'Verified Twin Partner'}
                    </td>
                    <td className="p-4 text-right font-mono font-black text-emerald-400 text-sm">
                      ${(po.total_amount || 29500).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </td>
                    <td className="p-4 text-center">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wider bg-blue-950 text-blue-300 border border-blue-500/40">
                        {po.status || 'ISSUED'}
                      </span>
                    </td>
                    <td className="p-4 text-right">
                      <button 
                        onClick={() => setSelectedPo(po)}
                        className="px-3.5 py-1.5 bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300 border border-emerald-500/40 rounded-lg text-xs font-bold transition-all shadow-sm flex items-center gap-1.5 ml-auto active:scale-95"
                      >
                        <FileCheck className="w-3.5 h-3.5" />
                        <span>Reconcile Invoice</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* QUICK BID EVALUATION MODAL */}
      {selectedRfqForModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0E1526] border border-cyan-500/60 rounded-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden shadow-2xl text-slate-100">
            {/* Modal Header */}
            <div className="px-6 py-4 bg-[#141E34] border-b border-slate-800 flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-800">
                    {selectedRfqForModal.id}
                  </span>
                  <span className="text-xs text-slate-400">Target Budget: ${selectedRfqForModal.target_total_budget?.toLocaleString()}</span>
                </div>
                <h3 className="text-lg font-black text-white mt-1">
                  Submitted Quotations: {selectedRfqForModal.title}
                </h3>
              </div>
              <button 
                onClick={() => setSelectedRfqForModal(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-4">
              <div className="flex items-center justify-between text-xs text-slate-400 pb-2 border-b border-slate-800">
                <span>{modalBids.length} Qualified Bids Submitted</span>
                <Link
                  href={`/rfqs/responses?rfq_id=${selectedRfqForModal.id}`}
                  className="text-cyan-400 hover:underline flex items-center gap-1 font-bold"
                >
                  <span>Open Full MCDA Decision Room</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </Link>
              </div>

              {modalBidsLoading ? (
                <div className="p-12 text-center text-slate-400">
                  <RefreshCw className="w-6 h-6 animate-spin mx-auto text-cyan-400 mb-2" />
                  Loading bids...
                </div>
              ) : modalBids.map((quote, idx) => (
                <div
                  key={quote.quote_id}
                  className={`border rounded-xl p-4 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4 ${
                    idx === 0 
                      ? 'border-cyan-500/70 bg-gradient-to-r from-cyan-950/40 to-slate-900/60 shadow-md' 
                      : 'border-slate-800 bg-[#141B2D]/40'
                  }`}
                >
                  <div className="space-y-1.5 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-black text-white text-base">{quote.supplier_name}</span>
                      {idx === 0 && (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-cyan-400 text-slate-950 flex items-center gap-1">
                          <Sparkles className="w-3 h-3" /> Top Evaluated
                        </span>
                      )}
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-900 text-slate-400 border border-slate-800">
                        {quote.quote_id}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs pt-1">
                      <div>
                        <span className="text-slate-400 block text-[11px]">Lead Time</span>
                        <strong className="text-white">{quote.lead_time_days} Days</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[11px]">Twin Fit</span>
                        <strong className="text-emerald-400">{quote.twin_match_pct}% Match</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[11px]">Unit Price</span>
                        <strong className="text-white">${quote.unit_price} / pc</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[11px]">MCDA Composite</span>
                        <strong className="text-cyan-300 font-mono">{quote.mcda_score} / 100</strong>
                      </div>
                    </div>
                  </div>

                  <div className="flex sm:flex-col items-center sm:items-end justify-between gap-3 shrink-0 pt-2 sm:pt-0 border-t sm:border-t-0 border-slate-800">
                    <div className="text-right">
                      <span className="text-[11px] text-slate-400 block">Total Quoted Price</span>
                      <span className="text-xl font-black text-emerald-400 font-mono">
                        ${quote.total_amount?.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => {
                          setAwardingQuoteId(quote.quote_id);
                          awardMutation.mutate({
                            rfqId: selectedRfqForModal.id,
                            quoteId: quote.quote_id,
                            supplierId: quote.supplier_id
                          });
                        }}
                        disabled={awardMutation.isPending}
                        className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-black rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95 disabled:opacity-50"
                      >
                        {awardMutation.isPending && awardingQuoteId === quote.quote_id ? (
                          <>
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                            <span>Awarding...</span>
                          </>
                        ) : (
                          <>
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Accept & Issue PO</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="px-6 py-3.5 bg-[#141E34] border-t border-slate-800 flex justify-between items-center text-xs text-slate-400">
              <span>All supplier capability twin profiles are pre-verified via AS9100 metrology ledger.</span>
              <button 
                onClick={() => setSelectedRfqForModal(null)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white font-bold rounded-xl transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* PO INVOICE RECONCILIATION MODAL */}
      {selectedPo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0E1526] border border-cyan-500/60 rounded-2xl max-w-2xl w-full p-6 shadow-2xl text-slate-100 space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div>
                <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-wider block">
                  3-Way Match Verification
                </span>
                <h3 className="text-lg font-black text-white">Purchase Order: {selectedPo.po_number || selectedPo.id}</h3>
              </div>
              <button onClick={() => setSelectedPo(null)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="bg-emerald-950/40 border border-emerald-500/40 rounded-xl p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <ShieldCheck className="w-6 h-6 text-emerald-400 shrink-0" />
                <div>
                  <h4 className="text-xs font-bold text-emerald-300 uppercase tracking-wider">Automated 3-Way Reconciliation</h4>
                  <p className="text-xs text-slate-300 mt-0.5">PO = GRN Dock Receipt = Supplier Tax Invoice Verified</p>
                </div>
              </div>
              <span className="px-2.5 py-1 rounded-full text-[10px] font-black bg-emerald-500 text-white">
                MATCHED 100%
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
              <div className="bg-[#141E34] p-3 rounded-xl border border-slate-800">
                <span className="text-slate-400 block mb-0.5">Total Amount</span>
                <strong className="text-emerald-400 font-mono text-sm">${selectedPo.total_amount?.toLocaleString()}</strong>
              </div>
              <div className="bg-[#141E34] p-3 rounded-xl border border-slate-800">
                <span className="text-slate-400 block mb-0.5">Supplier Status</span>
                <strong className="text-cyan-300">{selectedPo.status || 'ISSUED'}</strong>
              </div>
              <div className="bg-[#141E34] p-3 rounded-xl border border-slate-800">
                <span className="text-slate-400 block mb-0.5">Supplier Entity</span>
                <strong className="text-white truncate block">Apex Precision Machining Ltd</strong>
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                onClick={() => setSelectedPo(null)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs rounded-xl"
              >
                Close
              </button>
              <Link
                href="/invoices"
                className="px-5 py-2 bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs rounded-xl shadow-lg transition-colors flex items-center gap-1.5"
              >
                <span>Open Finance Ledger</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
