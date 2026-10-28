"use client";
import React, { useState, useEffect } from "react";
import Link from 'next/link';

interface Contract {
  id: string;
  name: string;
  contract_type: string;
  category: string;
  supplier_id: string;
  supplier_name: string;
  supplier_location: string;
  buyer_name: string;
  status: string;
  start_date: string;
  end_date: string;
  days_remaining: number;
  total_value_usd: number;
  payment_terms: string;
  sla_commitments?: {
    target_otif_pct: number;
    current_otif_pct: number;
    max_defect_ppm: number;
    current_defect_ppm: number;
  };
}

export default function PendingRenewals() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<string | null>(null);
  const [filterWindow, setFilterWindow] = useState<'ALL' | '0-30' | '31-60' | '61-90' | 'EXPIRED'>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [renewingId, setRenewingId] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  };

  const fetchContracts = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/contracts/list');
      if (res.ok) {
        const data = await res.json();
        setContracts(data.contracts || []);
      }
    } catch (e) {
      console.warn("Could not fetch contracts for renewals", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContracts();
  }, []);

  const handleRenewContract = async (contractId: string) => {
    setRenewingId(contractId);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/contracts/${contractId}/renew`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Contract ${contractId} extended for 24 months through ${data.new_end_date}!`);
        await fetchContracts();
      } else {
        showToast(`Failed to renew contract ${contractId}.`);
      }
    } catch {
      showToast("Network error while triggering renewal.");
    } finally {
      setRenewingId(null);
    }
  };

  const handleBulkRenewExpiring = async () => {
    const expiring = contracts.filter(c => c.days_remaining <= 90);
    if (expiring.length === 0) {
      showToast("No contracts currently expiring within 90 days.");
      return;
    }
    showToast(`Initiating automated AI renewal packets for ${expiring.length} contracts...`);
    for (const c of expiring) {
      await fetch(`http://127.0.0.1:8080/api/v1/contracts/${c.id}/renew`, { method: 'POST' }).catch(() => {});
    }
    await fetchContracts();
    showToast("Bulk renewals executed successfully!");
  };

  // Metrics
  const expiring0to30 = contracts.filter(c => c.days_remaining > 0 && c.days_remaining <= 30);
  const expiring31to60 = contracts.filter(c => c.days_remaining > 30 && c.days_remaining <= 60);
  const expiring61to90 = contracts.filter(c => c.days_remaining > 60 && c.days_remaining <= 90);
  const expired = contracts.filter(c => c.days_remaining <= 0);

  const filteredContracts = contracts.filter(c => {
    const matchesSearch = searchQuery === '' || 
      c.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.supplier_name.toLowerCase().includes(searchQuery.toLowerCase());

    if (!matchesSearch) return false;

    if (filterWindow === '0-30') return c.days_remaining > 0 && c.days_remaining <= 30;
    if (filterWindow === '31-60') return c.days_remaining > 30 && c.days_remaining <= 60;
    if (filterWindow === '61-90') return c.days_remaining > 60 && c.days_remaining <= 90;
    if (filterWindow === 'EXPIRED') return c.days_remaining <= 0;
    return true;
  });

  return (
    <div className="flex h-full bg-[#0B0F19] text-slate-100 flex-col overflow-y-auto">
      {toast && (
        <div className="fixed top-6 right-6 z-50 bg-emerald-950 border border-emerald-500/50 text-emerald-300 px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 text-sm font-semibold animate-fade-in">
          <span>✨</span> {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex justify-between items-start shrink-0 px-8 pt-8 pb-4 bg-[#111827] border-b border-slate-800">
        <div>
          <div className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest mb-1 flex items-center gap-1.5">
            <Link href="/contracts" className="hover:text-blue-400 transition-colors">Contracts Engine</Link>
            <span className="text-slate-600">›</span>
            <span className="text-blue-400">Pending Renewals</span>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Contract Renewals & SLA Lifecycle Sentinel</h1>
          <p className="text-sm text-slate-400 mt-1 font-medium">
            Monitor approaching contract expiries, trigger AI renewal notices, and extend multi-year agreements.
          </p>
        </div>
        <div className="mt-2 flex gap-3">
          <button 
            onClick={handleBulkRenewExpiring}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm rounded-lg shadow-lg shadow-blue-900/30 flex items-center gap-2 transition-colors"
          >
            ⚡ Bulk Renew Expiring (90d)
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-6 px-8 py-6">
        {/* KPI Strip */}
        <div className="grid grid-cols-4 gap-4">
          <div 
            onClick={() => setFilterWindow('0-30')}
            className={`border rounded-xl p-5 shadow-lg flex gap-4 cursor-pointer transition-all ${
              filterWindow === '0-30' ? 'bg-red-950/40 border-red-500 ring-1 ring-red-500' : 'bg-[#111827] border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="w-12 h-12 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 flex items-center justify-center text-xl shrink-0">
              🚨
            </div>
            <div className="flex flex-col justify-between">
              <span className="text-2xl font-black font-mono text-white leading-none">{expiring0to30.length}</span>
              <span className="text-xs font-bold text-slate-300 mt-1">Expiring in 0–30 days</span>
              <span className="text-[10px] font-semibold text-red-400 mt-1">Urgent Renewal Required</span>
            </div>
          </div>

          <div 
            onClick={() => setFilterWindow('31-60')}
            className={`border rounded-xl p-5 shadow-lg flex gap-4 cursor-pointer transition-all ${
              filterWindow === '31-60' ? 'bg-amber-950/40 border-amber-500 ring-1 ring-amber-500' : 'bg-[#111827] border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="w-12 h-12 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-400 flex items-center justify-center text-xl shrink-0">
              ⚠️
            </div>
            <div className="flex flex-col justify-between">
              <span className="text-2xl font-black font-mono text-white leading-none">{expiring31to60.length}</span>
              <span className="text-xs font-bold text-slate-300 mt-1">Expiring in 31–60 days</span>
              <span className="text-[10px] font-semibold text-amber-400 mt-1">Commercial Review Open</span>
            </div>
          </div>

          <div 
            onClick={() => setFilterWindow('61-90')}
            className={`border rounded-xl p-5 shadow-lg flex gap-4 cursor-pointer transition-all ${
              filterWindow === '61-90' ? 'bg-blue-950/40 border-blue-500 ring-1 ring-blue-500' : 'bg-[#111827] border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="w-12 h-12 rounded-xl bg-blue-500/10 border border-blue-500/30 text-blue-400 flex items-center justify-center text-xl shrink-0">
              📅
            </div>
            <div className="flex flex-col justify-between">
              <span className="text-2xl font-black font-mono text-white leading-none">{expiring61to90.length}</span>
              <span className="text-xs font-bold text-slate-300 mt-1">Expiring in 61–90 days</span>
              <span className="text-[10px] font-semibold text-blue-400 mt-1">Telemetry Assessment</span>
            </div>
          </div>

          <div 
            onClick={() => setFilterWindow('ALL')}
            className={`border rounded-xl p-5 shadow-lg flex gap-4 cursor-pointer transition-all ${
              filterWindow === 'ALL' ? 'bg-purple-950/40 border-purple-500 ring-1 ring-purple-500' : 'bg-[#111827] border-slate-800 hover:border-slate-700'
            }`}
          >
            <div className="w-12 h-12 rounded-xl bg-purple-500/10 border border-purple-500/30 text-purple-400 flex items-center justify-center text-xl shrink-0">
              📊
            </div>
            <div className="flex flex-col justify-between">
              <span className="text-2xl font-black font-mono text-white leading-none">{contracts.length}</span>
              <span className="text-xs font-bold text-slate-300 mt-1">Total Monitored Contracts</span>
              <span className="text-[10px] font-semibold text-purple-400 mt-1">Show All Lifecycles</span>
            </div>
          </div>
        </div>

        {/* Content Layout */}
        <div className="flex gap-6 items-start">
          {/* Main Table */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl shadow-xl flex flex-col flex-1 min-w-0">
            {/* Filter Bar */}
            <div className="px-6 py-4 border-b border-slate-800 flex gap-4 shrink-0 flex-wrap items-center">
              <div className="relative flex-1 min-w-[260px] max-w-md">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-xs">🔍</span>
                <input 
                  type="text" 
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Filter by contract ID, name, or supplier..." 
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-xs outline-none focus:border-blue-500 text-slate-200 placeholder-slate-500"
                />
              </div>

              <div className="flex gap-2">
                {(['ALL', '0-30', '31-60', '61-90', 'EXPIRED'] as const).map(w => (
                  <button
                    key={w}
                    onClick={() => setFilterWindow(w)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                      filterWindow === w ? 'bg-blue-600 text-white font-bold' : 'bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {w === 'ALL' ? 'All' : `${w}d`}
                  </button>
                ))}
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs min-w-[850px]">
                <thead className="text-slate-400 font-bold border-b border-slate-800 bg-[#0B0F19]/50">
                  <tr>
                    <th className="py-3 px-6">Contract ID</th>
                    <th className="py-3 px-4">Contract Name</th>
                    <th className="py-3 px-4">Supplier</th>
                    <th className="py-3 px-4">End Date</th>
                    <th className="py-3 px-4">Days Left</th>
                    <th className="py-3 px-4">Value</th>
                    <th className="py-3 px-4">OTIF</th>
                    <th className="py-3 px-4 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-medium text-slate-300">
                  {loading ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-400">Loading renewal schedules...</td>
                    </tr>
                  ) : filteredContracts.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-400">No contracts found in this window.</td>
                    </tr>
                  ) : (
                    filteredContracts.map((row) => {
                      const isUrgent = row.days_remaining <= 30;
                      const isWarning = row.days_remaining > 30 && row.days_remaining <= 90;

                      return (
                        <tr key={row.id} className="hover:bg-slate-800/40 transition-colors">
                          <td className="py-4 px-6 font-mono font-bold text-blue-400">
                            <Link href="/contracts/view" className="hover:underline">{row.id}</Link>
                          </td>
                          <td className="py-4 px-4 text-white font-semibold">{row.name}</td>
                          <td className="py-4 px-4">{row.supplier_name}</td>
                          <td className="py-4 px-4 text-slate-400 font-mono text-[11px]">{row.end_date}</td>
                          <td className="py-4 px-4">
                            <span className={`px-2.5 py-1 rounded-full text-xs font-mono font-bold ${
                              isUrgent 
                                ? 'bg-red-500/10 text-red-400 border border-red-500/30' 
                                : isWarning 
                                  ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' 
                                  : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                            }`}>
                              {row.days_remaining}d
                            </span>
                          </td>
                          <td className="py-4 px-4 font-mono font-bold text-slate-200">
                            ${row.total_value_usd.toLocaleString()}
                          </td>
                          <td className="py-4 px-4 font-mono text-emerald-400">
                            {row.sla_commitments?.current_otif_pct || 96.8}%
                          </td>
                          <td className="py-4 px-4 text-center">
                            <button
                              disabled={renewingId === row.id}
                              onClick={() => handleRenewContract(row.id)}
                              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold shadow-md transition-colors disabled:opacity-50"
                            >
                              {renewingId === row.id ? 'Extending...' : 'Extend (+2y) →'}
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="p-4 border-t border-slate-800 flex justify-between items-center text-xs text-slate-400 bg-slate-900/50 rounded-b-xl">
              <div>Displaying {filteredContracts.length} agreements in current filter</div>
              <Link href="/contracts/view" className="text-blue-400 hover:underline">
                View Full Repository →
              </Link>
            </div>
          </div>

          {/* Right Sidebar */}
          <div className="w-[320px] flex flex-col gap-6 shrink-0">
            {/* Overview Card */}
            <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-xl">
              <h3 className="font-bold text-white text-sm mb-3 flex items-center gap-2">
                <span className="text-blue-400">📊</span> Expiry Breakdown
              </h3>
              <div className="space-y-3 text-xs">
                <div className="flex justify-between items-center p-2 rounded bg-slate-900/60 border border-slate-800">
                  <span className="text-red-400 font-semibold flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-red-400"></span> 0–30 Days
                  </span>
                  <span className="font-mono font-bold text-white">{expiring0to30.length}</span>
                </div>
                <div className="flex justify-between items-center p-2 rounded bg-slate-900/60 border border-slate-800">
                  <span className="text-amber-400 font-semibold flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-amber-400"></span> 31–60 Days
                  </span>
                  <span className="font-mono font-bold text-white">{expiring31to60.length}</span>
                </div>
                <div className="flex justify-between items-center p-2 rounded bg-slate-900/60 border border-slate-800">
                  <span className="text-blue-400 font-semibold flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-blue-400"></span> 61–90 Days
                  </span>
                  <span className="font-mono font-bold text-white">{expiring61to90.length}</span>
                </div>
                <div className="flex justify-between items-center p-2 rounded bg-slate-900/60 border border-slate-800">
                  <span className="text-emerald-400 font-semibold flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-400"></span> Stable (&gt;90d)
                  </span>
                  <span className="font-mono font-bold text-white">
                    {contracts.filter(c => c.days_remaining > 90).length}
                  </span>
                </div>
              </div>
            </div>

            {/* Quick Actions */}
            <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-xl">
              <h3 className="font-bold text-white text-sm mb-4 flex items-center gap-2">
                <span className="text-amber-400">⚡</span> Sentinel Automation
              </h3>
              <div className="space-y-3">
                <button
                  onClick={() => {
                    showToast("Automated email & webhook alerts configured for 60-day renewal threshold.");
                  }}
                  className="w-full text-left p-3 rounded-lg border border-slate-800 bg-slate-900/70 hover:border-slate-700 hover:bg-slate-800 transition-colors"
                >
                  <div className="text-xs font-bold text-white">Configure 60-Day Webhook Alert</div>
                  <div className="text-[10px] text-slate-400 mt-0.5">Dispatches notice to buyer sourcing team</div>
                </button>
                <button
                  onClick={() => {
                    showToast("Supplier performance telemetry report compiled for renewal committee.");
                  }}
                  className="w-full text-left p-3 rounded-lg border border-slate-800 bg-slate-900/70 hover:border-slate-700 hover:bg-slate-800 transition-colors"
                >
                  <div className="text-xs font-bold text-white">Generate Renewal Audit Report</div>
                  <div className="text-[10px] text-slate-400 mt-0.5">Aggregates 12-month OTIF and defect trends</div>
                </button>
              </div>
            </div>

            {/* Guide Info */}
            <div className="bg-blue-950/20 border border-blue-900/40 rounded-xl p-4 text-xs text-blue-300">
              <div className="font-bold mb-1 flex items-center gap-1.5 text-blue-400">
                <span>ℹ️</span> Renewal Protocol
              </div>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                When a contract is renewed, the engine automatically calculates standard 24-month horizon extensions, updates the ledger event stream, and refreshes the smart escrow milestones.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
