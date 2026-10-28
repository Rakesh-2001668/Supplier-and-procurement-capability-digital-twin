"use client";

import React, { useState, useMemo } from 'react';
import Link from 'next/link';
import { 
  Trophy, Sparkles, ShieldCheck, CheckCircle2, Clock, ArrowRight,
  ExternalLink, FileText, Sliders, ChevronDown, Send, MessageSquare,
  AlertTriangle, Check, X, RefreshCw, Download, Layers, Cpu, Zap,
  Building2, DollarSign, TrendingDown, ArrowLeft, Filter, CheckCircle,
  HelpCircle, CheckCheck
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, TEST_TENANT_ID } from '@/lib/apiClient';

interface SupplierBid {
  quote_id: string;
  supplier_id: string;
  supplier_name: string;
  supplier_tier: string;
  supplier_location: string;
  unit_price: number;
  total_amount: number;
  tooling_nre_cost: number;
  lead_time_days: number;
  committed_delivery_date: string;
  twin_match_pct: number;
  digital_twin_fit: string;
  atp_status: string;
  atp_badge: string;
  quality_ppm: number;
  quality_score: number;
  esg_score: number;
  incoterms: string;
  payment_terms: string;
  validity_days: number;
  mcda_score: number;
  mcda_breakdown?: {
    price_score: number;
    lead_time_score: number;
    quality_score: number;
    twin_fit_score: number;
    esg_score: number;
  };
  ai_recommendation: string;
  ai_reasoning: string;
  status: string;
  submitted_at: string;
}

export default function SupplierResponses() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'bids' | 'mcda' | 'technical' | 'clarifications'>('bids');
  const [selectedRfqId, setSelectedRfqId] = useState<string>('RFQ-2026-092');
  const [awardingBid, setAwardingBid] = useState<SupplierBid | null>(null);
  const [awardSuccess, setAwardSuccess] = useState<any | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // MCDA Custom Weights (Sum to 1.0)
  const [costWeight, setCostWeight] = useState(0.35);
  const [leadTimeWeight, setLeadTimeWeight] = useState(0.25);
  const [qualityWeight, setQualityWeight] = useState(0.20);
  const [twinFitWeight, setTwinFitWeight] = useState(0.15);
  const [esgWeight, setEsgWeight] = useState(0.05);

  // Clarification Form State
  const [clarificationMsg, setClarificationMsg] = useState('');
  const [targetSupplierId, setTargetSupplierId] = useState('ALL');

  // 1. Fetch live RFQ List
  const { data: rfqList = [] } = useQuery({
    queryKey: ['buyer-rfqs-list'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/rfqs/list');
      return res.data;
    }
  });

  // 2. Fetch specific RFQ Detail
  const { data: rfqDetail, isLoading: rfqLoading } = useQuery({
    queryKey: ['buyer-rfq-detail', selectedRfqId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/procurement/rfqs/${selectedRfqId}`);
      return res.data;
    },
    enabled: !!selectedRfqId
  });

  // 3. Fetch RFQ Bids with dynamic MCDA scoring
  const { data: bidsData, isLoading: bidsLoading, refetch: refetchBids } = useQuery({
    queryKey: ['buyer-rfq-bids', selectedRfqId, costWeight, leadTimeWeight, qualityWeight, twinFitWeight, esgWeight],
    queryFn: async () => {
      const res = await apiClient.get(
        `/api/v1/procurement/rfqs/${selectedRfqId}/bids?cost_weight=${costWeight}&lead_time_weight=${leadTimeWeight}&quality_weight=${qualityWeight}&twin_fit_weight=${twinFitWeight}&esg_weight=${esgWeight}`
      );
      return res.data;
    },
    enabled: !!selectedRfqId
  });

  // 4. Award Mutation
  const awardMutation = useMutation({
    mutationFn: async ({ quoteId, supplierId, notes }: { quoteId: string; supplierId: string; notes?: string }) => {
      const res = await apiClient.post(`/api/v1/procurement/rfqs/${selectedRfqId}/award`, {
        quote_id: quoteId,
        supplier_id: supplierId,
        notes: notes || 'Awarded via Multi-Criteria Decision Analysis (MCDA) Sourcing Engine.',
        buyer_tenant_id: TEST_TENANT_ID
      });
      return res.data;
    },
    onSuccess: (data) => {
      setAwardSuccess(data.award);
      setAwardingBid(null);
      setToastMessage(`Contract awarded! Purchase Order ${data.award.po_number} generated.`);
      queryClient.invalidateQueries({ queryKey: ['buyer-rfq-detail', selectedRfqId] });
      queryClient.invalidateQueries({ queryKey: ['buyer-rfq-bids', selectedRfqId] });
      queryClient.invalidateQueries({ queryKey: ['buyer-rfqs-list'] });
      queryClient.invalidateQueries({ queryKey: ['rfq-awards-list'] });
    },
    onError: (err: any) => {
      setToastMessage(`Failed to award RFQ: ${err?.response?.data?.detail || err.message}`);
    }
  });

  // 5. Submit Clarification Mutation
  const clarificationMutation = useMutation({
    mutationFn: async ({ message, supplierId }: { message: string; supplierId?: string }) => {
      const res = await apiClient.post(`/api/v1/procurement/rfqs/${selectedRfqId}/clarify`, {
        message,
        supplier_id: supplierId === 'ALL' ? undefined : supplierId,
        sender_name: 'Procurement Lead (Alex Sharma)'
      });
      return res.data;
    },
    onSuccess: () => {
      setClarificationMsg('');
      setToastMessage('Clarification inquiry transmitted to supplier twin queue.');
      queryClient.invalidateQueries({ queryKey: ['buyer-rfq-detail', selectedRfqId] });
    }
  });

  const bids: SupplierBid[] = bidsData?.bids || [];
  const topBid = bids.length > 0 ? bids[0] : null;

  // Best metrics across all bids for benchmarking
  const lowestPriceBid = useMemo(() => {
    if (!bids.length) return null;
    return [...bids].sort((a, b) => a.total_amount - b.total_amount)[0];
  }, [bids]);

  const fastestDeliveryBid = useMemo(() => {
    if (!bids.length) return null;
    return [...bids].sort((a, b) => a.lead_time_days - b.lead_time_days)[0];
  }, [bids]);

  const isAwarded = rfqDetail?.status === 'AWARDED' || !!rfqDetail?.awarded_info;

  return (
    <div className="flex flex-col min-h-screen bg-[#070B14] text-slate-100 animate-in fade-in duration-300">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] border border-cyan-500/40 text-white px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3 backdrop-blur-md animate-bounce">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-semibold">{toastMessage}</span>
          <button onClick={() => setToastMessage(null)} className="ml-2 text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* TOP HEADER */}
      <div className="border-b border-slate-800 bg-[#0B0F19]/90 backdrop-blur-md px-8 py-6 shrink-0 sticky top-0 z-30">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="text-[11px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-1.5">
              <Link href="/rfqs" className="hover:underline text-slate-400">RFQ Sourcing Hub</Link>
              <span className="text-slate-600">›</span>
              <Link href="/rfqs/my-rfqs" className="hover:underline text-slate-400">Buyer RFQs</Link>
              <span className="text-slate-600">›</span>
              <span className="text-cyan-400 font-extrabold">Multi-Supplier Bidding & Decision Portal</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-black text-white tracking-tight flex items-center gap-3">
              <span>Multi-Supplier Bid Evaluation Matrix</span>
              <span className={`px-2.5 py-0.5 rounded-full text-xs font-black uppercase tracking-wider border ${
                isAwarded 
                  ? 'bg-purple-950/70 text-purple-300 border-purple-500/50'
                  : 'bg-emerald-950/70 text-emerald-300 border-emerald-500/50'
              }`}>
                {isAwarded ? '🏆 Contract Awarded' : '● Live Bidding Active'}
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-3xl">
              Side-by-side technical & commercial evaluation engine with Multi-Criteria Decision Analysis (MCDA), 
              Available-to-Promise (ATP) twin validation, and 1-click Purchase Order generation.
            </p>
          </div>

          {/* Quick Actions & RFQ Switcher */}
          <div className="flex items-center gap-3 shrink-0">
            <div className="flex items-center gap-2 bg-[#141B2D] border border-slate-700/80 rounded-xl px-3 py-2">
              <span className="text-xs text-slate-400 font-medium">Active RFQ:</span>
              <select
                value={selectedRfqId}
                onChange={(e) => setSelectedRfqId(e.target.value)}
                className="bg-transparent text-sm font-bold text-cyan-300 outline-none cursor-pointer pr-2"
              >
                {rfqList.map((r: any) => (
                  <option key={r.id} value={r.id} className="bg-[#141B2D] text-white">
                    {r.id} - {r.title.length > 35 ? r.title.slice(0, 35) + '...' : r.title}
                  </option>
                ))}
              </select>
            </div>

            <Link
              href="/rfqs/my-rfqs"
              className="px-4 py-2.5 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-xs font-bold transition-all flex items-center gap-2 shadow-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Back to Registry</span>
            </Link>
          </div>
        </div>
      </div>

      <div className="flex-1 px-8 py-6 space-y-6 max-w-7xl w-full mx-auto">
        {/* RFQ OVERVIEW CARD */}
        {rfqDetail && (
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden">
            <div className="absolute top-0 right-0 w-96 h-96 bg-cyan-500/5 rounded-full blur-3xl -z-0 pointer-events-none" />
            
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 relative z-10">
              <div className="space-y-3 flex-1">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="px-2.5 py-1 rounded-lg text-xs font-black bg-cyan-950/80 text-cyan-300 border border-cyan-800">
                    {rfqDetail.id}
                  </span>
                  <span className="text-xs text-slate-400 font-medium">Part #: <strong className="text-white">{rfqDetail.part_number}</strong></span>
                  <span className="text-xs text-slate-400 font-medium">Category: <strong className="text-slate-300">{rfqDetail.category}</strong></span>
                  <span className="text-xs text-slate-400 font-medium">Buyer: <strong className="text-slate-300">{rfqDetail.buyer_org}</strong></span>
                </div>

                <h2 className="text-xl md:text-2xl font-black text-white">
                  {rfqDetail.title}
                </h2>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs pt-1">
                  <div className="bg-[#141E34] p-3 rounded-xl border border-slate-800">
                    <span className="text-slate-400 block mb-0.5">Quantity Requested</span>
                    <span className="text-lg font-black text-white">{rfqDetail.quantity.toLocaleString()} Units</span>
                  </div>
                  <div className="bg-[#141E34] p-3 rounded-xl border border-slate-800">
                    <span className="text-slate-400 block mb-0.5">Target Budget (USD)</span>
                    <span className="text-lg font-black text-emerald-400">
                      ${rfqDetail.target_total_budget.toLocaleString()} (${rfqDetail.target_unit_price}/unit)
                    </span>
                  </div>
                  <div className="bg-[#141E34] p-3 rounded-xl border border-slate-800">
                    <span className="text-slate-400 block mb-0.5">Target Delivery Date</span>
                    <span className="text-lg font-black text-white">{rfqDetail.target_delivery_date}</span>
                  </div>
                  <div className="bg-[#141E34] p-3 rounded-xl border border-slate-800">
                    <span className="text-slate-400 block mb-0.5">Bids Received</span>
                    <span className="text-lg font-black text-cyan-300">
                      {bids.length} of {rfqDetail.invited_suppliers || 4} Invited
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-4 text-xs text-slate-300 pt-1 flex-wrap">
                  <span className="flex items-center gap-1.5 bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800">
                    <Cpu className="w-3.5 h-3.5 text-cyan-400" />
                    <strong>Material:</strong> {rfqDetail.material_spec}
                  </span>
                  <span className="flex items-center gap-1.5 bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800">
                    <Zap className="w-3.5 h-3.5 text-amber-400" />
                    <strong>Tolerance:</strong> {rfqDetail.precision_tolerance}
                  </span>
                  <span className="flex items-center gap-1.5 bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                    <strong>Incoterms:</strong> {rfqDetail.incoterms} • {rfqDetail.payment_terms}
                  </span>
                </div>
              </div>

              {/* Awarded status banner or quick stats */}
              {isAwarded ? (
                <div className="bg-gradient-to-br from-purple-950/60 to-slate-900 border border-purple-500/40 p-5 rounded-2xl shrink-0 lg:w-80 shadow-lg">
                  <div className="flex items-center gap-2 text-purple-300 font-black text-sm mb-2">
                    <Trophy className="w-5 h-5 text-amber-400" />
                    <span>CONTRACT AWARDED</span>
                  </div>
                  <div className="space-y-1.5 text-xs text-slate-300">
                    <div>Supplier: <strong className="text-white">{rfqDetail.awarded_info?.supplier_name}</strong></div>
                    <div>Purchase Order: <strong className="text-emerald-400">{rfqDetail.awarded_info?.po_number}</strong></div>
                    <div>Contract Sum: <strong className="text-white">${rfqDetail.awarded_info?.total_amount?.toLocaleString()}</strong></div>
                    <div>Budget Savings: <strong className="text-emerald-400">${rfqDetail.awarded_info?.savings?.toLocaleString()} ({rfqDetail.awarded_info?.savings_pct}%)</strong></div>
                  </div>
                  <Link
                    href="/rfqs/awards"
                    className="mt-4 w-full py-2 bg-purple-700/80 hover:bg-purple-600 text-white font-bold text-xs rounded-xl flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <span>View in Award Registry</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </Link>
                </div>
              ) : (
                <div className="bg-[#141E34] border border-cyan-500/30 p-5 rounded-2xl shrink-0 lg:w-80 shadow-lg">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">AI Evaluation</span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-black bg-cyan-950 text-cyan-300 border border-cyan-700">
                      MCDA Active
                    </span>
                  </div>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-400">Evaluated Winner:</span>
                      <strong className="text-emerald-400">{topBid?.supplier_name || 'Calculating...'}</strong>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Composite Score:</span>
                      <strong className="text-cyan-300 font-mono text-sm">{topBid?.mcda_score || 0} / 100</strong>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-400">Potential Savings:</span>
                      <strong className="text-emerald-400">
                        ${lowestPriceBid ? (rfqDetail.target_total_budget - lowestPriceBid.total_amount).toLocaleString() : 0}
                      </strong>
                    </div>
                  </div>
                  <button
                    onClick={() => setActiveTab('mcda')}
                    className="mt-4 w-full py-2 bg-cyan-600/20 hover:bg-cyan-600/30 border border-cyan-500/40 text-cyan-300 font-bold text-xs rounded-xl flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <Sliders className="w-3.5 h-3.5" />
                    <span>Adjust Criteria Weights</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TABS NAVIGATION */}
        <div className="flex items-center gap-3 border-b border-slate-800 pb-3 overflow-x-auto">
          <button
            onClick={() => setActiveTab('bids')}
            className={`px-4 py-2.5 rounded-xl text-xs font-black transition-all flex items-center gap-2 whitespace-nowrap ${
              activeTab === 'bids'
                ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-600/30'
                : 'bg-[#0E1526] hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <Trophy className="w-4 h-4" />
            <span>Supplier Proposals ({bids.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('mcda')}
            className={`px-4 py-2.5 rounded-xl text-xs font-black transition-all flex items-center gap-2 whitespace-nowrap ${
              activeTab === 'mcda'
                ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-600/30'
                : 'bg-[#0E1526] hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <Sliders className="w-4 h-4" />
            <span>MCDA Decision Matrix & Weights</span>
          </button>

          <button
            onClick={() => setActiveTab('technical')}
            className={`px-4 py-2.5 rounded-xl text-xs font-black transition-all flex items-center gap-2 whitespace-nowrap ${
              activeTab === 'technical'
                ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-600/30'
                : 'bg-[#0E1526] hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Technical Drawing & Metrology</span>
          </button>

          <button
            onClick={() => setActiveTab('clarifications')}
            className={`px-4 py-2.5 rounded-xl text-xs font-black transition-all flex items-center gap-2 whitespace-nowrap ${
              activeTab === 'clarifications'
                ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-600/30'
                : 'bg-[#0E1526] hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <MessageSquare className="w-4 h-4" />
            <span>Clarifications ({rfqDetail?.clarifications?.length || 0})</span>
          </button>

          <div className="ml-auto">
            <Link
              href="/rfqs/compare"
              className="px-3.5 py-2 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-cyan-300 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 shadow-sm"
            >
              <span>Full Line-Item Compare Matrix</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>

        {/* TAB 1: SUPPLIER PROPOSALS (SIDE-BY-SIDE CARDS) */}
        {activeTab === 'bids' && (
          <div className="space-y-6">
            {bidsLoading ? (
              <div className="p-16 text-center text-slate-400 bg-[#0E1526] rounded-2xl border border-slate-800">
                <RefreshCw className="w-8 h-8 animate-spin mx-auto text-cyan-400 mb-3" />
                <p className="text-sm font-semibold">Loading live multi-supplier quotation matrix...</p>
              </div>
            ) : bids.length === 0 ? (
              <div className="p-16 text-center text-slate-400 bg-[#0E1526] rounded-2xl border border-slate-800">
                <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto mb-3" />
                <p className="text-sm font-semibold">No quotation responses received for this RFQ yet.</p>
                <p className="text-xs text-slate-500 mt-1">Suppliers are currently reviewing technical CAD drawings and available machining cells.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {bids.map((bid, idx) => {
                  const isTopRanked = idx === 0;
                  const isAwardedBid = bid.status === 'AWARDED' || rfqDetail?.awarded_info?.quote_id === bid.quote_id;
                  const isLowestPrice = lowestPriceBid?.quote_id === bid.quote_id;
                  const isFastest = fastestDeliveryBid?.quote_id === bid.quote_id;

                  return (
                    <div
                      key={bid.quote_id}
                      className={`rounded-2xl border transition-all flex flex-col justify-between relative overflow-hidden ${
                        isAwardedBid
                          ? 'bg-gradient-to-b from-[#16122C] to-[#0A0D18] border-purple-500/80 shadow-2xl shadow-purple-900/30 ring-2 ring-purple-500/30'
                          : isTopRanked
                          ? 'bg-gradient-to-b from-[#0F1E38] to-[#0A0F1E] border-cyan-500/70 shadow-2xl shadow-cyan-950/40 ring-1 ring-cyan-500/40'
                          : 'bg-[#0E1526] border-slate-800 hover:border-slate-700 shadow-md'
                      }`}
                    >
                      {/* Top Badges */}
                      <div className="p-5 pb-0">
                        <div className="flex items-center justify-between gap-2 mb-3">
                          <span className="text-[11px] font-mono text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded border border-slate-800">
                            {bid.quote_id}
                          </span>

                          <div className="flex items-center gap-1.5 flex-wrap">
                            {isAwardedBid && (
                              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black bg-purple-500 text-white flex items-center gap-1">
                                <Trophy className="w-3 h-3" /> WINNER
                              </span>
                            )}
                            {isTopRanked && !isAwardedBid && (
                              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black bg-cyan-400 text-slate-950 flex items-center gap-1 shadow-md">
                                <Sparkles className="w-3 h-3" /> TOP EVALUATED
                              </span>
                            )}
                            {isLowestPrice && (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-emerald-950 text-emerald-300 border border-emerald-500/40">
                                Lowest Bid
                              </span>
                            )}
                            {isFastest && (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-blue-950 text-blue-300 border border-blue-500/40">
                                Fastest Delivery
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Supplier Info */}
                        <div className="mb-4">
                          <h3 className="text-lg font-black text-white hover:text-cyan-300 transition-colors flex items-center gap-2">
                            <span>{bid.supplier_name}</span>
                          </h3>
                          <div className="text-xs text-slate-400 flex items-center gap-2 mt-0.5">
                            <span>{bid.supplier_tier}</span>
                            <span>•</span>
                            <span>{bid.supplier_location}</span>
                          </div>
                        </div>

                        {/* Pricing Highlight */}
                        <div className="bg-[#141C30] border border-slate-800/80 rounded-xl p-4 mb-4">
                          <div className="flex justify-between items-baseline">
                            <span className="text-xs text-slate-400 font-medium">Total Contract Price:</span>
                            <span className="text-2xl font-black text-white">
                              ${bid.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                          </div>
                          <div className="flex justify-between items-center text-xs mt-1 pt-1 border-t border-slate-800">
                            <span className="text-slate-400">Unit Price:</span>
                            <strong className="text-cyan-300">${bid.unit_price} / pc</strong>
                          </div>
                          {bid.tooling_nre_cost > 0 && (
                            <div className="flex justify-between items-center text-xs mt-1 text-amber-400">
                              <span>Tooling / NRE:</span>
                              <strong>+${bid.tooling_nre_cost.toLocaleString()}</strong>
                            </div>
                          )}
                        </div>

                        {/* Key Metrics Grid */}
                        <div className="grid grid-cols-2 gap-2 text-xs mb-4">
                          <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-800/80">
                            <span className="text-slate-400 block mb-0.5">Lead Time</span>
                            <span className="font-extrabold text-white flex items-center gap-1">
                              <Clock className="w-3.5 h-3.5 text-cyan-400" />
                              {bid.lead_time_days} Days
                            </span>
                          </div>
                          <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-800/80">
                            <span className="text-slate-400 block mb-0.5">Twin Match</span>
                            <span className="font-extrabold text-emerald-400 flex items-center gap-1">
                              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                              {bid.twin_match_pct}% Fit
                            </span>
                          </div>
                          <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-800/80">
                            <span className="text-slate-400 block mb-0.5">Quality (AS9100)</span>
                            <span className="font-extrabold text-white">
                              {bid.quality_score}% ({bid.quality_ppm} PPM)
                            </span>
                          </div>
                          <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-800/80">
                            <span className="text-slate-400 block mb-0.5">MCDA Score</span>
                            <span className="font-mono font-black text-cyan-300 text-sm">
                              {bid.mcda_score} / 100
                            </span>
                          </div>
                        </div>

                        {/* ATP Badge */}
                        <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-3 mb-4 text-xs">
                          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">
                            Available-To-Promise (ATP) Verification:
                          </div>
                          <div className="text-emerald-300 font-bold flex items-center gap-1.5">
                            <span>{bid.atp_badge}</span>
                          </div>
                          <div className="text-[11px] text-slate-400 mt-1">
                            {bid.digital_twin_fit}
                          </div>
                        </div>

                        {/* Commercial Terms */}
                        <div className="text-[11px] text-slate-400 space-y-1 mb-4 border-t border-slate-800/60 pt-3">
                          <div className="flex justify-between">
                            <span>Incoterms:</span>
                            <strong className="text-slate-200">{bid.incoterms}</strong>
                          </div>
                          <div className="flex justify-between">
                            <span>Payment Terms:</span>
                            <strong className="text-slate-200">{bid.payment_terms}</strong>
                          </div>
                          <div className="flex justify-between">
                            <span>Committed Delivery:</span>
                            <strong className="text-slate-200">{bid.committed_delivery_date}</strong>
                          </div>
                        </div>

                        {/* AI Rationale */}
                        <div className="p-3 bg-slate-950/60 rounded-xl border border-slate-800 text-xs text-slate-300 mb-5">
                          <div className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-1 mb-1">
                            <Sparkles className="w-3 h-3 text-cyan-400" />
                            AI Recommendation Rationale
                          </div>
                          <p className="leading-relaxed text-[11px] text-slate-300">{bid.ai_reasoning}</p>
                        </div>
                      </div>

                      {/* Card Actions */}
                      <div className="p-5 pt-3 border-t border-slate-800/80 bg-slate-950/40 flex items-center gap-3">
                        <Link
                          href={`/buyer/negotiation/${bid.quote_id}`}
                          className="flex-1 py-2.5 px-3 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 text-xs font-bold rounded-xl transition-all flex items-center justify-center gap-1.5 text-center"
                        >
                          <MessageSquare className="w-3.5 h-3.5" />
                          <span>Negotiate</span>
                        </Link>

                        {isAwarded ? (
                          <div className="flex-1 py-2.5 px-3 text-center text-xs font-black rounded-xl bg-slate-800 text-slate-400">
                            {isAwardedBid ? 'Contract Awarded' : 'Not Selected'}
                          </div>
                        ) : (
                          <button
                            onClick={() => setAwardingBid(bid)}
                            disabled={awardMutation.isPending}
                            className={`flex-1 py-2.5 px-3 text-xs font-black rounded-xl transition-all flex items-center justify-center gap-1.5 shadow-md active:scale-95 ${
                              isTopRanked
                                ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/30'
                                : 'bg-cyan-600 hover:bg-cyan-500 text-white shadow-cyan-600/30'
                            }`}
                          >
                            <Trophy className="w-3.5 h-3.5" />
                            <span>Award Contract</span>
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* TAB 2: MCDA CRITERIA WEIGHTS SLIDERS */}
        {activeTab === 'mcda' && (
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-800">
              <div>
                <h3 className="text-lg font-black text-white flex items-center gap-2">
                  <Sliders className="w-5 h-5 text-cyan-400" />
                  <span>Weighted Multi-Criteria Decision Analysis (MCDA) Scoring Engine</span>
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  Adjust parameter weights to dynamically recompute composite supplier scores. 
                  Weights are automatically normalized across cost, lead time, quality, digital twin capability, and ESG.
                </p>
              </div>

              <button
                onClick={() => {
                  setCostWeight(0.35);
                  setLeadTimeWeight(0.25);
                  setQualityWeight(0.20);
                  setTwinFitWeight(0.15);
                  setEsgWeight(0.05);
                  setToastMessage('Weights reset to aerospace industry baseline.');
                }}
                className="px-4 py-2 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-xs font-bold transition-colors"
              >
                Reset to Baseline
              </button>
            </div>

            {/* Sliders Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {/* Cost Weight */}
              <div className="bg-[#141E34] p-4 rounded-xl border border-slate-800 space-y-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-extrabold text-white flex items-center gap-1.5">
                    <DollarSign className="w-4 h-4 text-emerald-400" /> Total Contract Cost
                  </span>
                  <span className="font-mono font-black text-emerald-400 text-sm">
                    {Math.round(costWeight * 100)}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="0.6"
                  step="0.05"
                  value={costWeight}
                  onChange={(e) => setCostWeight(parseFloat(e.target.value))}
                  className="w-full accent-emerald-500 cursor-pointer"
                />
                <span className="text-[11px] text-slate-400 block">
                  Evaluates unit pricing & tooling amortized against target budget.
                </span>
              </div>

              {/* Lead Time Weight */}
              <div className="bg-[#141E34] p-4 rounded-xl border border-slate-800 space-y-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-extrabold text-white flex items-center gap-1.5">
                    <Clock className="w-4 h-4 text-cyan-400" /> Turnaround & Speed
                  </span>
                  <span className="font-mono font-black text-cyan-400 text-sm">
                    {Math.round(leadTimeWeight * 100)}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="0.5"
                  step="0.05"
                  value={leadTimeWeight}
                  onChange={(e) => setLeadTimeWeight(parseFloat(e.target.value))}
                  className="w-full accent-cyan-500 cursor-pointer"
                />
                <span className="text-[11px] text-slate-400 block">
                  Calendar days from PO issuance to committed destination delivery.
                </span>
              </div>

              {/* Quality & AS9100 */}
              <div className="bg-[#141E34] p-4 rounded-xl border border-slate-800 space-y-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-extrabold text-white flex items-center gap-1.5">
                    <ShieldCheck className="w-4 h-4 text-purple-400" /> Quality & Metrology
                  </span>
                  <span className="font-mono font-black text-purple-400 text-sm">
                    {Math.round(qualityWeight * 100)}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="0.4"
                  step="0.05"
                  value={qualityWeight}
                  onChange={(e) => setQualityWeight(parseFloat(e.target.value))}
                  className="w-full accent-purple-500 cursor-pointer"
                />
                <span className="text-[11px] text-slate-400 block">
                  AS9100 / ISO 9001 compliance, historical defect PPM, Zeiss CMM verification.
                </span>
              </div>

              {/* Digital Twin Fit */}
              <div className="bg-[#141E34] p-4 rounded-xl border border-slate-800 space-y-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-extrabold text-white flex items-center gap-1.5">
                    <Cpu className="w-4 h-4 text-amber-400" /> Twin ATP & Machine Fit
                  </span>
                  <span className="font-mono font-black text-amber-400 text-sm">
                    {Math.round(twinFitWeight * 100)}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0.05"
                  max="0.3"
                  step="0.05"
                  value={twinFitWeight}
                  onChange={(e) => setTwinFitWeight(parseFloat(e.target.value))}
                  className="w-full accent-amber-500 cursor-pointer"
                />
                <span className="text-[11px] text-slate-400 block">
                  Raw billet in yard, spindle axis capability, and CNC capacity slotting.
                </span>
              </div>

              {/* ESG & Sustainability */}
              <div className="bg-[#141E34] p-4 rounded-xl border border-slate-800 space-y-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-extrabold text-white flex items-center gap-1.5">
                    <Zap className="w-4 h-4 text-emerald-400" /> ESG & Carbon Footprint
                  </span>
                  <span className="font-mono font-black text-emerald-400 text-sm">
                    {Math.round(esgWeight * 100)}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0.0"
                  max="0.2"
                  step="0.05"
                  value={esgWeight}
                  onChange={(e) => setEsgWeight(parseFloat(e.target.value))}
                  className="w-full accent-emerald-500 cursor-pointer"
                />
                <span className="text-[11px] text-slate-400 block">
                  Scope 1-3 emissions, renewable energy usage, closed-loop swarf recycling.
                </span>
              </div>
            </div>

            {/* Recalculated Score League Table */}
            <div className="pt-4 border-t border-slate-800">
              <h4 className="text-sm font-black text-white mb-3">Live Recalibrated Supplier League Table</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400 uppercase tracking-wider">
                      <th className="py-2.5 px-3">Rank</th>
                      <th className="py-2.5 px-3">Supplier Name</th>
                      <th className="py-2.5 px-3 text-right">Price Score</th>
                      <th className="py-2.5 px-3 text-right">Lead Time Score</th>
                      <th className="py-2.5 px-3 text-right">Quality Score</th>
                      <th className="py-2.5 px-3 text-right">Twin Fit Score</th>
                      <th className="py-2.5 px-3 text-right">Composite MCDA</th>
                      <th className="py-2.5 px-3 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {bids.map((b, i) => (
                      <tr key={b.quote_id} className="hover:bg-slate-800/40 font-medium">
                        <td className="py-3 px-3 font-bold text-white">#{i + 1}</td>
                        <td className="py-3 px-3 font-bold text-cyan-300">{b.supplier_name}</td>
                        <td className="py-3 px-3 text-right font-mono text-slate-300">{b.mcda_breakdown?.price_score || 0}</td>
                        <td className="py-3 px-3 text-right font-mono text-slate-300">{b.mcda_breakdown?.lead_time_score || 0}</td>
                        <td className="py-3 px-3 text-right font-mono text-slate-300">{b.mcda_breakdown?.quality_score || 0}</td>
                        <td className="py-3 px-3 text-right font-mono text-slate-300">{b.mcda_breakdown?.twin_fit_score || 0}</td>
                        <td className="py-3 px-3 text-right font-mono font-black text-emerald-400 text-sm">
                          {b.mcda_score} / 100
                        </td>
                        <td className="py-3 px-3 text-center">
                          {i === 0 ? (
                            <span className="px-2 py-0.5 rounded text-[10px] font-black bg-emerald-950 text-emerald-300 border border-emerald-500">
                              RECOMMENDED WINNER
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded text-[10px] text-slate-400 bg-slate-800">
                              Ranked #{i + 1}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: TECHNICAL DRAWINGS & METROLOGY SPECIFICATIONS */}
        {activeTab === 'technical' && rfqDetail && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 bg-[#0E1526] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
              <div>
                <h3 className="text-lg font-black text-white flex items-center gap-2">
                  <FileText className="w-5 h-5 text-cyan-400" />
                  <span>Technical Blueprint & CAD Model Package</span>
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  Validated against the Digital Engineering Twin catalog with AS9100 metrology tolerances.
                </p>
              </div>

              <div className="p-4 bg-[#141E34] border border-slate-800 rounded-xl flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-cyan-950 text-cyan-400 flex items-center justify-center font-black">
                    3D
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-white">{rfqDetail.cad_filename}</h4>
                    <span className="text-xs text-slate-400">File size: {rfqDetail.cad_filesize} • STEP AP242 with Embedded PMI</span>
                  </div>
                </div>
                <button
                  onClick={() => setToastMessage(`Downloading ${rfqDetail.cad_filename}...`)}
                  className="px-4 py-2 bg-cyan-600/20 hover:bg-cyan-600/30 border border-cyan-500/40 text-cyan-300 font-bold text-xs rounded-xl flex items-center gap-1.5 transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download STEP</span>
                </button>
              </div>

              {/* Critical GD&T Constraints */}
              <div>
                <h4 className="text-sm font-bold text-white mb-3">Critical GD&T & Inspection Criteria</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800">
                    <span className="text-slate-400 block mb-1">Precision Tolerance</span>
                    <strong className="text-white text-sm">{rfqDetail.precision_tolerance}</strong>
                    <span className="text-[11px] text-slate-400 block mt-1">3D CMM Metrology Report required with each shipment</span>
                  </div>
                  <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800">
                    <span className="text-slate-400 block mb-1">Material Certification</span>
                    <strong className="text-white text-sm">{rfqDetail.material_spec}</strong>
                    <span className="text-[11px] text-slate-400 block mt-1">EN 10204 3.1 Inspection Certificate required</span>
                  </div>
                  <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800">
                    <span className="text-slate-400 block mb-1">Surface Finish</span>
                    <strong className="text-white text-sm">{rfqDetail.surface_treatment}</strong>
                    <span className="text-[11px] text-slate-400 block mt-1">Anodize thickness 50 µm ± 5 µm with dielectric test</span>
                  </div>
                  <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800">
                    <span className="text-slate-400 block mb-1">First Article Inspection (FAIR)</span>
                    <strong className="text-white text-sm">AS9102 Rev B Form 1, 2, 3</strong>
                    <span className="text-[11px] text-slate-400 block mt-1">Mandatory submission prior to batch delivery</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Checklist */}
            <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
              <h4 className="text-sm font-bold text-white">Quality Sign-Off Gate</h4>
              <div className="space-y-3 text-xs">
                <div className="flex items-start gap-2.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-white">AS9100 Rev D Verification</strong>
                    <p className="text-slate-400 text-[11px]">Supplier cleanroom machining audited and current.</p>
                  </div>
                </div>
                <div className="flex items-start gap-2.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-white">Zeiss Coordinate Metrology</strong>
                    <p className="text-slate-400 text-[11px]">Calibrated probe scanning for concentricity and runout.</p>
                  </div>
                </div>
                <div className="flex items-start gap-2.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-white">Traceability & Lot Heat #</strong>
                    <p className="text-slate-400 text-[11px]">Raw ingot mill origin logged in blockchain vault.</p>
                  </div>
                </div>
                <div className="flex items-start gap-2.5">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <strong className="text-white">Mil-Spec Packaging</strong>
                    <p className="text-slate-400 text-[11px]">ESD vacuum sealed packaging with desiccants.</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: CLARIFICATIONS & MESSAGES */}
        {activeTab === 'clarifications' && (
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
            <div>
              <h3 className="text-lg font-black text-white flex items-center gap-2">
                <MessageSquare className="w-5 h-5 text-cyan-400" />
                <span>Buyer - Supplier Clarification Log</span>
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Direct Q&A channel with bidding suppliers. All inquiries and responses are archived in the audit trail.
              </p>
            </div>

            {/* Inquiries List */}
            <div className="space-y-4">
              {rfqDetail?.clarifications?.length === 0 ? (
                <div className="p-8 text-center text-slate-400 bg-slate-900/40 rounded-xl border border-slate-800">
                  <p className="text-xs">No clarification inquiries recorded for this RFQ yet.</p>
                </div>
              ) : (
                rfqDetail?.clarifications?.map((c: any) => (
                  <div key={c.id} className="bg-[#141E34] border border-slate-800 rounded-xl p-4 space-y-2 text-xs">
                    <div className="flex justify-between items-center text-slate-400 text-[11px]">
                      <span className="font-bold text-cyan-400">#{c.id} • To: {c.recipient}</span>
                      <span>{c.date}</span>
                    </div>
                    <p className="text-slate-200 font-semibold">{c.message}</p>
                    {c.reply && (
                      <div className="pl-3 border-l-2 border-emerald-500 pt-1 mt-2 text-[11px] text-emerald-300">
                        <strong>Supplier Reply:</strong> {c.reply}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>

            {/* New Inquiry Form */}
            <div className="pt-4 border-t border-slate-800 space-y-3">
              <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
                Transmit New Clarification Inquiry
              </h4>
              <div className="flex flex-col sm:flex-row gap-3">
                <select
                  value={targetSupplierId}
                  onChange={(e) => setTargetSupplierId(e.target.value)}
                  className="bg-[#141E34] border border-slate-700 rounded-xl px-3 py-2 text-xs text-white outline-none sm:w-64"
                >
                  <option value="ALL">Broadcast to All Bidders</option>
                  {bids.map((b) => (
                    <option key={b.supplier_id} value={b.supplier_id}>
                      {b.supplier_name}
                    </option>
                  ))}
                </select>

                <input
                  type="text"
                  placeholder="Enter technical query, tolerance confirmation, or schedule requirement..."
                  value={clarificationMsg}
                  onChange={(e) => setClarificationMsg(e.target.value)}
                  className="flex-1 bg-[#141E34] border border-slate-700 rounded-xl px-4 py-2 text-xs text-white placeholder-slate-500 outline-none focus:border-cyan-500"
                />

                <button
                  onClick={() => {
                    if (clarificationMsg.trim()) {
                      clarificationMutation.mutate({
                        message: clarificationMsg,
                        supplierId: targetSupplierId
                      });
                    }
                  }}
                  disabled={clarificationMutation.isPending || !clarificationMsg.trim()}
                  className="px-5 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white font-bold text-xs rounded-xl flex items-center justify-center gap-1.5 transition-colors shadow-sm"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>Transmit</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 1-CLICK AWARD CONFIRMATION MODAL */}
      {awardingBid && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0E1526] border border-cyan-500/60 rounded-2xl max-w-lg w-full p-6 shadow-2xl text-slate-100 space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2.5">
                <div className="w-10 h-10 rounded-xl bg-emerald-950 text-emerald-400 flex items-center justify-center">
                  <Trophy className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-black text-white">Award Contract & Issue PO</h3>
                  <p className="text-xs text-slate-400">Commercial contract locking & purchase order dispatch.</p>
                </div>
              </div>
              <button onClick={() => setAwardingBid(null)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs bg-[#141E34] p-4 rounded-xl border border-slate-800">
              <div className="flex justify-between">
                <span className="text-slate-400">Awarding To:</span>
                <strong className="text-white">{awardingBid.supplier_name}</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Quotation ID:</span>
                <strong className="text-cyan-300 font-mono">{awardingBid.quote_id}</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Contract Value:</span>
                <strong className="text-emerald-400 text-sm">
                  ${awardingBid.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Lead Time & Delivery:</span>
                <strong className="text-white">{awardingBid.lead_time_days} Days ({awardingBid.committed_delivery_date})</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">MCDA Evaluated Score:</span>
                <strong className="text-cyan-300">{awardingBid.mcda_score} / 100</strong>
              </div>
            </div>

            <p className="text-xs text-slate-400 leading-relaxed">
              Awarding this quote will instantly generate an approved <strong className="text-slate-200">Purchase Order (PO-2026-XXXX)</strong>, 
              notify <strong className="text-slate-200">{awardingBid.supplier_name}</strong>, and notify competing suppliers that the bidding phase has closed.
            </p>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                onClick={() => setAwardingBid(null)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs rounded-xl transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  awardMutation.mutate({
                    quoteId: awardingBid.quote_id,
                    supplierId: awardingBid.supplier_id
                  });
                }}
                disabled={awardMutation.isPending}
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-black text-xs rounded-xl shadow-lg shadow-emerald-600/30 flex items-center gap-1.5 transition-all"
              >
                {awardMutation.isPending ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Issuing PO...</span>
                  </>
                ) : (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    <span>Confirm Award & Generate PO</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* AWARD SUCCESS MODAL */}
      {awardSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0E1526] border border-emerald-500/80 rounded-2xl max-w-lg w-full p-6 shadow-2xl text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-500/50 flex items-center justify-center mx-auto shadow-xl shadow-emerald-950">
              <Trophy className="w-8 h-8" />
            </div>

            <h3 className="text-xl font-black text-white">Purchase Order Issued!</h3>
            <p className="text-xs text-slate-400 max-w-md mx-auto">
              RFQ <strong>{selectedRfqId}</strong> has been awarded to <strong>{awardSuccess.supplier_name}</strong>.
            </p>

            <div className="bg-[#141E34] border border-slate-800 rounded-xl p-4 text-xs space-y-2 text-left max-w-sm mx-auto">
              <div className="flex justify-between">
                <span className="text-slate-400">Purchase Order:</span>
                <strong className="text-emerald-400 font-mono text-sm">{awardSuccess.po_number}</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Contract Sum:</span>
                <strong className="text-white">${awardSuccess.total_amount?.toLocaleString()}</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Budget Savings:</span>
                <strong className="text-emerald-400">${awardSuccess.savings?.toLocaleString()} ({awardSuccess.savings_pct}%)</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Target Delivery:</span>
                <strong className="text-white">{awardSuccess.committed_delivery_date}</strong>
              </div>
            </div>

            <div className="flex items-center justify-center gap-3 pt-3">
              <Link
                href="/rfqs/awards"
                className="px-5 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs rounded-xl shadow-lg transition-colors flex items-center gap-1.5"
              >
                <span>View Award Registry</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
              <button
                onClick={() => setAwardSuccess(null)}
                className="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs rounded-xl transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
