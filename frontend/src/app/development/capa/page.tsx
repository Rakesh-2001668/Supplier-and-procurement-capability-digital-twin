'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { 
  ShieldAlert, ArrowLeft, CheckCircle2, AlertTriangle, 
  Clock, CheckCheck, Users, Search, RefreshCw, Plus, 
  ChevronRight, ArrowRight, FileText, Activity, ShieldCheck, 
  Layers, Lock, Sparkles, AlertCircle, FileSpreadsheet, X
} from 'lucide-react';
import axios from 'axios';

interface CapaTeamMember {
  name: string;
  role: string;
  organization: string;
}

interface FiveWhy {
  level: number;
  question: string;
  answer: string;
}

interface EightDStructure {
  d1_team: CapaTeamMember[];
  d2_problem_statement: {
    what: string;
    where: string;
    when: string;
    magnitude: string;
  };
  d3_interim_containment: {
    actions: string[];
    effectiveness_pct: number;
    quarantine_lot?: string;
    containment_date?: string;
  };
  d4_root_cause_analysis: {
    methodology: string;
    root_cause_summary?: string;
    five_whys: FiveWhy[];
    escape_point?: string;
  };
  d5_permanent_corrective_action: {
    selected_pca: string[];
    status: string;
    validation_method?: string;
  };
  d6_implementation_and_validation: {
    validation_status: string;
    pilot_sample_size?: number;
    cpk_result?: number;
    verification_date?: string;
  };
  d7_prevention_of_recurrence: {
    sop_updated?: string;
    pfmea_rpn_initial?: number;
    pfmea_rpn_revised?: number;
    institutionalized: boolean;
    systemic_actions?: string[];
  };
  d8_closure_and_recognition: {
    closure_date?: string;
    signoff_auditor?: string;
    status: string;
    lessons_learned?: string;
  };
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
  supplier_rep: string;
  risk_impact: string;
  eight_d: EightDStructure;
}

const EIGHT_D_STAGES = [
  { id: 'D1_TEAM', num: 'D1', label: 'Team', desc: 'Cross-functional champions' },
  { id: 'D2_PROBLEM_STATEMENT', num: 'D2', label: 'Problem', desc: '5W2H specification' },
  { id: 'D3_CONTAINMENT', num: 'D3', label: 'Containment', desc: '24h Quarantine & Stop-Ship' },
  { id: 'D4_ROOT_CAUSE', num: 'D4', label: 'Root Cause', desc: '5-Whys & Escape Point' },
  { id: 'D5_PCA_SELECTION', num: 'D5', label: 'Corrective Action', desc: 'Permanent fix selection' },
  { id: 'D6_VALIDATION', num: 'D6', label: 'Validation', desc: 'Cp/Cpk verification run' },
  { id: 'D7_RECURRENCE_PREVENTION', num: 'D7', label: 'Prevention', desc: 'PFMEA & SOP revision' },
  { id: 'D8_CLOSURE', num: 'D8', label: 'Closure', desc: 'Signoff & Institutionalize' }
];

function CapaWorkbenchContent() {
  const searchParams = useSearchParams();
  const initialCapaId = searchParams?.get('id') || null;

  const [capasList, setCapasList] = useState<CapaCase[]>([]);
  const [selectedCapa, setSelectedCapa] = useState<CapaCase | null>(null);
  const [selectedStageTab, setSelectedStageTab] = useState<string>('D3_CONTAINMENT');
  const [loading, setLoading] = useState(true);
  const [filterSeverity, setFilterSeverity] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');

  // Modals & Forms
  const [showAdvanceModal, setShowAdvanceModal] = useState(false);
  const [showAddActionModal, setShowAddActionModal] = useState(false);
  const [targetStageToAdvance, setTargetStageToAdvance] = useState('');
  const [transitionNotes, setTransitionNotes] = useState('');
  const [newActionType, setNewActionType] = useState('INTERIM_CONTAINMENT');
  const [newActionDesc, setNewActionDesc] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const triggerToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4500);
  };

  const loadCapas = async () => {
    setLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8080/api/v1/development/capa');
      if (res.data.status === 'success') {
        const items: CapaCase[] = res.data.capas || [];
        setCapasList(items);

        if (initialCapaId) {
          const match = items.find(c => c.id === initialCapaId);
          if (match) {
            setSelectedCapa(match);
            setSelectedStageTab(match.current_stage || 'D3_CONTAINMENT');
            return;
          }
        }
        if (items.length > 0 && !selectedCapa) {
          setSelectedCapa(items[0]);
          setSelectedStageTab(items[0].current_stage || 'D3_CONTAINMENT');
        }
      }
    } catch (err) {
      console.error('Failed to load CAPA cases:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCapas();
  }, [initialCapaId]);

  // Stage transition handler
  const handleStageTransition = async () => {
    if (!selectedCapa || !targetStageToAdvance) return;
    setSubmitting(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/development/capa/${selectedCapa.id}/transition`, {
        target_stage: targetStageToAdvance,
        actor: 'Lead Aerospace Quality Auditor',
        root_cause_summary: targetStageToAdvance.includes('D4') ? transitionNotes : undefined
      });

      if (res.data.status === 'success') {
        triggerToast(`CAPA ${selectedCapa.id} transitioned to stage ${targetStageToAdvance}.`);
        setSelectedCapa(res.data.capa);
        setSelectedStageTab(targetStageToAdvance);
        setShowAdvanceModal(false);
        setTransitionNotes('');
        loadCapas();
      }
    } catch (err: any) {
      alert(`Stage transition failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  // Add Action handler
  const handleAddAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedCapa || !newActionDesc.trim()) return;
    setSubmitting(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/development/capa/${selectedCapa.id}/action`, {
        action_type: newActionType,
        action_description: newActionDesc,
        actor: 'Lead Aerospace Auditor'
      });

      if (res.data.status === 'success') {
        triggerToast(`Action appended to 8D report.`);
        setSelectedCapa(res.data.capa);
        setShowAddActionModal(false);
        setNewActionDesc('');
        loadCapas();
      }
    } catch (err: any) {
      alert(`Failed to add action: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const getStageIndex = (stageCode: string) => {
    const idx = EIGHT_D_STAGES.findIndex(s => s.id === stageCode || stageCode.includes(s.num));
    return idx >= 0 ? idx : 0;
  };

  const currentStageIndex = selectedCapa ? getStageIndex(selectedCapa.current_stage) : 0;

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 md:p-8 space-y-6 font-sans">
      
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-3 bg-emerald-950/90 border border-emerald-500/50 text-emerald-200 px-5 py-3.5 rounded-xl shadow-2xl backdrop-blur-md animate-in fade-in duration-200">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
        </div>
      )}

      {/* Top Breadcrumb & Navigation */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div className="flex items-center gap-3">
          <Link 
            href="/development"
            className="p-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-bold text-rose-400 uppercase tracking-widest bg-rose-950/80 px-2 py-0.5 rounded border border-rose-800/60">
                8D Corrective Action
              </span>
              <span className="text-xs text-slate-400">/ Resolution Studio</span>
            </div>
            <h1 className="text-2xl font-black text-white tracking-tight mt-1">
              8-Discipline (8D) Problem Solving Workbench
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={() => {
              if (currentStageIndex < EIGHT_D_STAGES.length - 1) {
                setTargetStageToAdvance(EIGHT_D_STAGES[currentStageIndex + 1].id);
                setShowAdvanceModal(true);
              }
            }}
            disabled={currentStageIndex >= EIGHT_D_STAGES.length - 1}
            className="px-4 py-2 rounded-xl text-xs font-bold bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 text-white shadow-lg shadow-cyan-900/40 flex items-center gap-2 transition-all border border-cyan-400/30"
          >
            <ArrowRight className="w-4 h-4" /> Advance 8D Stage
          </button>
          <button 
            onClick={() => setShowAddActionModal(true)}
            className="px-4 py-2 rounded-xl text-xs font-bold bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-700 flex items-center gap-2 transition-colors"
          >
            <Plus className="w-4 h-4 text-rose-400" /> Log 8D Action
          </button>
          <button 
            onClick={loadCapas}
            disabled={loading}
            className="p-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main Grid: Left Dossier List & Right 8D Stepper/Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">

        {/* Left Column: CAPA Cases Drawer (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-4 shadow-xl space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Active CAPA Dossiers ({capasList.length})
              </span>
              <select 
                value={filterSeverity} 
                onChange={(e) => setFilterSeverity(e.target.value)}
                className="text-[11px] bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-slate-300"
              >
                <option value="All">All Severities</option>
                <option value="CRITICAL">Critical</option>
                <option value="MAJOR">Major</option>
                <option value="MINOR">Minor</option>
              </select>
            </div>

            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input 
                type="text" 
                placeholder="Search case, supplier, part..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </div>

            {/* List */}
            <div className="space-y-2 max-h-[750px] overflow-y-auto pr-1">
              {capasList
                .filter(c => {
                  if (filterSeverity !== 'All' && c.severity !== filterSeverity) return false;
                  if (!searchQuery) return true;
                  const q = searchQuery.toLowerCase();
                  return c.title.toLowerCase().includes(q) || 
                         c.id.toLowerCase().includes(q) || 
                         c.supplier_name.toLowerCase().includes(q) || 
                         c.part_number.toLowerCase().includes(q);
                })
                .map((capa) => {
                  const isSelected = selectedCapa?.id === capa.id;
                  return (
                    <div 
                      key={capa.id}
                      onClick={() => {
                        setSelectedCapa(capa);
                        setSelectedStageTab(capa.current_stage);
                      }}
                      className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                        isSelected 
                          ? 'bg-[#0F1E38] border-rose-500/60 shadow-lg shadow-rose-950/20' 
                          : 'bg-[#070B14]/70 border-slate-800/80 hover:bg-slate-900/60 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-mono text-[11px] font-bold text-white">
                          {capa.id}
                        </span>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase ${
                          capa.severity === 'CRITICAL' ? 'bg-rose-950 text-rose-400 border-rose-800' : 'bg-amber-950 text-amber-400 border-amber-800'
                        }`}>
                          {capa.severity}
                        </span>
                      </div>

                      <h4 className="text-xs font-semibold text-slate-200 mt-1 line-clamp-2">
                        {capa.title}
                      </h4>

                      <div className="mt-2 pt-2 border-t border-slate-800/60 flex items-center justify-between text-[11px] text-slate-400">
                        <span>{capa.supplier_name}</span>
                        <span className="font-mono text-cyan-300">{capa.part_number}</span>
                      </div>

                      <div className="mt-2 flex items-center justify-between text-[10px]">
                        <span className="text-slate-500">Stage: {capa.current_stage}</span>
                        <span className="text-rose-400 font-semibold">{capa.days_open}d active</span>
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        </div>

        {/* Right Column: 8D Deep Stepper & Stage Resolution View (8 cols) */}
        <div className="lg:col-span-8 space-y-6">
          {selectedCapa ? (
            <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
              
              {/* Header Info of Selected CAPA */}
              <div className="space-y-3 border-b border-slate-800 pb-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-lg font-black text-white font-mono">{selectedCapa.id}</span>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-bold border uppercase ${
                      selectedCapa.severity === 'CRITICAL' ? 'bg-rose-950 text-rose-400 border-rose-800' : 'bg-amber-950 text-amber-400 border-amber-800'
                    }`}>
                      {selectedCapa.severity} SEVERITY
                    </span>
                    <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-900 text-slate-300 border border-slate-700">
                      Status: {selectedCapa.status}
                    </span>
                  </div>

                  <div className="text-xs text-slate-400">
                    Opened {selectedCapa.opened_date} • Target: <span className="text-white font-medium">{selectedCapa.target_closure_date}</span>
                  </div>
                </div>

                <h2 className="text-lg font-bold text-white">
                  {selectedCapa.title}
                </h2>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs bg-[#070B14]/80 p-3 rounded-xl border border-slate-800">
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase font-bold">Supplier</span>
                    <span className="text-slate-200 font-medium">{selectedCapa.supplier_name}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase font-bold">Part Number / Name</span>
                    <span className="text-cyan-300 font-mono">{selectedCapa.part_number}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase font-bold">Auditor Champion</span>
                    <span className="text-slate-200">{selectedCapa.champion_name}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase font-bold">Supplier Lead</span>
                    <span className="text-slate-200">{selectedCapa.supplier_rep}</span>
                  </div>
                </div>

                <div className="text-xs text-rose-300/90 bg-rose-950/30 border border-rose-800/40 p-2.5 rounded-lg flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                  <span><strong>Flight Risk Impact:</strong> {selectedCapa.risk_impact}</span>
                </div>
              </div>

              {/* 8D Discipline Stepper */}
              <div className="space-y-3">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center justify-between">
                  <span>8-Discipline (8D) Workflow Progression</span>
                  <span className="text-cyan-400 font-mono text-[11px]">
                    Current: Stage {EIGHT_D_STAGES[currentStageIndex]?.num} ({currentStageIndex + 1}/8)
                  </span>
                </span>

                <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
                  {EIGHT_D_STAGES.map((stg, idx) => {
                    const isPassed = idx < currentStageIndex;
                    const isCurrent = idx === currentStageIndex;
                    const isViewing = selectedStageTab.includes(stg.num);

                    return (
                      <button
                        key={stg.id}
                        onClick={() => setSelectedStageTab(stg.id)}
                        className={`p-2.5 rounded-xl border flex flex-col items-center justify-center text-center transition-all ${
                          isViewing
                            ? 'bg-cyan-950/80 border-cyan-400 text-white shadow-md shadow-cyan-950/50'
                            : isPassed
                            ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300 hover:bg-emerald-950/70'
                            : isCurrent
                            ? 'bg-rose-950/50 border-rose-500 text-rose-200 animate-pulse'
                            : 'bg-slate-900/60 border-slate-800 text-slate-500 hover:text-slate-300'
                        }`}
                      >
                        <span className="text-xs font-black font-mono">{stg.num}</span>
                        <span className="text-[10px] font-semibold truncate w-full mt-0.5">{stg.label}</span>
                        {isPassed && <CheckCheck className="w-3 h-3 text-emerald-400 mt-1" />}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Stage Detail Pane */}
              <div className="bg-[#070B14]/90 border border-slate-800 rounded-xl p-5 space-y-5">
                
                {/* D1: Team */}
                {selectedStageTab.includes('D1') && (
                  <div className="space-y-4 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <Users className="w-4 h-4 text-cyan-400" />
                        <h3 className="font-bold text-white text-sm">D1: Cross-Functional 8D Problem Solving Team</h3>
                      </div>
                      <span className="text-xs text-slate-400">Championed by {selectedCapa.champion_name}</span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {selectedCapa.eight_d?.d1_team?.map((mem, i) => (
                        <div key={i} className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 flex items-center justify-between text-xs">
                          <div>
                            <div className="font-bold text-white">{mem.name}</div>
                            <div className="text-slate-400 text-[11px]">{mem.organization}</div>
                          </div>
                          <span className="px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 text-[10px] font-medium">
                            {mem.role}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* D2: Problem Statement */}
                {selectedStageTab.includes('D2') && (
                  <div className="space-y-4 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-amber-400" />
                        <h3 className="font-bold text-white text-sm">D2: 5W2H Problem Statement Definition</h3>
                      </div>
                      <span className="text-xs text-slate-400">AS9100D Metrology Non-Conformance</span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                      <div className="p-3.5 rounded-lg bg-slate-900/80 border border-slate-800 space-y-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase">What Failed?</span>
                        <p className="text-slate-200">{selectedCapa.eight_d?.d2_problem_statement?.what}</p>
                      </div>
                      <div className="p-3.5 rounded-lg bg-slate-900/80 border border-slate-800 space-y-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase">Where Detected?</span>
                        <p className="text-slate-200">{selectedCapa.eight_d?.d2_problem_statement?.where}</p>
                      </div>
                      <div className="p-3.5 rounded-lg bg-slate-900/80 border border-slate-800 space-y-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase">When Observed?</span>
                        <p className="text-slate-200 font-mono">{selectedCapa.eight_d?.d2_problem_statement?.when}</p>
                      </div>
                      <div className="p-3.5 rounded-lg bg-slate-900/80 border border-slate-800 space-y-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase">Magnitude / Defect Rate</span>
                        <p className="text-rose-300 font-medium">{selectedCapa.eight_d?.d2_problem_statement?.magnitude}</p>
                      </div>
                    </div>
                  </div>
                )}

                {/* D3: Containment */}
                {selectedStageTab.includes('D3') && (
                  <div className="space-y-4 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <ShieldAlert className="w-4 h-4 text-rose-400" />
                        <h3 className="font-bold text-white text-sm">D3: Interim Containment Action (ICA) - 24h Stop-Ship</h3>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold">
                          {selectedCapa.eight_d?.d3_interim_containment?.effectiveness_pct ?? 100}% Containment Verified
                        </span>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <span className="text-xs text-slate-400 font-medium">Executed Containment Countermeasures:</span>
                      {selectedCapa.eight_d?.d3_interim_containment?.actions?.map((act, idx) => (
                        <div key={idx} className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 flex items-start gap-3 text-xs">
                          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                          <span className="text-slate-200 leading-relaxed">{act}</span>
                        </div>
                      ))}
                    </div>

                    <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs flex items-center justify-between text-slate-400">
                      <span>Quarantine Lot ID: <strong className="text-white font-mono">{selectedCapa.eight_d?.d3_interim_containment?.quarantine_lot || 'QUAR-2025-BATCH-01'}</strong></span>
                      <span>Verified: {selectedCapa.eight_d?.d3_interim_containment?.containment_date || selectedCapa.opened_date}</span>
                    </div>
                  </div>
                )}

                {/* D4: Root Cause */}
                {selectedStageTab.includes('D4') && (
                  <div className="space-y-4 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <Layers className="w-4 h-4 text-purple-400" />
                        <h3 className="font-bold text-white text-sm">D4: Root Cause Analysis (5-Whys & Escape Point)</h3>
                      </div>
                      <span className="text-xs px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800 font-mono">
                        {selectedCapa.eight_d?.d4_root_cause_analysis?.methodology || '5-Whys / Fishbone'}
                      </span>
                    </div>

                    {selectedCapa.eight_d?.d4_root_cause_analysis?.root_cause_summary && (
                      <div className="p-3.5 rounded-lg bg-purple-950/30 border border-purple-800/40 text-xs">
                        <span className="font-bold text-purple-300 block mb-1">Identified Systemic Root Cause:</span>
                        <p className="text-slate-200">{selectedCapa.eight_d?.d4_root_cause_analysis?.root_cause_summary}</p>
                      </div>
                    )}

                    <div className="space-y-2">
                      <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Iterative 5-Whys Breakdown</span>
                      {selectedCapa.eight_d?.d4_root_cause_analysis?.five_whys?.map((why, idx) => (
                        <div key={idx} className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 text-xs space-y-1">
                          <div className="flex items-center gap-2 font-bold text-cyan-300">
                            <span className="w-5 h-5 rounded-full bg-cyan-950 border border-cyan-800 flex items-center justify-center text-[10px]">
                              {why.level}
                            </span>
                            <span>Why? {why.question}</span>
                          </div>
                          <p className="text-slate-300 pl-7 text-[11px] leading-relaxed">
                            ↳ <em>{why.answer}</em>
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* D5: Permanent Corrective Action */}
                {selectedStageTab.includes('D5') && (
                  <div className="space-y-4 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-indigo-400" />
                        <h3 className="font-bold text-white text-sm">D5: Selected Permanent Corrective Action (PCA)</h3>
                      </div>
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-800 font-semibold">
                        Status: {selectedCapa.eight_d?.d5_permanent_corrective_action?.status || 'IMPLEMENTED'}
                      </span>
                    </div>

                    <div className="space-y-2">
                      <span className="text-xs text-slate-400 font-medium">Selected Engineering & Process Solutions:</span>
                      {selectedCapa.eight_d?.d5_permanent_corrective_action?.selected_pca?.map((pca, idx) => (
                        <div key={idx} className="p-3 rounded-lg bg-slate-900/80 border border-slate-800 flex items-start gap-3 text-xs">
                          <CheckCheck className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                          <span className="text-slate-200">{pca}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* D6: Implementation & Validation */}
                {selectedStageTab.includes('D6') && (
                  <div className="space-y-4 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <Activity className="w-4 h-4 text-cyan-400" />
                        <h3 className="font-bold text-white text-sm">D6: Implementation & Statistical Validation (Cp/Cpk)</h3>
                      </div>
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800 font-semibold">
                        Validation: {selectedCapa.eight_d?.d6_implementation_and_validation?.validation_status || 'VERIFIED'}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                      <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                        <span className="text-slate-500 block text-[10px] uppercase font-bold">Pilot Sample Size</span>
                        <span className="text-lg font-bold text-white">{selectedCapa.eight_d?.d6_implementation_and_validation?.pilot_sample_size || 150} Units</span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                        <span className="text-slate-500 block text-[10px] uppercase font-bold">Statistical Capability Result</span>
                        <span className="text-lg font-bold text-emerald-400">Cpk {selectedCapa.eight_d?.d6_implementation_and_validation?.cpk_result || 1.82}</span>
                      </div>
                      <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                        <span className="text-slate-500 block text-[10px] uppercase font-bold">Signoff Date</span>
                        <span className="text-sm font-mono text-slate-300">{selectedCapa.eight_d?.d6_implementation_and_validation?.verification_date || '2025-03-01'}</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* D7: Recurrence Prevention */}
                {selectedStageTab.includes('D7') && (
                  <div className="space-y-4 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <ShieldCheck className="w-4 h-4 text-teal-400" />
                        <h3 className="font-bold text-white text-sm">D7: Prevention of Recurrence (PFMEA & SOP Institutionalization)</h3>
                      </div>
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-teal-950 text-teal-300 border border-teal-800 font-semibold">
                        Institutionalized
                      </span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                      <div className="p-3.5 rounded-lg bg-slate-900 border border-slate-800 space-y-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase">Standard Operating Procedure</span>
                        <p className="text-teal-300 font-mono font-medium">{selectedCapa.eight_d?.d7_prevention_of_recurrence?.sop_updated || 'SOP-AERO-CAST-882 Rev D'}</p>
                      </div>
                      <div className="p-3.5 rounded-lg bg-slate-900 border border-slate-800 space-y-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase">PFMEA RPN Reduction</span>
                        <p className="text-emerald-400 font-bold">
                          {selectedCapa.eight_d?.d7_prevention_of_recurrence?.pfmea_rpn_initial || 280} → {selectedCapa.eight_d?.d7_prevention_of_recurrence?.pfmea_rpn_revised || 36} (-87% Risk Reduction)
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* D8: Closure & Recognition */}
                {selectedStageTab.includes('D8') && (
                  <div className="space-y-4 animate-in fade-in duration-200">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <CheckCheck className="w-4 h-4 text-emerald-400" />
                        <h3 className="font-bold text-white text-sm">D8: Formal Closure & Team Recognition</h3>
                      </div>
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800 font-semibold">
                        Auditor Signoff
                      </span>
                    </div>

                    <div className="p-4 rounded-lg bg-emerald-950/20 border border-emerald-800/40 text-xs space-y-2">
                      <div className="flex justify-between text-slate-400">
                        <span>Lead Auditor Signoff:</span>
                        <span className="text-emerald-300 font-semibold">{selectedCapa.eight_d?.d8_closure_and_recognition?.signoff_auditor || selectedCapa.champion_name}</span>
                      </div>
                      <div className="flex justify-between text-slate-400">
                        <span>Closure Date:</span>
                        <span className="text-white font-mono">{selectedCapa.eight_d?.d8_closure_and_recognition?.closure_date || 'Pending Final Audit'}</span>
                      </div>
                      <div className="pt-2 border-t border-emerald-800/40 text-slate-300">
                        <strong>Lessons Learned:</strong> {selectedCapa.eight_d?.d8_closure_and_recognition?.lessons_learned || 'Automated sensor feedback integrated into enterprise MES to alert tool wear before tolerance drift occurs.'}
                      </div>
                    </div>
                  </div>
                )}

              </div>
            </div>
          ) : (
            <div className="bg-[#0B1528]/80 border border-slate-800 rounded-2xl p-12 text-center text-slate-500">
              No CAPA selected. Please choose a case from the dossier drawer.
            </div>
          )}
        </div>

      </div>

      {/* Advance 8D Stage Modal */}
      {showAdvanceModal && selectedCapa && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0B1528] border border-slate-700 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <ArrowRight className="w-4 h-4 text-cyan-400" /> Advance 8D Stage
              </h3>
              <button onClick={() => setShowAdvanceModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <p className="text-slate-300">
                You are transitioning CAPA <strong>{selectedCapa.id}</strong> to:
              </p>
              <select 
                value={targetStageToAdvance}
                onChange={(e) => setTargetStageToAdvance(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-cyan-500 font-bold"
              >
                {EIGHT_D_STAGES.map(s => (
                  <option key={s.id} value={s.id}>{s.num}: {s.label} ({s.desc})</option>
                ))}
              </select>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold">Transition Verification Notes / Root Cause Summary</label>
                <textarea 
                  rows={3}
                  placeholder="Detail the supporting evidence, test results, or auditor approval..."
                  value={transitionNotes}
                  onChange={(e) => setTransitionNotes(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
              <button 
                onClick={() => setShowAdvanceModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 text-xs font-semibold"
              >
                Cancel
              </button>
              <button 
                onClick={handleStageTransition}
                disabled={submitting}
                className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-cyan-900/40"
              >
                {submitting ? 'Advancing...' : 'Confirm Transition'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Action Modal */}
      {showAddActionModal && selectedCapa && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0B1528] border border-slate-700 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Plus className="w-4 h-4 text-rose-400" /> Log 8D Countermeasure Action
              </h3>
              <button onClick={() => setShowAddActionModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleAddAction} className="space-y-3 text-xs">
              <div className="space-y-1">
                <label className="text-slate-400 font-semibold">Action Discipline Type</label>
                <select 
                  value={newActionType}
                  onChange={(e) => setNewActionType(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-rose-500"
                >
                  <option value="INTERIM_CONTAINMENT">D3: Interim Containment Action (ICA)</option>
                  <option value="PERMANENT_CORRECTIVE">D5: Permanent Corrective Action (PCA)</option>
                  <option value="PREVENTIVE">D7: Preventive / Systemic Action</option>
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold">Action Description</label>
                <textarea 
                  rows={3}
                  required
                  placeholder="e.g. Ultrasonic inspection protocol deployed at supplier bay 3 with 100% CMM cross-check..."
                  value={newActionDesc}
                  onChange={(e) => setNewActionDesc(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-rose-500"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button 
                  type="button"
                  onClick={() => setShowAddActionModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 text-xs font-semibold"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-rose-900/40"
                >
                  {submitting ? 'Saving...' : 'Append to 8D'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}

export default function CapaWorkbenchPage() {
  return (
    <React.Suspense fallback={
      <div className="min-h-screen bg-[#070B14] text-slate-400 p-8 flex items-center justify-center">
        <div className="flex items-center gap-3 text-sm">
          <div className="w-5 h-5 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
          <span>Loading 8D CAPA Workbench...</span>
        </div>
      </div>
    }>
      <CapaWorkbenchContent />
    </React.Suspense>
  );
}
