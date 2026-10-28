'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  BarChart3, PieChart, ShieldAlert, AlertTriangle, 
  ArrowRight, Search, RefreshCw, DollarSign, Layers, 
  Building2, Sparkles, Filter, ChevronRight, TrendingUp, 
  ArrowDownRight, CheckCircle2, ShieldCheck, Box, Tag
} from 'lucide-react';
import axios from 'axios';

interface SpendCubeData {
  total_spend_cr: number;
  on_contract_spend_cr: number;
  maverick_spend_cr: number;
  contract_compliance_pct: number;
  record_count: number;
  commodity_breakdown: { commodity: string; spend_cr: number }[];
  top_suppliers: { supplier_name: string; spend_cr: number }[];
}

interface MaverickData {
  maverick_spend_cr: number;
  records: any[];
  principle_p03_warning: string;
}

interface TailData {
  tail_threshold_pct: number;
  tail_spend_cr: number;
  tail_supplier_count: number;
  total_suppliers: number;
  insight: string;
}

export default function SpendCubePage() {
  const [cubeData, setCubeData] = useState<SpendCubeData | null>(null);
  const [maverickData, setMaverickData] = useState<MaverickData | null>(null);
  const [tailData, setTailData] = useState<TailData | null>(null);
  const [selectedPlant, setSelectedPlant] = useState('All');
  const [selectedCommodity, setSelectedCommodity] = useState('All');
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const fetchSpendData = async () => {
    setLoading(true);
    try {
      const [cubeRes, mavRes, tailRes] = await Promise.all([
        axios.get(`http://localhost:8080/api/v1/spend/cube?plant=${selectedPlant}&commodity=${selectedCommodity}`),
        axios.get('http://localhost:8080/api/v1/spend/maverick'),
        axios.get('http://localhost:8080/api/v1/spend/tail')
      ]);

      if (cubeRes.data && cubeRes.data.status === 'success') {
        setCubeData(cubeRes.data);
      }
      if (mavRes.data && mavRes.data.status === 'success') {
        setMaverickData(mavRes.data);
      }
      if (tailRes.data && tailRes.data.status === 'success') {
        setTailData(tailRes.data);
      }
    } catch (err) {
      console.error('Failed to load spend cube data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSpendData();
  }, [selectedPlant, selectedCommodity]);

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
            <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold tracking-wider uppercase bg-blue-500/10 text-blue-400 border border-blue-500/20">
              Module M01 • SPD-01..09
            </span>
            <span className="text-xs text-slate-400 font-mono">Multidimensional Spend Intelligence</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Spend Analytics Cube & Maverick Spend Detector
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            8-dimensional spend aggregation across plants, categories, and contracts with automated Principle P03 maverick detection.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchSpendData}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-slate-700/60 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <Link
            href="/savings"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-emerald-400 border border-emerald-500/30 transition"
          >
            <DollarSign className="w-3.5 h-3.5" />
            Savings Realisation
          </Link>
          <Link
            href="/contracts/agreements"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-xs font-semibold text-white shadow-lg shadow-blue-600/20 transition"
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            Active Contracts
          </Link>
        </div>
      </div>

      {/* Principle P03 Maverick Spend Alert */}
      {maverickData && maverickData.maverick_spend_cr > 0 && (
        <div className="p-4 rounded-xl bg-gradient-to-r from-rose-950/50 via-slate-900/60 to-slate-900/40 border border-rose-500/40 flex items-start gap-3.5">
          <ShieldAlert className="w-5 h-5 text-rose-400 mt-0.5 shrink-0" />
          <div className="space-y-1 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-bold text-rose-300 uppercase tracking-wider">
                Principle P03 Leakage Alert: ₹{maverickData.maverick_spend_cr.toFixed(2)} Cr Off-Contract Maverick Spend
              </span>
              <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30">
                Action Required
              </span>
            </div>
            <p className="text-slate-300 leading-relaxed">
              {maverickData.principle_p03_warning}
            </p>
          </div>
        </div>
      )}

      {/* Filter Bar */}
      <div className="p-4 rounded-xl bg-[#0B1528] border border-slate-800 flex flex-wrap items-center gap-4 text-xs">
        <span className="text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1.5">
          <Filter className="w-3.5 h-3.5 text-cyan-400" />
          Filter Dimensions:
        </span>

        <div className="flex items-center gap-2">
          <span className="text-slate-400">Plant:</span>
          <select
            value={selectedPlant}
            onChange={(e) => setSelectedPlant(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs font-mono text-slate-200 focus:outline-none"
          >
            <option value="All">All Plants (Hosur & Chennai)</option>
            <option value="P100 Hosur">P100 Hosur (Powertrain)</option>
            <option value="P200 Chennai">P200 Chennai (Chassis)</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-slate-400">Commodity:</span>
          <select
            value={selectedCommodity}
            onChange={(e) => setSelectedCommodity(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs font-mono text-slate-200 focus:outline-none"
          >
            <option value="All">All Commodities</option>
            <option value="Castings & Forgings">Castings & Forgings</option>
            <option value="Electrical & Motors">Electrical & Motors</option>
            <option value="Fasteners & Hardware">Fasteners & Hardware</option>
          </select>
        </div>
      </div>

      {/* Spend Cube KPI Summary Cards */}
      {cubeData && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-5 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-2">
            <span className="text-xs text-slate-400 uppercase font-semibold flex items-center justify-between">
              Total Audited Spend
              <BarChart3 className="w-4 h-4 text-blue-400" />
            </span>
            <div className="text-2xl font-bold text-white font-mono">
              ₹{cubeData.total_spend_cr.toFixed(2)} Cr
            </div>
            <span className="text-[11px] text-slate-400 font-mono">
              Across {cubeData.record_count} active line items
            </span>
          </div>

          <div className="p-5 rounded-2xl bg-[#0B1528] border border-emerald-500/30 shadow-xl space-y-2">
            <span className="text-xs text-emerald-400 uppercase font-semibold flex items-center justify-between">
              On-Contract Spend
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            </span>
            <div className="text-2xl font-bold text-emerald-400 font-mono">
              ₹{cubeData.on_contract_spend_cr.toFixed(2)} Cr
            </div>
            <span className="text-[11px] text-emerald-400/80 font-mono">
              {cubeData.contract_compliance_pct}% Contract Coverage
            </span>
          </div>

          <div className="p-5 rounded-2xl bg-[#0B1528] border border-rose-500/30 shadow-xl space-y-2">
            <span className="text-xs text-rose-400 uppercase font-semibold flex items-center justify-between">
              Maverick Off-Contract
              <AlertTriangle className="w-4 h-4 text-rose-400" />
            </span>
            <div className="text-2xl font-bold text-rose-400 font-mono">
              ₹{cubeData.maverick_spend_cr.toFixed(2)} Cr
            </div>
            <span className="text-[11px] text-rose-400/80 font-mono">
              {(100 - cubeData.contract_compliance_pct).toFixed(1)}% Maverick Leakage
            </span>
          </div>

          {tailData && (
            <div className="p-5 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-2">
              <span className="text-xs text-amber-400 uppercase font-semibold flex items-center justify-between">
                Tail Spend Friction
                <PieChart className="w-4 h-4 text-amber-400" />
              </span>
              <div className="text-2xl font-bold text-amber-400 font-mono">
                ₹{tailData.tail_spend_cr.toFixed(2)} Cr
              </div>
              <span className="text-[11px] text-slate-400 font-mono">
                {tailData.tail_supplier_count} of {tailData.total_suppliers} vendors (80/20)
              </span>
            </div>
          )}
        </div>
      )}

      {/* Multi-Dimensional Breakdowns Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Commodity Spend & Top Suppliers (6 cols) */}
        <div className="lg:col-span-6 space-y-6">
          {/* Commodity Breakdown */}
          <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
              <Layers className="w-4 h-4 text-cyan-400" />
              Spend by Commodity Group
            </h3>

            <div className="space-y-3">
              {cubeData?.commodity_breakdown.map((comm) => {
                const pct = cubeData.total_spend_cr > 0 
                  ? Math.round((comm.spend_cr / cubeData.total_spend_cr) * 100) 
                  : 0;
                return (
                  <div key={comm.commodity} className="space-y-1 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="text-slate-300 font-medium">{comm.commodity}</span>
                      <span className="font-mono text-cyan-400 font-bold">₹{comm.spend_cr.toFixed(2)} Cr ({pct}%)</span>
                    </div>
                    <div className="w-full bg-slate-900 rounded-full h-2 overflow-hidden">
                      <div 
                        className="bg-gradient-to-r from-blue-600 to-cyan-500 h-2 rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Top Suppliers Pareto Table */}
          <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
              <Building2 className="w-4 h-4 text-emerald-400" />
              Top Suppliers by Audited Volume
            </h3>

            <div className="overflow-x-auto rounded-xl border border-slate-800/80">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-900/80 text-slate-400 font-medium border-b border-slate-800">
                  <tr>
                    <th className="py-2.5 px-3">Supplier Name</th>
                    <th className="py-2.5 px-3 text-right">Spend</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {cubeData?.top_suppliers.map((s) => (
                    <tr key={s.supplier_name} className="hover:bg-slate-800/30">
                      <td className="py-2.5 px-3 text-slate-200 font-sans">{s.supplier_name}</td>
                      <td className="py-2.5 px-3 text-right font-bold text-emerald-400">₹{s.spend_cr.toFixed(2)} Cr</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right: Maverick Spend Detail Log (6 cols) */}
        <div className="lg:col-span-6 space-y-6">
          <div className="p-6 rounded-2xl bg-[#0B1528] border border-rose-500/30 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-bold text-rose-300 uppercase tracking-wider flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-rose-400" />
                Maverick Purchases Requiring Contract Remediation
              </h3>
              <span className="text-[11px] font-mono text-rose-400 bg-rose-950/60 px-2 py-0.5 rounded border border-rose-500/30">
                P03 Violations
              </span>
            </div>

            <div className="space-y-3">
              {maverickData?.records.map((mav: any) => (
                <div 
                  key={mav.id}
                  className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2 text-xs"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="font-mono text-cyan-400 font-bold">{mav.material_id}</span>
                      <h4 className="text-sm font-bold text-white mt-0.5">{mav.supplier_name}</h4>
                    </div>
                    <span className="text-base font-bold text-rose-400 font-mono">
                      ₹{(mav.spend_inr / 10000000).toFixed(2)} Cr
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400 font-mono pt-2 border-t border-slate-800/80">
                    <div>Plant: <strong className="text-slate-200">{mav.plant}</strong></div>
                    <div>Period: <strong className="text-slate-200">{mav.period}</strong></div>
                    <div>Price: ₹{mav.unit_price_inr} / {mav.uom}</div>
                    <div>Type: <span className="text-rose-400">{mav.purchase_type}</span></div>
                  </div>

                  <div className="pt-2 flex items-center justify-between text-[11px]">
                    <span className="text-slate-400">Available Alternative: SA-5520 @ ₹398.00</span>
                    <Link
                      href="/contracts/agreements"
                      className="inline-flex items-center gap-1 text-cyan-400 hover:text-cyan-300 font-semibold transition"
                    >
                      Consolidate to SA-5520
                      <ArrowRight className="w-3 h-3" />
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Tail Spend Consolidation Recommendation */}
          {tailData && (
            <div className="p-6 rounded-2xl bg-gradient-to-br from-amber-950/20 via-slate-900/40 to-slate-900/80 border border-amber-500/30 space-y-3 text-xs">
              <h4 className="text-sm font-bold text-amber-300 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-amber-400" />
                Tail Spend Optimization (SPD-07)
              </h4>
              <p className="text-slate-300 leading-relaxed">
                {tailData.insight} Consolidating the bottom 84 suppliers through digital catalogs will yield an estimated 
                <strong> ₹18.5 L</strong> in administrative processing savings and eliminate repetitive manual spot POs.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
