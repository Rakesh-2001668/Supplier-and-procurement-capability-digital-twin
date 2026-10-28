'use client';

import React, { useState, useEffect } from 'react';
import { 
  Leaf, Award, UploadCloud, CheckCircle2, TrendingDown, 
  ShieldCheck, AlertCircle, FileText, Download, RefreshCw, 
  Sun, Zap, Factory, Truck, Layers, Filter, Plus, ChevronRight,
  ExternalLink, BarChart3, Calculator, Check, ArrowUpRight, Flame
} from 'lucide-react';
import { 
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, LineChart, Line, 
  XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, PieChart, Pie, Cell 
} from 'recharts';

export default function SupplierESG() {
  const [activeTab, setActiveTab] = useState<'overview' | 'calculator' | 'certificates' | 'batches'>('overview');
  const [loading, setLoading] = useState(true);
  const [overviewData, setOverviewData] = useState<any>(null);
  const [certificates, setCertificates] = useState<any[]>([]);
  const [batchAudits, setBatchAudits] = useState<any[]>([]);

  // Batch Calculator State
  const [calcMaterial, setCalcMaterial] = useState('aluminum_7075');
  const [calcQuantity, setCalcQuantity] = useState<number>(50);
  const [calcBilletWeight, setCalcBilletWeight] = useState<number>(4.2);
  const [calcMachinedWeight, setCalcMachinedWeight] = useState<number>(1.45);
  const [calcProcess, setCalcProcess] = useState('5_axis_cnc');
  const [calcHours, setCalcHours] = useState<number>(2.5);
  const [calcRecycling, setCalcRecycling] = useState<number>(85);
  const [calcDistance, setCalcDistance] = useState<number>(850);
  const [calcTransport, setCalcTransport] = useState('road_freight');
  const [calcSolarMix, setCalcSolarMix] = useState<number>(68);

  // Live Calculation Result
  const [calcResult, setCalcResult] = useState<any>(null);
  const [isCalculating, setIsCalculating] = useState(false);
  const [passportCopied, setPassportCopied] = useState(false);

  // Upload Modal State
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [newCertTitle, setNewCertTitle] = useState('');
  const [newCertIssuer, setNewCertIssuer] = useState('');
  const [newCertCategory, setNewCertCategory] = useState('Environmental Management');
  const [newCertExpiry, setNewCertExpiry] = useState('2027-12-31');
  const [newCertScope, setNewCertScope] = useState('');
  const [isSubmittingCert, setIsSubmittingCert] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);

  // Fetch ESG Data
  const fetchData = async () => {
    try {
      setLoading(true);
      const [resOverview, resCerts, resAudits] = await Promise.all([
        fetch('http://127.0.0.1:8080/api/v1/esg/overview'),
        fetch('http://127.0.0.1:8080/api/v1/esg/certificates'),
        fetch('http://127.0.0.1:8080/api/v1/esg/batch-audits')
      ]);

      if (resOverview.ok) {
        const data = await resOverview.json();
        setOverviewData(data);
      }
      if (resCerts.ok) {
        const certData = await resCerts.json();
        setCertificates(certData.certificates || []);
      }
      if (resAudits.ok) {
        const auditData = await resAudits.json();
        setBatchAudits(auditData.audits || []);
      }
    } catch (err) {
      console.error('Failed to load ESG hub data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Run Calculator
  const handleCalculate = async () => {
    try {
      setIsCalculating(true);
      const payload = {
        material: calcMaterial,
        quantity_units: Number(calcQuantity),
        billet_weight_kg: Number(calcBilletWeight),
        machined_weight_kg: Number(calcMachinedWeight),
        manufacturing_process: calcProcess,
        machining_hours_per_unit: Number(calcHours),
        scrap_recycled_percent: Number(calcRecycling),
        delivery_distance_km: Number(calcDistance),
        transport_mode: calcTransport,
        clean_solar_power_percent: Number(calcSolarMix)
      };

      const res = await fetch('http://127.0.0.1:8080/api/v1/esg/calculate-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const data = await res.json();
        setCalcResult(data);
      }
    } catch (err) {
      console.error('Calculation failed:', err);
    } finally {
      setIsCalculating(false);
    }
  };

  // Initial calculation on mount
  useEffect(() => {
    handleCalculate();
  }, [calcMaterial, calcQuantity, calcBilletWeight, calcMachinedWeight, calcProcess, calcHours, calcRecycling, calcDistance, calcTransport, calcSolarMix]);

  // Handle Certificate Upload
  const handleUploadCert = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCertTitle || !newCertIssuer) return;

    try {
      setIsSubmittingCert(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/esg/certificates/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: newCertTitle,
          issuer: newCertIssuer,
          category: newCertCategory,
          issue_date: new Date().toISOString().slice(0, 10),
          expiry_date: newCertExpiry,
          scope: newCertScope || 'Precision aerospace manufacturing & circular scrap recycling'
        })
      });

      if (res.ok) {
        setUploadSuccess(true);
        setTimeout(() => {
          setShowUploadModal(false);
          setUploadSuccess(false);
          setNewCertTitle('');
          setNewCertIssuer('');
          setNewCertScope('');
          fetchData();
        }, 1200);
      }
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      setIsSubmittingCert(false);
    }
  };

  const copyPassportId = (id: string) => {
    navigator.clipboard.writeText(id);
    setPassportCopied(true);
    setTimeout(() => setPassportCopied(false), 2000);
  };

  const scopePieData = overviewData ? [
    { name: 'Scope 1 (Direct)', value: overviewData.scopes_breakdown.scope1.emissions_mt, color: '#f59e0b' },
    { name: 'Scope 2 (Electricity)', value: overviewData.scopes_breakdown.scope2.emissions_mt, color: '#3b82f6' },
    { name: 'Scope 3 (Supply Chain)', value: overviewData.scopes_breakdown.scope3.emissions_mt, color: '#10b981' }
  ] : [];

  return (
    <div className="p-6 md:p-8 space-y-8 max-w-[1600px] mx-auto min-h-screen bg-slate-50/50">
      
      {/* 1. Header Banner & Preferred Green Supplier Credential */}
      <div className="bg-gradient-to-r from-[#0B2550] via-[#0D366B] to-[#0A4D54] rounded-3xl p-6 md:p-8 text-white shadow-xl relative overflow-hidden">
        <div className="absolute right-0 top-0 w-96 h-96 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        <div className="absolute left-1/2 bottom-0 w-80 h-80 bg-blue-500/10 rounded-full blur-2xl pointer-events-none"></div>

        <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="px-3 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 rounded-full text-xs font-bold flex items-center gap-1.5 backdrop-blur-sm">
                <Leaf size={14} className="text-emerald-400 animate-pulse" />
                ISO 14064-1 & EU CBAM Verified
              </span>
              <span className="px-3 py-1 bg-blue-500/20 text-blue-200 border border-blue-400/30 rounded-full text-xs font-bold backdrop-blur-sm">
                Tenant: Apex Precision Tooling
              </span>
            </div>

            <h1 className="text-2xl md:text-4xl font-black tracking-tight text-white flex items-center gap-3">
              <span>Carbon Footprint & Scope 1–3 ESG Hub</span>
            </h1>

            <p className="text-blue-100/90 text-sm md:text-base max-w-2xl leading-relaxed">
              Live corporate greenhouse gas (GHG) telemetry, closed-loop alloy circularity credits, 
              and automated batch Product Carbon Footprint (PCF) certification for aerospace & defense enterprise compliance.
            </p>
          </div>

          {/* Platinum Green Advantage Card */}
          <div className="bg-white/10 backdrop-blur-md border border-white/20 rounded-2xl p-5 shrink-0 max-w-sm flex items-center gap-4 shadow-lg">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center text-slate-900 shadow-md shrink-0">
              <Award size={30} className="text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-extrabold text-white text-sm">Preferred Green Supplier</h3>
                <span className="bg-emerald-400/30 text-emerald-300 text-[10px] font-black px-1.5 py-0.5 rounded">ACTIVE</span>
              </div>
              <p className="text-xs text-emerald-200 mt-1">
                <span className="font-bold text-white text-sm">+15% Score Boost</span> in automated buyer RFQ bid evaluations due to verified emission reductions.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Executive KPI Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
        
        {/* KPI 1: Total Corporate Carbon */}
        <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">
            <span>Corporate Emissions YTD</span>
            <span className="p-2 bg-amber-50 rounded-xl text-amber-600"><Flame size={18} /></span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black text-slate-900">
              {overviewData ? overviewData.kpis.total_emissions_mt : '235.2'}
            </span>
            <span className="text-xs font-bold text-slate-500">MT CO₂e</span>
          </div>
          <div className="mt-3">
            <div className="flex justify-between text-[11px] font-semibold text-slate-600 mb-1">
              <span>Budget: 280 MT</span>
              <span className="text-emerald-600 font-bold">84% Utilized (16% buffer)</span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-2">
              <div className="bg-emerald-500 h-2 rounded-full" style={{ width: '84%' }}></div>
            </div>
          </div>
        </div>

        {/* KPI 2: YoY Carbon Reduction */}
        <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">
            <span>YoY Carbon Reduction</span>
            <span className="p-2 bg-emerald-50 rounded-xl text-emerald-600"><TrendingDown size={18} /></span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black text-emerald-600">
              {overviewData ? overviewData.kpis.yoy_reduction_percent : '-18.4'}%
            </span>
            <span className="text-xs font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full">Exceeding -12% Target</span>
          </div>
          <p className="text-xs text-slate-500 mt-3 flex items-center gap-1">
            <CheckCircle2 size={13} className="text-emerald-500" />
            Driven by solar rooftop integration & swarf recovery
          </p>
        </div>

        {/* KPI 3: Clean Energy Mix */}
        <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">
            <span>Renewable Energy Mix</span>
            <span className="p-2 bg-blue-50 rounded-xl text-blue-600"><Sun size={18} /></span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black text-blue-600">
              {overviewData ? overviewData.kpis.renewable_energy_mix_percent : '68.0'}%
            </span>
            <span className="text-xs font-bold text-slate-500">of Plant Power</span>
          </div>
          <div className="mt-3">
            <div className="flex justify-between text-[11px] font-semibold text-slate-600 mb-1">
              <span>Solar On-Site Generation</span>
              <span className="text-blue-600 font-bold">412,500 kWh YTD</span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-2">
              <div className="bg-blue-600 h-2 rounded-full" style={{ width: '68%' }}></div>
            </div>
          </div>
        </div>

        {/* KPI 4: Circular Swarf Alloy Recycled */}
        <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">
            <span>Closed-Loop Swarf Recycled</span>
            <span className="p-2 bg-teal-50 rounded-xl text-teal-600"><Layers size={18} /></span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black text-teal-700">
              {overviewData ? overviewData.kpis.recycled_swarf_alloy_mt : '48.6'}
            </span>
            <span className="text-xs font-bold text-slate-500">Metric Tonnes</span>
          </div>
          <p className="text-xs text-slate-500 mt-3 flex items-center gap-1">
            <span className="font-bold text-teal-600">85% Smelter Offset</span>
            <span>credited to manufactured batches</span>
          </p>
        </div>
      </div>

      {/* 3. Navigation Tabs */}
      <div className="flex border-b border-slate-200 gap-2 overflow-x-auto pb-1">
        <button
          onClick={() => setActiveTab('overview')}
          className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
            activeTab === 'overview'
              ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
          }`}
        >
          <BarChart3 size={16} className={activeTab === 'overview' ? 'text-blue-600' : 'text-slate-400'} />
          <span>Scope 1, 2 & 3 Telemetry</span>
        </button>

        <button
          onClick={() => setActiveTab('calculator')}
          className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
            activeTab === 'calculator'
              ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
          }`}
        >
          <Calculator size={16} className={activeTab === 'calculator' ? 'text-emerald-600' : 'text-slate-400'} />
          <span>Batch Carbon & CBAM Calculator</span>
        </button>

        <button
          onClick={() => setActiveTab('certificates')}
          className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
            activeTab === 'certificates'
              ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
          }`}
        >
          <ShieldCheck size={16} className={activeTab === 'certificates' ? 'text-indigo-600' : 'text-slate-400'} />
          <span>ESG Certificate Vault ({certificates.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('batches')}
          className={`flex items-center gap-2 px-5 py-3 font-bold text-sm rounded-t-xl transition-all whitespace-nowrap ${
            activeTab === 'batches'
              ? 'bg-white border-x border-t border-slate-200 text-[#0B2550] shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/60'
          }`}
        >
          <FileText size={16} className={activeTab === 'batches' ? 'text-teal-600' : 'text-slate-400'} />
          <span>Product Carbon Passports ({batchAudits.length})</span>
        </button>
      </div>

      {/* 4. Tab 1: Scope 1, 2 & 3 Telemetry */}
      {activeTab === 'overview' && overviewData && (
        <div className="space-y-8 animate-in fade-in duration-200">
          
          {/* Scope 1, 2, 3 Breakdown Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            
            {/* Scope 1 */}
            <div className="bg-white rounded-2xl p-6 border border-slate-200/90 shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-black uppercase tracking-wider text-amber-700 bg-amber-50 px-2.5 py-1 rounded-lg border border-amber-200">
                    Scope 1 • Direct
                  </span>
                  <span className="text-xs font-bold text-slate-400">
                    {overviewData.scopes_breakdown.scope1.share_percent}% of Total
                  </span>
                </div>
                <div className="flex items-baseline gap-2 mb-2">
                  <span className="text-3xl font-black text-slate-900">
                    {overviewData.scopes_breakdown.scope1.emissions_mt}
                  </span>
                  <span className="text-xs font-bold text-slate-500">MT CO₂e</span>
                </div>
                <p className="text-xs text-slate-500 mb-4">Direct plant natural gas heating, backup diesel generators, and fleet vehicles.</p>

                <div className="space-y-2 border-t border-slate-100 pt-3">
                  {overviewData.scopes_breakdown.scope1.sources.map((s: any, idx: number) => (
                    <div key={idx} className="flex justify-between items-center text-xs">
                      <span className="text-slate-600 font-medium">{s.name}</span>
                      <span className="font-bold text-slate-900">{s.value_mt} MT</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-5 pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-emerald-700 font-bold">
                <span>Natural Gas Heat Recirculation</span>
                <span>Active 94%</span>
              </div>
            </div>

            {/* Scope 2 */}
            <div className="bg-white rounded-2xl p-6 border border-slate-200/90 shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-black uppercase tracking-wider text-blue-700 bg-blue-50 px-2.5 py-1 rounded-lg border border-blue-200">
                    Scope 2 • Purchased Power
                  </span>
                  <span className="text-xs font-bold text-slate-400">
                    {overviewData.scopes_breakdown.scope2.share_percent}% of Total
                  </span>
                </div>
                <div className="flex items-baseline gap-2 mb-2">
                  <span className="text-3xl font-black text-blue-600">
                    {overviewData.scopes_breakdown.scope2.emissions_mt}
                  </span>
                  <span className="text-xs font-bold text-slate-500">MT CO₂e (Net)</span>
                </div>
                <p className="text-xs text-slate-500 mb-4">
                  Gross: <span className="font-bold">{overviewData.scopes_breakdown.scope2.gross_grid_emissions_mt} MT</span> minus <span className="font-bold text-emerald-600">{Math.abs(overviewData.scopes_breakdown.scope2.solar_rooftop_offset_mt)} MT Solar Offset</span>.
                </p>

                <div className="space-y-2 border-t border-slate-100 pt-3">
                  {overviewData.scopes_breakdown.scope2.sources.map((s: any, idx: number) => (
                    <div key={idx} className="flex justify-between items-center text-xs">
                      <span className="text-slate-600 font-medium">{s.name}</span>
                      <span className="font-bold text-slate-900">{s.value_mt} MT</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-5 pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-blue-700 font-bold">
                <span>Rooftop Solar Array PPA</span>
                <span>68% Renewable Mix</span>
              </div>
            </div>

            {/* Scope 3 */}
            <div className="bg-white rounded-2xl p-6 border border-slate-200/90 shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-black uppercase tracking-wider text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-lg border border-emerald-200">
                    Scope 3 • Supply Chain
                  </span>
                  <span className="text-xs font-bold text-slate-400">
                    {overviewData.scopes_breakdown.scope3.share_percent}% of Total
                  </span>
                </div>
                <div className="flex items-baseline gap-2 mb-2">
                  <span className="text-3xl font-black text-emerald-700">
                    {overviewData.scopes_breakdown.scope3.emissions_mt}
                  </span>
                  <span className="text-xs font-bold text-slate-500">MT CO₂e</span>
                </div>
                <p className="text-xs text-slate-500 mb-4">Upstream raw alloy billet smelter emissions & outbound customer freight delivery.</p>

                <div className="space-y-2 border-t border-slate-100 pt-3">
                  {overviewData.scopes_breakdown.scope3.sources.map((s: any, idx: number) => (
                    <div key={idx} className="flex justify-between items-center text-xs">
                      <span className="text-slate-600 font-medium truncate pr-2">{s.name}</span>
                      <span className="font-bold text-slate-900 shrink-0">{s.value_mt} MT</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-5 pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-teal-700 font-bold">
                <span>EU CBAM Readiness</span>
                <span>Audit Verified</span>
              </div>
            </div>
          </div>

          {/* 12-Month Emissions Trend Chart */}
          <div className="bg-white rounded-2xl p-6 border border-slate-200 shadow-xs">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-100 mb-6 gap-3">
              <div>
                <h3 className="text-base font-extrabold text-slate-900">12-Month Corporate Emissions & Solar Offset Trajectory</h3>
                <p className="text-xs text-slate-500 mt-0.5">Tracking Scope 1, 2, and 3 monthly output alongside clean solar rooftop displacement.</p>
              </div>
              <div className="flex items-center gap-3 text-xs font-bold">
                <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#f59e0b]"></span> Scope 1</span>
                <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#3b82f6]"></span> Scope 2</span>
                <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#10b981]"></span> Scope 3</span>
                <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#14b8a6]"></span> Solar Offset</span>
              </div>
            </div>

            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={overviewData.monthly_trend} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="scope1Grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.8}/>
                      <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.1}/>
                    </linearGradient>
                    <linearGradient id="scope2Grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8}/>
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.1}/>
                    </linearGradient>
                    <linearGradient id="scope3Grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.8}/>
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.1}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis dataKey="month" stroke="#94a3b8" fontSize={11} tickLine={false} />
                  <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} tickFormatter={(v) => `${v} MT`} />
                  <RechartsTooltip 
                    formatter={(val: any) => [`${val} MT CO₂e`, 'Emissions']}
                    contentStyle={{ backgroundColor: '#0B2550', borderColor: '#1e3a8a', borderRadius: '12px', color: '#fff' }}
                  />
                  <Area type="monotone" dataKey="scope3" stackId="1" stroke="#10b981" fill="url(#scope3Grad)" name="Scope 3" />
                  <Area type="monotone" dataKey="scope2" stackId="1" stroke="#3b82f6" fill="url(#scope2Grad)" name="Scope 2" />
                  <Area type="monotone" dataKey="scope1" stackId="1" stroke="#f59e0b" fill="url(#scope1Grad)" name="Scope 1" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Aerospace Material Emission Intensity Table */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h3 className="text-base font-extrabold text-slate-900">Aerospace Raw Alloy Carbon Intensity Index</h3>
                <p className="text-xs text-slate-500 mt-0.5">Embodied cradle-to-gate carbon emission factors utilized in our ISO 14067 batch carbon accounting.</p>
              </div>
              <span className="text-xs font-bold text-slate-500 bg-slate-100 px-3 py-1 rounded-full">
                Database: Ecoinvent 3.9 & EU CBAM Directives
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50/80 text-slate-500 font-bold uppercase tracking-wider border-b border-slate-200">
                  <tr>
                    <th className="py-3.5 px-6">Raw Material Specification</th>
                    <th className="py-3.5 px-6">Emissions Factor (kg CO₂e / kg alloy)</th>
                    <th className="py-3.5 px-6">Primary Aerospace Application</th>
                    <th className="py-3.5 px-6 text-right">Circularity Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {overviewData.material_carbon_intensity_index.map((mat: any, idx: number) => (
                    <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3.5 px-6 font-bold text-slate-900 flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                        {mat.material}
                      </td>
                      <td className="py-3.5 px-6 font-mono font-bold text-slate-800">
                        {mat.emission_factor_kg_per_kg} kg CO₂e
                      </td>
                      <td className="py-3.5 px-6 text-slate-600 font-medium">{mat.primary_use}</td>
                      <td className="py-3.5 px-6 text-right">
                        {mat.material.includes('Recycled') ? (
                          <span className="px-2.5 py-1 bg-emerald-100 text-emerald-800 font-extrabold rounded-md text-[11px]">
                            84% Smelter Carbon Saved
                          </span>
                        ) : (
                          <span className="px-2.5 py-1 bg-slate-100 text-slate-600 font-semibold rounded-md text-[11px]">
                            Traceable Smelter
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      )}

      {/* 5. Tab 2: Batch Carbon & CBAM Calculator Workstation */}
      {activeTab === 'calculator' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 animate-in fade-in duration-200">
          
          {/* Inputs Panel (Left 7 Cols) */}
          <div className="lg:col-span-7 bg-white rounded-2xl p-6 md:p-8 border border-slate-200 shadow-xs space-y-6">
            <div className="border-b border-slate-100 pb-4 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-black text-slate-900 flex items-center gap-2">
                  <Calculator size={20} className="text-emerald-600" />
                  <span>Production Batch Product Carbon Footprint (PCF) Calculator</span>
                </h3>
                <p className="text-xs text-slate-500 mt-1">Configure batch bill-of-materials and manufacturing telemetry to calculate cradle-to-gate kg CO₂e.</p>
              </div>
              <button 
                onClick={handleCalculate}
                disabled={isCalculating}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-sm active:scale-95 transition-all"
              >
                <RefreshCw size={14} className={isCalculating ? 'animate-spin' : ''} />
                <span>Recalculate</span>
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              
              {/* Alloy Material */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">Alloy Material Grade</label>
                <select
                  value={calcMaterial}
                  onChange={(e) => setCalcMaterial(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-bold text-slate-900 focus:ring-2 focus:ring-emerald-500 outline-none"
                >
                  <option value="aluminum_7075">Aluminum 7075-T6 (Aerospace Grade)</option>
                  <option value="aluminum_6061">Aluminum 6061-T6 (General Precision)</option>
                  <option value="titanium_ti6al4v">Titanium Ti-6Al-4V Grade 5</option>
                  <option value="stainless_316l">Stainless Steel 316L (Marine/Medical)</option>
                  <option value="inconel_718">Inconel 718 Superalloy (High Temp)</option>
                  <option value="carbon_fiber">Carbon Fiber Pre-preg Composite</option>
                </select>
              </div>

              {/* Batch Quantity */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">Batch Order Quantity (Units)</label>
                <input
                  type="number"
                  min="1"
                  value={calcQuantity}
                  onChange={(e) => setCalcQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-bold text-slate-900 focus:ring-2 focus:ring-emerald-500 outline-none"
                />
              </div>

              {/* Raw Billet Weight */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">Raw Billet Mass per Unit (kg)</label>
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  value={calcBilletWeight}
                  onChange={(e) => setCalcBilletWeight(parseFloat(e.target.value) || 0.1)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-bold text-slate-900 focus:ring-2 focus:ring-emerald-500 outline-none"
                />
              </div>

              {/* Final Machined Weight */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">Finished Component Mass (kg)</label>
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  value={calcMachinedWeight}
                  onChange={(e) => setCalcMachinedWeight(parseFloat(e.target.value) || 0.1)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-bold text-slate-900 focus:ring-2 focus:ring-emerald-500 outline-none"
                />
              </div>

              {/* Manufacturing Process */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">Machining Workcenter</label>
                <select
                  value={calcProcess}
                  onChange={(e) => setCalcProcess(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-bold text-slate-900 focus:ring-2 focus:ring-emerald-500 outline-none"
                >
                  <option value="5_axis_cnc">DMG Mori DMU 65 (5-Axis CNC Mill)</option>
                  <option value="wire_edm">GF Machining AgieCharmilles (Wire EDM)</option>
                  <option value="laser_additive_slm">Laser Powder Bed Fusion (SLM Additive)</option>
                  <option value="turning">Mazak Quick Turn 250 (Turn-Mill)</option>
                </select>
              </div>

              {/* Spindle Machining Hours */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">Spindle Cutting Time per Part (Hours)</label>
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  value={calcHours}
                  onChange={(e) => setCalcHours(parseFloat(e.target.value) || 0.1)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-bold text-slate-900 focus:ring-2 focus:ring-emerald-500 outline-none"
                />
              </div>

              {/* Transport Mode */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">Outbound Logistics Carrier</label>
                <select
                  value={calcTransport}
                  onChange={(e) => setCalcTransport(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-bold text-slate-900 focus:ring-2 focus:ring-emerald-500 outline-none"
                >
                  <option value="road_freight">Road Freight (Dedicated EV/Euro-6 Truck)</option>
                  <option value="rail_intermodal">Rail Intermodal (Low-Carbon)</option>
                  <option value="air_cargo">Air Cargo Express (Priority Flight)</option>
                  <option value="sea_freight">Ocean Container Carrier</option>
                </select>
              </div>

              {/* Delivery Distance */}
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">Customer Delivery Distance (km)</label>
                <input
                  type="number"
                  min="0"
                  value={calcDistance}
                  onChange={(e) => setCalcDistance(parseInt(e.target.value) || 0)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-bold text-slate-900 focus:ring-2 focus:ring-emerald-500 outline-none"
                />
              </div>

            </div>

            {/* Circularity & Green Energy Sliders */}
            <div className="bg-slate-50 p-5 rounded-2xl border border-slate-200/80 space-y-5">
              
              {/* Closed Loop Recycling Slider */}
              <div>
                <div className="flex justify-between items-center text-xs font-bold mb-1.5">
                  <span className="text-slate-800 flex items-center gap-1.5">
                    <Layers size={14} className="text-teal-600" />
                    Closed-Loop Swarf Recycling Credit:
                  </span>
                  <span className="text-teal-700 font-mono text-sm">{calcRecycling}% Recycled</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={calcRecycling}
                  onChange={(e) => setCalcRecycling(parseInt(e.target.value))}
                  className="w-full accent-teal-600 cursor-pointer"
                />
                <p className="text-[11px] text-slate-500 mt-1">High-vacuum briquetted alloy swarf returned directly to smelting partners, avoiding 85% of primary mining footprint.</p>
              </div>

              {/* Solar Renewable Mix Slider */}
              <div>
                <div className="flex justify-between items-center text-xs font-bold mb-1.5">
                  <span className="text-slate-800 flex items-center gap-1.5">
                    <Sun size={14} className="text-amber-500" />
                    Rooftop Solar & Green Power Grid Mix:
                  </span>
                  <span className="text-amber-600 font-mono text-sm">{calcSolarMix}% Clean Power</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={calcSolarMix}
                  onChange={(e) => setCalcSolarMix(parseInt(e.target.value))}
                  className="w-full accent-amber-500 cursor-pointer"
                />
                <p className="text-[11px] text-slate-500 mt-1">Apex Tooling on-site 850 kWp solar PV array offsets CNC spindle electrical power demand.</p>
              </div>

            </div>

          </div>

          {/* Results Certificate Workstation (Right 5 Cols) */}
          <div className="lg:col-span-5 space-y-6">
            
            {calcResult ? (
              <div className="bg-gradient-to-br from-slate-900 via-[#0B2550] to-slate-900 text-white rounded-3xl p-6 md:p-8 shadow-xl border border-slate-700/60 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-64 h-64 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none"></div>

                <div className="flex items-center justify-between border-b border-white/10 pb-4 mb-6">
                  <div>
                    <span className="text-[10px] font-black uppercase tracking-widest text-emerald-400 bg-emerald-500/20 px-2 py-0.5 rounded">
                      DIGITAL CARBON PASSPORT
                    </span>
                    <h4 className="text-xl font-black text-white mt-1">Verified Batch PCF</h4>
                  </div>
                  <div className="text-right">
                    <span className="text-xs font-mono text-slate-300 block">{calcResult.passport_id}</span>
                    <button
                      onClick={() => copyPassportId(calcResult.passport_id)}
                      className="text-[10px] text-emerald-300 hover:text-white font-bold inline-flex items-center gap-1 mt-0.5"
                    >
                      {passportCopied ? <Check size={10} /> : null}
                      {passportCopied ? 'Copied!' : 'Copy Hash'}
                    </button>
                  </div>
                </div>

                {/* Big Emissions Metric */}
                <div className="bg-white/5 border border-white/10 rounded-2xl p-5 mb-6 text-center">
                  <span className="text-xs font-bold text-slate-300 uppercase tracking-wider block mb-1">Total Batch Footprint</span>
                  <div className="flex items-baseline justify-center gap-2">
                    <span className="text-4xl md:text-5xl font-black text-emerald-400">
                      {calcResult.summary.total_batch_co2e_kg}
                    </span>
                    <span className="text-sm font-bold text-slate-300">kg CO₂e</span>
                  </div>
                  <div className="mt-2 text-xs font-semibold text-slate-300">
                    <span className="text-white font-bold">{calcResult.summary.per_unit_co2e_kg} kg CO₂e</span> per finished unit
                  </div>

                  {/* Benchmark comparison pill */}
                  <div className="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 text-xs font-bold">
                    <TrendingDown size={14} />
                    <span>{calcResult.summary.carbon_savings_percent}% vs Industry Standard Baseline</span>
                  </div>
                </div>

                {/* Breakdown by Scope */}
                <div className="space-y-3 mb-6">
                  <h5 className="text-xs font-extrabold uppercase tracking-wider text-slate-400">Cradle-to-Gate Scope Segments</h5>
                  
                  <div className="space-y-2 text-xs">
                    <div>
                      <div className="flex justify-between font-semibold mb-1">
                        <span className="text-slate-300">Scope 1 (Direct Fuel & Heat)</span>
                        <span className="font-mono text-white font-bold">{calcResult.scopes.scope1_direct_fuel_kg} kg</span>
                      </div>
                      <div className="w-full bg-white/10 rounded-full h-1.5">
                        <div className="bg-amber-400 h-1.5 rounded-full" style={{ width: '12%' }}></div>
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between font-semibold mb-1">
                        <span className="text-slate-300">Scope 2 (CNC Electrical Spindle)</span>
                        <span className="font-mono text-white font-bold">{calcResult.scopes.scope2_electricity_kg} kg</span>
                      </div>
                      <div className="w-full bg-white/10 rounded-full h-1.5">
                        <div className="bg-blue-400 h-1.5 rounded-full" style={{ width: '28%' }}></div>
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between font-semibold mb-1">
                        <span className="text-slate-300">Scope 3 (Net Embodied Alloy & Logistics)</span>
                        <span className="font-mono text-white font-bold">{calcResult.scopes.scope3_upstream_and_freight_kg} kg</span>
                      </div>
                      <div className="w-full bg-white/10 rounded-full h-1.5">
                        <div className="bg-emerald-400 h-1.5 rounded-full" style={{ width: '60%' }}></div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* CBAM EU Customs Compliance Box */}
                <div className="bg-blue-500/10 border border-blue-400/20 rounded-xl p-4 mb-6">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-black text-blue-300 uppercase">EU CBAM Regulation 2023/956</span>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-500/30 text-blue-200">READY</span>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    Estimated EU ETS Tariff Liability Avoided: <span className="font-black text-white">€{calcResult.summary.cbam_tariff_savings_eur}</span> via direct certified low-carbon manufacturing.
                  </p>
                </div>

                {/* Action button */}
                <button
                  onClick={() => alert(`CBAM Carbon Passport ${calcResult.passport_id} generated and permanently cryptographically registered for this PO batch.`)}
                  className="w-full py-3 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-black text-xs uppercase tracking-wider rounded-xl shadow-lg transition-all flex items-center justify-center gap-2 active:scale-95"
                >
                  <Download size={16} />
                  <span>Issue & Sign Carbon Passport Certificate</span>
                </button>
              </div>
            ) : (
              <div className="p-8 text-center text-slate-400 bg-white rounded-2xl border border-slate-200">
                <RefreshCw size={24} className="animate-spin mx-auto mb-2 text-slate-400" />
                <span>Computing batch telemetry...</span>
              </div>
            )}

          </div>

        </div>
      )}

      {/* 6. Tab 3: Auditable ESG Certificate Vault */}
      {activeTab === 'certificates' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-5 rounded-2xl border border-slate-200 shadow-xs">
            <div>
              <h3 className="text-base font-extrabold text-slate-900">Environmental & Regulatory Audit Vault</h3>
              <p className="text-xs text-slate-500 mt-0.5">Audited credentials guaranteeing zero greenwashing for defense & aerospace Tier-1 supply chains.</p>
            </div>
            <button
              onClick={() => setShowUploadModal(true)}
              className="px-4 py-2.5 bg-[#0B2550] hover:bg-blue-900 text-white rounded-xl text-xs font-bold flex items-center gap-2 shadow-sm transition-all"
            >
              <Plus size={16} />
              <span>Register New Audit Certificate</span>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {certificates.map((cert) => (
              <div key={cert.id} className="bg-white rounded-2xl p-6 border border-slate-200/90 shadow-xs hover:shadow-md transition-shadow flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-[10px] font-black uppercase tracking-wider text-emerald-800 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-lg">
                      {cert.category}
                    </span>
                    <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">
                      <CheckCircle2 size={12} /> Verified
                    </span>
                  </div>

                  <h4 className="text-base font-black text-slate-900 leading-snug mb-2">{cert.title}</h4>
                  
                  <p className="text-xs text-slate-600 font-medium mb-4">{cert.scope}</p>

                  <div className="space-y-2 bg-slate-50 p-3.5 rounded-xl border border-slate-200/60 text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500 font-semibold">Issuing Body:</span>
                      <span className="font-bold text-slate-800">{cert.issuer}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500 font-semibold">Valid Period:</span>
                      <span className="font-bold text-slate-800">{cert.issue_date} to {cert.expiry_date}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500 font-semibold">Ledger Hash:</span>
                      <span className="font-mono text-[10px] text-slate-600 truncate max-w-[180px]">{cert.verification_hash}</span>
                    </div>
                  </div>
                </div>

                <div className="mt-5 pt-4 border-t border-slate-100 flex items-center justify-between text-xs">
                  <span className="text-slate-400 font-mono text-[11px]">{cert.id}</span>
                  <button 
                    onClick={() => alert(`Opening official certified audit statement for ${cert.title}`)}
                    className="text-blue-600 hover:text-blue-800 font-bold flex items-center gap-1"
                  >
                    <span>View Official PDF</span>
                    <ExternalLink size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>

        </div>
      )}

      {/* 7. Tab 4: Production Batch Audits Ledger */}
      {activeTab === 'batches' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          
          <div className="bg-white rounded-2xl border border-slate-200 shadow-xs overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-extrabold text-slate-900">Historical Batch Carbon Passports Ledger</h3>
                <p className="text-xs text-slate-500 mt-0.5">Auditable record of all completed production POs with calculated product carbon footprints (PCF).</p>
              </div>
              <span className="text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-full">
                Avg Carbon Reduction: -26.9% vs Baseline
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50/80 text-slate-500 font-bold uppercase tracking-wider border-b border-slate-200">
                  <tr>
                    <th className="py-3.5 px-6">Batch & PO Number</th>
                    <th className="py-3.5 px-6">Component Part</th>
                    <th className="py-3.5 px-6">Alloy Spec</th>
                    <th className="py-3.5 px-6">Quantity</th>
                    <th className="py-3.5 px-6">Total Batch Footprint</th>
                    <th className="py-3.5 px-6">Per-Unit CO₂e</th>
                    <th className="py-3.5 px-6">Carbon Savings</th>
                    <th className="py-3.5 px-6 text-right">Digital Passport</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {batchAudits.map((batch: any) => (
                    <tr key={batch.batch_id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3.5 px-6">
                        <span className="font-bold text-slate-900 block">{batch.po_id}</span>
                        <span className="text-[10px] text-slate-400 font-mono">{batch.batch_id}</span>
                      </td>
                      <td className="py-3.5 px-6 font-semibold text-slate-800">{batch.part_name}</td>
                      <td className="py-3.5 px-6 text-slate-600 font-medium">{batch.material}</td>
                      <td className="py-3.5 px-6 font-bold">{batch.quantity_units} pcs</td>
                      <td className="py-3.5 px-6 font-mono font-bold text-slate-900">{batch.total_emissions_kg} kg</td>
                      <td className="py-3.5 px-6 font-mono text-emerald-700 font-bold">{batch.per_unit_emissions_kg} kg/pc</td>
                      <td className="py-3.5 px-6">
                        <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-black text-[11px]">
                          {batch.carbon_savings_percent}%
                        </span>
                      </td>
                      <td className="py-3.5 px-6 text-right">
                        <button
                          onClick={() => alert(`Product Carbon Passport verified: ${batch.passport_hash}\nEligible for EU CBAM tariff relief.`)}
                          className="px-2.5 py-1 bg-slate-100 hover:bg-slate-200 text-slate-800 rounded-lg font-bold text-[11px] inline-flex items-center gap-1 transition-all"
                        >
                          <ShieldCheck size={12} className="text-emerald-600" />
                          <span>{batch.passport_hash}</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      )}

      {/* 8. Register New Certificate Modal */}
      {showUploadModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in">
          <div className="bg-white rounded-3xl max-w-lg w-full p-6 md:p-8 shadow-2xl border border-slate-200 relative">
            <h3 className="text-xl font-black text-slate-900 mb-1 flex items-center gap-2">
              <ShieldCheck className="text-emerald-600" size={24} />
              <span>Register Audit Certificate</span>
            </h3>
            <p className="text-xs text-slate-500 mb-5">Upload an audited environmental statement or ISO standard certification to the cryptographic vault.</p>

            <form onSubmit={handleUploadCert} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Certificate Title</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. ISO 50001 Energy Management Standard"
                  value={newCertTitle}
                  onChange={(e) => setNewCertTitle(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Issuing Body</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. DNV GL / TÜV SÜD"
                    value={newCertIssuer}
                    onChange={(e) => setNewCertIssuer(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Expiry Date</label>
                  <input
                    type="date"
                    required
                    value={newCertExpiry}
                    onChange={(e) => setNewCertExpiry(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Category</label>
                <select
                  value={newCertCategory}
                  onChange={(e) => setNewCertCategory(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-emerald-500"
                >
                  <option value="Environmental Management">Environmental Management (ISO 14001)</option>
                  <option value="Carbon Accounting">Carbon Accounting (ISO 14064 / GHG)</option>
                  <option value="Energy Management">Energy Efficiency (ISO 50001)</option>
                  <option value="Regulatory Trade">Trade / CBAM Declaration</option>
                  <option value="Hazardous Substances">RoHS 3 / REACH SVHC</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Scope Description</label>
                <textarea
                  rows={2}
                  placeholder="Scope of manufacturing operations and certified plant facilities..."
                  value={newCertScope}
                  onChange={(e) => setNewCertScope(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-emerald-500"
                ></textarea>
              </div>

              {uploadSuccess && (
                <div className="p-3 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-xl text-xs font-bold flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-emerald-600" />
                  <span>Certificate registered in vault with cryptographic ledger verification!</span>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowUploadModal(false)}
                  className="px-4 py-2 border border-slate-300 text-slate-600 rounded-xl text-xs font-bold hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingCert}
                  className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold shadow-md transition-all flex items-center gap-1.5"
                >
                  {isSubmittingCert ? <RefreshCw size={14} className="animate-spin" /> : <UploadCloud size={14} />}
                  <span>Save Certificate</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
