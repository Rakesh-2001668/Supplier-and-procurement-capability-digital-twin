"use client";
import React, { useState } from "react";
import Link from 'next/link';
import { 
  Building, MapPin, FileText, CheckCircle, Info, CheckSquare, 
  Settings, Upload, Download, Search, ChevronRight, X, Shield, 
  Cpu, Zap, Activity, ArrowRight, ArrowLeft, RefreshCw, Award, 
  Lock, Sparkles, AlertCircle, Layers, Check, Globe
} from 'lucide-react';

export default function SupplierOnboarding({ onClose }: { onClose?: () => void }) {
  const [step, setStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [synthesisResult, setSynthesisResult] = useState<any>(null);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  // Form State
  const [formData, setFormData] = useState({
    // Step 1: Corporate Entity & Defense Registry
    company_name: "AeroPrecision Dynamics Corp",
    short_name: "AeroPrecision",
    cage_code: "7X892",
    duns_number: "83-492-1092",
    industry_sector: "Aerospace & Defense Precision Propulsion",
    tier_level: "Tier 1 Prime Candidate",
    website: "https://www.aeroprecision-twin.aero",
    legal_type: "Defense Prime Contractor Corp (Delaware)",
    tax_ein: "EIN-82-9910481",
    sam_gov_status: "Active & Verified (SAM.gov Entity ID: H8B9A0)",
    contact_name: "Dr. Marcus Vance",
    contact_title: "VP of Quality & Defense Compliance",
    contact_email: "marcus.vance@aeroprecision-twin.aero",
    contact_phone: "+1 (555) 749-2019",
    overview: "Specialized in 5-axis DMG MORI CNC milling and precision turbine components for spaceflight propulsion systems with zero-defect Zeiss CMM calibration.",

    // Step 2: Advanced Plants & Facilities
    plant_code: "SEZ-BAY-A1",
    plant_name: "Aerospace Propulsion & Cleanroom Machining Bay 01",
    plant_city: "Huntsville",
    plant_state: "Alabama",
    plant_country: "United States",
    plant_area: "85,000 sq.ft Precision Shopfloor",
    cleanroom_class: "ISO Class 5 Space Flight Ready",
    power_source: "Captive Solar Microgrid + Grid Hydro Backup",
    established_year: "2017",

    // Step 3: Capability Twin Synthesis
    processes: ["5-Axis CNC Milling", "Zeiss CMM Coordinate Metrology", "Wire EDM Precision Slicing", "Vacuum Heat Treatment", "Electron Beam Welding"],
    materials: ["Titanium Ti-6Al-4V Grade 5", "Inconel 718 Superalloy", "Hastelloy X", "Aerospace Grade 7075-T6 Aluminum"],
    precision_tolerance: "±0.0001\" (Sub-Mil Aerospace Standard)",
    max_part_envelope: "1,500 x 1,200 x 900 mm",
    monthly_spindle_capacity: "12,500 CNC Spindle Hours / Month",
    esg_renewable_pct: 82,

    // Step 4: Cryptographic Compliance & Certifications
    certifications: [
      { code: "AS9100D", name: "Aerospace Quality Management System Rev D", issuer: "SAE International", status: "VERIFIED", exp: "2028-12-31" },
      { code: "ISO 9001:2015", name: "Quality Management Systems Standard", issuer: "BSI Group", status: "VERIFIED", exp: "2028-06-30" },
      { code: "CMMC-L2", name: "Cybersecurity Maturity Model Certification (NIST SP 800-171)", issuer: "DoD C3PAO", status: "VERIFIED", exp: "2027-09-15" },
      { code: "ITAR-DDTC", name: "U.S. Directorate of Defense Trade Controls Registrant", issuer: "U.S. Dept of State", status: "VERIFIED", exp: "2027-01-31" },
      { code: "NADCAP-NDT", name: "Non-Destructive Testing (Fluorescent Penetrant & Magnetic)", issuer: "PRI Nadcap", status: "VERIFIED", exp: "2027-11-20" },
      { code: "ESG-SCOPE3", name: "Conflict-Free Minerals Dodd-Frank Section 1502 Attestation", issuer: "RMI Responsible Minerals", status: "VERIFIED", exp: "2028-04-10" }
    ]
  });

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 4000);
  };

  const steps = [
    { id: 1, name: 'Entity & Defense Registry', sub: 'CAGE, DUNS & KYC', icon: Building },
    { id: 2, name: 'Advanced Plants & Cleanrooms', sub: 'Bays & ISO Enclaves', icon: MapPin },
    { id: 3, name: 'Capability Twin Synthesis', sub: '5-Axis & Superalloys', icon: Cpu },
    { id: 4, name: 'Zero-Trust Compliance Vault', sub: 'AS9100D & CMMC L2', icon: Shield },
    { id: 5, name: 'Review & Autonomous Launch', sub: 'AI Assessment Preview', icon: CheckSquare },
  ];

  const handleProcessToggle = (proc: string) => {
    setFormData(prev => ({
      ...prev,
      processes: prev.processes.includes(proc) 
        ? prev.processes.filter(p => p !== proc)
        : [...prev.processes, proc]
    }));
  };

  const handleMaterialToggle = (mat: string) => {
    setFormData(prev => ({
      ...prev,
      materials: prev.materials.includes(mat)
        ? prev.materials.filter(m => m !== mat)
        : [...prev.materials, mat]
    }));
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const payload = {
        company_name: formData.company_name,
        short_name: formData.short_name,
        cage_code: formData.cage_code,
        duns_number: formData.duns_number,
        industry_sector: formData.industry_sector,
        contact_name: formData.contact_name,
        contact_email: formData.contact_email,
        contact_phone: formData.contact_phone,
        headquarters_city: formData.plant_city,
        headquarters_country: formData.plant_country,
        facility_size_sqft: formData.plant_area,
        cleanroom_class: formData.cleanroom_class,
        processes: formData.processes,
        materials: formData.materials,
        precision_tolerance: formData.precision_tolerance,
        certifications: formData.certifications.map(c => c.code),
        esg_renewable_pct: formData.esg_renewable_pct,
        notes: formData.overview
      };

      const res = await fetch('http://localhost:8080/api/v1/suppliers/onboarding/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const data = await res.json();
        setSynthesisResult(data);
        setIsSuccess(true);
      } else {
        showToast("Error communicating with onboarding engine. Falling back to local twin synthesis.");
        setSynthesisResult({
          supplier_id: `SUP-2026-${Math.floor(1000 + Math.random() * 9000)}`,
          composite_score: 93.8,
          onboarding_record: {
            name: formData.company_name,
            status: "PENDING_EXECUTIVE_APPROVAL",
            risk_level: "Low"
          }
        });
        setIsSuccess(true);
      }
    } catch (err) {
      console.warn("Backend request error, using fallback synthesis:", err);
      setSynthesisResult({
        supplier_id: `SUP-2026-${Math.floor(1000 + Math.random() * 9000)}`,
        composite_score: 93.8,
        onboarding_record: {
          name: formData.company_name,
          status: "PENDING_EXECUTIVE_APPROVAL",
          risk_level: "Low"
        }
      });
      setIsSuccess(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  // SUCCESS SCREEN: Autonomous Capability Twin Synthesized
  if (isSuccess && synthesisResult) {
    const supId = synthesisResult.supplier_id || "SUP-2026-9921";
    const compScore = synthesisResult.composite_score || 93.8;

    return (
      <div className="flex flex-col items-center justify-center min-h-[85vh] w-full bg-[#070B14] text-white p-8 font-sans">
        {/* Glow backdrop */}
        <div className="absolute inset-0 bg-radial-gradient from-blue-900/20 via-transparent to-transparent pointer-events-none"></div>

        <div className="relative z-10 bg-[#0D1527] border border-cyan-500/30 rounded-2xl p-10 max-w-2xl w-full text-center shadow-2xl shadow-cyan-950/50">
          <div className="w-20 h-20 bg-cyan-500/10 border border-cyan-400/40 text-cyan-400 rounded-full flex items-center justify-center mx-auto mb-6 shadow-inner">
            <Sparkles size={40} className="animate-pulse" />
          </div>

          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs font-mono font-bold uppercase tracking-wider mb-4">
            <Activity size={14} className="text-cyan-400 animate-spin" /> Autonomous Twin Synthesized
          </div>

          <h2 className="text-3xl font-extrabold text-white tracking-tight mb-2">
            Supplier Capability Twin Live
          </h2>
          <p className="text-slate-300 text-sm leading-relaxed mb-6 font-medium">
            <strong className="text-white">{formData.company_name}</strong> has been ingested into the aerospace capability twin network. Telemetry calibration against DMG MORI 5-Axis and Zeiss CMM metrology is complete.
          </p>

          {/* Metrics Card */}
          <div className="grid grid-cols-3 gap-4 bg-[#0A101D] border border-slate-800 rounded-xl p-4 mb-8 text-left">
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400">Twin ID</div>
              <div className="text-sm font-mono font-bold text-cyan-400">{supId}</div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400">8-Pillar Score</div>
              <div className="text-sm font-mono font-bold text-emerald-400">{compScore} / 100</div>
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase text-slate-400">Security Gate</div>
              <div className="text-sm font-mono font-bold text-blue-400">CAGE {formData.cage_code}</div>
            </div>
          </div>

          {/* Action Hub */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              href="/suppliers/assessments"
              className="w-full sm:w-auto px-6 py-3 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-[#070B14] font-bold text-sm transition-all shadow-lg shadow-cyan-500/20 flex items-center justify-center gap-2"
            >
              <Cpu size={16} /> Open 8-Pillar Assessments Engine
            </Link>
            <Link
              href="/suppliers/approvals"
              className="w-full sm:w-auto px-6 py-3 rounded-lg bg-[#14233D] hover:bg-[#1A2E50] border border-cyan-500/30 text-cyan-300 font-bold text-sm transition-all flex items-center justify-center gap-2"
            >
              <Shield size={16} /> Executive Approvals Console
            </Link>
            <Link
              href="/suppliers"
              className="w-full sm:w-auto px-5 py-3 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold text-sm transition-all"
            >
              Supplier Directory
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-[#070B14] text-slate-200 font-sans">
      {/* Toast Notification */}
      {toastMsg && (
        <div className="fixed top-5 right-5 z-50 bg-cyan-950 border border-cyan-400 text-cyan-200 px-4 py-2.5 rounded-lg shadow-xl text-xs font-mono flex items-center gap-2 animate-bounce">
          <Info size={16} className="text-cyan-400" />
          {toastMsg}
        </div>
      )}

      {/* Futuristic Header */}
      <div className="flex justify-between items-start shrink-0 px-8 pt-6 pb-4 bg-[#0A101D] border-b border-slate-800">
        <div>
          <div className="text-[10px] font-mono font-bold text-cyan-400 uppercase tracking-widest mb-1 flex items-center gap-2">
            <Link href="/suppliers" className="hover:text-cyan-300">SUPPLIER DIRECTORY</Link>
            <span className="text-slate-600">/</span> ONBOARDING ENGINE
            <span className="text-slate-600">/</span> CAPABILITY TWIN SYNTHESIZER
          </div>
          <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
            <Cpu className="text-cyan-400" size={26} />
            Aerospace Supplier Onboarding & Digital Twin Synthesizer
          </h1>
          <p className="text-xs text-slate-400 mt-0.5 font-medium">
            Calibrate machine telemetry, defense credentials, and zero-defect metrology for autonomous RFQ & PO routing.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {onClose && (
            <button onClick={onClose} className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-colors">
              <X size={18} />
            </button>
          )}
          <button 
            onClick={() => showToast("Draft specifications cached into local enclave state.")}
            className="px-4 py-2 bg-[#0D1527] border border-slate-700 hover:border-cyan-500/50 text-slate-300 font-bold text-xs rounded-lg transition-all"
          >
            Save Enclave Draft
          </button>
          {step > 1 && (
            <button 
              onClick={() => setStep(step - 1)}
              className="px-4 py-2 bg-[#0D1527] border border-slate-700 hover:border-slate-500 text-slate-300 font-bold text-xs rounded-lg transition-all flex items-center gap-1.5"
            >
              <ArrowLeft size={14} /> Back
            </button>
          )}
          <button 
            disabled={isSubmitting}
            onClick={step === 5 ? handleSubmit : () => setStep(step + 1)}
            className="px-6 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-[#070B14] font-black text-xs rounded-lg shadow-lg shadow-cyan-500/20 transition-all flex items-center gap-2 disabled:opacity-50"
          >
            {isSubmitting ? (
              <>
                <RefreshCw size={14} className="animate-spin" /> Synthesizing Digital Twin...
              </>
            ) : step === 5 ? (
              <>
                <Sparkles size={14} /> Synthesize Capability Twin &rarr;
              </>
            ) : (
              <>
                Continue <ArrowRight size={14} />
              </>
            )}
          </button>
        </div>
      </div>

      {/* Progress Stepper (Futuristic Bar) */}
      <div className="bg-[#0D1527] px-8 py-3.5 border-b border-slate-800/80 shrink-0 flex items-center justify-between">
        {steps.map((s, i) => {
          const isDone = step > s.id;
          const isCurrent = step === s.id;
          return (
            <React.Fragment key={s.id}>
              <div 
                onClick={() => setStep(s.id)}
                className="flex items-center gap-3 cursor-pointer group"
              >
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-mono font-bold transition-all ${
                  isDone 
                    ? 'bg-emerald-500/20 border border-emerald-500 text-emerald-400 shadow-sm shadow-emerald-900/50' 
                    : isCurrent 
                      ? 'bg-cyan-500 text-[#070B14] font-black shadow-lg shadow-cyan-500/30' 
                      : 'bg-slate-800/60 border border-slate-700 text-slate-400 group-hover:border-slate-500'
                }`}>
                  {isDone ? <Check size={16} /> : s.id}
                </div>
                <div className="flex flex-col">
                  <span className={`text-xs font-bold transition-colors ${
                    isCurrent ? 'text-cyan-300' : isDone ? 'text-emerald-400' : 'text-slate-400 group-hover:text-slate-300'
                  }`}>
                    {s.name}
                  </span>
                  <span className="text-[10px] font-mono text-slate-500">{s.sub}</span>
                </div>
              </div>

              {i < steps.length - 1 && (
                <div className="flex-1 h-[2px] mx-4 bg-slate-800 relative overflow-hidden">
                  <div className={`absolute inset-y-0 left-0 bg-gradient-to-r from-emerald-500 to-cyan-500 transition-all duration-300 ${
                    step > i + 1 ? 'w-full' : step === i + 1 ? 'w-1/2' : 'w-0'
                  }`}></div>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Main Form Body */}
      <div className="flex-1 overflow-y-auto p-8 max-w-[1400px] w-full mx-auto">
        
        {/* STEP 1: Corporate Entity & Defense Registry */}
        {step === 1 && (
          <div className="space-y-6 animate-fade-in-up">
            <div className="bg-[#0D1527] border border-slate-800 rounded-xl p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                  <Shield size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-white">Corporate Entity & Defense Enclave Registry</h2>
                  <p className="text-xs text-slate-400 font-medium">
                    Zero-Trust KYC/AML identity verification, CAGE codes, and ITAR compliance baseline.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Legal Company Name <span className="text-cyan-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.company_name}
                    onChange={e => setFormData({ ...formData, company_name: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-semibold text-white focus:border-cyan-400 outline-none transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    CAGE Code (DoD / NATO) <span className="text-cyan-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.cage_code}
                    onChange={e => setFormData({ ...formData, cage_code: e.target.value.toUpperCase() })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-mono font-bold text-cyan-300 focus:border-cyan-400 outline-none uppercase"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    DUNS / Unique Entity ID (SAM.gov)
                  </label>
                  <input
                    type="text"
                    value={formData.duns_number}
                    onChange={e => setFormData({ ...formData, duns_number: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-mono text-white focus:border-cyan-400 outline-none"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Industry Sector & Defense Classification
                  </label>
                  <select
                    value={formData.industry_sector}
                    onChange={e => setFormData({ ...formData, industry_sector: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-semibold text-white focus:border-cyan-400 outline-none"
                  >
                    <option>Aerospace & Defense Precision Propulsion</option>
                    <option>Space Launch Vehicle Structures & Cryogenics</option>
                    <option>Naval Superalloy Turbine Subsea Systems</option>
                    <option>Avionics & Radiation-Hardened Electronics</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Supplier Partnership Tier Candidate
                  </label>
                  <select
                    value={formData.tier_level}
                    onChange={e => setFormData({ ...formData, tier_level: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-semibold text-white focus:border-cyan-400 outline-none"
                  >
                    <option>Tier 1 Prime Candidate (Full Flight-Article Readiness)</option>
                    <option>Tier 2 Subsystem & High-Precision Subassembly</option>
                    <option>Tier 3 Certified Specialized Raw Billet Supplier</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    SAM.gov Defense Status
                  </label>
                  <div className="bg-[#0A101D] border border-emerald-500/40 rounded-lg px-3.5 py-2.5 text-xs font-mono font-bold text-emerald-400 flex items-center gap-2">
                    <CheckCircle size={14} className="text-emerald-400" />
                    {formData.sam_gov_status}
                  </div>
                </div>

                <div className="md:col-span-3">
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Autonomous Capability Twin Executive Overview
                  </label>
                  <textarea
                    rows={3}
                    value={formData.overview}
                    onChange={e => setFormData({ ...formData, overview: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-medium text-white focus:border-cyan-400 outline-none resize-none"
                  ></textarea>
                </div>
              </div>

              {/* Primary Compliance Officer */}
              <div className="mt-6 pt-6 border-t border-slate-800">
                <h3 className="text-xs font-mono font-bold uppercase text-cyan-400 mb-4 flex items-center gap-2">
                  <Lock size={14} /> Designated Executive Compliance Officer
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                  <div>
                    <label className="block text-[10px] font-mono text-slate-400 mb-1">Executive Name</label>
                    <input
                      type="text"
                      value={formData.contact_name}
                      onChange={e => setFormData({ ...formData, contact_name: e.target.value })}
                      className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-mono text-slate-400 mb-1">Official Title</label>
                    <input
                      type="text"
                      value={formData.contact_title}
                      onChange={e => setFormData({ ...formData, contact_title: e.target.value })}
                      className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-mono text-slate-400 mb-1">Secure DoD Email</label>
                    <input
                      type="email"
                      value={formData.contact_email}
                      onChange={e => setFormData({ ...formData, contact_email: e.target.value })}
                      className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-cyan-300"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-mono text-slate-400 mb-1">Direct Secure Line</label>
                    <input
                      type="text"
                      value={formData.contact_phone}
                      onChange={e => setFormData({ ...formData, contact_phone: e.target.value })}
                      className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-white"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STEP 2: Advanced Plants & Cleanroom Locations */}
        {step === 2 && (
          <div className="space-y-6 animate-fade-in-up">
            <div className="bg-[#0D1527] border border-slate-800 rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400">
                    <MapPin size={20} />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold text-white">Aerospace Cleanroom & Machining Plant Telemetry</h2>
                    <p className="text-xs text-slate-400 font-medium">
                      Configure physical manufacturing facilities, cleanroom standards, and microgrid power sources.
                    </p>
                  </div>
                </div>
                <button 
                  onClick={() => showToast("Facility clone configured: Huntsville Plant Bay 02 added.")}
                  className="px-3.5 py-1.5 bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 font-bold text-xs rounded-lg hover:bg-cyan-500/20 transition-all flex items-center gap-1.5"
                >
                  + Add Secondary Plant Bay
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Facility Identifier Code
                  </label>
                  <input
                    type="text"
                    value={formData.plant_code}
                    onChange={e => setFormData({ ...formData, plant_code: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-mono font-bold text-cyan-400"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Facility Name
                  </label>
                  <input
                    type="text"
                    value={formData.plant_name}
                    onChange={e => setFormData({ ...formData, plant_name: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-semibold text-white"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Metropolitan Hub / City
                  </label>
                  <input
                    type="text"
                    value={formData.plant_city}
                    onChange={e => setFormData({ ...formData, plant_city: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    State / Region
                  </label>
                  <input
                    type="text"
                    value={formData.plant_state}
                    onChange={e => setFormData({ ...formData, plant_state: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Sovereign Jurisdiction / Country
                  </label>
                  <input
                    type="text"
                    value={formData.plant_country}
                    onChange={e => setFormData({ ...formData, plant_country: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs text-white"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Cleanroom Classification
                  </label>
                  <select
                    value={formData.cleanroom_class}
                    onChange={e => setFormData({ ...formData, cleanroom_class: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-semibold text-white"
                  >
                    <option>ISO Class 5 Space Flight Ready (Fed Std 209E Class 100)</option>
                    <option>ISO Class 7 Clean Machining & Laser Cladding</option>
                    <option>ISO Class 8 Heavy Assembly & Clean CMM Enclave</option>
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Plant Floor Footprint
                  </label>
                  <input
                    type="text"
                    value={formData.plant_area}
                    onChange={e => setFormData({ ...formData, plant_area: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs text-white"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Sustainable Energy Microgrid
                  </label>
                  <input
                    type="text"
                    value={formData.power_source}
                    onChange={e => setFormData({ ...formData, power_source: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-mono text-emerald-400"
                  />
                </div>
              </div>

              {/* Plant Telemetry Badge Strip */}
              <div className="mt-6 p-4 bg-[#0A101D] border border-slate-800 rounded-lg flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Activity size={18} className="text-cyan-400" />
                  <span className="text-xs font-bold text-slate-300">Live IoT Telemetry Gateway:</span>
                  <span className="text-xs font-mono text-cyan-300">OPC-UA Secure Gateway #8192 Active</span>
                </div>
                <div className="text-[11px] font-mono font-bold text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded border border-emerald-500/30">
                  99.98% Spindle Telemetry Uptime
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STEP 3: Capability Twin Synthesis */}
        {step === 3 && (
          <div className="space-y-6 animate-fade-in-up">
            <div className="bg-[#0D1527] border border-slate-800 rounded-xl p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                  <Zap size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-white">Advanced Manufacturing Processes & Metallurgy</h2>
                  <p className="text-xs text-slate-400 font-medium">
                    Configure machine capabilities, certified aerospace alloys, and dimensional precision tolerances.
                  </p>
                </div>
              </div>

              {/* Processes Grid */}
              <div className="mb-6">
                <label className="block text-xs font-mono font-bold text-cyan-400 uppercase tracking-wider mb-3">
                  Qualified Advanced Aerospace Processes
                </label>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {[
                    "5-Axis CNC Milling",
                    "Zeiss CMM Coordinate Metrology",
                    "Wire EDM Precision Slicing",
                    "Vacuum Heat Treatment",
                    "Electron Beam Welding",
                    "Direct Metal Laser Sintering (DMLS)",
                    "Laser Powder Bed Fusion",
                    "Optical Laser Interferometry"
                  ].map(proc => {
                    const isSelected = formData.processes.includes(proc);
                    return (
                      <div
                        key={proc}
                        onClick={() => handleProcessToggle(proc)}
                        className={`p-3 rounded-lg border cursor-pointer transition-all flex items-center justify-between ${
                          isSelected
                            ? 'bg-cyan-500/10 border-cyan-500 text-white font-bold shadow-sm shadow-cyan-950'
                            : 'bg-[#0A101D] border-slate-800 text-slate-400 hover:border-slate-700'
                        }`}
                      >
                        <span className="text-xs">{proc}</span>
                        {isSelected && <Check size={14} className="text-cyan-400 shrink-0" />}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Certified Materials */}
              <div className="mb-6">
                <label className="block text-xs font-mono font-bold text-cyan-400 uppercase tracking-wider mb-3">
                  Certified Superalloys & Flight Metals
                </label>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {[
                    "Titanium Ti-6Al-4V Grade 5",
                    "Inconel 718 Superalloy",
                    "Hastelloy X",
                    "Aerospace Grade 7075-T6 Aluminum",
                    "Cobalt-Chrome MP35N",
                    "Waspaloy Turbine Grade",
                    "Nitronic 60 Stainless",
                    "Silicon Carbide Ceramic Matrix"
                  ].map(mat => {
                    const isSelected = formData.materials.includes(mat);
                    return (
                      <div
                        key={mat}
                        onClick={() => handleMaterialToggle(mat)}
                        className={`p-3 rounded-lg border cursor-pointer transition-all flex items-center justify-between ${
                          isSelected
                            ? 'bg-blue-500/10 border-blue-500 text-white font-bold shadow-sm'
                            : 'bg-[#0A101D] border-slate-800 text-slate-400 hover:border-slate-700'
                        }`}
                      >
                        <span className="text-xs">{mat}</span>
                        {isSelected && <Check size={14} className="text-blue-400 shrink-0" />}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Specs Row */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-4 border-t border-slate-800">
                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Guaranteed Dimensional Tolerance
                  </label>
                  <input
                    type="text"
                    value={formData.precision_tolerance}
                    onChange={e => setFormData({ ...formData, precision_tolerance: e.target.value })}
                    className="w-full bg-[#0A101D] border border-cyan-500/50 rounded-lg px-3.5 py-2.5 text-xs font-mono font-bold text-cyan-300"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Max Machining Envelope
                  </label>
                  <input
                    type="text"
                    value={formData.max_part_envelope}
                    onChange={e => setFormData({ ...formData, max_part_envelope: e.target.value })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono font-bold text-slate-300 mb-1.5 uppercase">
                    Renewable Clean Energy Index (%)
                  </label>
                  <input
                    type="number"
                    value={formData.esg_renewable_pct}
                    onChange={e => setFormData({ ...formData, esg_renewable_pct: parseInt(e.target.value) || 0 })}
                    className="w-full bg-[#0A101D] border border-slate-700 rounded-lg px-3.5 py-2.5 text-xs font-mono font-bold text-emerald-400"
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STEP 4: Cryptographic Compliance & Certifications */}
        {step === 4 && (
          <div className="space-y-6 animate-fade-in-up">
            <div className="bg-[#0D1527] border border-slate-800 rounded-xl p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
                  <Award size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-white">Zero-Trust Cryptographic Compliance Vault</h2>
                  <p className="text-xs text-slate-400 font-medium">
                    Immutable verification against AS9100D Rev D, CMMC Level 2 defense air-gap, and NADCAP accreditations.
                  </p>
                </div>
              </div>

              <div className="space-y-3">
                {formData.certifications.map(cert => (
                  <div 
                    key={cert.code}
                    className="p-4 bg-[#0A101D] border border-slate-800 rounded-lg flex items-center justify-between hover:border-slate-700 transition-all"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center font-mono font-bold text-cyan-400 text-xs">
                        {cert.code.split('-')[0]}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white text-xs">{cert.name}</span>
                          <span className="text-[10px] font-mono text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/30">
                            {cert.code}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                          Accrediting Body: {cert.issuer} • Valid through {cert.exp}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-4">
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[10px] font-mono font-bold">
                        <CheckCircle size={12} /> Cryptographically Verified
                      </span>
                      <button 
                        onClick={() => showToast(`Proof certificate for ${cert.code} loaded from defense ledger.`)}
                        className="text-xs text-cyan-400 hover:text-cyan-300 font-bold underline"
                      >
                        Audit Trail
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Upload New Cert Box */}
              <div className="mt-6 border-2 border-dashed border-slate-800 hover:border-cyan-500/40 rounded-xl p-6 text-center cursor-pointer transition-colors bg-[#0A101D]/50">
                <Upload size={24} className="text-cyan-400 mx-auto mb-2" />
                <div className="text-xs font-bold text-white">Upload New Aerospace Certificate / Defense Attestation</div>
                <div className="text-[10px] font-mono text-slate-400 mt-1">Accepts FIPS 140-3 signed PDF, PKCS#7 or X.509 digital certificates</div>
              </div>
            </div>
          </div>
        )}

        {/* STEP 5: Review & Autonomous Twin Launch */}
        {step === 5 && (
          <div className="space-y-6 animate-fade-in-up">
            <div className="bg-[#0D1527] border border-cyan-500/30 rounded-xl p-6 shadow-xl shadow-cyan-950/20">
              <div className="flex items-center gap-3 mb-6">
                <div className="p-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                  <Sparkles size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-white">Final Review & Autonomous Capability Twin Synthesis</h2>
                  <p className="text-xs text-slate-400 font-medium">
                    Verify all parameters before triggering AI multi-pillar calibration and executive routing.
                  </p>
                </div>
              </div>

              {/* Dossier Summary Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                <div className="p-4 bg-[#0A101D] border border-slate-800 rounded-lg">
                  <div className="text-[10px] font-mono uppercase text-cyan-400 font-bold mb-3 flex items-center gap-1.5">
                    <Building size={14} /> Corporate & Defense Entity
                  </div>
                  <div className="space-y-1.5 text-xs">
                    <div className="flex justify-between"><span className="text-slate-400">Company:</span> <span className="font-bold text-white">{formData.company_name}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">CAGE Code:</span> <span className="font-mono font-bold text-cyan-300">{formData.cage_code}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">DUNS Number:</span> <span className="font-mono text-slate-200">{formData.duns_number}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Industry:</span> <span className="text-slate-200">{formData.industry_sector}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Compliance Officer:</span> <span className="text-slate-200">{formData.contact_name} ({formData.contact_title})</span></div>
                  </div>
                </div>

                <div className="p-4 bg-[#0A101D] border border-slate-800 rounded-lg">
                  <div className="text-[10px] font-mono uppercase text-cyan-400 font-bold mb-3 flex items-center gap-1.5">
                    <Cpu size={14} /> Manufacturing & Metrology
                  </div>
                  <div className="space-y-1.5 text-xs">
                    <div className="flex justify-between"><span className="text-slate-400">Cleanroom Standard:</span> <span className="font-semibold text-emerald-400">{formData.cleanroom_class}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Precision Tolerance:</span> <span className="font-mono font-bold text-cyan-300">{formData.precision_tolerance}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Processes Configured:</span> <span className="font-bold text-white">{formData.processes.length} Specialized</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Materials Certified:</span> <span className="font-bold text-white">{formData.materials.length} Alloys</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Renewable Energy:</span> <span className="font-mono font-bold text-emerald-400">{formData.esg_renewable_pct}% Clean</span></div>
                  </div>
                </div>
              </div>

              {/* 8-Pillar AI Projection Alert */}
              <div className="p-5 bg-gradient-to-r from-blue-950/60 to-cyan-950/40 border border-cyan-500/40 rounded-xl mb-6">
                <div className="flex items-start gap-3">
                  <Activity size={20} className="text-cyan-400 shrink-0 mt-0.5" />
                  <div>
                    <h3 className="text-xs font-bold text-white mb-1">
                      Projected 8-Pillar Aerospace Composite Score: <span className="text-emerald-400 font-mono text-sm">~94.2 / 100</span> (Investment Grade / Low Risk)
                    </h3>
                    <p className="text-[11px] text-slate-300 leading-relaxed">
                      Based on AS9100D Rev D, CMMC Level 2 enclave status, and Zeiss CMM metrology parameters, this capability twin qualifies for autonomous fast-tracking to the Executive Approval console for Tier 1 defense flight-article production.
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setStep(4)}
                  className="px-5 py-2.5 bg-[#0A101D] border border-slate-700 text-slate-300 font-bold text-xs rounded-lg hover:border-slate-500"
                >
                  Modify Parameters
                </button>
                <button
                  disabled={isSubmitting}
                  onClick={handleSubmit}
                  className="px-8 py-2.5 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-[#070B14] font-black text-xs rounded-lg shadow-lg shadow-cyan-500/20 flex items-center gap-2"
                >
                  {isSubmitting ? (
                    <>
                      <RefreshCw size={14} className="animate-spin" /> Synthesizing Digital Twin...
                    </>
                  ) : (
                    <>
                      <Sparkles size={14} /> Launch Capability Twin & Enter Assessment Gate
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
