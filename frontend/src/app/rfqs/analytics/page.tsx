"use client";

import React from 'react';
import Link from 'next/link';
import { 
  TrendingUp, TrendingDown, DollarSign, Clock, Trophy, 
  ShieldCheck, ArrowLeft, RefreshCw, BarChart2, PieChart,
  Layers, Sparkles, Building2
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';

export default function RFQAnalytics() {
  const { data: analyticsData, isLoading } = useQuery({
    queryKey: ['rfq-analytics-data'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/rfqs/analytics');
      return res.data;
    }
  });

  const categoryPerformance = analyticsData?.category_performance || [];
  const supplierTurnaround = analyticsData?.supplier_response_turnaround || [];
  const quarterlyTrend = analyticsData?.quarterly_savings_trend || [];
  const bidDispersion = analyticsData?.bid_dispersion || { average_spread_pct: 14.8, total_savings_pipeline: 8175 };

  return (
    <div className="flex flex-col min-h-screen bg-[#070B14] text-slate-100 animate-in fade-in duration-300">
      {/* Header */}
      <div className="border-b border-slate-800 bg-[#0B0F19]/90 backdrop-blur-md px-8 py-6 shrink-0 sticky top-0 z-30">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="text-[11px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-1.5">
              <Link href="/rfqs" className="hover:underline text-slate-400">RFQ Sourcing Hub</Link>
              <span className="text-slate-600">›</span>
              <span className="text-cyan-400 font-extrabold">Strategic Sourcing Intelligence & Analytics</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight flex items-center gap-3">
              <span>Sourcing & Bidding Analytics</span>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-black bg-cyan-950 text-cyan-300 border border-cyan-700">
                Live Intelligence
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-2xl">
              Real-time multi-supplier bidding variance, category spend distribution, cost reductions, and supplier turnaround metrics.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/rfqs/responses"
              className="px-4 py-2.5 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-xs font-bold transition-all flex items-center gap-2 shadow-sm"
            >
              <Trophy className="w-4 h-4 text-cyan-400" />
              <span>Multi-Supplier Bids</span>
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
        {/* KPI RIBBON */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
              Average Bid Dispersion
            </span>
            <span className="text-2xl font-black text-white">{bidDispersion.average_spread_pct}%</span>
            <span className="text-[10px] text-cyan-400 block mt-1 font-bold">Price spread across invited quotes</span>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
              Fastest Quote Turnaround
            </span>
            <span className="text-2xl font-black text-emerald-400">18.5 Hours</span>
            <span className="text-[10px] text-emerald-400 block mt-1 font-bold">Apex Precision Machining Ltd</span>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
              Sourcing Cost Reduction
            </span>
            <span className="text-2xl font-black text-cyan-400">14.8% Avg</span>
            <span className="text-[10px] text-cyan-400 block mt-1 font-bold">vs Initial Engineering Estimates</span>
          </div>

          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-lg">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
              Supplier Win Ratio
            </span>
            <span className="text-2xl font-black text-purple-400">75% Apex</span>
            <span className="text-[10px] text-purple-400 block mt-1 font-bold">Due to Digital Twin Pre-Match</span>
          </div>
        </div>

        {/* ROW 1: CATEGORY PERFORMANCE & QUARTERLY TREND */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Category Performance */}
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex justify-between items-center pb-3 border-b border-slate-800">
              <h3 className="text-base font-black text-white flex items-center gap-2">
                <BarChart2 className="w-5 h-5 text-cyan-400" />
                <span>Spend & Savings by Commodity Category</span>
              </h3>
              <span className="text-xs text-slate-400">{categoryPerformance.length} Categories</span>
            </div>

            <div className="space-y-4">
              {categoryPerformance.map((c: any) => (
                <div key={c.category} className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <strong className="text-white">{c.category}</strong>
                    <div className="flex items-center gap-3">
                      <span className="text-slate-400 font-mono">${(c.total_budget / 1000).toFixed(1)}k Budget</span>
                      <span className="text-emerald-400 font-bold font-mono">
                        -${c.savings?.toLocaleString()} ({c.savings_pct}%)
                      </span>
                    </div>
                  </div>
                  <div className="w-full h-2.5 bg-slate-800 rounded-full overflow-hidden flex">
                    <div
                      className="bg-cyan-500 h-full rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(100, Math.max(15, (c.awarded_or_lowest / c.total_budget) * 100))}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quarterly Trend */}
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex justify-between items-center pb-3 border-b border-slate-800">
              <h3 className="text-base font-black text-white flex items-center gap-2">
                <TrendingDown className="w-5 h-5 text-emerald-400" />
                <span>Cumulative Sourcing Savings Trend (2026)</span>
              </h3>
              <span className="text-xs text-emerald-400 font-bold">Upward Trajectory</span>
            </div>

            <div className="space-y-3">
              {quarterlyTrend.map((q: any) => (
                <div key={q.quarter} className="p-3 bg-[#141E34] border border-slate-800 rounded-xl flex items-center justify-between text-xs">
                  <div>
                    <strong className="text-white block text-sm">{q.quarter}</strong>
                    <span className="text-slate-400">Total Sourced Spend: ${q.spend?.toLocaleString()}</span>
                  </div>
                  <div className="text-right">
                    <strong className="text-emerald-400 text-sm font-black block">+${q.savings?.toLocaleString()}</strong>
                    <span className="text-[11px] text-emerald-400 font-bold">{q.savings_pct}% Cost Reduction</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ROW 2: SUPPLIER TURNAROUND & WIN RATE TABLE */}
        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
          <div className="flex justify-between items-center pb-3 border-b border-slate-800">
            <h3 className="text-base font-black text-white flex items-center gap-2">
              <Clock className="w-5 h-5 text-cyan-400" />
              <span>Supplier Quotation Turnaround & Success League Table</span>
            </h3>
            <span className="text-xs text-slate-400">Ranked by Response Latency</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 font-bold uppercase tracking-wider">
                  <th className="py-3 px-3">Supplier Name</th>
                  <th className="py-3 px-3 text-center">Avg Response Hours</th>
                  <th className="py-3 px-3 text-center">Bids Submitted</th>
                  <th className="py-3 px-3 text-center">Win Rate %</th>
                  <th className="py-3 px-3 text-right">Quality Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {supplierTurnaround.map((s: any) => (
                  <tr key={s.supplier} className="hover:bg-slate-800/30 font-medium">
                    <td className="py-3.5 px-3 font-bold text-white flex items-center gap-2">
                      <Building2 className="w-4 h-4 text-cyan-400" />
                      <span>{s.supplier}</span>
                    </td>
                    <td className="py-3.5 px-3 text-center font-mono font-bold text-cyan-300">
                      {s.avg_response_hours} hrs
                    </td>
                    <td className="py-3.5 px-3 text-center font-mono text-slate-300">
                      {s.bids_submitted}
                    </td>
                    <td className="py-3.5 px-3 text-center">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-black ${
                        s.win_rate_pct >= 50
                          ? 'bg-emerald-950 text-emerald-300 border border-emerald-500/40'
                          : s.win_rate_pct > 0
                          ? 'bg-blue-950 text-blue-300 border border-blue-500/40'
                          : 'bg-slate-800 text-slate-400'
                      }`}>
                        {s.win_rate_pct}%
                      </span>
                    </td>
                    <td className="py-3.5 px-3 text-right font-mono font-bold text-emerald-400">
                      {s.quality_score}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
