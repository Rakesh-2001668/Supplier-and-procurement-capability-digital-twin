"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { 
  Trophy, ShieldCheck, CheckCircle2, Clock, ArrowRight,
  ExternalLink, FileText, Search, Filter, Download, 
  Building2, DollarSign, TrendingDown, ArrowLeft, RefreshCw
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';

export default function AwardManagement() {
  const [searchQuery, setSearchQuery] = useState('');

  // 1. Fetch live awards list
  const { data: awards = [], isLoading: awardsLoading, refetch } = useQuery({
    queryKey: ['rfq-awards-list'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/rfqs/awards/list');
      return res.data;
    }
  });

  const totalAwardedValue = awards.reduce((acc: number, a: any) => acc + (a.total_amount || 0), 0);
  const totalSavingsAchieved = awards.reduce((acc: number, a: any) => acc + (a.savings || 0), 0);

  const filteredAwards = awards.filter((a: any) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      a.rfq_id?.toLowerCase().includes(q) ||
      a.rfq_title?.toLowerCase().includes(q) ||
      a.supplier_name?.toLowerCase().includes(q) ||
      a.po_number?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="flex flex-col min-h-screen bg-[#070B14] text-slate-100 animate-in fade-in duration-300">
      {/* Header */}
      <div className="border-b border-slate-800 bg-[#0B0F19]/90 backdrop-blur-md px-8 py-6 shrink-0 sticky top-0 z-30">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="text-[11px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-1.5">
              <Link href="/rfqs" className="hover:underline text-slate-400">RFQ Sourcing Hub</Link>
              <span className="text-slate-600">›</span>
              <span className="text-cyan-400 font-extrabold">Awarded Contracts & Purchase Orders</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight flex items-center gap-3">
              <span>Contract Award Registry</span>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-black bg-purple-950 text-purple-300 border border-purple-700">
                {awards.length} Executed Awards
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-2xl">
              Commercial contracts awarded via the MCDA bidding engine with locked terms and generated purchase orders.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/rfqs/responses"
              className="px-4 py-2.5 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-xs font-bold transition-all flex items-center gap-2 shadow-sm"
            >
              <Trophy className="w-4 h-4 text-cyan-400" />
              <span>Multi-Supplier Bidding</span>
            </Link>

            <Link
              href="/rfqs"
              className="px-4 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl text-xs font-black shadow-lg shadow-cyan-600/30 flex items-center gap-2 transition-all"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Sourcing Hub</span>
            </Link>
          </div>
        </div>
      </div>

      <div className="flex-1 px-8 py-6 space-y-6 max-w-7xl w-full mx-auto">
        {/* KPI CARDS */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-purple-950 border border-purple-800 text-purple-400 flex items-center justify-center shrink-0">
              <Trophy className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Awarded Contracts</span>
              <span className="text-2xl font-black text-white">{awards.length} Contracts</span>
              <span className="text-[10px] text-purple-400 block mt-0.5 font-bold">100% POs Issued</span>
            </div>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-cyan-950 border border-cyan-800 text-cyan-400 flex items-center justify-center shrink-0">
              <DollarSign className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Total Awarded Volume</span>
              <span className="text-2xl font-black text-white">
                ${totalAwardedValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className="text-[10px] text-cyan-400 block mt-0.5 font-bold">Committed Production Spend</span>
            </div>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-emerald-950 border border-emerald-800 text-emerald-400 flex items-center justify-center shrink-0">
              <TrendingDown className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Net Savings Achieved</span>
              <span className="text-2xl font-black text-emerald-400">
                ${totalSavingsAchieved.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className="text-[10px] text-emerald-400 block mt-0.5 font-bold">vs Initial Target Budget</span>
            </div>
          </div>
        </div>

        {/* SEARCH & FILTERS */}
        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-lg flex items-center justify-between gap-4">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search by supplier, PO number, RFQ ID, or title..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#141B2D] border border-slate-700 rounded-xl pl-9 pr-4 py-2 text-xs text-white placeholder-slate-500 outline-none focus:border-cyan-500"
            />
          </div>

          <span className="text-xs text-slate-400 font-semibold">
            Showing {filteredAwards.length} of {awards.length} Awarded Contracts
          </span>
        </div>

        {/* AWARDS TABLE */}
        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl shadow-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 bg-[#141B2D]/60 text-slate-400 font-bold uppercase tracking-wider">
                  <th className="py-3.5 px-4">Award ID / PO #</th>
                  <th className="py-3.5 px-4">RFQ Reference & Title</th>
                  <th className="py-3.5 px-4">Awarded Supplier</th>
                  <th className="py-3.5 px-4 text-right">Awarded Amount</th>
                  <th className="py-3.5 px-4 text-right">Savings Achieved</th>
                  <th className="py-3.5 px-4 text-center">Delivery Target</th>
                  <th className="py-3.5 px-4 text-center">Contract Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {awardsLoading ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-400">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto text-cyan-400 mb-2" />
                      Loading awarded contracts...
                    </td>
                  </tr>
                ) : filteredAwards.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-400">
                      No awarded contracts found.
                    </td>
                  </tr>
                ) : (
                  filteredAwards.map((a: any) => (
                    <tr key={a.award_id} className="hover:bg-slate-800/30 transition-colors">
                      <td className="py-4 px-4">
                        <strong className="text-purple-300 font-mono text-sm block">{a.po_number}</strong>
                        <span className="text-[11px] text-slate-400">{a.award_id}</span>
                      </td>
                      <td className="py-4 px-4">
                        <strong className="text-white font-bold block max-w-sm truncate">{a.rfq_title}</strong>
                        <span className="text-[11px] text-slate-400">{a.rfq_id} • {a.category}</span>
                      </td>
                      <td className="py-4 px-4">
                        <strong className="text-cyan-300 font-bold block">{a.supplier_name}</strong>
                        <span className="text-[11px] text-slate-400">{a.supplier_location || 'Verified Digital Twin'}</span>
                      </td>
                      <td className="py-4 px-4 text-right">
                        <strong className="text-white block font-mono text-sm">
                          ${a.total_amount?.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </strong>
                        <span className="text-[11px] text-slate-400">${a.unit_price}/unit</span>
                      </td>
                      <td className="py-4 px-4 text-right">
                        <strong className="text-emerald-400 block font-mono">
                          +${a.savings?.toLocaleString()}
                        </strong>
                        <span className="text-[10px] text-emerald-400 font-bold">
                          {a.savings_pct}% vs Target Budget
                        </span>
                      </td>
                      <td className="py-4 px-4 text-center">
                        <span className="font-bold text-white block">{a.committed_delivery_date}</span>
                        <span className="text-[10px] text-slate-400 font-medium">{a.lead_time_days} Days Lead Time</span>
                      </td>
                      <td className="py-4 px-4 text-center">
                        <span className="px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-wider bg-purple-950 text-purple-300 border border-purple-500/40">
                          {a.contract_status?.replace(/_/g, ' ') || 'CONTRACT LOCKED'}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
