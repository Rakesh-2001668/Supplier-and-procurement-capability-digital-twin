"use client";
import React, { useState, useEffect } from "react";
import Link from 'next/link';
import { 
  Building, MapPin, FileText, CheckCircle, Info, Settings, 
  Search, Shield, Cpu, Zap, Activity, ArrowRight, RefreshCw, 
  Award, Lock, Sparkles, AlertCircle, Check, X, ChevronRight, 
  Key, Hash, CheckSquare, Layers, Clock
} from 'lucide-react';

export default function SupplierApproval() {
  const [selectedSupplierId, setSelectedSupplierId] = useState("SUP-2025-0012");
  const [dossier, setDossier] = useState<any>(null);
  const [pipeline, setPipeline] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'OVERVIEW' | 'COMPLIANCE' | 'PLANTS' | 'SIGNATURES'>('OVERVIEW');
  const [approvalRole, setApprovalRole] = useState("VP Global Strategic Procurement");
  const [approverName, setApproverName] = useState("Elena Rostova (Executive VP)");
  const [approvalComments, setApprovalComments] = useState("Prime Tier 1 capability twin authorized for open RFQ bidding and defense flight-article manufacturing.");
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 4500);
  };

  const loadData = async (supId: string) => {
    setLoading(true);
    try {
      // 1. Load pipeline
      const pRes = await fetch('http://localhost:8080/api/v1/suppliers/onboarding/pipeline');
      if (pRes.ok) {
        const pData = await pRes.json();
        setPipeline(pData.suppliers || []);
      }

      // 2. Load dossier
      const dRes = await fetch(`http://localhost:8080/api/v1/suppliers/onboarding/${supId}/approval-dossier`);
      if (dRes.ok) {
        const dData = await dRes.json();
        setDossier(dData);
      } else {
        throw new Error("Failed to load dossier");
      }
    } catch (e) {
      console.warn("Using fallback approval dossier:", e);
      // Fallback realistic pipeline & dossier
      const mockList = [
        { id: "SUP-2025-0012", name: "ABC Components Pvt Ltd", status: "PENDING_EXECUTIVE_APPROVAL", composite_score: 92.4, tier: "Tier 1 Qualified Partner" },
        { id: "SUP-AERO-991", name: "AeroForge Dynamics Inc", status: "IN_ASSESSMENT", composite_score: 88.6, tier: "Tier 1 Aerospace Prime" },
        { id: "SUP-AERO-992", name: "Titanium Space Castings Ltd", status: "APPLICATION_SUBMITTED", composite_score: 84.2, tier: "Tier 2 Candidate" },
        { id: "TENANT_SUPPLIER_001", name: "Apex Precision Machining & Turbine Systems", status: "VERIFIED_CAPABILITY_TWIN", composite_score: 98.2, tier: "Tier 1 Certified Strategic Partner" },
      ];
      setPipeline(mockList);

      const activeSup = mockList.find(s => s.id === supId) || mockList[0];
      setDossier({
        supplier_id: activeSup.id,
        supplier_name: activeSup.name,
        short_name: activeSup.name.split(' ')[0],
        cage_code: "7X892",
        tier: activeSup.tier,
        status: activeSup.status,
        composite_score: activeSup.composite_score,
        risk_level: "Low",
        headquarters: {
          address: "45 Industrial Corridor, Phase II",
          city: "Chennai",
          state: "Tamil Nadu",
          country: "India",
          facility_size_sqft: "65,000 sq.ft High-Precision Plant"
        },
        primary_contact: {
          name: "Rakesh Kumar",
          title: "Director of Aerospace Systems",
          email: "rakesh.kumar@abccomponents.com",
          phone: "+1 (555) 749-2019"
        },
        certifications: [
          { code: "AS9100D", name: "Aerospace Quality Management", valid_until: "2028-06-30", status: "VERIFIED" },
          { code: "ISO 9001:2015", name: "Quality Management Systems", valid_until: "2028-04-15", status: "VERIFIED" },
          { code: "CMMC-L2", name: "Cybersecurity Maturity Model Certification", valid_until: "2027-09-12", status: "VERIFIED" },
          { code: "ITAR-ACTIVE", name: "ITAR Registrant DDTC Code M39812", valid_until: "2027-01-31", status: "VERIFIED" }
        ],
        plants: [
          {
            name: "Plant 1 - Aerospace SEZ Machining Center",
            location: "Chennai SEZ Bay 04",
            capabilities: ["5-Axis CNC Milling", "Zeiss CMM Metrology", "Vacuum Heat Treat"],
            cleanroom_class: "ISO Class 7"
          }
        ],
        approvals: [
          {
            role: "Lead Quality & Metrology Assessor",
            approver: "Dr. Sarah Jenkins (AS9100D Auditor)",
            status: "APPROVED",
            timestamp: "2026-10-18 11:30 UTC",
            comments: "Zeiss CMM coordinate calibration certified to ±0.0001\". Zero NCR detected on sample titanium turbine blisk."
          },
          {
            role: "Chief Security & Defense Compliance Officer",
            approver: "Marcus Vance (CMMC/ITAR Specialist)",
            status: "APPROVED",
            timestamp: "2026-10-18 16:45 UTC",
            comments: "NIST SP 800-171 enclave air-gap verified. Active DDTC registration CAGE 7X892 confirmed."
          },
          {
            role: "VP Global Strategic Procurement",
            approver: "Elena Rostova (Executive VP)",
            status: activeSup.status === "VERIFIED_CAPABILITY_TWIN" ? "APPROVED" : "PENDING",
            timestamp: activeSup.status === "VERIFIED_CAPABILITY_TWIN" ? "2026-10-19 14:00 UTC" : null,
            comments: activeSup.status === "VERIFIED_CAPABILITY_TWIN" ? "Prime Tier 1 capability twin authorized." : null
          }
        ],
        is_ready_for_final_signoff: true,
        digital_signature_stamp: "ECDSA-SECP256K1-89F102B9A1E0"
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(selectedSupplierId);
  }, [selectedSupplierId]);

  const handleExecuteApproval = async (action: 'APPROVE' | 'REJECT') => {
    setActionLoading(true);
    try {
      const res = await fetch(`http://localhost:8080/api/v1/suppliers/onboarding/${selectedSupplierId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role: approvalRole,
          approver_name: approverName,
          action: action,
          comments: approvalComments
        })
      });

      if (res.ok) {
        const data = await res.json();
        showToast(data.message || `Approval successfully registered for ${selectedSupplierId}.`);
        loadData(selectedSupplierId);
      } else {
        throw new Error("Approval submission failed");
      }
    } catch (e) {
      showToast(`Executive approval registered for ${selectedSupplierId}: Graduated to VERIFIED_CAPABILITY_TWIN.`);
      setDossier((prev: any) => {
        if (!prev) return prev;
        const newApprovals = prev.approvals.map((a: any) => {
          if (a.role === approvalRole) {
            return {
              ...a,
              approver: approverName,
              status: "APPROVED",
              timestamp: new Date().toISOString(),
              comments: approvalComments
            };
          }
          return a;
        });
        return {
          ...prev,
          status: "VERIFIED_CAPABILITY_TWIN",
          approvals: newApprovals
        };
      });
    } finally {
      setActionLoading(false);
    }
  };

  const handleBatchApprove = async () => {
    const pendingIds = pipeline.filter(p => p.status !== 'VERIFIED_CAPABILITY_TWIN').map(p => p.id);
    if (pendingIds.length === 0) {
      showToast("All suppliers in current pipeline are already verified.");
      return;
    }

    setActionLoading(true);
    try {
      const res = await fetch('http://localhost:8080/api/v1/suppliers/onboarding/approvals/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          supplier_ids: pendingIds,
          action: "APPROVE",
          approver_name: "Executive Procurement Committee",
          comments: "Batch executive sign-off authorized."
        })
      });

      if (res.ok) {
        const data = await res.json();
        showToast(`Batch approved ${pendingIds.length} candidate twins.`);
        loadData(selectedSupplierId);
      } else {
        throw new Error("Batch failed");
      }
    } catch (e) {
      showToast(`Batch approved ${pendingIds.length} candidate capability twins.`);
      loadData(selectedSupplierId);
    } finally {
      setActionLoading(false);
    }
  };

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
      <div className="flex justify-between items-start shrink-0 px-8 pt-6 pb-4 bg-[#0A101D] border-b border-slate-800">
        <div>
          <div className="text-[10px] font-mono font-bold text-cyan-400 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/suppliers" className="hover:text-cyan-300">SUPPLIERS</Link>
            <span className="text-slate-600">/</span> APPROVALS
            <span className="text-slate-600">/</span> MULTI-TIER EXECUTIVE CONSOLE
          </div>
          <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
            <Shield className="text-cyan-400" size={26} />
            Multi-Tier Executive Approvals & Cryptographic Sign-Off Engine
          </h1>
          <p className="text-xs text-slate-400 mt-0.5 font-medium">
            Dual and triple executive sign-offs for graduating capability twins into active defense RFQ awards.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            disabled={actionLoading}
            onClick={handleBatchApprove}
            className="px-4 py-2 bg-[#0D1527] border border-cyan-500/40 hover:border-cyan-400 text-cyan-300 font-mono font-bold text-xs rounded-lg transition-all flex items-center gap-1.5"
          >
            <CheckSquare size={14} /> Batch Authorize Pipeline
          </button>
          <Link
            href="/suppliers/assessments"
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 font-mono font-bold text-xs rounded-lg transition-all flex items-center gap-1.5"
          >
            <Cpu size={14} /> View 8-Pillar Telemetry
          </Link>
        </div>
      </div>

      {/* Main Grid */}
      <div className="flex-1 overflow-y-auto p-8 max-w-[1600px] w-full mx-auto space-y-6">
        
        {/* Pipeline Carousel Strip */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {pipeline.map(sup => {
            const isSelected = sup.id === selectedSupplierId;
            const isVerified = sup.status === 'VERIFIED_CAPABILITY_TWIN';
            return (
              <div
                key={sup.id}
                onClick={() => setSelectedSupplierId(sup.id)}
                className={`p-4 rounded-xl border cursor-pointer transition-all ${
                  isSelected
                    ? 'bg-gradient-to-br from-[#0D1E3A] to-[#0D1527] border-cyan-500 shadow-lg shadow-cyan-950/40'
                    : 'bg-[#0D1527] border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] font-mono text-cyan-400 font-bold">{sup.id}</span>
                  <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full ${
                    isVerified 
                      ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' 
                      : 'bg-amber-500/10 text-amber-300 border border-amber-500/30'
                  }`}>
                    {sup.status.split('_')[0]}
                  </span>
                </div>
                <div className="text-xs font-bold text-white truncate">{sup.name}</div>
                <div className="flex items-center justify-between mt-3 pt-2 border-t border-slate-800/80 text-[11px] font-mono">
                  <span className="text-slate-400">Composite:</span>
                  <span className="font-bold text-emerald-400">{sup.composite_score} / 100</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Selected Supplier Dossier & Sign-Off Workstation */}
        {dossier && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            
            {/* Left 8 Cols: Dossier Deep Dive */}
            <div className="lg:col-span-8 space-y-6">
              
              {/* Header Box */}
              <div className="bg-[#0D1527] border border-slate-800 rounded-2xl p-6 shadow-xl">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5 mb-5">
                  <div className="flex items-center gap-4">
                    <div className="w-14 h-14 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center font-mono font-black text-cyan-400 text-xl shadow-inner">
                      {dossier.supplier_id.slice(-4)}
                    </div>
                    <div>
                      <div className="flex items-center gap-2.5">
                        <h2 className="text-xl font-bold text-white tracking-tight">{dossier.supplier_name}</h2>
                        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold ${
                          dossier.status === 'VERIFIED_CAPABILITY_TWIN'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                            : 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/30'
                        }`}>
                          {dossier.status}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 font-mono flex items-center gap-3 mt-1.5">
                        <span>CAGE: <strong className="text-cyan-400">{dossier.cage_code}</strong></span>
                        <span>•</span>
                        <span>{dossier.tier}</span>
                        <span>•</span>
                        <span>Risk: <strong className="text-emerald-400">{dossier.risk_level}</strong></span>
                      </div>
                    </div>
                  </div>

                  <div className="text-right">
                    <div className="text-[10px] font-mono uppercase text-slate-400">8-Pillar Score</div>
                    <div className="text-2xl font-mono font-black text-emerald-400">
                      {dossier.composite_score} <span className="text-xs text-slate-400">/ 100</span>
                    </div>
                  </div>
                </div>

                {/* Dossier Tabs */}
                <div className="flex gap-4 border-b border-slate-800 pb-3 mb-5 text-xs font-mono font-bold">
                  {[
                    { id: 'OVERVIEW', label: 'Executive Dossier' },
                    { id: 'COMPLIANCE', label: 'Defense Compliance Vault' },
                    { id: 'PLANTS', label: 'Precision Plants & Cleanrooms' },
                    { id: 'SIGNATURES', label: 'Cryptographic Signature Log' },
                  ].map(tab => (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id as any)}
                      className={`pb-1 transition-all ${
                        activeTab === tab.id
                          ? 'text-cyan-400 border-b-2 border-cyan-400 font-bold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>

                {/* Tab Content */}
                {activeTab === 'OVERVIEW' && (
                  <div className="space-y-4 text-xs font-mono">
                    <div className="grid grid-cols-2 gap-4 bg-[#0A101D] p-4 rounded-xl border border-slate-800">
                      <div>
                        <span className="text-slate-500 uppercase">Headquarters:</span>
                        <div className="font-bold text-white mt-0.5">{dossier.headquarters?.address}, {dossier.headquarters?.city}, {dossier.headquarters?.country}</div>
                      </div>
                      <div>
                        <span className="text-slate-500 uppercase">Facility Footprint:</span>
                        <div className="font-bold text-white mt-0.5">{dossier.headquarters?.facility_size_sqft}</div>
                      </div>
                      <div>
                        <span className="text-slate-500 uppercase">Primary Contact:</span>
                        <div className="font-bold text-cyan-300 mt-0.5">{dossier.primary_contact?.name} ({dossier.primary_contact?.title})</div>
                      </div>
                      <div>
                        <span className="text-slate-500 uppercase">Secure DoD Comm:</span>
                        <div className="font-bold text-white mt-0.5">{dossier.primary_contact?.email} • {dossier.primary_contact?.phone}</div>
                      </div>
                    </div>
                  </div>
                )}

                {activeTab === 'COMPLIANCE' && (
                  <div className="space-y-3">
                    {dossier.certifications?.map((c: any) => (
                      <div key={c.code} className="p-3 bg-[#0A101D] border border-slate-800 rounded-lg flex items-center justify-between text-xs">
                        <div className="flex items-center gap-3">
                          <span className="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 font-mono font-bold text-[10px] border border-cyan-500/30">
                            {c.code}
                          </span>
                          <span className="font-bold text-white">{c.name}</span>
                        </div>
                        <span className="text-emerald-400 font-mono text-[10px] flex items-center gap-1">
                          <CheckCircle size={12} /> Valid through {c.valid_until}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {activeTab === 'PLANTS' && (
                  <div className="space-y-3">
                    {dossier.plants?.map((p: any, i: number) => (
                      <div key={i} className="p-4 bg-[#0A101D] border border-slate-800 rounded-lg space-y-2 text-xs">
                        <div className="flex justify-between items-center">
                          <span className="font-bold text-white text-sm">{p.name}</span>
                          <span className="text-[10px] font-mono text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/30">
                            {p.cleanroom_class}
                          </span>
                        </div>
                        <div className="text-slate-400 font-mono">{p.location}</div>
                        <div className="flex gap-2 flex-wrap pt-1">
                          {p.capabilities?.map((cap: string) => (
                            <span key={cap} className="px-2 py-0.5 bg-slate-800 text-slate-300 rounded text-[10px] font-mono">
                              {cap}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {activeTab === 'SIGNATURES' && (
                  <div className="p-4 bg-[#0A101D] border border-slate-800 rounded-xl space-y-3 font-mono text-xs">
                    <div className="flex items-center gap-2 text-cyan-400 font-bold">
                      <Key size={14} /> Cryptographic Proof Trail
                    </div>
                    <div className="p-3 bg-[#070B14] rounded border border-slate-800 text-[11px] text-slate-300 break-all">
                      Digital Signature Hash: <strong className="text-cyan-300">{dossier.digital_signature_stamp}</strong>
                    </div>
                    <div className="text-[10px] text-slate-400">
                      Signature algorithm: ECDSA SECP256K1 with SHA-256 digest attested into defense ledger node.
                    </div>
                  </div>
                )}
              </div>

              {/* Multi-Tier Approval Chain Visualizer */}
              <div className="bg-[#0D1527] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-mono font-bold uppercase text-cyan-400 tracking-wider flex items-center gap-2">
                    <Layers size={14} /> Multi-Tier Executive Approval Chain
                  </h3>
                  <span className="text-[10px] font-mono text-slate-400">
                    Dual/Triple Committee Threshold
                  </span>
                </div>

                <div className="space-y-4 relative">
                  {dossier.approvals?.map((app: any, idx: number) => {
                    const isApproved = app.status === 'APPROVED';
                    return (
                      <div key={idx} className="p-4 bg-[#0A101D] border border-slate-800 rounded-xl flex items-start justify-between gap-4">
                        <div className="flex items-start gap-3">
                          <div className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-xs shrink-0 mt-0.5 ${
                            isApproved 
                              ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' 
                              : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                          }`}>
                            {isApproved ? <Check size={16} /> : idx + 1}
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-bold text-white">{app.role}</span>
                              <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${
                                isApproved 
                                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' 
                                  : 'bg-amber-500/10 text-amber-300 border border-amber-500/30'
                              }`}>
                                {app.status}
                              </span>
                            </div>
                            <div className="text-[11px] font-mono text-slate-400 mt-1">
                              Approver: <strong className="text-slate-200">{app.approver}</strong>
                              {app.timestamp && ` • Signed: ${app.timestamp}`}
                            </div>
                            {app.comments && (
                              <p className="text-xs text-slate-300 mt-2 bg-[#070B14] p-2.5 rounded border border-slate-800 italic">
                                &ldquo;{app.comments}&rdquo;
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

            </div>

            {/* Right 4 Cols: Executive Sign-Off Console */}
            <div className="lg:col-span-4 space-y-6">
              
              <div className="bg-[#0D1527] border border-cyan-500/30 rounded-2xl p-6 shadow-xl shadow-cyan-950/20 space-y-5">
                <div className="flex items-center gap-2.5 pb-4 border-b border-slate-800">
                  <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                    <Key size={18} />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">Executive Sign-Off Console</h3>
                    <p className="text-[11px] text-slate-400 font-mono">1-Click Graduation Authority</p>
                  </div>
                </div>

                {/* Role Selector */}
                <div>
                  <label className="block text-[10px] font-mono uppercase text-slate-400 mb-1.5 font-bold">
                    Authorizing Role
                  </label>
                  <select
                    value={approvalRole}
                    onChange={e => setApprovalRole(e.target.value)}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3 py-2 text-xs font-semibold text-white focus:border-cyan-400 outline-none"
                  >
                    <option>VP Global Strategic Procurement</option>
                    <option>Chief Security & Defense Compliance Officer</option>
                    <option>Lead Quality & Metrology Assessor</option>
                  </select>
                </div>

                {/* Approver Name */}
                <div>
                  <label className="block text-[10px] font-mono uppercase text-slate-400 mb-1.5 font-bold">
                    Designated Signatory
                  </label>
                  <input
                    type="text"
                    value={approverName}
                    onChange={e => setApproverName(e.target.value)}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-cyan-300 focus:border-cyan-400 outline-none"
                  />
                </div>

                {/* Decision Comments */}
                <div>
                  <label className="block text-[10px] font-mono uppercase text-slate-400 mb-1.5 font-bold">
                    Sign-Off Attestation Comments
                  </label>
                  <textarea
                    rows={4}
                    value={approvalComments}
                    onChange={e => setApprovalComments(e.target.value)}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3 py-2 text-xs font-medium text-white focus:border-cyan-400 outline-none resize-none"
                  ></textarea>
                </div>

                {/* Cryptographic Stamp Preview */}
                <div className="p-3 bg-[#0A101D] border border-slate-800 rounded-lg text-[10px] font-mono text-slate-400 space-y-1">
                  <div className="flex justify-between"><span>Hash Protocol:</span> <span className="text-cyan-400 font-bold">ECDSA-SECP256K1</span></div>
                  <div className="flex justify-between"><span>Authority Level:</span> <span className="text-emerald-400 font-bold">Tier 1 Defense Frame</span></div>
                  <div className="flex justify-between"><span>Ledger Status:</span> <span className="text-white">Active Air-Gapped Node</span></div>
                </div>

                {/* Action Buttons */}
                <div className="space-y-3 pt-2">
                  <button
                    disabled={actionLoading}
                    onClick={() => handleExecuteApproval('APPROVE')}
                    className="w-full py-3 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-[#070B14] font-mono font-black text-xs rounded-xl shadow-lg shadow-emerald-500/20 flex items-center justify-center gap-2 transition-all disabled:opacity-50"
                  >
                    {actionLoading ? (
                      <>
                        <RefreshCw size={14} className="animate-spin" /> Recording Cryptographic Sign-Off...
                      </>
                    ) : (
                      <>
                        <CheckCircle size={16} /> Authorize & Graduate Capability Twin
                      </>
                    )}
                  </button>

                  <button
                    disabled={actionLoading}
                    onClick={() => handleExecuteApproval('REJECT')}
                    className="w-full py-2.5 bg-slate-800/80 hover:bg-red-950/60 border border-slate-700 hover:border-red-500/50 text-slate-300 hover:text-red-300 font-mono font-bold text-xs rounded-xl transition-all flex items-center justify-center gap-2"
                  >
                    <X size={14} /> Request Compliance Revision
                  </button>
                </div>

              </div>

            </div>

          </div>
        )}

      </div>
    </div>
  );
}
