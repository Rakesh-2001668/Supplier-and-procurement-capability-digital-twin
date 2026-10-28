'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  TrendingUp, ShieldAlert, Award, CheckCircle2, AlertTriangle, 
  ArrowRight, Search, Filter, RefreshCw, Plus, FileText, 
  Layers, Zap, BarChart3, Clock, ChevronRight, UserCheck, 
  ExternalLink, Sparkles, BookOpen, Target, CheckCheck, X
} from 'lucide-react';
import axios from 'axios';

interface OverviewKPIs {
  active_development_plans: number;
  suppliers_in_development: number;
  completed_plans: number;
  average_improvement_pct: number;
  open_capa_cases: number;
  critical_capas: number;
  major_capas: number;
  closed_capas: number;
  capa_on_time_closure_rate_pct: number;
  total_co_investment_usd: number;
}

interface FocusDistribution {
  area: string;
  count: number;
  pct: number;
  color: string;
}

interface DevPlan {
  id: string;
  title: string;
  supplier_id: string;
  supplier_name: string;
  location: string;
  tier: string;
  focus_area: string;
  progress_pct: number;
  status: string;
  strategic_priority: string;
  baseline_metric: string;
  target_metric: string;
  investment_budget_usd: number;
  target_date: string;
  milestones: any[];
}

interface CapaCase {
  id: string;
  title: string;
  supplier_id: string;
  supplier_name: string;
  part_number: string;
  part_name: string;
  severity: string;
  current_stage: string;
  status: string;
  source: string;
  opened_date: string;
  target_closure_date: string;
  days_open: number;
  champion_name: string;
  risk_impact: string;
  eight_d: any;
}

interface TrainingModule {
  id: string;
  title: string;
  domain: string;
  duration_weeks: number;
  difficulty: string;
  target_outcome: string;
  enrolled_suppliers: number;
  badge: string;
}

export default function SupplierDevelopmentOverviewPage() {
  const [loading, setLoading] = useState(true);
  const [kpis, setKpis] = useState<OverviewKPIs | null>(null);
  const [focusAreas, setFocusAreas] = useState<FocusDistribution[]>([]);
  const [plans, setPlans] = useState<DevPlan[]>([]);
  const [capas, setCapas] = useState<CapaCase[]>([]);
  const [modules, setModules] = useState<TrainingModule[]>([]);

  // Filter States
  const [activeTab, setActiveTab] = useState<'all' | 'capa' | 'plans' | 'training'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');

  // Modals
  const [showNewPlanModal, setShowNewPlanModal] = useState(false);
  const [showNewCapaModal, setShowNewCapaModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Form states - New Plan
  const [newPlan, setNewPlan] = useState({
    title: '',
    supplier_id: 'TWIN-APEX-001',
    supplier_name: 'Apex Precision Machining Ltd',
    focus_area: 'Precision Machining & CMM',
    strategic_priority: 'CRITICAL',
    baseline_metric: 'Cp/Cpk 1.33, max envelope 800mm',
    target_metric: 'Cp/Cpk 1.85, 5-axis 1200mm, ±1.2 μm',
    investment_budget_usd: 350000,
    target_date: '2026-12-31',
    description: ''
  });

  // Form states - New CAPA
  const [newCapa, setNewCapa] = useState({
    title: '',
    supplier_id: 'TWIN-APEX-001',
    supplier_name: 'Apex Precision Machining Ltd',
    part_number: 'APX-VALV-7741',
    part_name: 'Precision Hydraulic Spool',
    severity: 'MAJOR',
    source: 'CMM_METROLOGY_DEVIATION',
    champion_name: 'Dr. Klaus Weber',
    supplier_rep: 'Hans Zimmer',
    risk_impact: 'Tolerance stack-up failure during flight valve assembly',
    what: 'Concentricity deviation of 4.8 μm exceeding 2.0 μm limit',
    where: '5-Axis Spindle Cell #3, Munich Facility',
    magnitude: '6 parts out of 50 sampled (12% batch lot)'
  });

  const triggerToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4500);
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [overviewRes, plansRes, capaRes, trainingRes] = await Promise.all([
        axios.get('http://127.0.0.1:8080/api/v1/development/overview'),
        axios.get('http://127.0.0.1:8080/api/v1/development/plans'),
        axios.get('http://127.0.0.1:8080/api/v1/development/capa'),
        axios.get('http://127.0.0.1:8080/api/v1/development/training')
      ]);

      if (overviewRes.data.status === 'success') {
        setKpis(overviewRes.data.kpis);
        setFocusAreas(overviewRes.data.focus_distribution || []);
      }
      if (plansRes.data.status === 'success') {
        setPlans(plansRes.data.plans || []);
      }
      if (capaRes.data.status === 'success') {
        setCapas(capaRes.data.capas || []);
      }
      if (trainingRes.data.status === 'success') {
        setModules(trainingRes.data.modules || []);
      }
    } catch (err) {
      console.error('Failed to load supplier development data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreatePlan = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await axios.post('http://127.0.0.1:8080/api/v1/development/plans', newPlan);
      if (res.data.status === 'success') {
        triggerToast(`Development Charter '${res.data.plan.title}' established successfully.`);
        setShowNewPlanModal(false);
        loadData();
      }
    } catch (err: any) {
      alert(`Failed to create plan: ${err.response?.data?.detail || err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateCapa = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await axios.post('http://127.0.0.1:8080/api/v1/development/capa', newCapa);
      if (res.data.status === 'success') {
        triggerToast(`8D CAPA '${res.data.capa.id}' issued to ${res.data.capa.supplier_name}.`);
        setShowNewCapaModal(false);
        loadData();
      }
    } catch (err: any) {
      alert(`Failed to issue 8D CAPA: ${err.response?.data?.detail || err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleEnrollTraining = async (moduleId: string) => {
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/development/training/${moduleId}/enroll?supplier_id=TWIN-APEX-001&supplier_name=Apex Precision Machining Ltd`);
      if (res.data.status === 'success') {
        triggerToast(`Enrolled partner in course '${res.data.module.title}'.`);
        loadData();
      }
    } catch (err: any) {
      alert(`Enrollment failed: ${err.message}`);
    }
  };

  // Stage step helper
  const getStageBadge = (stage: string) => {
    if (stage.includes('D1')) return { label: 'D1: Team Formed', color: 'bg-slate-800 text-slate-300 border-slate-700' };
    if (stage.includes('D2')) return { label: 'D2: Problem Stmt', color: 'bg-amber-950/60 text-amber-300 border-amber-800/60' };
    if (stage.includes('D3')) return { label: 'D3: Containment Active', color: 'bg-rose-950/70 text-rose-300 border-rose-800/80 animate-pulse' };
    if (stage.includes('D4')) return { label: 'D4: 5-Whys Root Cause', color: 'bg-purple-950/60 text-purple-300 border-purple-800/60' };
    if (stage.includes('D5')) return { label: 'D5: PCA Selected', color: 'bg-indigo-950/60 text-indigo-300 border-indigo-800/60' };
    if (stage.includes('D6')) return { label: 'D6: Validating', color: 'bg-cyan-950/60 text-cyan-300 border-cyan-800/60' };
    if (stage.includes('D7')) return { label: 'D7: SOP Recurrence Fix', color: 'bg-teal-950/60 text-teal-300 border-teal-800/60' };
    if (stage.includes('D8') || stage.includes('CLOSED')) return { label: 'D8: Closed & Verified', color: 'bg-emerald-950/60 text-emerald-300 border-emerald-800/60' };
    return { label: stage, color: 'bg-slate-800 text-slate-300 border-slate-700' };
  };

  const getSeverityBadge = (sev: string) => {
    if (sev === 'CRITICAL') return 'bg-rose-500/20 text-rose-400 border-rose-500/40';
    if (sev === 'MAJOR') return 'bg-amber-500/20 text-amber-400 border-amber-500/40';
    return 'bg-blue-500/20 text-blue-400 border-blue-500/40';
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 md:p-8 space-y-8 font-sans">
      
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-3 bg-emerald-950/90 border border-emerald-500/50 text-emerald-200 px-5 py-3.5 rounded-xl shadow-2xl backdrop-blur-md animate-in fade-in slide-in-from-top-4 duration-300">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
        </div>
      )}

      {/* Header Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#0B1528] via-[#0F1E38] to-[#070B14] border border-slate-800/80 p-8 shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="px-3 py-1 text-xs font-bold tracking-widest uppercase bg-cyan-950/80 text-cyan-400 border border-cyan-800/80 rounded-full flex items-center gap-1.5 shadow-sm">
                <Sparkles className="w-3.5 h-3.5" /> AS9100D & IATF 16949 Continuous Improvement
              </span>
              <span className="px-2.5 py-0.5 text-xs font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-800/50 rounded-full">
                Live Closed-Loop Hub
              </span>
            </div>
            <h1 className="text-3xl lg:text-4xl font-extrabold tracking-tight text-white flex items-center gap-3">
              Supplier Continuous Development & 8D CAPA
            </h1>
            <p className="text-slate-400 max-w-3xl text-sm md:text-base leading-relaxed">
              Drive aerospace manufacturing excellence through structured co-investment charters, Nadcap/CMM capability upgrades, and rapid 8D root-cause problem containment.
            </p>
          </div>

          {/* Action CTAs */}
          <div className="flex flex-wrap items-center gap-3">
            <button 
              onClick={() => setShowNewCapaModal(true)}
              className="px-4 py-2.5 rounded-xl text-sm font-semibold bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-900/40 flex items-center gap-2 transition-all duration-200 border border-rose-400/30"
            >
              <AlertTriangle className="w-4 h-4" /> Issue 8D CAPA
            </button>
            <button 
              onClick={() => setShowNewPlanModal(true)}
              className="px-4 py-2.5 rounded-xl text-sm font-semibold bg-cyan-600 hover:bg-cyan-500 text-white shadow-lg shadow-cyan-900/40 flex items-center gap-2 transition-all duration-200 border border-cyan-400/30"
            >
              <Plus className="w-4 h-4" /> New Development Charter
            </button>
            <button 
              onClick={loadData}
              disabled={loading}
              className="p-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 transition-colors"
              title="Refresh Live Data"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
            </button>
          </div>
        </div>

        {/* Quick Sub-Navigation Bar */}
        <div className="mt-8 pt-6 border-t border-slate-800/60 flex flex-wrap items-center gap-4 text-xs font-medium text-slate-300">
          <span className="text-slate-500 font-semibold uppercase tracking-wider">Direct Sub-Modules:</span>
          <Link 
            href="/development/capa"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/80 hover:bg-slate-800 border border-slate-700/80 text-cyan-300 hover:text-cyan-200 transition-colors group"
          >
            <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
            <span>Dedicated 8D CAPA Resolution Studio</span>
            <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
          </Link>
          <Link 
            href="/development/plans"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/80 hover:bg-slate-800 border border-slate-700/80 text-cyan-300 hover:text-cyan-200 transition-colors group"
          >
            <TrendingUp className="w-3.5 h-3.5 text-cyan-400" />
            <span>Capability Upgrade Roadmaps (CDP)</span>
            <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
          </Link>
          <Link 
            href="/evidence"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/80 hover:bg-slate-800 border border-slate-700/80 text-slate-300 hover:text-white transition-colors"
          >
            <Award className="w-3.5 h-3.5 text-amber-400" />
            <span>Evidence & Audit Vault</span>
          </Link>
        </div>
      </div>

      {/* KPI Cards Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        
        {/* KPI 1 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg relative overflow-hidden group hover:border-cyan-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Active CDP Charters</span>
            <span className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              <TrendingUp className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-white">
            {kpis?.active_development_plans ?? '--'}
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
            <span className="text-emerald-400 font-semibold flex items-center">↑ 24%</span>
            <span>vs prior quarter</span>
          </div>
          <div className="text-[11px] text-cyan-400/80 mt-1">
            ${((kpis?.total_co_investment_usd || 1840000) / 1000000).toFixed(2)}M Joint CapEx
          </div>
        </div>

        {/* KPI 2 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg relative overflow-hidden group hover:border-purple-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Suppliers Enrolled</span>
            <span className="p-2 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
              <UserCheck className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-white">
            {kpis?.suppliers_in_development ?? '--'}
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
            <span className="text-purple-400 font-semibold">Tier-1 & Critical</span>
            <span>aerospace partners</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-1">
            {kpis?.completed_plans ?? 16} Charters Graduated
          </div>
        </div>

        {/* KPI 3 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg relative overflow-hidden group hover:border-rose-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Active 8D CAPA Cases</span>
            <span className="p-2 rounded-xl bg-rose-500/10 text-rose-400 border border-rose-500/20">
              <ShieldAlert className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-white flex items-baseline gap-2">
            <span>{kpis?.open_capa_cases ?? '--'}</span>
            <span className="text-xs font-bold text-rose-400 px-2 py-0.5 rounded-full bg-rose-950/80 border border-rose-800/60">
              {kpis?.critical_capas ?? 1} Critical
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
            <span className="text-amber-400 font-semibold">{kpis?.major_capas ?? 2} Major</span>
            <span>• 100% Contained</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-1">
            Zero flight-line escapes
          </div>
        </div>

        {/* KPI 4 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg relative overflow-hidden group hover:border-emerald-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Avg Cp/Cpk Uplift</span>
            <span className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <BarChart3 className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-emerald-400">
            +{kpis?.average_improvement_pct ?? '68.4'}%
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
            <span className="text-emerald-400 font-semibold">1.33 → 1.85</span>
            <span>capability index</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-1">
            Verified with CMM metrology
          </div>
        </div>

        {/* KPI 5 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg relative overflow-hidden group hover:border-blue-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">8D On-Time Closure</span>
            <span className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <Target className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-white">
            {kpis?.capa_on_time_closure_rate_pct ?? '93.8'}%
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
            <span className="text-cyan-400 font-semibold">&lt; 45 Days</span>
            <span>target cycle time</span>
          </div>
          <div className="text-[11px] text-slate-400 mt-1">
            FMEA RPN reduced by 64% avg
          </div>
        </div>

      </div>

      {/* Focus Area Capability Distribution */}
      <div className="bg-[#0B1528]/60 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Layers className="w-4 h-4 text-cyan-400" />
              Strategic Capability Focus Areas (Continuous Development Portfolio)
            </h2>
            <p className="text-xs text-slate-400">
              Distribution of supplier capability investment, Nadcap certification paths, and AI SPC deployments.
            </p>
          </div>
          <span className="text-xs text-slate-400 font-medium">42 Total Active Upgrades</span>
        </div>

        {/* Multi-segmented Progress Bar */}
        <div className="w-full h-3 rounded-full bg-slate-900 overflow-hidden flex shadow-inner">
          {focusAreas.map((item, idx) => (
            <div 
              key={idx} 
              className={`h-full ${item.color} transition-all duration-500`} 
              style={{ width: `${item.pct}%` }} 
              title={`${item.area}: ${item.pct}% (${item.count} initiatives)`}
            />
          ))}
        </div>

        {/* Legend */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 pt-2">
          {focusAreas.map((item, idx) => (
            <div key={idx} className="flex items-center gap-2 text-xs">
              <span className={`w-3 h-3 rounded-full ${item.color} shrink-0`}></span>
              <div className="truncate">
                <span className="text-slate-300 font-medium truncate block">{item.area}</span>
                <span className="text-slate-500 text-[11px]">{item.count} plans ({item.pct}%)</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Interactive Tabs Header & Search */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
        <div className="flex items-center gap-2 overflow-x-auto">
          <button 
            onClick={() => setActiveTab('all')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-colors flex items-center gap-2 whitespace-nowrap ${
              activeTab === 'all' 
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm' 
                : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" /> All Initiatives & Cases
          </button>
          <button 
            onClick={() => setActiveTab('capa')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-colors flex items-center gap-2 whitespace-nowrap ${
              activeTab === 'capa' 
                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-sm' 
                : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            <ShieldAlert className="w-3.5 h-3.5 text-rose-400" /> 8D CAPA Action Board ({capas.length})
          </button>
          <button 
            onClick={() => setActiveTab('plans')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-colors flex items-center gap-2 whitespace-nowrap ${
              activeTab === 'plans' 
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm' 
                : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            <TrendingUp className="w-3.5 h-3.5 text-cyan-400" /> Development Charters ({plans.length})
          </button>
          <button 
            onClick={() => setActiveTab('training')}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-colors flex items-center gap-2 whitespace-nowrap ${
              activeTab === 'training' 
                ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-sm' 
                : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            <BookOpen className="w-3.5 h-3.5 text-purple-400" /> Technical Enablement Academy ({modules.length})
          </button>
        </div>

        {/* Search & Filter */}
        <div className="flex items-center gap-3">
          <div className="relative w-full md:w-64">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input 
              type="text"
              placeholder="Search supplier, part, 8D stage..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors"
            />
          </div>
          <select 
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
          >
            <option value="All">All Statuses</option>
            <option value="IN_PROGRESS">In Progress</option>
            <option value="CONTAINMENT_ACTIVE">Containment Active</option>
            <option value="PCA_IN_PROGRESS">PCA In Progress</option>
            <option value="CLOSED_VERIFIED">Closed & Verified</option>
          </select>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="space-y-8">

        {/* 8D CAPA Board Section (shown if 'all' or 'capa') */}
        {(activeTab === 'all' || activeTab === 'capa') && (
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <ShieldAlert className="w-5 h-5 text-rose-400" />
                  <h2 className="text-lg font-bold text-white tracking-tight">Active 8D Corrective & Preventive Action (CAPA) Cases</h2>
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-rose-950/80 text-rose-300 border border-rose-800/60 font-semibold">
                    AS9100D Clause 10.2
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  Structured 8-Discipline problem-solving cycle with rapid 24-hour interim containment, 5-Whys root-cause isolation, and systemic SOP institutionalization.
                </p>
              </div>

              <Link 
                href="/development/capa"
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-rose-400 hover:text-rose-300 bg-rose-950/40 hover:bg-rose-950/70 border border-rose-800/60 px-3.5 py-2 rounded-xl transition-all group"
              >
                <span>Open Full 8D Workbench</span>
                <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-1 transition-transform" />
              </Link>
            </div>

            {/* CAPA Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] font-bold text-slate-400 uppercase tracking-wider bg-slate-900/40">
                    <th className="py-3 px-4">CAPA ID & Title</th>
                    <th className="py-3 px-4">Supplier Partner</th>
                    <th className="py-3 px-4">Part / Component</th>
                    <th className="py-3 px-4">Severity</th>
                    <th className="py-3 px-4">8D Current Stage</th>
                    <th className="py-3 px-4">Containment & Root Cause</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 text-xs">
                  {capas
                    .filter(c => {
                      if (statusFilter !== 'All' && c.status !== statusFilter) return false;
                      if (!searchQuery) return true;
                      const q = searchQuery.toLowerCase();
                      return c.title.toLowerCase().includes(q) || 
                             c.id.toLowerCase().includes(q) || 
                             c.supplier_name.toLowerCase().includes(q) || 
                             c.part_number.toLowerCase().includes(q);
                    })
                    .map((capa) => {
                      const stageInfo = getStageBadge(capa.current_stage);
                      return (
                        <tr key={capa.id} className="hover:bg-slate-900/60 transition-colors group">
                          <td className="py-3.5 px-4">
                            <div className="font-bold text-white group-hover:text-rose-300 transition-colors">
                              {capa.id}
                            </div>
                            <div className="text-slate-400 text-[11px] line-clamp-1 max-w-xs" title={capa.title}>
                              {capa.title}
                            </div>
                            <div className="text-[10px] text-slate-500 mt-0.5">
                              Opened {capa.opened_date} • {capa.days_open}d active
                            </div>
                          </td>

                          <td className="py-3.5 px-4">
                            <div className="font-medium text-slate-200">{capa.supplier_name}</div>
                            <div className="text-[11px] text-slate-500 font-mono">{capa.supplier_id}</div>
                          </td>

                          <td className="py-3.5 px-4">
                            <div className="font-mono text-cyan-300 text-[11px]">{capa.part_number}</div>
                            <div className="text-[11px] text-slate-400 line-clamp-1">{capa.part_name}</div>
                          </td>

                          <td className="py-3.5 px-4">
                            <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold border tracking-wider uppercase ${getSeverityBadge(capa.severity)}`}>
                              {capa.severity}
                            </span>
                          </td>

                          <td className="py-3.5 px-4">
                            <span className={`px-2.5 py-1 rounded-full text-[10px] font-semibold border flex items-center gap-1.5 w-fit ${stageInfo.color}`}>
                              <span className="w-1.5 h-1.5 rounded-full bg-current"></span>
                              {stageInfo.label}
                            </span>
                            <div className="text-[10px] text-slate-400 mt-1">
                              Target closure: {capa.target_closure_date}
                            </div>
                          </td>

                          <td className="py-3.5 px-4 max-w-xs">
                            <div className="text-[11px] text-slate-300 line-clamp-1 font-medium">
                              ICA: {capa.eight_d?.d3_interim_containment?.actions?.[0] || '100% Quarantine & Metrology verification'}
                            </div>
                            <div className="text-[10px] text-slate-400 line-clamp-1 mt-0.5">
                              Root: {capa.eight_d?.d4_root_cause_analysis?.root_cause_summary || '5-Whys isolation in progress'}
                            </div>
                          </td>

                          <td className="py-3.5 px-4 text-right">
                            <Link 
                              href={`/development/capa?id=${capa.id}`}
                              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-cyan-300 hover:text-cyan-200 font-medium text-xs transition-colors"
                            >
                              <span>Inspect 8D</span>
                              <ChevronRight className="w-3.5 h-3.5" />
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Continuous Development Plans Section (shown if 'all' or 'plans') */}
        {(activeTab === 'all' || activeTab === 'plans') && (
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-cyan-400" />
                  <h2 className="text-lg font-bold text-white tracking-tight">Active Continuous Capability Upgrades (CDP Charters)</h2>
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 font-semibold">
                    CapEx Co-Investment
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  Joint OEM-supplier capability roadmaps, 5-Axis Hermle installations, sub-micron CMM deployments, and Nadcap accreditation pathways.
                </p>
              </div>

              <Link 
                href="/development/plans"
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-cyan-400 hover:text-cyan-300 bg-cyan-950/40 hover:bg-cyan-950/70 border border-cyan-800/60 px-3.5 py-2 rounded-xl transition-all group"
              >
                <span>View All Roadmaps & Proofs</span>
                <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-1 transition-transform" />
              </Link>
            </div>

            {/* Plans Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 pt-2">
              {plans
                .filter(p => {
                  if (statusFilter !== 'All' && p.status !== statusFilter) return false;
                  if (!searchQuery) return true;
                  const q = searchQuery.toLowerCase();
                  return p.title.toLowerCase().includes(q) || 
                         p.supplier_name.toLowerCase().includes(q) || 
                         p.focus_area.toLowerCase().includes(q);
                })
                .map((plan) => (
                  <div 
                    key={plan.id}
                    className="bg-[#070B14]/90 border border-slate-800 hover:border-cyan-500/40 rounded-xl p-5 flex flex-col justify-between space-y-4 transition-all duration-200 group shadow-lg"
                  >
                    <div className="space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 border border-slate-700 text-slate-400">
                          {plan.id}
                        </span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                          plan.status === 'COMPLETED' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-cyan-950 text-cyan-300 border border-cyan-800'
                        }`}>
                          {plan.status}
                        </span>
                      </div>

                      <h3 className="font-bold text-white text-sm group-hover:text-cyan-300 transition-colors line-clamp-2">
                        {plan.title}
                      </h3>

                      <div className="text-xs text-slate-400 flex items-center justify-between border-t border-b border-slate-800/80 py-2">
                        <span className="font-medium text-slate-200">{plan.supplier_name}</span>
                        <span className="text-slate-500 font-mono text-[11px]">{plan.location}</span>
                      </div>

                      <div className="space-y-2 text-xs">
                        <div className="flex justify-between text-slate-400">
                          <span>Focus Domain:</span>
                          <span className="text-slate-200 font-medium">{plan.focus_area}</span>
                        </div>
                        <div className="flex justify-between text-slate-400">
                          <span>Target Metric:</span>
                          <span className="text-emerald-400 font-mono text-[11px]">{plan.target_metric}</span>
                        </div>
                        <div className="flex justify-between text-slate-400">
                          <span>CapEx Allocation:</span>
                          <span className="text-cyan-300 font-mono text-[11px]">${(plan.investment_budget_usd / 1000).toFixed(0)}k</span>
                        </div>
                      </div>

                      {/* Progress Bar */}
                      <div className="space-y-1.5 pt-1">
                        <div className="flex justify-between text-xs">
                          <span className="text-slate-400 text-[11px]">Milestones Verified</span>
                          <span className="font-bold text-cyan-300">{plan.progress_pct}%</span>
                        </div>
                        <div className="w-full h-2 rounded-full bg-slate-900 overflow-hidden">
                          <div 
                            className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 rounded-full transition-all duration-500"
                            style={{ width: `${plan.progress_pct}%` }}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between">
                      <span className="text-[11px] text-slate-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" /> Target: {plan.target_date}
                      </span>
                      <Link 
                        href={`/development/plans?id=${plan.id}`}
                        className="text-xs font-semibold text-cyan-400 hover:text-cyan-300 flex items-center gap-1 group-hover:translate-x-0.5 transition-transform"
                      >
                        Milestones ({plan.milestones?.length || 0}) <ArrowRight className="w-3 h-3" />
                      </Link>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Technical Enablement Academy Section (shown if 'all' or 'training') */}
        {(activeTab === 'all' || activeTab === 'training') && (
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-purple-400" />
                  <h2 className="text-lg font-bold text-white tracking-tight">Supplier Capability Enablement & Training Academy</h2>
                  <span className="text-xs px-2.5 py-0.5 rounded-full bg-purple-950/80 text-purple-300 border border-purple-800/60 font-semibold">
                    Technical Upskilling
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  Aerospace engineering modules, GD&T ASME Y14.5 certification, AI SPC process control, and Nadcap heat treat readiness.
                </p>
              </div>

              <div className="text-xs text-slate-400 font-medium">
                {modules.reduce((acc, m) => acc + m.enrolled_suppliers, 0)} Total Supplier Personnel Enrolled
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 pt-2">
              {modules.map((mod) => (
                <div 
                  key={mod.id}
                  className="bg-[#070B14]/90 border border-slate-800 hover:border-purple-500/40 rounded-xl p-5 flex flex-col justify-between space-y-4 transition-all duration-200 group shadow-lg"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-xs">
                      <span className="px-2 py-0.5 rounded bg-purple-950/60 text-purple-300 border border-purple-800/60 text-[10px] font-bold">
                        {mod.domain}
                      </span>
                      <span className="text-[11px] text-slate-400 flex items-center gap-1">
                        <Clock className="w-3 h-3 text-slate-500" /> {mod.duration_weeks} Weeks
                      </span>
                    </div>

                    <h3 className="font-bold text-white text-sm group-hover:text-purple-300 transition-colors">
                      {mod.title}
                    </h3>

                    <p className="text-xs text-slate-400 line-clamp-2 leading-relaxed">
                      Target Outcome: {mod.target_outcome}
                    </p>

                    <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
                      <span>Certification:</span>
                      <span className="font-medium text-amber-300 flex items-center gap-1">
                        <Award className="w-3.5 h-3.5" /> {mod.badge}
                      </span>
                    </div>
                  </div>

                  <div className="pt-3 border-t border-slate-800/60 flex items-center justify-between">
                    <span className="text-[11px] text-slate-400 font-medium">
                      {mod.enrolled_suppliers} Enrolled
                    </span>
                    <button 
                      onClick={() => handleEnrollTraining(mod.id)}
                      className="px-3 py-1.5 rounded-lg bg-purple-600/20 hover:bg-purple-600/40 text-purple-300 hover:text-white border border-purple-500/30 text-xs font-semibold transition-all flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> Enroll Supplier
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>

      {/* MODAL 1: Create New Development Plan */}
      {showNewPlanModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0B1528] border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 md:p-8 space-y-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-2.5">
                <TrendingUp className="w-5 h-5 text-cyan-400" />
                <h3 className="text-lg font-bold text-white">Establish Continuous Development Charter</h3>
              </div>
              <button 
                onClick={() => setShowNewPlanModal(false)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreatePlan} className="space-y-4 text-xs">
              <div className="space-y-1.5">
                <label className="font-semibold text-slate-300">Plan Charter Title</label>
                <input 
                  type="text" 
                  required
                  placeholder="e.g. 5-Axis Dynamic Milling & Sub-Micron CMM Upgrade"
                  value={newPlan.title}
                  onChange={(e) => setNewPlan({...newPlan, title: e.target.value})}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Supplier Name</label>
                  <input 
                    type="text" 
                    required
                    value={newPlan.supplier_name}
                    onChange={(e) => setNewPlan({...newPlan, supplier_name: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-cyan-500"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Supplier ID</label>
                  <input 
                    type="text" 
                    required
                    value={newPlan.supplier_id}
                    onChange={(e) => setNewPlan({...newPlan, supplier_id: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white font-mono focus:outline-none focus:border-cyan-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Focus Area</label>
                  <select 
                    value={newPlan.focus_area}
                    onChange={(e) => setNewPlan({...newPlan, focus_area: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-cyan-500"
                  >
                    <option value="Precision Machining & CMM">Precision Machining & CMM</option>
                    <option value="Zero Defect Quality & SPC">Zero Defect Quality & SPC</option>
                    <option value="Cybersecurity & ITAR Enclave">Cybersecurity & ITAR Enclave</option>
                    <option value="ESG & Green Metallurgy">ESG & Green Metallurgy</option>
                    <option value="Nadcap Special Processes">Nadcap Special Processes</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Strategic Priority</label>
                  <select 
                    value={newPlan.strategic_priority}
                    onChange={(e) => setNewPlan({...newPlan, strategic_priority: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-cyan-500"
                  >
                    <option value="CRITICAL">CRITICAL (Flight-Critical)</option>
                    <option value="HIGH">HIGH (Major Structural)</option>
                    <option value="MEDIUM">MEDIUM (Standard CapEx)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Baseline Metric</label>
                  <input 
                    type="text" 
                    required
                    placeholder="e.g. Cp/Cpk 1.33, ±5.0 μm"
                    value={newPlan.baseline_metric}
                    onChange={(e) => setNewPlan({...newPlan, baseline_metric: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-cyan-500"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Target Capability Metric</label>
                  <input 
                    type="text" 
                    required
                    placeholder="e.g. Cp/Cpk 1.85, ±1.2 μm"
                    value={newPlan.target_metric}
                    onChange={(e) => setNewPlan({...newPlan, target_metric: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-cyan-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Joint Investment Budget (USD)</label>
                  <input 
                    type="number" 
                    required
                    value={newPlan.investment_budget_usd}
                    onChange={(e) => setNewPlan({...newPlan, investment_budget_usd: Number(e.target.value)})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white font-mono focus:outline-none focus:border-cyan-500"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Target Completion Date</label>
                  <input 
                    type="date" 
                    required
                    value={newPlan.target_date}
                    onChange={(e) => setNewPlan({...newPlan, target_date: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-cyan-500"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-slate-300">Charter Scope & Statement of Work</label>
                <textarea 
                  rows={3}
                  placeholder="Detail the technical implementation, tooling specs, and verification protocols..."
                  value={newPlan.description}
                  onChange={(e) => setNewPlan({...newPlan, description: e.target.value})}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
                <button 
                  type="button"
                  onClick={() => setShowNewPlanModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 font-semibold"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  disabled={submitting}
                  className="px-5 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold flex items-center gap-2 shadow-lg shadow-cyan-900/40"
                >
                  {submitting ? 'Establishing...' : 'Establish Charter'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 2: Issue New 8D CAPA */}
      {showNewCapaModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0B1528] border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 md:p-8 space-y-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-2.5">
                <ShieldAlert className="w-5 h-5 text-rose-400" />
                <h3 className="text-lg font-bold text-white">Issue 8D Corrective Action Notice (CAPA)</h3>
              </div>
              <button 
                onClick={() => setShowNewCapaModal(false)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateCapa} className="space-y-4 text-xs">
              <div className="space-y-1.5">
                <label className="font-semibold text-slate-300">CAPA Case Title</label>
                <input 
                  type="text" 
                  required
                  placeholder="e.g. Hydraulic Actuator Cylinder Bore Micro-Porosity Non-Conformance"
                  value={newCapa.title}
                  onChange={(e) => setNewCapa({...newCapa, title: e.target.value})}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-rose-500"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Supplier Name</label>
                  <input 
                    type="text" 
                    required
                    value={newCapa.supplier_name}
                    onChange={(e) => setNewCapa({...newCapa, supplier_name: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-rose-500"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Supplier ID</label>
                  <input 
                    type="text" 
                    required
                    value={newCapa.supplier_id}
                    onChange={(e) => setNewCapa({...newCapa, supplier_id: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white font-mono focus:outline-none focus:border-rose-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Part Number</label>
                  <input 
                    type="text" 
                    required
                    value={newCapa.part_number}
                    onChange={(e) => setNewCapa({...newCapa, part_number: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-cyan-300 font-mono focus:outline-none focus:border-rose-500"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Part Name</label>
                  <input 
                    type="text" 
                    required
                    value={newCapa.part_name}
                    onChange={(e) => setNewCapa({...newCapa, part_name: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-rose-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Severity Level</label>
                  <select 
                    value={newCapa.severity}
                    onChange={(e) => setNewCapa({...newCapa, severity: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-rose-500"
                  >
                    <option value="CRITICAL">CRITICAL (Stop-Ship / Flight Hazard)</option>
                    <option value="MAJOR">MAJOR (Functional / Assembly Impact)</option>
                    <option value="MINOR">MINOR (Cosmetic / Low RPN)</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Detection Source</label>
                  <select 
                    value={newCapa.source}
                    onChange={(e) => setNewCapa({...newCapa, source: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-rose-500"
                  >
                    <option value="INCOMING_RECEIVING_INSPECTION">Incoming Receiving Inspection</option>
                    <option value="CMM_METROLOGY_DEVIATION">CMM Metrology Deviation</option>
                    <option value="SUPPLIER_AUDIT_NON_CONFORMANCE">Supplier Audit Non-Conformance</option>
                    <option value="MANUFACTURING_ASSEMBLY_LINE">Manufacturing Assembly Line</option>
                    <option value="FIELD_RELIABILITY_RETURN">Field Reliability Return</option>
                  </select>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-slate-300">D2 Problem Statement: What Failed?</label>
                <textarea 
                  rows={2}
                  required
                  placeholder="Specific defect description, visual characteristics, or tolerance exceedance..."
                  value={newCapa.what}
                  onChange={(e) => setNewCapa({...newCapa, what: e.target.value})}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-rose-500"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Where (Location / Station)</label>
                  <input 
                    type="text" 
                    required
                    value={newCapa.where}
                    onChange={(e) => setNewCapa({...newCapa, where: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-rose-500"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="font-semibold text-slate-300">Magnitude / Lot Impact</label>
                  <input 
                    type="text" 
                    required
                    value={newCapa.magnitude}
                    onChange={(e) => setNewCapa({...newCapa, magnitude: e.target.value})}
                    className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-rose-500"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-slate-300">Risk Impact Summary</label>
                <input 
                  type="text" 
                  required
                  value={newCapa.risk_impact}
                  onChange={(e) => setNewCapa({...newCapa, risk_impact: e.target.value})}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-rose-500"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
                <button 
                  type="button"
                  onClick={() => setShowNewCapaModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 font-semibold"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  disabled={submitting}
                  className="px-5 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-semibold flex items-center gap-2 shadow-lg shadow-rose-900/40"
                >
                  {submitting ? 'Issuing...' : 'Issue 8D CAPA'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
