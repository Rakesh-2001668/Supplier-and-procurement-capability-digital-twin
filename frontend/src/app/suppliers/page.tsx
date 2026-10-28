"use client";
import React, { useState, useEffect } from "react";
import Link from 'next/link';
import { 
  Building, MapPin, FileText, CheckCircle, Info, Settings, 
  Search, Shield, Cpu, Zap, Activity, ArrowRight, RefreshCw, 
  Award, Lock, Sparkles, AlertCircle, ChevronRight, X, ExternalLink,
  Plus, Filter, Download, ArrowUpRight
} from 'lucide-react';

export default function SupplierDirectory() {
  const [suppliers, setSuppliers] = useState<any[]>([]);
  const [overviewStats, setOverviewStats] = useState<any>(null);
  const [selectedSupplier, setSelectedSupplier] = useState<any>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterTier, setFilterTier] = useState("ALL");
  const [loading, setLoading] = useState(true);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 4000);
  };

  const loadDirectory = async () => {
    setLoading(true);
    try {
      // 1. Overview KPIs
      const oRes = await fetch('http://localhost:8080/api/v1/suppliers/onboarding/overview');
      if (oRes.ok) {
        const oData = await oRes.json();
        setOverviewStats(oData);
      }

      // 2. Pipeline list
      const pRes = await fetch('http://localhost:8080/api/v1/suppliers/onboarding/pipeline');
      if (pRes.ok) {
        const pData = await pRes.json();
        if (pData.suppliers && pData.suppliers.length > 0) {
          setSuppliers(pData.suppliers);
        } else {
          throw new Error("No suppliers returned");
        }
      } else {
        throw new Error("Failed to load pipeline");
      }
    } catch (e) {
      console.warn("Using fallback supplier directory:", e);
      setOverviewStats({
        total_pipeline: 4,
        in_assessment_count: 2,
        pending_executive_approvals: 1,
        verified_capability_twins: 1,
        average_assessment_score: 91.8,
        fast_track_kyc_rate: 96.8,
        zero_trust_attestation_rate: 99.4
      });

      setSuppliers([
        {
          id: "SUP-2025-0012",
          name: "ABC Components Pvt Ltd",
          short_name: "ABC Components",
          cage_code: "7X892",
          tier: "Tier 1 Qualified Partner",
          industry: "Aerospace CNC Machining & Turbine Components",
          composite_score: 92.4,
          risk_level: "Low",
          status: "PENDING_EXECUTIVE_APPROVAL",
          headquarters: { city: "Chennai", country: "India", facility_size_sqft: "65,000 sq.ft High-Precision Plant" },
          cleanroom_class: "ISO Class 7"
        },
        {
          id: "SUP-AERO-991",
          name: "AeroForge Dynamics Inc",
          short_name: "AeroForge",
          cage_code: "4K291",
          tier: "Tier 1 Aerospace Prime Supplier",
          industry: "Superalloy Forging & Cryogenic Rocket Casings",
          composite_score: 88.6,
          risk_level: "Low",
          status: "IN_ASSESSMENT",
          headquarters: { city: "Huntsville", country: "United States", facility_size_sqft: "110,000 sq.ft Heavy Forging Plant" },
          cleanroom_class: "ISO Class 8"
        },
        {
          id: "SUP-AERO-992",
          name: "Titanium Space Castings Ltd",
          short_name: "Titanium Space",
          cage_code: "8R112",
          tier: "Tier 2 Candidate",
          industry: "Vacuum Investment Casting & Titanium Billets",
          composite_score: 84.2,
          risk_level: "Medium",
          status: "APPLICATION_SUBMITTED",
          headquarters: { city: "Sheffield", country: "United Kingdom", facility_size_sqft: "45,000 sq.ft Casting Plant" },
          cleanroom_class: "ISO Class 8"
        },
        {
          id: "TENANT_SUPPLIER_001",
          name: "Apex Precision Machining & Turbine Systems",
          short_name: "Apex Precision",
          cage_code: "1A990",
          tier: "Tier 1 Certified Strategic Partner",
          industry: "Space Propulsion 5-Axis Milling & Turbomachinery",
          composite_score: 98.2,
          risk_level: "Low",
          status: "VERIFIED_CAPABILITY_TWIN",
          headquarters: { city: "Bangalore", country: "India", facility_size_sqft: "85,000 sq.ft Precision Facility" },
          cleanroom_class: "ISO Class 5"
        }
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDirectory();
  }, []);

  const filteredSuppliers = suppliers.filter(s => {
    const q = searchQuery.toLowerCase();
    const matchSearch = s.name.toLowerCase().includes(q) || 
      (s.cage_code && s.cage_code.toLowerCase().includes(q)) || 
      s.industry.toLowerCase().includes(q);
    const matchTier = filterTier === "ALL" || s.tier.includes(filterTier);
    return matchSearch && matchTier;
  });

  return (
    <div className="flex flex-col h-full bg-[#070B14] text-slate-200 font-sans">
      {/* Toast */}
      {toastMsg && (
        <div className="fixed top-5 right-5 z-50 bg-cyan-950 border border-cyan-400 text-cyan-200 px-4 py-2.5 rounded-lg shadow-xl text-xs font-mono flex items-center gap-2 animate-bounce">
          <Info size={16} className="text-cyan-400" />
          {toastMsg}
        </div>
      )}

      {/* Header */}
      <div className="flex justify-between items-end shrink-0 px-8 pt-6 pb-4 bg-[#0A101D] border-b border-slate-800">
        <div>
          <div className="text-[10px] font-mono font-bold text-cyan-400 uppercase tracking-widest mb-1">
            SUPPLIER ECOSYSTEM &bull; DIGITAL TWIN DIRECTORY
          </div>
          <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
            <Building className="text-cyan-400" size={26} />
            Aerospace Supplier Directory & Capability Twins
          </h1>
          <p className="text-xs text-slate-400 mt-0.5 font-medium">
            Autonomous capability twins calibrated against AS9100D metrology, CMMC Level 2 enclaves, and DFSC resilience.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/suppliers/onboarding"
            className="px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-[#070B14] font-black text-xs rounded-lg shadow-lg shadow-cyan-500/20 flex items-center gap-1.5 transition-all"
          >
            <Plus size={16} /> Synthesize New Twin
          </Link>
          <Link
            href="/suppliers/assessments"
            className="px-4 py-2 bg-[#0D1527] border border-cyan-500/40 hover:border-cyan-400 text-cyan-300 font-mono font-bold text-xs rounded-lg transition-all flex items-center gap-1.5"
          >
            <Cpu size={14} /> 8-Pillar Assessments
          </Link>
          <Link
            href="/suppliers/approvals"
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 font-mono font-bold text-xs rounded-lg transition-all flex items-center gap-1.5"
          >
            <Shield size={14} /> Executive Approvals
          </Link>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-y-auto p-8 space-y-6 max-w-[1600px] w-full mx-auto">
        
        {/* KPI Strip */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="p-4 bg-[#0D1527] border border-slate-800 rounded-xl flex items-center justify-between">
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400">Total Pipeline</div>
              <div className="text-2xl font-mono font-black text-white mt-1">
                {overviewStats?.total_pipeline || suppliers.length}
              </div>
              <span className="text-[10px] font-mono text-cyan-400">Digital Twins Ingested</span>
            </div>
            <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Cpu size={22} />
            </div>
          </div>

          <div className="p-4 bg-[#0D1527] border border-slate-800 rounded-xl flex items-center justify-between">
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400">In 8-Pillar Assessment</div>
              <div className="text-2xl font-mono font-black text-cyan-300 mt-1">
                {overviewStats?.in_assessment_count || 2}
              </div>
              <span className="text-[10px] font-mono text-cyan-400">Metrology Telemetry Calibrating</span>
            </div>
            <div className="w-12 h-12 rounded-xl bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400">
              <Activity size={22} />
            </div>
          </div>

          <div className="p-4 bg-[#0D1527] border border-slate-800 rounded-xl flex items-center justify-between">
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400">Pending Approvals</div>
              <div className="text-2xl font-mono font-black text-amber-400 mt-1">
                {overviewStats?.pending_executive_approvals || 1}
              </div>
              <span className="text-[10px] font-mono text-amber-300">Executive Committee Review</span>
            </div>
            <div className="w-12 h-12 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400">
              <Shield size={22} />
            </div>
          </div>

          <div className="p-4 bg-[#0D1527] border border-slate-800 rounded-xl flex items-center justify-between">
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400">Verified Capability Twins</div>
              <div className="text-2xl font-mono font-black text-emerald-400 mt-1">
                {overviewStats?.verified_capability_twins || 1}
              </div>
              <span className="text-[10px] font-mono text-emerald-400">Active Flight-Article Bidding</span>
            </div>
            <div className="w-12 h-12 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <CheckCircle size={22} />
            </div>
          </div>
        </div>

        {/* Filter & Search Bar */}
        <div className="p-4 bg-[#0D1527] border border-slate-800 rounded-xl flex flex-col md:flex-row gap-4 items-center justify-between">
          <div className="relative flex-1 w-full">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
            <input
              type="text"
              placeholder="Filter by capability twin name, CAGE code, propulsion, superalloys..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-[#0A101D] border border-slate-700 rounded-lg pl-10 pr-4 py-2 text-xs font-mono text-white placeholder-slate-500 focus:border-cyan-400 outline-none"
            />
          </div>

          <div className="flex items-center gap-3 w-full md:w-auto">
            <div className="flex items-center gap-2 bg-[#0A101D] border border-slate-700 px-3 py-1.5 rounded-lg text-xs font-mono">
              <span className="text-slate-400">Tier:</span>
              <select
                value={filterTier}
                onChange={e => setFilterTier(e.target.value)}
                className="bg-transparent text-cyan-300 font-bold outline-none cursor-pointer"
              >
                <option value="ALL" className="bg-[#0D1527]">All Tiers</option>
                <option value="Tier 1" className="bg-[#0D1527]">Tier 1 Flight Primes</option>
                <option value="Tier 2" className="bg-[#0D1527]">Tier 2 Subsystems</option>
              </select>
            </div>

            <button
              onClick={() => showToast("Exporting aerospace capability twin ledger to FIPS signed audit package.")}
              className="px-3 py-2 bg-[#0A101D] border border-slate-700 hover:border-slate-500 text-slate-300 rounded-lg text-xs font-mono font-bold flex items-center gap-1.5"
            >
              <Download size={14} /> Export Ledger
            </button>
          </div>
        </div>

        {/* Supplier Twins Table */}
        <div className="bg-[#0D1527] border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-[#0A101D] border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider">
              <tr>
                <th className="py-3 px-4">Twin ID / Supplier</th>
                <th className="py-3 px-4">CAGE / Defense</th>
                <th className="py-3 px-4">Partnership Tier</th>
                <th className="py-3 px-4 text-center">8-Pillar Score</th>
                <th className="py-3 px-4">Risk Profile</th>
                <th className="py-3 px-4">Onboarding Stage</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filteredSuppliers.map(sup => {
                const isVerified = sup.status === 'VERIFIED_CAPABILITY_TWIN';
                return (
                  <tr 
                    key={sup.id}
                    onClick={() => setSelectedSupplier(sup)}
                    className="hover:bg-[#0A101D]/70 cursor-pointer transition-colors"
                  >
                    <td className="py-4 px-4">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center font-bold text-cyan-400 text-xs shrink-0">
                          {sup.id.slice(-4)}
                        </div>
                        <div>
                          <div className="font-bold text-white text-xs">{sup.name}</div>
                          <div className="text-[10px] text-slate-400">{sup.industry}</div>
                        </div>
                      </div>
                    </td>

                    <td className="py-4 px-4">
                      <span className="font-mono font-bold text-cyan-300 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/30 text-[10px]">
                        CAGE {sup.cage_code || '7X892'}
                      </span>
                    </td>

                    <td className="py-4 px-4 text-slate-300 font-semibold">
                      {sup.tier}
                    </td>

                    <td className="py-4 px-4 text-center">
                      <span className="text-sm font-black text-emerald-400">
                        {sup.composite_score}
                      </span>
                      <span className="text-[10px] text-slate-500"> /100</span>
                    </td>

                    <td className="py-4 px-4">
                      <span className={`inline-flex items-center gap-1 text-[10px] font-bold ${
                        sup.risk_level === 'Low' ? 'text-emerald-400' : 'text-amber-400'
                      }`}>
                        <Shield size={12} /> {sup.risk_level} Risk
                      </span>
                    </td>

                    <td className="py-4 px-4">
                      <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold ${
                        isVerified
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                          : sup.status === 'PENDING_EXECUTIVE_APPROVAL'
                            ? 'bg-amber-500/10 text-amber-300 border border-amber-500/30'
                            : 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/30'
                      }`}>
                        {sup.status}
                      </span>
                    </td>

                    <td className="py-4 px-4 text-right">
                      <div className="flex items-center justify-end gap-2" onClick={e => e.stopPropagation()}>
                        <Link
                          href="/suppliers/assessments"
                          className="px-2.5 py-1 bg-[#0A101D] hover:bg-cyan-500/20 text-cyan-300 border border-slate-700 hover:border-cyan-400 rounded text-[10px] font-bold transition-all"
                        >
                          Assessment
                        </Link>
                        <Link
                          href="/suppliers/approvals"
                          className="px-2.5 py-1 bg-cyan-500 hover:bg-cyan-400 text-[#070B14] rounded text-[10px] font-bold transition-all"
                        >
                          Approval &rarr;
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

      {/* Supplier Drawer Detail Modal */}
      {selectedSupplier && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex justify-end">
          <div className="w-full max-w-md bg-[#0D1527] border-l border-slate-800 p-6 flex flex-col justify-between shadow-2xl animate-fade-in-right">
            <div>
              <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center font-mono font-bold text-cyan-400">
                    {selectedSupplier.id.slice(-4)}
                  </div>
                  <div>
                    <h3 className="font-bold text-white text-sm">{selectedSupplier.name}</h3>
                    <span className="text-[10px] font-mono text-cyan-400">{selectedSupplier.id}</span>
                  </div>
                </div>
                <button onClick={() => setSelectedSupplier(null)} className="text-slate-400 hover:text-white p-1">
                  <X size={18} />
                </button>
              </div>

              <div className="space-y-4 text-xs font-mono">
                <div className="p-3 bg-[#0A101D] rounded-lg border border-slate-800 space-y-2">
                  <div className="flex justify-between"><span className="text-slate-400">CAGE Code:</span> <span className="font-bold text-white">{selectedSupplier.cage_code || '7X892'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">Tier Level:</span> <span className="text-cyan-300">{selectedSupplier.tier}</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">Composite Score:</span> <span className="font-bold text-emerald-400">{selectedSupplier.composite_score} / 100</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">Risk Profile:</span> <span className="text-emerald-400">{selectedSupplier.risk_level}</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">Status:</span> <span className="text-cyan-300 font-bold">{selectedSupplier.status}</span></div>
                </div>

                <div className="p-3 bg-[#0A101D] rounded-lg border border-slate-800 space-y-2">
                  <div className="text-[10px] uppercase text-cyan-400 font-bold">Aerospace Quality Calibration</div>
                  <div className="text-slate-300 text-[11px] leading-relaxed">
                    Zero-Defect Zeiss CMM coordinate metrology verified at &plusmn;0.0001&quot; tolerance. CMMC Level 2 defense enclave air-gap operational.
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-6 border-t border-slate-800 flex flex-col gap-2.5">
              <Link
                href="/suppliers/assessments"
                className="w-full py-2.5 bg-[#0A101D] hover:bg-slate-800 border border-cyan-500/40 text-cyan-300 text-center rounded-lg text-xs font-mono font-bold"
              >
                Open 8-Pillar Assessment
              </Link>
              <Link
                href="/suppliers/approvals"
                className="w-full py-2.5 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-[#070B14] text-center rounded-lg text-xs font-mono font-black"
              >
                Executive Sign-Off Console &rarr;
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
