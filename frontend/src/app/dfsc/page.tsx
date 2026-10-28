'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Sparkles, UploadCloud, RefreshCw, CheckCircle2, AlertTriangle, 
  ArrowRight, Check, X, Download, Sliders, Box, Cpu, Eye, 
  FileText, Send, ChevronRight, Info, ShieldAlert, Award, 
  Compass, Layers, RotateCw, ZoomIn, ZoomOut, CheckCheck, TrendingDown,
  Building2, MapPin, DollarSign, Clock, Flame
} from 'lucide-react';

export default function GenerativeDFSCPage() {
  const [loading, setLoading] = useState(true);
  const [cadModels, setCadModels] = useState<any[]>([]);
  const [selectedCadId, setSelectedCadId] = useState('CAD-ACT-7075');
  const [modelData, setModelData] = useState<any>(null);
  const [unlockedSuppliers, setUnlockedSuppliers] = useState<any[]>([]);
  const [isApplyingRedesign, setIsApplyingRedesign] = useState<string | null>(null);

  // Viewport states
  const [viewportMode, setViewportMode] = useState<'CROSS_SECTION' | 'WIREFRAME' | 'SHADED'>('CROSS_SECTION');
  const [showDimensions, setShowDimensions] = useState(true);
  const [zoomLevel, setZoomLevel] = useState(1);

  // Modals
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportPackage, setExportPackage] = useState<any>(null);
  const [isExporting, setIsExporting] = useState(false);

  // Upload Form
  const [uploadFileName, setUploadFileName] = useState('');
  const [uploadMaterial, setUploadMaterial] = useState('Aluminum 7075-T6');
  const [uploadCategory, setUploadCategory] = useState('Structural Precision Enclosure');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);

  // Success Notification banner
  const [actionNotification, setActionNotification] = useState<string | null>(null);

  const showNotification = (msg: string) => {
    setActionNotification(msg);
    setTimeout(() => setActionNotification(null), 4000);
  };

  // 1. Fetch available CAD models
  const fetchCadModels = async () => {
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/dfsc/models');
      if (res.ok) {
        const data = await res.json();
        setCadModels(data.models || []);
      }
    } catch (err) {
      console.error('Failed to load CAD models:', err);
    }
  };

  // 2. Fetch selected CAD model details & unlocked suppliers
  const fetchModelDetails = async (cadId: string) => {
    try {
      setLoading(true);
      const [resModel, resSuppliers] = await Promise.all([
        fetch(`http://127.0.0.1:8080/api/v1/dfsc/model/${cadId}`),
        fetch(`http://127.0.0.1:8080/api/v1/dfsc/unlocked-suppliers/${cadId}`)
      ]);

      if (resModel.ok) {
        const data = await resModel.json();
        setModelData(data);
      }
      if (resSuppliers.ok) {
        const supData = await resSuppliers.json();
        setUnlockedSuppliers(supData.suppliers || []);
      }
    } catch (err) {
      console.error('Failed to fetch CAD model analysis:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCadModels();
  }, []);

  useEffect(() => {
    if (selectedCadId) {
      fetchModelDetails(selectedCadId);
    }
  }, [selectedCadId]);

  // Toggle/Apply Generative Redesign
  const handleToggleRedesign = async (constraintId: string, currentStatus: boolean) => {
    try {
      setIsApplyingRedesign(constraintId);
      const res = await fetch('http://127.0.0.1:8080/api/v1/dfsc/apply-redesign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cad_id: selectedCadId,
          constraint_id: constraintId,
          apply: !currentStatus
        })
      });

      if (res.ok) {
        const updated = await res.json();
        setModelData(updated);

        // Refresh unlocked suppliers
        const supRes = await fetch(`http://127.0.0.1:8080/api/v1/dfsc/unlocked-suppliers/${selectedCadId}`);
        if (supRes.ok) {
          const supData = await supRes.json();
          setUnlockedSuppliers(supData.suppliers || []);
        }

        if (!currentStatus) {
          showNotification(`✨ Generative constraint ${constraintId} optimized! Supply base elasticity recalculated.`);
        } else {
          showNotification(`Reverted ${constraintId} back to original drawing specification.`);
        }
      }
    } catch (err) {
      console.error('Failed to apply redesign:', err);
    } finally {
      setIsApplyingRedesign(null);
    }
  };

  // Run full DFM geometric analysis
  const handleRunFullDfm = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/dfsc/analyze-dfm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cad_id: selectedCadId })
      });
      if (res.ok) {
        await fetchModelDetails(selectedCadId);
        showNotification('✅ Full 3D geometric constraint graph matched against 1,280+ digital twins.');
      }
    } catch (err) {
      console.error('DFM analysis error:', err);
    } finally {
      setLoading(false);
    }
  };

  // Export revised STEP package
  const handleExportStep = async () => {
    try {
      setIsExporting(true);
      const res = await fetch(`http://127.0.0.1:8080/api/v1/dfsc/export-revised-step/${selectedCadId}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setExportPackage(data);
        setShowExportModal(true);
      }
    } catch (err) {
      console.error('Export error:', err);
    } finally {
      setIsExporting(false);
    }
  };

  // Upload CAD Model
  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsUploading(true);
      const formData = new FormData();
      formData.append('material', uploadMaterial);
      formData.append('category', uploadCategory);

      // Create a dummy blob representing the STEP file
      const blob = new Blob(['ISO-10303-21; HEADER; FILE_DESCRIPTION(("AP242 STEP"), "2;1");'], { type: 'application/step' });
      formData.append('file', blob, uploadFileName || 'aerospace_custom_part.step');

      const res = await fetch('http://127.0.0.1:8080/api/v1/dfsc/upload-step', {
        method: 'POST',
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        setUploadSuccess(true);
        setTimeout(() => {
          setShowUploadModal(false);
          setUploadSuccess(false);
          setUploadFileName('');
          fetchCadModels();
          setSelectedCadId(data.model.id);
        }, 1200);
      }
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      setIsUploading(false);
    }
  };

  const model = modelData?.model;
  const kpis = modelData?.active_kpis;
  const constraints = model?.dfm_constraints || [];
  const appliedCount = modelData?.applied_redesigns_count || 0;
  const isAnyConstraintApplied = appliedCount > 0;

  // Primary constraint status (DFM-01) for visual animation
  const isR2Resolved = constraints.find((c: any) => c.id === 'DFM-01')?.is_applied;
  const isTolResolved = constraints.find((c: any) => c.id === 'DFM-02')?.is_applied;
  const isWallResolved = constraints.find((c: any) => c.id === 'DFM-03')?.is_applied;

  return (
    <div className="p-6 md:p-8 space-y-8 max-w-[1600px] mx-auto min-h-screen bg-slate-50/50">
      
      {/* Action Notification Toast */}
      {actionNotification && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-2xl shadow-2xl border border-blue-400/40 text-xs font-bold flex items-center gap-3 animate-in fade-in slide-in-from-top-4">
          <Sparkles className="text-amber-400 animate-pulse" size={18} />
          <span>{actionNotification}</span>
        </div>
      )}

      {/* 1. Header Banner & CAD Switcher Toolbar */}
      <div className="bg-gradient-to-r from-[#0B2550] via-[#0D366B] to-[#144272] rounded-3xl p-6 md:p-8 text-white shadow-xl relative overflow-hidden">
        <div className="absolute right-0 top-0 w-96 h-96 bg-blue-400/10 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        <div className="absolute left-1/3 bottom-0 w-80 h-80 bg-teal-500/10 rounded-full blur-2xl pointer-events-none"></div>

        <div className="relative z-10 flex flex-col xl:flex-row xl:items-center justify-between gap-6">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="px-3 py-1 bg-blue-500/20 text-blue-300 border border-blue-400/30 rounded-full text-xs font-bold flex items-center gap-1.5 backdrop-blur-sm">
                <Sparkles size={14} className="text-amber-400" />
                AI Geometric Constraint Solver
              </span>
              <span className="px-3 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 rounded-full text-xs font-bold backdrop-blur-sm">
                1,280+ Supplier Digital Twins Connected
              </span>
            </div>

            <h1 className="text-2xl md:text-4xl font-black tracking-tight text-white flex items-center gap-3">
              <span>Generative Design for Supply Chain (DFSC)</span>
            </h1>

            <p className="text-blue-100/90 text-sm md:text-base max-w-2xl leading-relaxed">
              Automated 3D CAD Design for Manufacturability (DFM) engine. The AI analyzes geometric bottlenecks 
              (internal pocket radii, over-toleranced faces, thin walls) and suggests generative redesigns to unlock 10x more suppliers and slash unit costs.
            </p>
          </div>

          {/* Action Toolbar */}
          <div className="flex flex-wrap items-center gap-3 shrink-0">
            {/* Part Selector */}
            <div className="bg-white/10 backdrop-blur-md border border-white/20 rounded-2xl p-1.5 flex items-center">
              <span className="text-[11px] font-bold text-blue-200 px-3 uppercase tracking-wider">Active CAD Part:</span>
              <select
                value={selectedCadId}
                onChange={(e) => setSelectedCadId(e.target.value)}
                className="bg-[#0B2550] border border-blue-400/40 text-white rounded-xl py-2 px-3 text-xs font-extrabold outline-none cursor-pointer hover:border-blue-300"
              >
                {cadModels.map((m) => (
                  <option key={m.id} value={m.id} className="bg-slate-900 text-white">
                    {m.name} ({m.material.split(' ')[0]})
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={() => setShowUploadModal(true)}
              className="px-4 py-2.5 bg-white/10 hover:bg-white/20 text-white border border-white/20 rounded-2xl text-xs font-bold flex items-center gap-2 transition-all shadow-xs"
            >
              <UploadCloud size={16} />
              <span>Upload New STEP</span>
            </button>

            <button
              onClick={handleRunFullDfm}
              className="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-2xl text-xs font-extrabold flex items-center gap-2 shadow-md transition-all active:scale-95"
            >
              <Sparkles size={16} className="text-amber-300" />
              <span>Run DFM Analysis</span>
            </button>
          </div>
        </div>
      </div>

      {/* 2. Dynamic KPI Strip (Live Updates on Redesign Application) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
        
        {/* KPI 1: Eligible Suppliers */}
        <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-all">
          <div className="flex items-center justify-between text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">
            <span>Eligible Sourcing Base</span>
            <span className={`p-2 rounded-xl ${isAnyConstraintApplied ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
              <Building2 size={18} />
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black text-slate-900">
              {kpis ? kpis.eligible_suppliers_count : '12'}
            </span>
            <span className="text-xs font-bold text-slate-500">Suppliers Capable</span>
          </div>
          <div className="mt-3 flex items-center gap-1.5 text-xs font-bold">
            {isAnyConstraintApplied ? (
              <span className="text-emerald-600 flex items-center gap-1">
                <span className="text-base">↑</span> +{kpis.eligible_suppliers_count - model?.baseline_kpis.eligible_suppliers_count} Unlocked (+{Math.round(((kpis.eligible_suppliers_count - model?.baseline_kpis.eligible_suppliers_count) / model?.baseline_kpis.eligible_suppliers_count) * 100)}%)
              </span>
            ) : (
              <span className="text-rose-600">
                Severe Bottleneck (Only 0.9% of Network)
              </span>
            )}
          </div>
        </div>

        {/* KPI 2: Predicted Unit Cost */}
        <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-all">
          <div className="flex items-center justify-between text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">
            <span>Predicted Unit Cost</span>
            <span className={`p-2 rounded-xl ${isAnyConstraintApplied ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>
              <DollarSign size={18} />
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black text-slate-900">
              ${kpis ? kpis.predicted_unit_cost_usd.toLocaleString() : '1,850'}
            </span>
            <span className="text-xs font-bold text-slate-500">USD / Unit</span>
          </div>
          <div className="mt-3 flex items-center gap-1.5 text-xs font-bold">
            {isAnyConstraintApplied ? (
              <span className="text-emerald-600 flex items-center gap-1">
                <TrendingDown size={14} /> -${model?.baseline_kpis.predicted_unit_cost_usd - kpis.predicted_unit_cost_usd} (-{modelData?.cumulative_cost_savings_pct}%) Saved
              </span>
            ) : (
              <span className="text-slate-500">Includes $610 EDM Tooling Premium</span>
            )}
          </div>
        </div>

        {/* KPI 3: Average Lead Time */}
        <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-all">
          <div className="flex items-center justify-between text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">
            <span>Average Production Lead Time</span>
            <span className="p-2 bg-blue-50 rounded-xl text-blue-600"><Clock size={18} /></span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black text-blue-600">
              {kpis ? kpis.average_lead_time_weeks : '8'}
            </span>
            <span className="text-xs font-bold text-slate-500">Weeks</span>
          </div>
          <div className="mt-3 flex items-center gap-1.5 text-xs font-bold">
            {isAnyConstraintApplied ? (
              <span className="text-emerald-600">
                ↓ {model?.baseline_kpis.average_lead_time_weeks - kpis.average_lead_time_weeks} Weeks Faster Delivery
              </span>
            ) : (
              <span className="text-slate-500">Standard queue at EDM specialty shops</span>
            )}
          </div>
        </div>

        {/* KPI 4: Supply Risk Score */}
        <div className="bg-white rounded-2xl p-5 border border-slate-200/90 shadow-xs hover:shadow-md transition-all">
          <div className="flex items-center justify-between text-slate-500 text-xs font-bold uppercase tracking-wider mb-2">
            <span>Supply Disruption Risk</span>
            <span className={`p-2 rounded-xl ${isAnyConstraintApplied ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
              <ShieldAlert size={18} />
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-3xl font-black ${isAnyConstraintApplied ? 'text-emerald-600' : 'text-rose-600'}`}>
              {kpis ? kpis.supply_risk_level : 'Critical'}
            </span>
          </div>
          <div className="mt-3 flex items-center gap-1 text-xs font-bold">
            {isAnyConstraintApplied ? (
              <span className="text-emerald-600 flex items-center gap-1">
                <CheckCircle2 size={13} /> High Redundancy Across Network
              </span>
            ) : (
              <span className="text-rose-600">
                Single-point manufacturing vulnerability
              </span>
            )}
          </div>
        </div>

      </div>

      {/* 3. Main 3D Geometric Viewport & AI Recommendations Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        
        {/* Left: 3D CAD Blueprint & Geometric Cross-Section Viewport (7 Cols) */}
        <div className="xl:col-span-7 bg-[#0A1128] rounded-3xl border border-slate-800 shadow-2xl overflow-hidden relative min-h-[620px] flex flex-col justify-between p-6">
          
          {/* Blueprint Grid Lines Background */}
          <div className="absolute inset-0 opacity-15" style={{
            backgroundImage: 'linear-gradient(#38BDF8 1px, transparent 1px), linear-gradient(90deg, #38BDF8 1px, transparent 1px)',
            backgroundSize: '40px 40px'
          }}></div>

          {/* Viewport Top Header & Controls */}
          <div className="relative z-10 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
              <span className="text-xs font-black uppercase tracking-wider text-slate-200">
                {model?.name} • 3D Geometric Cross-Section
              </span>
            </div>

            {/* View Mode Controls */}
            <div className="flex items-center gap-1.5 bg-slate-900/90 border border-slate-700/80 rounded-xl p-1 text-xs">
              <button
                onClick={() => setViewportMode('CROSS_SECTION')}
                className={`px-2.5 py-1 rounded-lg font-bold transition-all ${viewportMode === 'CROSS_SECTION' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                Cross-Section A-A
              </button>
              <button
                onClick={() => setViewportMode('WIREFRAME')}
                className={`px-2.5 py-1 rounded-lg font-bold transition-all ${viewportMode === 'WIREFRAME' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                Wireframe
              </button>
              <button
                onClick={() => setViewportMode('SHADED')}
                className={`px-2.5 py-1 rounded-lg font-bold transition-all ${viewportMode === 'SHADED' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                Isometric Shaded
              </button>
            </div>
          </div>

          {/* Central Interactive Blueprint SVG Canvas */}
          <div className="relative z-10 flex-1 flex items-center justify-center my-4">
            <div 
              className="relative w-full max-w-[480px] h-[340px] transition-transform duration-700"
              style={{ transform: `scale(${zoomLevel})` }}
            >
              <svg viewBox="0 0 300 220" fill="none" className="w-full h-full drop-shadow-[0_0_15px_rgba(56,189,248,0.3)]">
                
                {/* Outer Flange Housing Geometry */}
                <path
                  d="M 30,50 L 270,50 L 290,95 L 290,185 L 10,185 L 10,95 Z"
                  stroke="#38BDF8"
                  strokeWidth="2"
                  strokeDasharray={isTolResolved ? "0" : "5 2"}
                  fill={viewportMode === 'SHADED' ? "rgba(14, 116, 144, 0.25)" : "none"}
                />

                {/* Stiffening Rib (Constraint #3: Thin Wall) */}
                <rect
                  x="142"
                  y="50"
                  width={isWallResolved ? "16" : "7"}
                  height="70"
                  stroke={isWallResolved ? "#22C55E" : "#F59E0B"}
                  strokeWidth="1.5"
                  fill={isWallResolved ? "rgba(34, 197, 94, 0.2)" : "rgba(245, 158, 11, 0.2)"}
                  className="transition-all duration-700"
                />

                {/* Main Internal Cavity Pocket (Constraint #1: Corner Radius R2 vs R4.5) */}
                <rect
                  x="60"
                  y="90"
                  width="180"
                  height="70"
                  rx={isR2Resolved ? "18" : "4"}
                  ry={isR2Resolved ? "18" : "4"}
                  stroke={isR2Resolved ? "#22C55E" : "#EF4444"}
                  strokeWidth="2.5"
                  fill={isR2Resolved ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)"}
                  className="transition-all duration-700"
                />

                {/* Center Fluid Bearing Bore */}
                <circle
                  cx="150"
                  cy="125"
                  r="24"
                  stroke="#38BDF8"
                  strokeWidth="1.5"
                  strokeDasharray="4 2"
                />
                <circle cx="150" cy="125" r="2" fill="#38BDF8" />

                {/* Corner Radius Constraint Indicators */}
                {!isR2Resolved ? (
                  <g className="animate-pulse">
                    <circle cx="64" cy="94" r="6" fill="rgba(239, 68, 68, 0.4)" stroke="#EF4444" strokeWidth="2" />
                    <circle cx="236" cy="94" r="6" fill="rgba(239, 68, 68, 0.4)" stroke="#EF4444" strokeWidth="2" />
                    <circle cx="64" cy="156" r="6" fill="rgba(239, 68, 68, 0.4)" stroke="#EF4444" strokeWidth="2" />
                    <circle cx="236" cy="156" r="6" fill="rgba(239, 68, 68, 0.4)" stroke="#EF4444" strokeWidth="2" />
                    
                    {/* Callout Line & Tag */}
                    <line x1="236" y1="94" x2="270" y2="40" stroke="#EF4444" strokeWidth="1.5" />
                    <rect x="250" y="24" width="46" height="18" rx="4" fill="#EF4444" />
                    <text x="273" y="36" fill="#FFF" fontSize="9" fontWeight="bold" textAnchor="middle">R2 (EDM)</text>
                  </g>
                ) : (
                  <g>
                    <circle cx="74" cy="104" r="14" stroke="#22C55E" strokeWidth="2" strokeDasharray="3 2" />
                    <circle cx="226" cy="104" r="14" stroke="#22C55E" strokeWidth="2" strokeDasharray="3 2" />
                    <line x1="226" y1="104" x2="270" y2="40" stroke="#22C55E" strokeWidth="1.5" />
                    <rect x="250" y="24" width="46" height="18" rx="4" fill="#22C55E" />
                    <text x="273" y="36" fill="#FFF" fontSize="9" fontWeight="bold" textAnchor="middle">R4.5 (CNC)</text>
                  </g>
                )}

                {/* Dimension Overlays */}
                {showDimensions && (
                  <g fontSize="8" fill="#94A3B8" fontFamily="monospace">
                    {/* Bounding width */}
                    <line x1="10" y1="200" x2="290" y2="200" stroke="#475569" strokeWidth="1" />
                    <text x="150" y="212" textAnchor="middle">{model?.bounding_box_mm.x} mm</text>

                    {/* Bounding height */}
                    <line x1="3" y1="50" x2="3" y2="185" stroke="#475569" strokeWidth="1" />
                    <text x="6" y="120" textAnchor="start" transform="rotate(-90 6,120)">{model?.bounding_box_mm.z} mm</text>

                    {/* Rib Callout */}
                    <text x="150" y="44" textAnchor="middle" fill={isWallResolved ? "#22C55E" : "#F59E0B"} fontWeight="bold">
                      {isWallResolved ? "Wall: 2.4mm (Rigid)" : "Wall: 1.4mm (Chatter)"}
                    </text>
                  </g>
                )}
              </svg>
            </div>
          </div>

          {/* Viewport Bottom HUD & Camera Toolbar */}
          <div className="relative z-10 flex flex-wrap items-center justify-between gap-4 border-t border-slate-800/80 pt-3 text-xs">
            
            {/* Geometric Metadata Strip */}
            <div className="flex flex-wrap items-center gap-4 text-slate-300 font-mono text-[11px]">
              <div><span className="text-slate-500">Volume:</span> <span className="text-blue-400 font-bold">{model?.volume_cm3} cm³</span></div>
              <div><span className="text-slate-500">Mass:</span> <span className="text-blue-400 font-bold">{model?.mass_kg} kg</span></div>
              <div><span className="text-slate-500">Material:</span> <span className="text-emerald-400 font-bold">{model?.material.split(' ')[0]}</span></div>
              <div><span className="text-slate-500">Tightest Tol:</span> <span className="text-amber-400 font-bold">{isTolResolved ? '±0.050 mm' : '±0.010 mm'}</span></div>
            </div>

            {/* Viewport Zoom & HUD controls */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowDimensions(!showDimensions)}
                className={`px-2.5 py-1 rounded-lg text-xs font-bold border transition-all ${showDimensions ? 'bg-slate-800 text-blue-300 border-blue-500/40' : 'bg-slate-900 text-slate-500 border-slate-800'}`}
              >
                PMI Dimensions
              </button>

              <button
                onClick={() => setZoomLevel(Math.min(1.4, zoomLevel + 0.1))}
                className="p-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 rounded-lg"
                title="Zoom In"
              >
                <ZoomIn size={14} />
              </button>

              <button
                onClick={() => setZoomLevel(Math.max(0.7, zoomLevel - 0.1))}
                className="p-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 rounded-lg"
                title="Zoom Out"
              >
                <ZoomOut size={14} />
              </button>

              <button
                onClick={() => setZoomLevel(1)}
                className="p-1.5 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 rounded-lg"
                title="Reset Zoom"
              >
                <RotateCw size={14} />
              </button>
            </div>

          </div>

        </div>

        {/* Right: AI Generative Recommendations & Constraint Resolver (5 Cols) */}
        <div className="xl:col-span-5 space-y-6">
          
          <div className="bg-white rounded-3xl border border-slate-200/90 p-6 shadow-xs flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
                <div>
                  <h3 className="text-base font-black text-slate-900 flex items-center gap-2">
                    <Sparkles size={18} className="text-purple-600" />
                    <span>AI Geometric DFM Bottlenecks ({constraints.length})</span>
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">Constraint graph matched against 1,280+ machine shop capability twins.</p>
                </div>
                <span className="text-xs font-mono font-bold text-slate-500 bg-slate-100 px-2.5 py-1 rounded-full">
                  {appliedCount}/{constraints.length} Applied
                </span>
              </div>

              {/* List of Constraints */}
              <div className="space-y-4">
                {constraints.map((c: any) => {
                  const isApplied = c.is_applied;
                  const isProcessing = isApplyingRedesign === c.id;

                  return (
                    <div 
                      key={c.id}
                      className={`p-4 rounded-2xl border transition-all duration-300 ${
                        isApplied 
                          ? 'bg-emerald-50/80 border-emerald-200 shadow-xs' 
                          : c.severity === 'CRITICAL_BOTTLENECK'
                            ? 'bg-rose-50/70 border-rose-200 shadow-xs'
                            : 'bg-slate-50 border-slate-200'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <div className="space-y-0.5">
                          <span className={`text-[10px] font-black uppercase tracking-wider px-2 py-0.5 rounded ${
                            isApplied 
                              ? 'bg-emerald-200 text-emerald-900' 
                              : c.severity === 'CRITICAL_BOTTLENECK' 
                                ? 'bg-rose-200 text-rose-900 animate-pulse' 
                                : 'bg-slate-200 text-slate-800'
                          }`}>
                            {isApplied ? 'OPTIMIZATION APPLIED' : c.severity.replace('_', ' ')}
                          </span>
                          <h4 className="text-sm font-black text-slate-900 leading-snug">{c.title}</h4>
                          <span className="text-[11px] text-slate-500 font-semibold block">{c.component_zone}</span>
                        </div>

                        {/* Toggle Apply Button */}
                        <button
                          onClick={() => handleToggleRedesign(c.id, isApplied)}
                          disabled={isProcessing}
                          className={`px-3.5 py-1.5 rounded-xl text-xs font-bold shadow-xs transition-all active:scale-95 shrink-0 flex items-center gap-1.5 ${
                            isApplied 
                              ? 'bg-emerald-600 hover:bg-emerald-700 text-white' 
                              : 'bg-blue-600 hover:bg-blue-700 text-white'
                          }`}
                        >
                          {isProcessing ? (
                            <RefreshCw size={13} className="animate-spin" />
                          ) : isApplied ? (
                            <Check size={13} />
                          ) : (
                            <Sparkles size={13} />
                          )}
                          <span>{isApplied ? 'Applied' : 'Apply Redesign'}</span>
                        </button>
                      </div>

                      <p className="text-xs text-slate-700 leading-relaxed mb-3">
                        {isApplied ? c.proposed_redesign : c.description}
                      </p>

                      {/* Projected Gains Pill */}
                      <div className="bg-white/90 border border-slate-200/80 rounded-xl p-2.5 grid grid-cols-3 gap-2 text-center text-xs">
                        <div>
                          <span className="text-[10px] text-slate-400 block font-semibold">Suppliers</span>
                          <span className="font-black text-emerald-600 font-mono">+{c.projected_improvements.suppliers_unlocked}</span>
                        </div>
                        <div>
                          <span className="text-[10px] text-slate-400 block font-semibold">Unit Cost</span>
                          <span className="font-black text-emerald-600 font-mono">-${c.projected_improvements.unit_cost_reduction_usd}</span>
                        </div>
                        <div>
                          <span className="text-[10px] text-slate-400 block font-semibold">Lead Time</span>
                          <span className="font-black text-emerald-600 font-mono">-{c.projected_improvements.lead_time_reduction_weeks}w</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Bottom Export & RFQ Action Bar */}
            <div className="pt-5 border-t border-slate-100 mt-4 flex items-center justify-between gap-3">
              <button
                onClick={handleExportStep}
                disabled={isExporting}
                className="w-1/2 py-2.5 px-4 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2 transition-all shadow-sm"
              >
                {isExporting ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />}
                <span>Export Revised STEP</span>
              </button>

              <Link
                href="/rfqs"
                className="w-1/2 py-2.5 px-4 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2 transition-all shadow-sm text-center"
              >
                <span>Push to RFQ Sourcing</span>
                <ArrowRight size={14} />
              </Link>
            </div>

          </div>

        </div>

      </div>

      {/* 4. Live Sourcing Elasticity: Unlocked Capability Twins Network */}
      <div className="bg-white rounded-3xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-5 md:p-6 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-black text-slate-900 flex items-center gap-2">
              <Building2 size={18} className="text-blue-600" />
              <span>Real-Time Sourcing Elasticity: Unlocked Capability Twins ({unlockedSuppliers.length})</span>
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Suppliers whose physical machinery, tool changers, and tolerance profiles match this part based on current CAD redesigns.
            </p>
          </div>
          
          <span className="text-xs font-bold px-3 py-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-full">
            {unlockedSuppliers.filter(s => s.is_eligible).length} Verified Capable Facilities
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50/80 text-slate-500 font-bold uppercase tracking-wider border-b border-slate-200">
              <tr>
                <th className="py-3.5 px-6">Supplier Facility</th>
                <th className="py-3.5 px-6">Location & Tier</th>
                <th className="py-3.5 px-6">Machinery Center Fit</th>
                <th className="py-3.5 px-6">DFM Fit Score</th>
                <th className="py-3.5 px-6">Estimated Quoted Unit Price</th>
                <th className="py-3.5 px-6">Lead Time</th>
                <th className="py-3.5 px-6 text-right">Digital Twin Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {unlockedSuppliers.map((s: any) => (
                <tr key={s.supplier_id} className="hover:bg-slate-50/80 transition-colors">
                  <td className="py-3.5 px-6 font-bold text-slate-900">
                    <span className="block">{s.supplier_name}</span>
                    <span className="text-[10px] text-slate-400 font-mono">{s.supplier_id}</span>
                  </td>
                  <td className="py-3.5 px-6">
                    <span className="font-semibold text-slate-800 flex items-center gap-1">
                      <MapPin size={12} className="text-slate-400" />
                      {s.location}
                    </span>
                    <span className="text-[10px] text-blue-700 font-bold block mt-0.5">{s.tier}</span>
                  </td>
                  <td className="py-3.5 px-6 text-slate-600 font-medium">
                    {s.machinery}
                  </td>
                  <td className="py-3.5 px-6">
                    <div className="flex items-center gap-2">
                      <div className="w-16 bg-slate-100 rounded-full h-2">
                        <div 
                          className={`h-2 rounded-full ${s.capability_fit_score >= 90 ? 'bg-emerald-500' : s.capability_fit_score >= 50 ? 'bg-blue-500' : 'bg-slate-300'}`}
                          style={{ width: `${s.capability_fit_score}%` }}
                        ></div>
                      </div>
                      <span className={`font-mono font-black ${s.capability_fit_score >= 90 ? 'text-emerald-700' : 'text-slate-700'}`}>
                        {s.capability_fit_score}%
                      </span>
                    </div>
                  </td>
                  <td className="py-3.5 px-6 font-mono font-bold text-slate-900">
                    {typeof s.estimated_unit_cost_usd === 'number' ? `$${s.estimated_unit_cost_usd}` : s.estimated_unit_cost_usd}
                  </td>
                  <td className="py-3.5 px-6 font-semibold text-slate-800">
                    {s.lead_time_weeks} Weeks
                  </td>
                  <td className="py-3.5 px-6 text-right">
                    <Link
                      href={s.twin_url}
                      className="px-3 py-1.5 bg-[#0B2550] hover:bg-blue-900 text-white rounded-lg font-bold text-[11px] inline-flex items-center gap-1.5 transition-all shadow-xs"
                    >
                      <span>Inspect Twin</span>
                      <ChevronRight size={12} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 5. Upload STEP Modal */}
      {showUploadModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in">
          <div className="bg-white rounded-3xl max-w-lg w-full p-6 md:p-8 shadow-2xl border border-slate-200 relative">
            <button 
              onClick={() => setShowUploadModal(false)}
              className="absolute top-5 right-5 text-slate-400 hover:text-slate-600"
            >
              <X size={20} />
            </button>

            <h3 className="text-xl font-black text-slate-900 mb-1 flex items-center gap-2">
              <UploadCloud className="text-blue-600" size={24} />
              <span>Upload 3D CAD (.STEP) Model</span>
            </h3>
            <p className="text-xs text-slate-500 mb-5">
              The AI will extract internal geometry, surface roughness constraints, and tolerance boundaries to match against the supplier twin network.
            </p>

            <form onSubmit={handleUploadSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">CAD File Name (.step / .stp)</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. titanium_gimbal_yoke_v2.step"
                  value={uploadFileName}
                  onChange={(e) => setUploadFileName(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Material Alloy Specification</label>
                <select
                  value={uploadMaterial}
                  onChange={(e) => setUploadMaterial(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="Aluminum 7075-T651">Aluminum 7075-T651 (Aerospace)</option>
                  <option value="Titanium Ti-6Al-4V Grade 5">Titanium Ti-6Al-4V Grade 5</option>
                  <option value="Inconel 718 Superalloy">Inconel 718 Superalloy</option>
                  <option value="Stainless Steel 316L">Stainless Steel 316L</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Component Category</label>
                <input
                  type="text"
                  value={uploadCategory}
                  onChange={(e) => setUploadCategory(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-300 rounded-xl p-2.5 text-xs font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="p-4 border-2 border-dashed border-slate-300 rounded-2xl text-center bg-slate-50">
                <UploadCloud size={28} className="mx-auto text-blue-500 mb-1" />
                <span className="text-xs font-bold text-slate-700 block">Drag and drop AP242 STEP file here</span>
                <span className="text-[10px] text-slate-400">Supports .STEP, .STP, .IGES up to 150MB</span>
              </div>

              {uploadSuccess && (
                <div className="p-3 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-xl text-xs font-bold flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-emerald-600" />
                  <span>CAD file uploaded! Extracting bounding topology and running DFM analysis...</span>
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
                  disabled={isUploading}
                  className="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold shadow-md transition-all flex items-center gap-1.5"
                >
                  {isUploading ? <RefreshCw size={14} className="animate-spin" /> : <UploadCloud size={14} />}
                  <span>Ingest & Analyze</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 6. Export STEP-REV2 Package Modal */}
      {showExportModal && exportPackage && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in">
          <div className="bg-white rounded-3xl max-w-md w-full p-6 md:p-8 shadow-2xl border border-slate-200 relative">
            <button 
              onClick={() => setShowExportModal(false)}
              className="absolute top-5 right-5 text-slate-400 hover:text-slate-600"
            >
              <X size={20} />
            </button>

            <div className="w-12 h-12 rounded-2xl bg-emerald-100 flex items-center justify-center text-emerald-600 mb-4">
              <Download size={26} />
            </div>

            <h3 className="text-lg font-black text-slate-900 mb-1">Optimized CAD STEP-REV2 Export</h3>
            <p className="text-xs text-slate-500 mb-5">
              The revised AP242 geometry includes embedded PMI tolerances and relaxed internal radii ready for enterprise RFQ distribution.
            </p>

            <div className="space-y-3 bg-slate-50 p-4 rounded-2xl border border-slate-200/80 text-xs font-mono">
              <div>
                <span className="text-[10px] text-slate-400 font-sans uppercase font-bold block">Package Revision ID</span>
                <span className="text-blue-700 font-bold">{exportPackage.revision_package_id}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-sans uppercase font-bold block">Digital Signature Hash</span>
                <span className="text-slate-700 break-all">{exportPackage.digital_signature_hash}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-sans uppercase font-bold block">STEP Protocol</span>
                <span className="text-emerald-700 font-bold font-sans">{exportPackage.export_format}</span>
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => setShowExportModal(false)}
                className="px-4 py-2 border border-slate-300 text-slate-600 rounded-xl text-xs font-bold"
              >
                Close
              </button>
              <button
                onClick={() => {
                  alert(`Downloading ${exportPackage.revision_package_id}.step with signed inspection tags.`);
                  setShowExportModal(false);
                }}
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold shadow-md"
              >
                Download Package (.STEP)
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
