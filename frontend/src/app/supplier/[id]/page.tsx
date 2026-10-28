'use client';

import React, { useState, useEffect, use } from 'react';
import Link from 'next/link';
import { 
  ShieldCheck, Award, Factory, CheckCircle2, Copy, Check, 
  ExternalLink, Send, Plus, ArrowRight, Download, Calendar, 
  Layers, Clock, Wrench, BarChart2, Leaf, AlertCircle, FileText, 
  ChevronRight, RefreshCw, Sparkles, Building2, MapPin, Phone, 
  Mail, Flame, Activity, X, QrCode
} from 'lucide-react';
import { RadarChart } from '@/components/ui/RadarChart';

export default function PublicCapabilityTwinPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const id = resolvedParams.id;

  const [loading, setLoading] = useState(true);
  const [twinData, setTwinData] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'OVERVIEW' | 'METROLOGY' | 'CAPACITY' | 'COMPLIANCE' | 'CATALOG'>('OVERVIEW');

  // Interactive Modals State
  const [showRfqModal, setShowRfqModal] = useState(false);
  const [showVerifyModal, setShowVerifyModal] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const [shortlisted, setShortlisted] = useState(false);

  // RFQ Invite Form State
  const [rfqTitle, setRfqTitle] = useState('Precision Actuator Housing Machining Batch');
  const [rfqPartName, setRfqPartName] = useState('Aerospace Housing Al-7075-T6');
  const [rfqQty, setRfqQty] = useState<number>(50);
  const [rfqDate, setRfqDate] = useState('2026-04-15');
  const [rfqBudget, setRfqBudget] = useState<string>('16500');
  const [rfqNotes, setRfqNotes] = useState('Strict sub-micron tolerance required (±0.003 mm). AS9102 FAI report required with delivery.');
  const [isSubmittingRfq, setIsSubmittingRfq] = useState(false);
  const [rfqSuccess, setRfqSuccess] = useState(false);

  // Fetch Public Twin Data
  useEffect(() => {
    const fetchTwin = async () => {
      try {
        setLoading(true);
        const res = await fetch(`http://127.0.0.1:8080/api/v1/suppliers/twin/public/${id}`);
        if (res.ok) {
          const data = await res.json();
          setTwinData(data);
        }
      } catch (err) {
        console.error('Error fetching public twin profile:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchTwin();
  }, [id]);

  // Copy shareable link
  const handleCopyLink = () => {
    if (typeof window !== 'undefined') {
      navigator.clipboard.writeText(window.location.href);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2500);
    }
  };

  // Add to ASL (Approved Supplier List)
  const handleShortlist = async () => {
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/suppliers/twin/shortlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          supplier_id: id,
          buyer_company: 'AlphaHelion Global Aerospace',
          tier_category: 'Strategic Tier-1 Approved Partner'
        })
      });
      if (res.ok) {
        setShortlisted(true);
      }
    } catch (err) {
      console.error('Failed to shortlist:', err);
    }
  };

  // Submit RFQ Invitation
  const handleSubmitRfq = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsSubmittingRfq(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/suppliers/twin/invite-rfq', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          supplier_id: id,
          buyer_name: 'Marcus Vance',
          buyer_company: 'AlphaHelion Global Aerospace',
          buyer_email: 'm.vance@alphahelion.com',
          rfq_title: rfqTitle,
          part_name: rfqPartName,
          target_qty: Number(rfqQty),
          target_delivery_date: rfqDate,
          target_budget_usd: parseFloat(rfqBudget) || 16500,
          notes: rfqNotes
        })
      });
      if (res.ok) {
        setRfqSuccess(true);
        setTimeout(() => {
          setShowRfqModal(false);
          setRfqSuccess(false);
        }, 1800);
      }
    } catch (err) {
      console.error('Failed to submit RFQ:', err);
    } finally {
      setIsSubmittingRfq(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-6 text-center">
        <RefreshCw size={36} className="text-blue-600 animate-spin mb-4" />
        <h3 className="text-lg font-black text-slate-800">Verifying Cryptographic Digital Twin Passport...</h3>
        <p className="text-xs text-slate-500 mt-1 font-mono">Querying W3C DID ledger & SCADA telemetry gateway for {id}</p>
      </div>
    );
  }

  const p = twinData?.profile || {};
  const metrics = twinData?.twin_composite_scores || {};
  const radar = twinData?.radar_capability_dimensions || { dimensions: [], supplier_scores: [], aerospace_industry_average: [] };
  const metrology = twinData?.audited_metrology || {};
  const materials = twinData?.materials_certified || [];
  const machinery = twinData?.machine_capacity_roster || [];
  const capacityForecast = twinData?.capacity_forecast_next_90_days || [];
  const certs = twinData?.certifications_vault || [];
  const catalog = twinData?.products_catalog || [];

  return (
    <div className="min-h-screen bg-slate-100/70 py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-[1600px] mx-auto space-y-6">

        {/* 1. Header Breadcrumbs & Public Share Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-4 px-6 rounded-2xl border border-slate-200/80 shadow-xs">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-500">
            <Link href="/buyer/discovery" className="hover:text-blue-600 transition-colors">Global Network</Link>
            <ChevronRight size={14} />
            <span className="text-slate-400">Verified Capability Twin</span>
            <ChevronRight size={14} />
            <span className="font-bold text-slate-900 font-mono">{id}</span>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={handleCopyLink}
              className="px-3.5 py-1.5 bg-slate-50 hover:bg-slate-100 text-slate-700 border border-slate-200 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all active:scale-95 shadow-xs"
            >
              {linkCopied ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
              <span>{linkCopied ? 'Link Copied!' : 'Share Twin Profile'}</span>
            </button>

            <button
              onClick={() => setShowVerifyModal(true)}
              className="px-3.5 py-1.5 bg-emerald-50 hover:bg-emerald-100 text-emerald-800 border border-emerald-200 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all shadow-xs"
            >
              <ShieldCheck size={14} className="text-emerald-600" />
              <span>Verify Cryptographic Seal</span>
            </button>
          </div>
        </div>

        {/* 2. Hero Credential Showcase Card */}
        <div className="bg-gradient-to-r from-[#0B2550] via-[#0D366B] to-[#124E66] rounded-3xl p-6 md:p-8 text-white shadow-xl relative overflow-hidden border border-blue-900/50">
          <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-400/10 rounded-full blur-3xl pointer-events-none -mr-32 -mt-32"></div>
          <div className="absolute bottom-0 left-1/3 w-80 h-80 bg-teal-500/10 rounded-full blur-2xl pointer-events-none"></div>

          <div className="relative z-10 flex flex-col xl:flex-row xl:items-start justify-between gap-8">
            
            {/* Left: Supplier Info & Verifications */}
            <div className="space-y-4 max-w-3xl">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="px-3 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 rounded-full text-xs font-black flex items-center gap-1.5 backdrop-blur-sm">
                  <ShieldCheck size={14} className="text-emerald-400" />
                  W3C DID Cryptographically Audited
                </span>
                <span className="px-3 py-1 bg-amber-500/20 text-amber-300 border border-amber-400/30 rounded-full text-xs font-black backdrop-blur-sm">
                  ITAR Registered (CAGE: 8X4K1)
                </span>
                <span className="px-3 py-1 bg-blue-500/20 text-blue-200 border border-blue-400/30 rounded-full text-xs font-bold backdrop-blur-sm">
                  DUNS: {p.duns_number}
                </span>
              </div>

              <div>
                <h1 className="text-2xl sm:text-4xl font-black text-white tracking-tight flex items-center gap-3">
                  <span>{p.company_name}</span>
                </h1>
                <p className="text-blue-200/90 text-sm font-semibold mt-1">
                  {p.legal_entity} • {p.tier_rating}
                </p>
              </div>

              <p className="text-blue-100/90 text-xs sm:text-sm leading-relaxed">
                {p.description}
              </p>

              <div className="flex flex-wrap items-center gap-4 text-xs text-blue-200 pt-1">
                <span className="flex items-center gap-1.5"><MapPin size={14} className="text-blue-400" /> {p.facility_location}</span>
                <span>•</span>
                <span className="flex items-center gap-1.5"><Factory size={14} className="text-blue-400" /> {p.facility_size_sqft}</span>
                <span>•</span>
                <span className="flex items-center gap-1.5"><Sparkles size={14} className="text-blue-400" /> {p.cleanroom_spec}</span>
              </div>
            </div>

            {/* Right: Direct Enterprise Action Panel */}
            <div className="bg-white/10 backdrop-blur-md border border-white/20 rounded-2xl p-5 md:p-6 shrink-0 w-full xl:w-96 space-y-4 shadow-lg">
              <div className="flex items-center justify-between border-b border-white/10 pb-3">
                <span className="text-[11px] font-black uppercase tracking-wider text-blue-200">Digital Capability Trust</span>
                <span className="px-2 py-0.5 rounded-full bg-emerald-400/20 text-emerald-300 border border-emerald-400/40 text-[10px] font-black">
                  TOP 2% TIER-1
                </span>
              </div>

              <div className="flex items-baseline justify-between">
                <div>
                  <span className="text-4xl font-black text-white">{metrics.overall_trust_score}</span>
                  <span className="text-xs text-blue-200 font-bold"> / 100</span>
                </div>
                <div className="text-right">
                  <span className="text-xs font-mono font-bold text-emerald-300 block">PPM: {metrics.quality_ppm_defect_rate}</span>
                  <span className="text-[11px] text-blue-200">OTIF: {metrics.otif_delivery_rate_percent}%</span>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="space-y-2.5 pt-2">
                <button
                  onClick={() => setShowRfqModal(true)}
                  className="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white font-extrabold text-xs uppercase tracking-wider rounded-xl shadow-md transition-all flex items-center justify-center gap-2 active:scale-95"
                >
                  <Send size={15} />
                  <span>Invite to Private RFQ</span>
                </button>

                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={handleShortlist}
                    disabled={shortlisted}
                    className={`py-2 px-3 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 transition-all border ${
                      shortlisted
                        ? 'bg-emerald-500/20 text-emerald-300 border-emerald-400/40'
                        : 'bg-white/10 hover:bg-white/20 text-white border-white/20'
                    }`}
                  >
                    {shortlisted ? <Check size={14} /> : <Plus size={14} />}
                    <span>{shortlisted ? 'In Buyer ASL' : '+ Add to ASL'}</span>
                  </button>

                  <button
                    onClick={() => alert(`Exporting verified Capability Passport package (JSON-LD & Cryptographically Signed PDF) for ${p.company_name}...`)}
                    className="py-2 px-3 bg-white/10 hover:bg-white/20 text-white rounded-xl text-xs font-bold border border-white/20 flex items-center justify-center gap-1.5 transition-all"
                  >
                    <Download size={14} />
                    <span>Export Passport</span>
                  </button>
                </div>
              </div>

              <p className="text-[10px] text-blue-200/80 text-center font-mono truncate">
                DID: {twinData?.w3c_did}
              </p>
            </div>

          </div>
        </div>

        {/* 3. Executive KPI Strip */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          
          <div className="bg-white p-4 rounded-2xl border border-slate-200/80 shadow-xs flex flex-col justify-between">
            <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">Trust Score</span>
            <div className="my-1.5">
              <span className="text-2xl font-black text-blue-600">{metrics.overall_trust_score}</span>
              <span className="text-xs font-bold text-slate-500"> /100</span>
            </div>
            <span className="text-[11px] font-bold text-emerald-600 flex items-center gap-1">
              <CheckCircle2 size={11} /> High Confidence
            </span>
          </div>

          <div className="bg-white p-4 rounded-2xl border border-slate-200/80 shadow-xs flex flex-col justify-between">
            <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">Metrology Accuracy</span>
            <div className="my-1.5">
              <span className="text-2xl font-black text-slate-900">{metrics.metrology_accuracy_index}%</span>
            </div>
            <span className="text-[11px] font-semibold text-slate-500">Zeiss CMM Laser</span>
          </div>

          <div className="bg-white p-4 rounded-2xl border border-slate-200/80 shadow-xs flex flex-col justify-between">
            <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">Defect Rejection</span>
            <div className="my-1.5">
              <span className="text-2xl font-black text-emerald-600">{metrics.quality_ppm_defect_rate}</span>
              <span className="text-xs font-bold text-slate-500"> PPM</span>
            </div>
            <span className="text-[11px] font-semibold text-slate-500">&lt; 15 PPM Spec</span>
          </div>

          <div className="bg-white p-4 rounded-2xl border border-slate-200/80 shadow-xs flex flex-col justify-between">
            <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">OTIF On-Time Rate</span>
            <div className="my-1.5">
              <span className="text-2xl font-black text-slate-900">{metrics.otif_delivery_rate_percent}%</span>
            </div>
            <span className="text-[11px] font-bold text-emerald-600">12-Month Audited</span>
          </div>

          <div className="bg-white p-4 rounded-2xl border border-slate-200/80 shadow-xs flex flex-col justify-between">
            <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">IoT SCADA Freshness</span>
            <div className="my-1.5 flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="text-lg font-black text-slate-900">Real-Time</span>
            </div>
            <span className="text-[11px] font-semibold text-slate-500">5s CNC Telemetry</span>
          </div>

          <div className="bg-white p-4 rounded-2xl border border-slate-200/80 shadow-xs flex flex-col justify-between">
            <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">ESG Sustainability</span>
            <div className="my-1.5">
              <span className="text-xs font-black text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-md inline-block">
                Platinum Green
              </span>
            </div>
            <span className="text-[11px] font-bold text-emerald-600">+15% RFQ Advantage</span>
          </div>

        </div>

        {/* 4. Tab Navigation Strip */}
        <div className="flex border-b border-slate-200 gap-2 overflow-x-auto pb-1">
          <button
            onClick={() => setActiveTab('OVERVIEW')}
            className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
              activeTab === 'OVERVIEW'
                ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
            }`}
          >
            <BarChart2 size={16} className={activeTab === 'OVERVIEW' ? 'text-blue-600' : 'text-slate-400'} />
            <span>12-D Capability Radar & Facilities</span>
          </button>

          <button
            onClick={() => setActiveTab('METROLOGY')}
            className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
              activeTab === 'METROLOGY'
                ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
            }`}
          >
            <Wrench size={16} className={activeTab === 'METROLOGY' ? 'text-emerald-600' : 'text-slate-400'} />
            <span>Sub-Micron Metrology & Materials</span>
          </button>

          <button
            onClick={() => setActiveTab('CAPACITY')}
            className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
              activeTab === 'CAPACITY'
                ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
            }`}
          >
            <Clock size={16} className={activeTab === 'CAPACITY' ? 'text-blue-600' : 'text-slate-400'} />
            <span>Live Machine Fleet & 90-Day Capacity ({machinery.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('COMPLIANCE')}
            className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
              activeTab === 'COMPLIANCE'
                ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
            }`}
          >
            <ShieldCheck size={16} className={activeTab === 'COMPLIANCE' ? 'text-indigo-600' : 'text-slate-400'} />
            <span>Certifications & Defense Ready ({certs.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('CATALOG')}
            className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
              activeTab === 'CATALOG'
                ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
            }`}
          >
            <Layers size={16} className={activeTab === 'CATALOG' ? 'text-teal-600' : 'text-slate-400'} />
            <span>Manufactured Parts & Stock ({catalog.length})</span>
          </button>
        </div>

        {/* 5. Tab 1: 12-Dimensional Radar & Facility Overview */}
        {activeTab === 'OVERVIEW' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-in fade-in duration-200">
            
            {/* Left: 12-D Capability Radar (7 Cols) */}
            <div className="lg:col-span-7 bg-white rounded-2xl p-6 border border-slate-200/90 shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
                  <div>
                    <h3 className="text-base font-black text-slate-900">12-Dimensional Capability Radar Benchmark</h3>
                    <p className="text-xs text-slate-500 mt-0.5">Audited capability footprint scored against top-tier global aerospace precision machining standards.</p>
                  </div>
                  <span className="text-xs font-bold text-blue-700 bg-blue-50 border border-blue-200 px-2.5 py-1 rounded-full">
                    AS9100D Audited
                  </span>
                </div>

                <div className="py-2">
                  <RadarChart
                    dimensions={radar.dimensions}
                    data={radar.supplier_scores}
                    benchmark={radar.aerospace_industry_average}
                  />
                </div>
              </div>

              <div className="flex items-center justify-center gap-8 pt-4 border-t border-slate-100 text-xs font-bold">
                <span className="flex items-center gap-2 text-blue-700">
                  <span className="w-3.5 h-3.5 rounded-full bg-blue-600"></span>
                  <span>{p.company_name} (Composite: 94.8)</span>
                </span>
                <span className="flex items-center gap-2 text-slate-500">
                  <span className="w-3.5 h-3.5 rounded-full border border-dashed border-slate-400 bg-slate-200"></span>
                  <span>Aerospace Industry Average (52.6)</span>
                </span>
              </div>
            </div>

            {/* Right: Facility Specs & Key Strengths (5 Cols) */}
            <div className="lg:col-span-5 space-y-6">
              
              <div className="bg-white rounded-2xl p-6 border border-slate-200/90 shadow-xs">
                <h3 className="text-base font-black text-slate-900 mb-4">Plant & Operational Profile</h3>
                
                <div className="space-y-3 text-xs">
                  <div className="flex justify-between py-1.5 border-b border-slate-100">
                    <span className="text-slate-500 font-semibold">Total Facility Footprint:</span>
                    <span className="font-bold text-slate-900">{p.facility_size_sqft}</span>
                  </div>
                  <div className="flex justify-between py-1.5 border-b border-slate-100">
                    <span className="text-slate-500 font-semibold">Cleanroom Standard:</span>
                    <span className="font-bold text-slate-900">{p.cleanroom_spec}</span>
                  </div>
                  <div className="flex justify-between py-1.5 border-b border-slate-100">
                    <span className="text-slate-500 font-semibold">Annual Machining Capacity:</span>
                    <span className="font-bold text-slate-900">{p.annual_machining_capacity_hours?.toLocaleString()} Machine Hours</span>
                  </div>
                  <div className="flex justify-between py-1.5 border-b border-slate-100">
                    <span className="text-slate-500 font-semibold">Active Technical Workforce:</span>
                    <span className="font-bold text-slate-900">{p.employees_count} Precision Machinists & CMM Engineers</span>
                  </div>
                  <div className="flex justify-between py-1.5 border-b border-slate-100">
                    <span className="text-slate-500 font-semibold">ITAR Export Control:</span>
                    <span className="font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">{p.itar_registration}</span>
                  </div>
                  <div className="flex justify-between py-1.5">
                    <span className="text-slate-500 font-semibold">Commercial Contact:</span>
                    <span className="font-bold text-blue-600">{p.contact_email}</span>
                  </div>
                </div>
              </div>

              {/* Verified Strengths Card */}
              <div className="bg-emerald-50/70 border border-emerald-200 rounded-2xl p-5">
                <h4 className="text-xs font-black uppercase tracking-wider text-emerald-900 mb-3 flex items-center gap-1.5">
                  <Award size={16} className="text-emerald-600" />
                  <span>Audited Enterprise Competitive Advantages</span>
                </h4>
                <ul className="space-y-2 text-xs text-emerald-950 font-medium">
                  <li className="flex items-start gap-2">
                    <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
                    <span><strong>Sub-Micron Milling:</strong> Simultaneous 5-axis geometric milling on DMG Mori DMU 65 down to ±0.003 mm.</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
                    <span><strong>Exotic Alloy Capability:</strong> Certified machining of Inconel 718, Titanium Ti-6Al-4V, and high-strength 7075-T651.</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
                    <span><strong>Zeiss Metrology Lab:</strong> 100% First Article Inspection (AS9102 FAI) reports digitally signed and sealed.</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
                    <span><strong>Preferred Green Supplier:</strong> -18.4% YoY carbon intensity reduction, 68% solar power mix, and full EU CBAM readiness.</span>
                  </li>
                </ul>
              </div>

            </div>

          </div>
        )}

        {/* 6. Tab 2: Sub-Micron Metrology & Materials */}
        {activeTab === 'METROLOGY' && (
          <div className="space-y-6 animate-in fade-in duration-200">
            
            {/* Metrology Standards Banner */}
            <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between pb-4 border-b border-slate-100 mb-6">
                <div>
                  <h3 className="text-base font-black text-slate-900">Certified Coordinate Metrology & Tolerancing Standards</h3>
                  <p className="text-xs text-slate-500 mt-0.5">High-precision metrology lab audited under ISO 10360-2 and NIST calibration standards.</p>
                </div>
                <span className="text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full">
                  Zeiss Contura Active Scanning
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/80">
                  <span className="text-[10px] font-black uppercase text-slate-400 block mb-1">Linear Machining Tolerance</span>
                  <span className="text-2xl font-black text-slate-900">{metrology.certified_tolerance}</span>
                  <p className="text-[11px] text-slate-500 mt-2">Validated with optical laser probes and coordinate scanning heads.</p>
                </div>

                <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/80">
                  <span className="text-[10px] font-black uppercase text-slate-400 block mb-1">Surface Roughness</span>
                  <span className="text-2xl font-black text-slate-900">{metrology.certified_surface_roughness}</span>
                  <p className="text-[11px] text-slate-500 mt-2">Ultra-fine diamond micro-turning and electropolishing capability.</p>
                </div>

                <div className="bg-slate-50 p-4 rounded-xl border border-slate-200/80">
                  <span className="text-[10px] font-black uppercase text-slate-400 block mb-1">AS9102 First Article Inspection</span>
                  <span className="text-2xl font-black text-emerald-600">100% Sealed</span>
                  <p className="text-[11px] text-slate-500 mt-2">Full ballooned drawings, raw material certs, and CMM reports included.</p>
                </div>
              </div>
            </div>

            {/* Certified Materials Matrix */}
            <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
              <div className="p-5 border-b border-slate-100 flex items-center justify-between">
                <div>
                  <h3 className="text-base font-black text-slate-900">Certified Aerospace & Defense Raw Materials Matrix</h3>
                  <p className="text-xs text-slate-500 mt-0.5">Approved mill sources with full chemical & mechanical heat-lot traceability.</p>
                </div>
                <span className="text-xs font-bold text-slate-500 bg-slate-100 px-3 py-1 rounded-full">
                  100% Traceable Mill Certs
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500 font-bold uppercase tracking-wider border-b border-slate-200">
                    <tr>
                      <th className="py-3.5 px-6">Alloy Grade</th>
                      <th className="py-3.5 px-6">Aerospace Specification (AMS/ASTM)</th>
                      <th className="py-3.5 px-6">Mission-Critical Applications</th>
                      <th className="py-3.5 px-6 text-right">Audit Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-slate-700">
                    {materials.map((m: any, idx: number) => (
                      <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                        <td className="py-3.5 px-6 font-bold text-slate-900 flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                          {m.alloy}
                        </td>
                        <td className="py-3.5 px-6 font-mono font-bold text-slate-800">{m.spec}</td>
                        <td className="py-3.5 px-6 text-slate-600 font-medium">{m.applications}</td>
                        <td className="py-3.5 px-6 text-right">
                          <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 border border-emerald-200 font-bold rounded-md text-[11px]">
                            Certified Production
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        )}

        {/* 7. Tab 3: Live Machine Fleet & 90-Day Available Capacity */}
        {activeTab === 'CAPACITY' && (
          <div className="space-y-6 animate-in fade-in duration-200">
            
            {/* Equipment Roster Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {machinery.map((m: any) => (
                <div key={m.machine_id} className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-shadow flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-black uppercase tracking-wider font-mono text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                        {m.machine_id}
                      </span>
                      <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                        {m.status}
                      </span>
                    </div>

                    <h4 className="text-base font-black text-slate-900 leading-snug">{m.name}</h4>
                    <p className="text-xs text-slate-500 font-medium mt-0.5 mb-3">{m.type}</p>

                    <div className="space-y-2 bg-slate-50 p-3 rounded-xl border border-slate-100 text-xs">
                      <div className="flex justify-between">
                        <span className="text-slate-500">Tolerance:</span>
                        <span className="font-mono font-bold text-slate-800">{m.tolerance}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500">Envelope:</span>
                        <span className="font-bold text-slate-800 truncate max-w-[180px]">{m.work_envelope}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500">Rapid Lead Time:</span>
                        <span className="font-bold text-emerald-700">{m.lead_time_days} Days</span>
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 pt-3 border-t border-slate-100">
                    <div className="flex justify-between text-xs font-semibold mb-1">
                      <span className="text-slate-500">Fleet Load: {m.load_current_pct}%</span>
                      <span className="text-emerald-600 font-bold">{m.available_capacity_pct}% Available</span>
                    </div>
                    <div className="w-full bg-slate-100 rounded-full h-2">
                      <div className="bg-blue-600 h-2 rounded-full" style={{ width: `${m.load_current_pct}%` }}></div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* 90-Day Available Capacity Forecast Table */}
            <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
              <div className="p-5 border-b border-slate-100 flex items-center justify-between">
                <div>
                  <h3 className="text-base font-black text-slate-900">Forward Machine Capacity Availability (Next 90 Days)</h3>
                  <p className="text-xs text-slate-500 mt-0.5">Live shop-floor ERP dispatch forecast enabling buyers to book guaranteed manufacturing slots.</p>
                </div>
                <span className="text-xs font-bold text-blue-700 bg-blue-50 px-3 py-1 rounded-full border border-blue-200">
                  Live Dispatch Stream
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500 font-bold uppercase tracking-wider border-b border-slate-200">
                    <tr>
                      <th className="py-3.5 px-6">Planning Window</th>
                      <th className="py-3.5 px-6">Total Facility Hours</th>
                      <th className="py-3.5 px-6">Committed Production</th>
                      <th className="py-3.5 px-6">Available Open Capacity</th>
                      <th className="py-3.5 px-6 text-right">Availability Ratio</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-slate-700">
                    {capacityForecast.map((c: any, idx: number) => (
                      <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                        <td className="py-3.5 px-6 font-bold text-slate-900 flex items-center gap-2">
                          <Calendar size={14} className="text-blue-600" />
                          {c.period}
                        </td>
                        <td className="py-3.5 px-6 font-mono">{c.total_plant_hours.toLocaleString()} hrs</td>
                        <td className="py-3.5 px-6 font-mono text-slate-500">{c.committed_hours.toLocaleString()} hrs</td>
                        <td className="py-3.5 px-6 font-mono font-bold text-emerald-700">
                          {c.available_hours.toLocaleString()} hrs open
                        </td>
                        <td className="py-3.5 px-6 text-right">
                          <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 border border-emerald-200 font-black rounded-md text-[11px]">
                            {c.availability_pct}% Open
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        )}

        {/* 8. Tab 4: Quality & Defense Regulatory Vault */}
        {activeTab === 'COMPLIANCE' && (
          <div className="space-y-6 animate-in fade-in duration-200">
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {certs.map((c: any, idx: number) => (
                <div key={idx} className="bg-white rounded-2xl p-6 border border-slate-200/90 shadow-xs flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-[10px] font-black uppercase tracking-wider text-emerald-800 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-lg">
                        {c.code}
                      </span>
                      <span className="text-[11px] font-bold text-emerald-600 flex items-center gap-1">
                        <CheckCircle2 size={12} /> Active & Verified
                      </span>
                    </div>

                    <h4 className="text-base font-black text-slate-900 leading-snug mb-2">{c.title}</h4>
                    <p className="text-xs text-slate-500 mb-4">Auditing Authority: <strong>{c.body}</strong></p>
                  </div>

                  <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs">
                    <span className="text-slate-500 font-semibold">Valid Through: <strong>{c.valid_until}</strong></span>
                    <button 
                      onClick={() => alert(`Viewing audited certificate for ${c.title}`)}
                      className="text-blue-600 hover:text-blue-800 font-bold flex items-center gap-1"
                    >
                      <span>View Credential</span>
                      <ExternalLink size={12} />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* ESG Green Supplier Strip */}
            <div className="bg-gradient-to-r from-emerald-900 via-teal-900 to-[#0B2550] text-white rounded-2xl p-6 shadow-md flex flex-col sm:flex-row items-center justify-between gap-6">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-emerald-500/20 border border-emerald-400/40 flex items-center justify-center text-emerald-300 shrink-0">
                  <Leaf size={24} />
                </div>
                <div>
                  <h4 className="text-base font-black text-white">Preferred Green Supplier Status</h4>
                  <p className="text-xs text-emerald-200/90 mt-0.5">
                    Meets ISO 14064 GHG protocol with -18.4% YoY carbon reduction. Automatically qualifies enterprise buyers for +15% RFQ evaluation score advantage.
                  </p>
                </div>
              </div>
              <Link
                href="/supplier/esg-reporting"
                className="px-4 py-2 bg-emerald-400 hover:bg-emerald-300 text-slate-950 font-bold text-xs rounded-xl shadow transition-all shrink-0"
              >
                Inspect ESG Telemetry Hub →
              </Link>
            </div>

          </div>
        )}

        {/* 9. Tab 5: Manufactured Parts & Live Inventory */}
        {activeTab === 'CATALOG' && (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden animate-in fade-in duration-200">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h3 className="text-base font-black text-slate-900">Synchronized Finished Goods & Manufactured Catalog</h3>
                <p className="text-xs text-slate-500 mt-0.5">Shop-floor certified production line items with real-time on-hand finished goods availability.</p>
              </div>
              <span className="text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full">
                Live Inventory Connected
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-500 font-bold uppercase tracking-wider border-b border-slate-200">
                  <tr>
                    <th className="py-3.5 px-6">Part Number</th>
                    <th className="py-3.5 px-6">Component Specification</th>
                    <th className="py-3.5 px-6">Material Alloy</th>
                    <th className="py-3.5 px-6">Unit Price (USD)</th>
                    <th className="py-3.5 px-6">MOQ / Lead Time</th>
                    <th className="py-3.5 px-6">Stock On-Hand</th>
                    <th className="py-3.5 px-6 text-right">Procure Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {catalog.map((prod: any) => (
                    <tr key={prod.id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3.5 px-6 font-mono font-bold text-slate-900">{prod.partNumber}</td>
                      <td className="py-3.5 px-6">
                        <span className="font-bold text-slate-800 block">{prod.name}</span>
                        <span className="text-[11px] text-slate-500">{prod.category}</span>
                      </td>
                      <td className="py-3.5 px-6 font-semibold text-slate-600">{prod.material}</td>
                      <td className="py-3.5 px-6 font-mono font-bold text-slate-900">${prod.unitPriceUsd}</td>
                      <td className="py-3.5 px-6 text-slate-600">
                        {prod.moq} pcs • {prod.leadTimeDays}d
                      </td>
                      <td className="py-3.5 px-6">
                        <span className="px-2.5 py-1 bg-emerald-50 text-emerald-700 border border-emerald-200 font-bold rounded-md font-mono">
                          {prod.stockAvailable} units
                        </span>
                      </td>
                      <td className="py-3.5 px-6 text-right">
                        <button
                          onClick={() => {
                            setRfqPartName(prod.name);
                            setRfqTitle(`Procurement of ${prod.name} (${prod.partNumber})`);
                            setRfqQty(prod.moq || 25);
                            setShowRfqModal(true);
                          }}
                          className="px-3 py-1.5 bg-[#0B2550] hover:bg-blue-900 text-white font-bold rounded-lg text-[11px] transition-all"
                        >
                          Request Quote
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

      </div>

      {/* 10. Invite to Private RFQ Modal */}
      {showRfqModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in">
          <div className="bg-white rounded-3xl max-w-lg w-full p-6 md:p-8 shadow-2xl border border-slate-200 relative">
            <button 
              onClick={() => setShowRfqModal(false)}
              className="absolute top-5 right-5 text-slate-400 hover:text-slate-600"
            >
              <X size={20} />
            </button>

            <h3 className="text-xl font-black text-slate-900 mb-1 flex items-center gap-2">
              <Send className="text-blue-600" size={22} />
              <span>Invite Supplier to Private RFQ</span>
            </h3>
            <p className="text-xs text-slate-500 mb-5">
              Send a direct procurement RFQ invitation to <strong>{p.company_name}</strong>. The supplier will be notified in real time.
            </p>

            <form onSubmit={handleSubmitRfq} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">RFQ Solicitation Title</label>
                <input
                  type="text"
                  required
                  value={rfqTitle}
                  onChange={(e) => setRfqTitle(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Target Component / Part Name</label>
                <input
                  type="text"
                  required
                  value={rfqPartName}
                  onChange={(e) => setRfqPartName(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Target Batch Qty</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={rfqQty}
                    onChange={(e) => setRfqQty(parseInt(e.target.value) || 1)}
                    className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Target Delivery Date</label>
                  <input
                    type="date"
                    required
                    value={rfqDate}
                    onChange={(e) => setRfqDate(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Target Budget Cap (USD)</label>
                <input
                  type="number"
                  value={rfqBudget}
                  onChange={(e) => setRfqBudget(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Engineering Notes & Tolerances</label>
                <textarea
                  rows={3}
                  value={rfqNotes}
                  onChange={(e) => setRfqNotes(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                ></textarea>
              </div>

              {rfqSuccess && (
                <div className="p-3 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-xl text-xs font-bold flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-emerald-600" />
                  <span>RFQ Invitation dispatched! Supplier capability twin has received the notification.</span>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowRfqModal(false)}
                  className="px-4 py-2 border border-slate-300 text-slate-600 rounded-xl text-xs font-bold hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingRfq}
                  className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold shadow-md transition-all flex items-center gap-1.5"
                >
                  {isSubmittingRfq ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
                  <span>Transmit RFQ Invitation</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 11. Cryptographic Seal Verification Modal */}
      {showVerifyModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in">
          <div className="bg-white rounded-3xl max-w-md w-full p-6 md:p-8 shadow-2xl border border-slate-200 relative">
            <button 
              onClick={() => setShowVerifyModal(false)}
              className="absolute top-5 right-5 text-slate-400 hover:text-slate-600"
            >
              <X size={20} />
            </button>

            <div className="w-12 h-12 rounded-2xl bg-emerald-100 flex items-center justify-center text-emerald-600 mb-4">
              <ShieldCheck size={28} />
            </div>

            <h3 className="text-lg font-black text-slate-900 mb-1">Cryptographic Digital Twin Seal</h3>
            <p className="text-xs text-slate-500 mb-5">
              Decentralized capability verification hash issued according to W3C Verifiable Credential specifications.
            </p>

            <div className="space-y-3 bg-slate-50 p-4 rounded-2xl border border-slate-200/80 text-xs font-mono">
              <div>
                <span className="text-[10px] text-slate-400 font-sans uppercase font-bold block">W3C Decentralized ID (DID)</span>
                <span className="text-blue-700 font-bold break-all">{twinData?.w3c_did}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-sans uppercase font-bold block">Ledger Verification Hash</span>
                <span className="text-slate-700 break-all">{twinData?.verification_hash}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-sans uppercase font-bold block">Audit Verification Status</span>
                <span className="text-emerald-700 font-bold font-sans flex items-center gap-1 mt-0.5">
                  <CheckCircle2 size={13} /> {twinData?.cryptographic_status}
                </span>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setShowVerifyModal(false)}
                className="px-5 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-bold"
              >
                Close Verification
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
