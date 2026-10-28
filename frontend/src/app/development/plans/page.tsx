'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { 
  TrendingUp, ArrowLeft, CheckCircle2, Clock, 
  Award, ShieldCheck, Search, Filter, RefreshCw, Plus, 
  CheckCheck, ArrowRight, FileText, ChevronRight, 
  Sparkles, DollarSign, Target, Calendar, UserCheck, X, FileCheck
} from 'lucide-react';
import axios from 'axios';

interface PlanMilestone {
  id: string;
  title: string;
  target_date: string;
  completed_date?: string | null;
  status: string;
  verification_proof?: string | null;
}

interface KpiImprovement {
  metric: string;
  baseline: string;
  current: string;
  target: string;
}

interface AuditLog {
  timestamp: string;
  actor: string;
  action: string;
  notes: string;
}

interface DevPlan {
  id: string;
  title: string;
  supplier_id: string;
  supplier_name: string;
  location: string;
  tier: string;
  focus_area: string;
  focus_color: string;
  lead_auditor: string;
  supplier_lead: string;
  start_date: string;
  target_date: string;
  progress_pct: number;
  status: string;
  strategic_priority: string;
  baseline_metric: string;
  target_metric: string;
  investment_budget_usd: number;
  co_investment_pct: number;
  description: string;
  milestones: PlanMilestone[];
  kpi_improvements: KpiImprovement[];
  audit_logs: AuditLog[];
}

function DevelopmentPlansContent() {
  const searchParams = useSearchParams();
  const initialPlanId = searchParams?.get('id') || null;

  const [plans, setPlans] = useState<DevPlan[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<DevPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [focusFilter, setFocusFilter] = useState('All');

  // Verify Milestone Modal
  const [showVerifyModal, setShowVerifyModal] = useState(false);
  const [selectedMilestone, setSelectedMilestone] = useState<PlanMilestone | null>(null);
  const [verifierName, setVerifierName] = useState('Dr. Klaus Weber (Lead Auditor)');
  const [verificationProof, setVerificationProof] = useState('');
  const [verifyNotes, setVerifyNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const triggerToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4500);
  };

  const loadPlans = async () => {
    setLoading(true);
    try {
      const res = await axios.get('http://127.0.0.1:8080/api/v1/development/plans');
      if (res.data.status === 'success') {
        const items: DevPlan[] = res.data.plans || [];
        setPlans(items);

        if (initialPlanId) {
          const match = items.find(p => p.id === initialPlanId);
          if (match) {
            setSelectedPlan(match);
            return;
          }
        }
        if (items.length > 0 && !selectedPlan) {
          setSelectedPlan(items[0]);
        }
      }
    } catch (err) {
      console.error('Failed to load plans:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPlans();
  }, [initialPlanId]);

  const handleVerifyMilestone = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedPlan || !selectedMilestone || !verificationProof.trim()) return;
    setSubmitting(true);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/development/plans/${selectedPlan.id}/milestones/${selectedMilestone.id}/verify`, {
        verification_proof: verificationProof,
        verifier_name: verifierName,
        notes: verifyNotes
      });

      if (res.data.status === 'success') {
        triggerToast(`Milestone '${selectedMilestone.title}' verified with proof artifact!`);
        setSelectedPlan(res.data.plan);
        setShowVerifyModal(false);
        setVerificationProof('');
        setVerifyNotes('');
        loadPlans();
      }
    } catch (err: any) {
      alert(`Milestone verification failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 md:p-8 space-y-6 font-sans">
      
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-3 bg-emerald-950/90 border border-emerald-500/50 text-emerald-200 px-5 py-3.5 rounded-xl shadow-2xl backdrop-blur-md animate-in fade-in duration-200">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
        </div>
      )}

      {/* Top Breadcrumb & Header */}
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
              <span className="text-xs font-mono font-bold text-cyan-400 uppercase tracking-widest bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-800/60">
                Continuous Development (CDP)
              </span>
              <span className="text-xs text-slate-400">/ Capability Roadmap & Verification</span>
            </div>
            <h1 className="text-2xl font-black text-white tracking-tight mt-1">
              Supplier Capability Upgrade Charters
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Link 
            href="/development/capa"
            className="px-4 py-2 rounded-xl text-xs font-bold bg-slate-900 hover:bg-slate-800 text-rose-300 border border-slate-700 flex items-center gap-2 transition-colors"
          >
            <span>8D CAPA Workbench</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <button 
            onClick={loadPlans}
            disabled={loading}
            className="p-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white border border-slate-800 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main Grid: Left Drawer (4 cols) & Right Detail View (8 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">

        {/* Left Drawer: Plans List (4 cols) */}
        <div className="lg:col-span-4 space-y-4">
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-4 shadow-xl space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Active Charters ({plans.length})
              </span>
              <select 
                value={focusFilter}
                onChange={(e) => setFocusFilter(e.target.value)}
                className="text-[11px] bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-slate-300"
              >
                <option value="All">All Domains</option>
                <option value="Precision">Machining & CMM</option>
                <option value="Quality">Zero Defect / SPC</option>
                <option value="Cyber">Cyber / ITAR</option>
                <option value="ESG">ESG / Metallurgy</option>
              </select>
            </div>

            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input 
                type="text" 
                placeholder="Search plan or supplier..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
            </div>

            {/* List */}
            <div className="space-y-2 max-h-[750px] overflow-y-auto pr-1">
              {plans
                .filter(p => {
                  if (focusFilter !== 'All' && !p.focus_area.toLowerCase().includes(focusFilter.toLowerCase())) return false;
                  if (!searchQuery) return true;
                  const q = searchQuery.toLowerCase();
                  return p.title.toLowerCase().includes(q) || 
                         p.supplier_name.toLowerCase().includes(q) || 
                         p.id.toLowerCase().includes(q);
                })
                .map((plan) => {
                  const isSelected = selectedPlan?.id === plan.id;
                  return (
                    <div 
                      key={plan.id}
                      onClick={() => setSelectedPlan(plan)}
                      className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                        isSelected 
                          ? 'bg-[#0F1E38] border-cyan-500/60 shadow-lg shadow-cyan-950/20' 
                          : 'bg-[#070B14]/70 border-slate-800/80 hover:bg-slate-900/60 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-mono text-[11px] font-bold text-white">
                          {plan.id}
                        </span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800">
                          {plan.progress_pct}%
                        </span>
                      </div>

                      <h4 className="text-xs font-semibold text-slate-200 mt-1 line-clamp-2">
                        {plan.title}
                      </h4>

                      <div className="mt-2 pt-2 border-t border-slate-800/60 flex items-center justify-between text-[11px] text-slate-400">
                        <span className="truncate max-w-[160px]">{plan.supplier_name}</span>
                        <span className="text-slate-500 font-mono text-[10px]">{plan.location}</span>
                      </div>

                      {/* Mini Progress */}
                      <div className="w-full h-1.5 rounded-full bg-slate-900 overflow-hidden mt-2">
                        <div 
                          className="h-full bg-gradient-to-r from-cyan-500 to-blue-500" 
                          style={{ width: `${plan.progress_pct}%` }} 
                        />
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        </div>

        {/* Right Detail Pane (8 cols) */}
        <div className="lg:col-span-8 space-y-6">
          {selectedPlan ? (
            <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
              
              {/* Header Info */}
              <div className="space-y-3 border-b border-slate-800 pb-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-lg font-black text-white font-mono">{selectedPlan.id}</span>
                    <span className="text-xs px-2.5 py-0.5 rounded-full font-bold bg-cyan-950 text-cyan-300 border border-cyan-800 uppercase">
                      {selectedPlan.strategic_priority} PRIORITY
                    </span>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full border ${
                      selectedPlan.status === 'COMPLETED' ? 'bg-emerald-950 text-emerald-300 border-emerald-800' : 'bg-slate-900 text-slate-300 border-slate-700'
                    }`}>
                      {selectedPlan.status}
                    </span>
                  </div>

                  <div className="text-xs text-slate-400">
                    Target Completion: <strong className="text-white font-mono">{selectedPlan.target_date}</strong>
                  </div>
                </div>

                <h2 className="text-lg font-bold text-white">
                  {selectedPlan.title}
                </h2>

                <p className="text-xs text-slate-300 leading-relaxed">
                  {selectedPlan.description}
                </p>

                {/* Metadata Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs bg-[#070B14]/80 p-3 rounded-xl border border-slate-800">
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase font-bold">Supplier</span>
                    <span className="text-slate-200 font-medium">{selectedPlan.supplier_name}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase font-bold">Lead Auditor</span>
                    <span className="text-slate-200">{selectedPlan.lead_auditor}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase font-bold">Total Investment</span>
                    <span className="text-cyan-300 font-mono font-bold">${(selectedPlan.investment_budget_usd / 1000).toFixed(0)}k USD</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase font-bold">OEM Co-Investment</span>
                    <span className="text-emerald-400 font-semibold">{selectedPlan.co_investment_pct}% Cost Share</span>
                  </div>
                </div>
              </div>

              {/* Capability Benchmark Comparison */}
              <div className="space-y-3">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Quantitative Capability Transformation Target
                </span>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                    <span className="text-[10px] font-bold text-slate-500 uppercase">Baseline State (Pre-Investment)</span>
                    <p className="text-sm font-semibold text-slate-300">{selectedPlan.baseline_metric}</p>
                  </div>
                  <div className="p-4 rounded-xl bg-cyan-950/30 border border-cyan-800/50 space-y-1">
                    <span className="text-[10px] font-bold text-cyan-400 uppercase">Target State (Validated Capability)</span>
                    <p className="text-sm font-semibold text-emerald-400">{selectedPlan.target_metric}</p>
                  </div>
                </div>
              </div>

              {/* Milestone Tracker & Verification Proof Drawer */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                    <CheckCheck className="w-4 h-4 text-cyan-400" />
                    Structured Milestones & Proof of Completion ({selectedPlan.milestones.length})
                  </span>
                  <div className="text-xs text-cyan-300 font-mono">
                    Progress: {selectedPlan.progress_pct}%
                  </div>
                </div>

                <div className="space-y-3">
                  {selectedPlan.milestones.map((m, idx) => {
                    const isCompleted = m.status === 'COMPLETED';

                    return (
                      <div 
                        key={m.id}
                        className={`p-4 rounded-xl border transition-all flex flex-col md:flex-row md:items-center justify-between gap-4 ${
                          isCompleted 
                            ? 'bg-emerald-950/20 border-emerald-800/50' 
                            : 'bg-slate-900/60 border-slate-800'
                        }`}
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-bold text-slate-400">{m.id}</span>
                            <span className="text-xs font-bold text-white">{m.title}</span>
                            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                              isCompleted ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-slate-800 text-slate-400'
                            }`}>
                              {m.status}
                            </span>
                          </div>

                          <div className="text-[11px] text-slate-400 flex items-center gap-4">
                            <span>Target Date: {m.target_date}</span>
                            {m.completed_date && (
                              <span className="text-emerald-400 font-medium">Completed: {m.completed_date}</span>
                            )}
                          </div>

                          {m.verification_proof && (
                            <div className="text-xs text-cyan-300 flex items-center gap-1.5 pt-1">
                              <FileCheck className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                              <span className="font-mono text-[11px]">Proof: {m.verification_proof}</span>
                            </div>
                          )}
                        </div>

                        {/* Action CTA */}
                        <div>
                          {isCompleted ? (
                            <div className="flex items-center gap-1.5 text-xs text-emerald-400 font-semibold px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-800/50">
                              <CheckCircle2 className="w-4 h-4" />
                              <span>Verified</span>
                            </div>
                          ) : (
                            <button
                              onClick={() => {
                                setSelectedMilestone(m);
                                setShowVerifyModal(true);
                              }}
                              className="px-3.5 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow-md shadow-cyan-900/40 transition-all"
                            >
                              <FileCheck className="w-3.5 h-3.5" />
                              <span>Verify Milestone</span>
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Audit Trail Log */}
              {selectedPlan.audit_logs && selectedPlan.audit_logs.length > 0 && (
                <div className="space-y-3 pt-3 border-t border-slate-800">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                    Immutable Verification Audit Trail
                  </span>
                  <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                    {selectedPlan.audit_logs.map((log, i) => (
                      <div key={i} className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 text-[11px] flex items-start justify-between gap-3">
                        <div>
                          <span className="font-bold text-slate-200">{log.action}</span>
                          <p className="text-slate-400 mt-0.5">{log.notes}</p>
                          <span className="text-slate-500 text-[10px]">{log.actor}</span>
                        </div>
                        <span className="font-mono text-[10px] text-slate-500 shrink-0">
                          {log.timestamp.slice(0, 16).replace('T', ' ')}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

            </div>
          ) : (
            <div className="bg-[#0B1528]/80 border border-slate-800 rounded-2xl p-12 text-center text-slate-500">
              No plan selected. Please choose a charter from the list.
            </div>
          )}
        </div>

      </div>

      {/* Verify Milestone Modal */}
      {showVerifyModal && selectedMilestone && selectedPlan && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0B1528] border border-slate-700 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <FileCheck className="w-4 h-4 text-cyan-400" /> Verify Milestone Proof
              </h3>
              <button onClick={() => setShowVerifyModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleVerifyMilestone} className="space-y-3 text-xs">
              <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                <span className="text-slate-500 block text-[10px] uppercase font-bold">Milestone</span>
                <span className="text-white font-bold">{selectedMilestone.id}: {selectedMilestone.title}</span>
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold">Verification Proof Artifact / Document Ref</label>
                <input 
                  type="text" 
                  required
                  placeholder="e.g. Installation signoff report #INST-HERMLE-4491 or Zeiss Cal Cert #882"
                  value={verificationProof}
                  onChange={(e) => setVerificationProof(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold">Lead Auditor / Verifier Name</label>
                <input 
                  type="text" 
                  required
                  value={verifierName}
                  onChange={(e) => setVerifierName(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold">Auditor Field Notes</label>
                <textarea 
                  rows={3}
                  placeholder="Physical verification conducted on-site; equipment meets tolerance requirements..."
                  value={verifyNotes}
                  onChange={(e) => setVerifyNotes(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button 
                  type="button"
                  onClick={() => setShowVerifyModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 text-xs font-semibold"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-cyan-900/40"
                >
                  {submitting ? 'Verifying...' : 'Submit Verification'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}

export default function DevelopmentPlansPage() {
  return (
    <React.Suspense fallback={
      <div className="min-h-screen bg-[#070B14] text-slate-400 p-8 flex items-center justify-center">
        <div className="flex items-center gap-3 text-sm">
          <div className="w-5 h-5 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
          <span>Loading Development Plans Roadmap...</span>
        </div>
      </div>
    }>
      <DevelopmentPlansContent />
    </React.Suspense>
  );
}
