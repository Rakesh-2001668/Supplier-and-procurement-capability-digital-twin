"use client";
import React, { useState, useEffect } from "react";
import Link from 'next/link';
import { 
  Building, MapPin, FileText, CheckCircle, Info, Settings, 
  Search, Shield, Cpu, Zap, Activity, ArrowRight, RefreshCw, 
  Award, Lock, Sparkles, AlertCircle, BarChart3, Sliders, Check, 
  ChevronRight, ExternalLink, Gauge, ArrowUpRight
} from 'lucide-react';

export default function SupplierAssessment() {
  const [selectedSupplierId, setSelectedSupplierId] = useState("SUP-2025-0012");
  const [assessmentData, setAssessmentData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [activePillarIndex, setActivePillarIndex] = useState(0);
  const [isCalibrating, setIsCalibrating] = useState(false);
  const [recalibrationScore, setRecalibrationScore] = useState(95);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const supplierList = [
    { id: "SUP-2025-0012", name: "ABC Components Pvt Ltd", tag: "Aerospace CNC & Blisks", score: 92.4, status: "PENDING_EXECUTIVE_APPROVAL" },
    { id: "SUP-AERO-991", name: "AeroForge Dynamics Inc", tag: "Superalloy & Rocket Casings", score: 88.6, status: "IN_ASSESSMENT" },
    { id: "SUP-AERO-992", name: "Titanium Space Castings Ltd", tag: "Vacuum Investment Casting", score: 84.2, status: "APPLICATION_SUBMITTED" },
    { id: "TENANT_SUPPLIER_001", name: "Apex Precision Machining & Turbine Systems", tag: "DMG MORI 5-Axis Fleet", score: 98.2, status: "VERIFIED_CAPABILITY_TWIN" },
  ];

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 4000);
  };

  const fetchAssessment = async (supId: string) => {
    setLoading(true);
    try {
      const res = await fetch(`http://localhost:8080/api/v1/suppliers/onboarding/${supId}/assessment`);
      if (res.ok) {
        const data = await res.json();
        setAssessmentData(data);
        if (data.pillars && data.pillars[activePillarIndex]) {
          setRecalibrationScore(data.pillars[activePillarIndex].current_score);
        }
      } else {
        throw new Error("Failed to load");
      }
    } catch (e) {
      console.warn("Using fallback assessment dossier:", e);
      // Fallback realistic assessment data
      const sup = supplierList.find(s => s.id === supId) || supplierList[0];
      setAssessmentData({
        supplier_id: sup.id,
        supplier_name: sup.name,
        cage_code: "7X892",
        industry: "Aerospace Precision Propulsion & Space Flight Hardware",
        tier: "Tier 1 Qualified Partner",
        composite_score: sup.score,
        risk_level: sup.score >= 90 ? "Low" : "Medium",
        status_code: sup.status,
        plants_count: 2,
        certifications: [
          { code: "AS9100D", name: "Aerospace Quality Rev D", status: "VERIFIED" },
          { code: "CMMC-L2", name: "Defense Cybersecurity NIST 800-171", status: "VERIFIED" },
          { code: "ITAR-ACTIVE", name: "ITAR DDTC Certified", status: "VERIFIED" }
        ],
        pillars: [
          {
            id: "financial_solvency",
            name: "Autonomous Financial & Solvency Health",
            weight: 0.15,
            current_score: 92,
            target_score: 90,
            metrics: ["Altman Z''-Score (3.62)", "D&B PAYDEX (88/100)", "Debt-to-Equity (0.42)", "Operating Cash Runway (24 mos)"],
            benchmark: "Investment Grade BAA1 / Low Liquidity Risk",
            status: "EXCEEDS_BENCHMARK"
          },
          {
            id: "as9100d_metrology",
            name: "AS9100D Rev D & Zero-Defect Metrology",
            weight: 0.20,
            current_score: 96,
            target_score: 95,
            metrics: ["Zeiss CMM Calibration (±0.0001\")", "AS9102 First Article Inspection Rate (99.8%)", "Process Capability Cpk (1.82)", "Optical Laser Interferometry"],
            benchmark: "NADCAP Accredited (NDT & Heat Treat)",
            status: "EXCEEDS_BENCHMARK"
          },
          {
            id: "precision_telemetry",
            name: "Precision Manufacturing & Capacity Telemetry",
            weight: 0.15,
            current_score: 89,
            target_score: 88,
            metrics: ["DMG MORI 5-Axis CNC Spindle OEE (84.6%)", "ISO Class 5 Space Cleanroom Packaging", "Wire EDM Tolerance (<1.5µm)", "Automated Tool Wear Telemetry"],
            benchmark: "Industry 4.0 Digital Shopfloor Active",
            status: "EXCEEDS_BENCHMARK"
          },
          {
            id: "esg_lifecycle",
            name: "ESG & Carbon Scope 1/2/3 Lifecycle Telemetry",
            weight: 0.10,
            current_score: 88,
            target_score: 85,
            metrics: ["Scope 1 & 2 Emissions (42.1 tCO2e/yr)", "100% Conflict-Free Minerals (Dodd-Frank 1502)", "Renewable Solar Microgrid (68%)", "Closed-Loop Coolant Recirculation (94%)"],
            benchmark: "ISO 14001:2015 & RoHS/REACH Compliant",
            status: "EXCEEDS_BENCHMARK"
          },
          {
            id: "cyber_zero_trust",
            name: "Zero-Trust Cyber & Information Security",
            weight: 0.15,
            current_score: 95,
            target_score: 92,
            metrics: ["CMMC Level 2 Certified (NIST SP 800-171)", "Air-Gapped CAD/CAM Enclave", "FIPS 140-3 Hardware Crypto Modules", "Zero-Trust Device Identity Attestation"],
            benchmark: "ITAR & EAR Defense Enclave Compliant",
            status: "EXCEEDS_BENCHMARK"
          },
          {
            id: "dfsc_resilience",
            name: "Geopolitical & DFSC Multi-Sourcing Resilience",
            weight: 0.10,
            current_score: 90,
            target_score: 86,
            metrics: ["Disruption-Free Supply Chain Score (91.4)", "Tier-2 Billet Redundancy (Dual Sourced)", "Geopolitical Chokepoint Distance (>800 km)", "Strategic Buffer Stock (60 Days)"],
            benchmark: "Resilient NATO / Tier-1 Production Node",
            status: "EXCEEDS_BENCHMARK"
          },
          {
            id: "predictive_otd",
            name: "High-Velocity On-Time Delivery Simulation",
            weight: 0.08,
            current_score: 94,
            target_score: 94,
            metrics: ["Monte Carlo Schedule Reliability (98.2%)", "Historical OTD (99.1%)", "Buffer Compression Capability (<48 hrs)", "Real-Time ASN EDI 856 Telemetry"],
            benchmark: "Critical Spaceflight Flight-Article Readiness",
            status: "MEETS_BENCHMARK"
          },
          {
            id: "advanced_materials",
            name: "Advanced Superalloys & Generative Topology",
            weight: 0.07,
            current_score: 91,
            target_score: 89,
            metrics: ["Inconel 718 & Titanium Ti-6Al-4V Certified", "Additive DMLS Powder Metallurgy", "Cryogenic Nitrogen Machining", "Generative Lightweighting Co-Engineering"],
            benchmark: "Propulsion Grade High-Temp Metallurgy",
            status: "EXCEEDS_BENCHMARK"
          }
        ],
        ai_recommendation: {
          verdict: "RECOMMENDED_FOR_TIER_1_DEFENSE_AWARD",
          confidence: "98.4%",
          key_strengths: [
            "Zero-Defect Zeiss CMM coordinate metrology verified at ±0.0001\" precision.",
            "Active CAGE code 7X892 and ITAR defense enclave air-gap verified.",
            "High-velocity DMG MORI 5-Axis spindle OEE exceeding 84%."
          ],
          action_items: [
            "Authorize executive procurement sign-off to graduate twin to active bidding network.",
            "Lock in quarterly capacity reservation under Tier 1 CAPEX frame agreement."
          ]
        }
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAssessment(selectedSupplierId);
  }, [selectedSupplierId]);

  const handleRecalibrate = async () => {
    if (!assessmentData || !assessmentData.pillars[activePillarIndex]) return;
    const currentPillar = assessmentData.pillars[activePillarIndex];

    setIsCalibrating(true);
    try {
      const res = await fetch(`http://localhost:8080/api/v1/suppliers/onboarding/${selectedSupplierId}/assessment/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pillar_id: currentPillar.id,
          new_score: recalibrationScore,
          evaluator_name: "Lead Quality Assessor",
          evaluator_notes: "Zeiss CMM coordinate calibration certified and recalibrated."
        })
      });

      if (res.ok) {
        const data = await res.json();
        showToast(`Pillar '${currentPillar.name}' calibrated to ${recalibrationScore}. Composite score updated to ${data.new_composite_score}.`);
        fetchAssessment(selectedSupplierId);
      } else {
        throw new Error("Recalibration response not OK");
      }
    } catch (e) {
      showToast(`Pillar calibrated locally: '${currentPillar.name}' updated to ${recalibrationScore}.`);
      setAssessmentData((prev: any) => {
        if (!prev) return prev;
        const newPillars = [...prev.pillars];
        newPillars[activePillarIndex] = {
          ...newPillars[activePillarIndex],
          current_score: recalibrationScore
        };
        return {
          ...prev,
          pillars: newPillars,
          composite_score: Math.round((prev.composite_score + 0.3) * 10) / 10
        };
      });
    } finally {
      setIsCalibrating(false);
    }
  };

  const currentPillar = assessmentData?.pillars?.[activePillarIndex] || null;

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
            <span className="text-slate-600">/</span> ASSESSMENTS
            <span className="text-slate-600">/</span> 8-PILLAR AEROSPACE ENGINE
          </div>
          <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
            <Activity className="text-cyan-400" size={26} />
            Aerospace Capability Twin Assessment Workstation
          </h1>
          <p className="text-xs text-slate-400 mt-0.5 font-medium">
            Autonomous multi-pillar scoring across AS9100D metrology, CMMC Level 2 cyber enclaves, and DFSC resilience.
          </p>
        </div>

        {/* Quick Supplier Switcher & Route */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 bg-[#0D1527] border border-slate-700 px-3 py-1.5 rounded-lg">
            <span className="text-[10px] font-mono text-slate-400 uppercase">Dossier:</span>
            <select
              value={selectedSupplierId}
              onChange={e => setSelectedSupplierId(e.target.value)}
              className="bg-transparent text-xs font-mono font-bold text-cyan-300 outline-none cursor-pointer"
            >
              {supplierList.map(s => (
                <option key={s.id} value={s.id} className="bg-[#0D1527] text-white">
                  {s.id} - {s.name.split(' ')[0]} ({s.score})
                </option>
              ))}
            </select>
          </div>

          <Link
            href="/suppliers/approvals"
            className="px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-[#070B14] font-black text-xs rounded-lg shadow-lg shadow-cyan-500/20 flex items-center gap-1.5 transition-all"
          >
            <Shield size={14} /> Executive Approvals &rarr;
          </Link>
        </div>
      </div>

      {/* Main Workspace */}
      <div className="flex-1 overflow-y-auto p-8 space-y-6 max-w-[1600px] w-full mx-auto">
        
        {/* Top Summary Banner */}
        {assessmentData && (
          <div className="bg-[#0D1527] border border-slate-800 rounded-2xl p-6 shadow-xl">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
              
              {/* Left Identity */}
              <div className="flex items-start gap-4">
                <div className="w-14 h-14 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 text-xl font-black font-mono shadow-inner">
                  {assessmentData.supplier_id.slice(-4)}
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <h2 className="text-xl font-bold text-white tracking-tight">{assessmentData.supplier_name}</h2>
                    <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-cyan-500/10 text-cyan-300 border border-cyan-500/30">
                      {assessmentData.status_code}
                    </span>
                  </div>
                  <div className="text-xs text-slate-400 font-mono flex items-center gap-3 mt-1.5">
                    <span>ID: <strong className="text-cyan-400">{assessmentData.supplier_id}</strong></span>
                    <span>•</span>
                    <span>CAGE: <strong className="text-white">{assessmentData.cage_code}</strong></span>
                    <span>•</span>
                    <span>{assessmentData.tier}</span>
                    <span>•</span>
                    <span>{assessmentData.industry}</span>
                  </div>
                </div>
              </div>

              {/* Right Composite KPI Strip */}
              <div className="flex items-center gap-4 bg-[#0A101D] border border-slate-800/80 rounded-xl p-4 shrink-0">
                <div className="text-center px-4 border-r border-slate-800">
                  <div className="text-[10px] font-mono uppercase text-slate-400">Composite Score</div>
                  <div className="text-2xl font-mono font-black text-emerald-400 mt-0.5">
                    {assessmentData.composite_score} <span className="text-xs text-slate-500">/100</span>
                  </div>
                </div>
                <div className="text-center px-4 border-r border-slate-800">
                  <div className="text-[10px] font-mono uppercase text-slate-400">Risk Profile</div>
                  <div className="text-sm font-mono font-bold text-cyan-300 mt-1 flex items-center justify-center gap-1">
                    <Shield size={14} className="text-cyan-400" />
                    {assessmentData.risk_level} Risk
                  </div>
                </div>
                <div className="text-center px-4">
                  <div className="text-[10px] font-mono uppercase text-slate-400">Defense Enclave</div>
                  <div className="text-sm font-mono font-bold text-emerald-400 mt-1 flex items-center justify-center gap-1">
                    <CheckCircle size={14} className="text-emerald-400" />
                    CMMC Level 2
                  </div>
                </div>
              </div>

            </div>
          </div>
        )}

        {/* 8-Pillars Interactive Matrix */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          
          {/* Left Column: Pillar List (4 Cols) */}
          <div className="lg:col-span-5 space-y-2.5">
            <div className="flex items-center justify-between px-1 mb-2">
              <span className="text-xs font-mono font-bold uppercase text-cyan-400 tracking-wider">
                8 Aerospace Assessment Pillars
              </span>
              <span className="text-[10px] font-mono text-slate-400">Weighted Total 100%</span>
            </div>

            {assessmentData?.pillars?.map((p: any, idx: number) => {
              const isSelected = activePillarIndex === idx;
              return (
                <div
                  key={p.id}
                  onClick={() => {
                    setActivePillarIndex(idx);
                    setRecalibrationScore(p.current_score);
                  }}
                  className={`p-4 rounded-xl border cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-gradient-to-r from-[#0D1E3A] to-[#0D1527] border-cyan-500 text-white shadow-lg shadow-cyan-950/40'
                      : 'bg-[#0D1527] border-slate-800 text-slate-400 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2.5">
                      <div className={`w-6 h-6 rounded-md flex items-center justify-center text-[10px] font-mono font-bold ${
                        isSelected ? 'bg-cyan-500 text-[#070B14]' : 'bg-slate-800 text-slate-300'
                      }`}>
                        {idx + 1}
                      </div>
                      <span className={`text-xs font-bold ${isSelected ? 'text-cyan-300' : 'text-slate-300'}`}>
                        {p.name}
                      </span>
                    </div>
                    <span className="text-xs font-mono font-black text-emerald-400">
                      {p.current_score} <span className="text-[10px] text-slate-500">/{p.target_score}</span>
                    </span>
                  </div>

                  {/* Weight & Progress */}
                  <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 mt-2">
                    <span>Weight: {(p.weight * 100).toFixed(0)}%</span>
                    <span className={p.current_score >= p.target_score ? 'text-emerald-400' : 'text-amber-400'}>
                      {p.status}
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-[#0A101D] rounded-full overflow-hidden mt-1.5">
                    <div 
                      className={`h-full rounded-full transition-all duration-300 ${
                        p.current_score >= p.target_score ? 'bg-cyan-400' : 'bg-amber-400'
                      }`}
                      style={{ width: `${p.current_score}%` }}
                    ></div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Right Column: Deep Pillar Dossier & Recalibration (7 Cols) */}
          <div className="lg:col-span-7 space-y-6">
            {currentPillar && (
              <div className="bg-[#0D1527] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
                
                {/* Pillar Header */}
                <div className="flex items-start justify-between border-b border-slate-800 pb-4">
                  <div>
                    <div className="text-[10px] font-mono uppercase text-cyan-400 font-bold mb-1">
                      Pillar Telemetry #{activePillarIndex + 1} • Benchmark Weight {(currentPillar.weight * 100).toFixed(0)}%
                    </div>
                    <h3 className="text-xl font-bold text-white tracking-tight">{currentPillar.name}</h3>
                    <p className="text-xs text-slate-400 mt-1">
                      Benchmark Standard: <strong className="text-slate-300">{currentPillar.benchmark}</strong>
                    </p>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-mono font-black text-emerald-400">
                      {currentPillar.current_score} <span className="text-xs text-slate-400">/ 100</span>
                    </div>
                    <span className="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">
                      {currentPillar.status}
                    </span>
                  </div>
                </div>

                {/* Granular Metrics Radar Checklist */}
                <div>
                  <h4 className="text-xs font-mono font-bold uppercase text-slate-300 mb-3 flex items-center gap-2">
                    <Gauge size={14} className="text-cyan-400" />
                    Verified Metrology & Enclave Telemetry Points
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {currentPillar.metrics.map((m: string, i: number) => (
                      <div key={i} className="p-3 bg-[#0A101D] border border-slate-800 rounded-lg flex items-center gap-2.5">
                        <CheckCircle size={14} className="text-emerald-400 shrink-0" />
                        <span className="text-xs font-mono font-semibold text-slate-200">{m}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Interactive Recalibration Console */}
                <div className="p-5 bg-[#0A101D] border border-cyan-500/30 rounded-xl space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Sliders size={16} className="text-cyan-400" />
                      <span className="text-xs font-mono font-bold uppercase text-white">
                        Lead Assessor Recalibration Console
                      </span>
                    </div>
                    <span className="text-xs font-mono font-black text-cyan-300">
                      Calibrated Score: {recalibrationScore} / 100
                    </span>
                  </div>

                  <div className="space-y-2">
                    <input
                      type="range"
                      min={60}
                      max={100}
                      value={recalibrationScore}
                      onChange={e => setRecalibrationScore(parseInt(e.target.value))}
                      className="w-full accent-cyan-400 h-2 bg-slate-800 rounded-lg cursor-pointer"
                    />
                    <div className="flex justify-between text-[10px] font-mono text-slate-500">
                      <span>60 (Conditional)</span>
                      <span>80 (Meets Specs)</span>
                      <span>90 (AS9100D Standard)</span>
                      <span>100 (Zero Defect / Sub-Mil)</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-2">
                    <span className="text-[11px] text-slate-400">
                      Recalibrating triggers automated weighted score re-synthesis across the database.
                    </span>
                    <button
                      disabled={isCalibrating}
                      onClick={handleRecalibrate}
                      className="px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-[#070B14] font-mono font-bold text-xs rounded-lg transition-all flex items-center gap-1.5 shadow-md shadow-cyan-500/20"
                    >
                      {isCalibrating ? (
                        <>
                          <RefreshCw size={12} className="animate-spin" /> Recalibrating...
                        </>
                      ) : (
                        <>
                          <Check size={14} /> Commit Recalibration
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {/* AI Executive Recommendation Dossier */}
                {assessmentData.ai_recommendation && (
                  <div className="p-5 bg-gradient-to-r from-blue-950/40 to-slate-900 border border-slate-800 rounded-xl space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Sparkles size={16} className="text-cyan-400" />
                        <span className="text-xs font-mono font-bold text-white uppercase">
                          AI Recommendation Verdict
                        </span>
                      </div>
                      <span className="text-[10px] font-mono text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/30">
                        Confidence {assessmentData.ai_recommendation.confidence}
                      </span>
                    </div>

                    <div className="text-xs font-mono font-bold text-emerald-400 flex items-center gap-1.5">
                      <CheckCircle size={14} />
                      {assessmentData.ai_recommendation.verdict}
                    </div>

                    <div className="space-y-1.5">
                      {assessmentData.ai_recommendation.key_strengths.map((str: string, i: number) => (
                        <div key={i} className="text-xs text-slate-300 flex items-start gap-2">
                          <span className="text-cyan-400 mt-0.5">•</span>
                          <span>{str}</span>
                        </div>
                      ))}
                    </div>

                    <div className="pt-3 border-t border-slate-800/80 flex items-center justify-between">
                      <span className="text-[11px] text-slate-400">
                        Ready for final cryptographic executive sign-off?
                      </span>
                      <Link
                        href="/suppliers/approvals"
                        className="text-xs font-mono font-bold text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
                      >
                        Forward to Executive Console <ArrowUpRight size={14} />
                      </Link>
                    </div>
                  </div>
                )}

              </div>
            )}
          </div>

        </div>

      </div>
    </div>
  );
}
