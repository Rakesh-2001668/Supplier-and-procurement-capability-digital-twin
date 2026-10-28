"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { 
  FileText, Plus, Search, Filter, ChevronRight, Clock, 
  CheckCircle2, AlertTriangle, ArrowRight, Trophy, RefreshCw,
  ExternalLink, Layers, Sparkles, Building2, ShieldCheck, X
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';

export default function MyRFQs() {
  const [activeTab, setActiveTab] = useState<'ALL' | 'OPEN_FOR_BIDS' | 'UNDER_EVALUATION' | 'AWARDED'>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('ALL');

  // 1. Fetch live Overview KPIs
  const { data: overviewData } = useQuery({
    queryKey: ['buyer-rfqs-overview'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/rfqs/overview');
      return res.data;
    }
  });

  // 2. Fetch live RFQ list
  const { data: rfqs = [], isLoading: rfqsLoading, refetch } = useQuery({
    queryKey: ['buyer-rfqs-list', activeTab, categoryFilter, searchQuery],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (activeTab !== 'ALL') params.append('status', activeTab);
      if (categoryFilter !== 'ALL') params.append('category', categoryFilter);
      if (searchQuery.trim()) params.append('search', searchQuery.trim());
      const res = await apiClient.get(`/api/v1/procurement/rfqs/list?${params.toString()}`);
      return res.data;
    }
  });

  const kpis = overviewData?.kpis || {
    total_rfqs: 6,
    active_rfqs: 4,
    under_evaluation: 2,
    awarded_rfqs: 2,
    total_pipeline_value: 306150,
    average_savings_pct: 12.4
  };

  const categories = Array.from(new Set(rfqs.map((r: any) => r.category))).filter(Boolean);

  return (
    <div className="flex flex-col min-h-screen bg-[#070B14] text-slate-100 animate-in fade-in duration-300">
      {/* Header */}
      <div className="border-b border-slate-800 bg-[#0B0F19]/90 backdrop-blur-md px-8 py-6 shrink-0 sticky top-0 z-30">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="text-[11px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-1.5">
              <Link href="/rfqs" className="hover:underline text-slate-400">RFQ Sourcing Hub</Link>
              <span className="text-slate-600">›</span>
              <span className="text-cyan-400 font-extrabold">Buyer RFQ Registry</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight flex items-center gap-3">
              <span>My RFQs & Sourcing Events</span>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-black bg-cyan-950 text-cyan-300 border border-cyan-700">
                {rfqs.length} Events
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-2xl">
              Track open sourcing requisitions, supplier participation, incoming quotations, and contract awards.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/rfqs/responses"
              className="px-4 py-2.5 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-xs font-bold transition-all flex items-center gap-2 shadow-sm"
            >
              <Trophy className="w-4 h-4 text-cyan-400" />
              <span>Multi-Supplier Portal</span>
            </Link>

            <Link
              href="/rfqs/create"
              className="px-5 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl text-xs font-black shadow-lg shadow-cyan-600/30 flex items-center gap-2 transition-all active:scale-95"
            >
              <Plus className="w-4 h-4" />
              <span>Create RFQ</span>
            </Link>
          </div>
        </div>
      </div>

      <div className="flex-1 px-8 py-6 space-y-6 max-w-7xl w-full mx-auto">
        {/* KPI CARDS RIBBON */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-cyan-950/80 border border-cyan-800 text-cyan-400 flex items-center justify-center shrink-0">
              <FileText className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Total RFQs</span>
              <span className="text-xl font-black text-white">{kpis.total_rfqs} Events</span>
              <span className="text-[10px] text-cyan-400 block mt-0.5 font-bold">100% Digital Twin Tracked</span>
            </div>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-950/80 border border-blue-800 text-blue-400 flex items-center justify-center shrink-0">
              <Clock className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Under Evaluation</span>
              <span className="text-xl font-black text-white">{kpis.under_evaluation} RFQs</span>
              <span className="text-[10px] text-blue-400 block mt-0.5 font-bold">MCDA Bidding Active</span>
            </div>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-emerald-950/80 border border-emerald-800 text-emerald-400 flex items-center justify-center shrink-0">
              <Trophy className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Awarded Contracts</span>
              <span className="text-xl font-black text-emerald-400">{kpis.awarded_rfqs} Awarded</span>
              <span className="text-[10px] text-emerald-400 block mt-0.5 font-bold">POs Issued to Plants</span>
            </div>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-purple-950/80 border border-purple-800 text-purple-400 flex items-center justify-center shrink-0">
              <Sparkles className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Pipeline Value</span>
              <span className="text-xl font-black text-white">
                ${(kpis.total_pipeline_value / 1000).toFixed(1)}k
              </span>
              <span className="text-[10px] text-emerald-400 block mt-0.5 font-bold">
                {kpis.average_savings_pct}% Avg Savings
              </span>
            </div>
          </div>
        </div>

        {/* CONTROLS & FILTER BAR */}
        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
          {/* Status Tabs */}
          <div className="flex items-center gap-2 overflow-x-auto pb-1 md:pb-0">
            {[
              { id: 'ALL', label: 'All RFQs' },
              { id: 'UNDER_EVALUATION', label: 'Under Evaluation' },
              { id: 'OPEN_FOR_BIDS', label: 'Open for Bids' },
              { id: 'AWARDED', label: 'Awarded' }
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all whitespace-nowrap ${
                  activeTab === tab.id
                    ? 'bg-cyan-600 text-white shadow-md shadow-cyan-600/30'
                    : 'bg-[#141B2D] text-slate-400 hover:text-white hover:bg-slate-800'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Search & Category Filter */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1 md:w-64">
              <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Search title, part #, RFQ ID..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-[#141B2D] border border-slate-700 rounded-xl pl-9 pr-3 py-1.5 text-xs text-white placeholder-slate-500 outline-none focus:border-cyan-500"
              />
            </div>

            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="bg-[#141B2D] border border-slate-700 rounded-xl px-3 py-1.5 text-xs text-slate-300 outline-none"
            >
              <option value="ALL">All Categories</option>
              {categories.map((c: any) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        </div>

        {/* RFQ TABLE */}
        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl shadow-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 bg-[#141B2D]/60 text-slate-400 font-bold uppercase tracking-wider">
                  <th className="py-3.5 px-4">RFQ / Part #</th>
                  <th className="py-3.5 px-4">Title & Category</th>
                  <th className="py-3.5 px-4 text-right">Target Budget</th>
                  <th className="py-3.5 px-4 text-center">Bids Received</th>
                  <th className="py-3.5 px-4 text-right">Lowest Bid</th>
                  <th className="py-3.5 px-4 text-center">Status</th>
                  <th className="py-3.5 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {rfqsLoading ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-400">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto text-cyan-400 mb-2" />
                      Loading buyer RFQs...
                    </td>
                  </tr>
                ) : rfqs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-400">
                      No matching RFQ events found for the selected criteria.
                    </td>
                  </tr>
                ) : (
                  rfqs.map((rfq: any) => {
                    const isAwarded = rfq.status === 'AWARDED';
                    return (
                      <tr key={rfq.id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="py-4 px-4">
                          <strong className="text-cyan-300 font-mono text-sm block">{rfq.id}</strong>
                          <span className="text-[11px] text-slate-400">{rfq.part_number}</span>
                        </td>
                        <td className="py-4 px-4">
                          <strong className="text-white font-bold block max-w-sm truncate">{rfq.title}</strong>
                          <span className="text-[11px] text-slate-400">{rfq.category} • {rfq.quantity} pcs</span>
                        </td>
                        <td className="py-4 px-4 text-right">
                          <strong className="text-white block font-mono">
                            ${rfq.target_total_budget?.toLocaleString()}
                          </strong>
                          <span className="text-[11px] text-slate-400">${rfq.target_unit_price}/unit</span>
                        </td>
                        <td className="py-4 px-4 text-center">
                          <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-800">
                            {rfq.quotes_received} Bids
                          </span>
                        </td>
                        <td className="py-4 px-4 text-right">
                          <strong className="text-emerald-400 block font-mono">
                            ${rfq.lowest_bid_amount?.toLocaleString()}
                          </strong>
                          {rfq.savings_pct > 0 && (
                            <span className="text-[10px] text-emerald-400 font-bold block">
                              -{rfq.savings_pct}% (${rfq.potential_savings?.toLocaleString()})
                            </span>
                          )}
                        </td>
                        <td className="py-4 px-4 text-center">
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
                        <td className="py-4 px-4 text-right">
                          <Link
                            href={`/rfqs/responses?rfq_id=${rfq.id}`}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-cyan-600/20 hover:bg-cyan-600/40 border border-cyan-500/40 text-cyan-300 rounded-lg text-xs font-bold transition-all shadow-sm active:scale-95"
                          >
                            <span>Evaluate Bids</span>
                            <ChevronRight className="w-3.5 h-3.5" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
