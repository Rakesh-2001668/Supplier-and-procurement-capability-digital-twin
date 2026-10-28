'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Building2, CheckCircle2, ShieldCheck, ShieldAlert, ArrowRight,
  Sparkles, Layers, Box, FileText, ShoppingCart, Target, Scale, 
  DollarSign, RefreshCw, ExternalLink, Activity, AlertTriangle, 
  Clock, Send, Check, X, ChevronRight, Sliders, Info, Shield, 
  TrendingUp, Users, AlertCircle, FileCheck2, FileWarning
} from 'lucide-react';

interface KraljicCategory {
  id: string;
  name: string;
  code: string;
  quadrant: 'STRATEGIC' | 'LEVERAGE' | 'BOTTLENECK' | 'ROUTINE';
  annual_spend_inr_cr: number;
  supply_risk_score: number;
  profit_impact_score: number;
  primary_suppliers: string[];
  strategic_levers: string[];
  action_wave: string;
  target_savings_inr_cr: number;
  contract_coverage_pct: number;
}

interface ExpeditingItem {
  id: string;
  po_number: string;
  line_no: number;
  item_description: string;
  supplier_name: string;
  supplier_id: string;
  plant: string;
  ordered_qty: number;
  unit: string;
  need_date: string;
  promised_date: string;
  late_delivery_prob: number;
  risk_level: string;
  transit_status: string;
  asn_number?: string | null;
  carrier_name: string;
  gps_corridor: string;
  delay_hours: number;
  escalation_status: string;
  last_ping_at: string;
}

interface ServiceEntrySheet {
  ses_id: string;
  po_number: string;
  po_line_no: number;
  vendor_name: string;
  vendor_id: string;
  service_title: string;
  compensation_type: string;
  service_period: string;
  service_owner_role: string;
  po_creator: string;
  candidate_approver: string;
  contracted_rate_inr_hr?: number | null;
  timesheet_hours_billed?: number | null;
  total_amount_inr: number;
  progress_pct: number;
  rate_card_compliant: boolean;
  status: string;
  approved_by?: string | null;
  approved_at?: string | null;
  retention_amount_inr?: number | null;
  advance_recovery_inr?: number | null;
  net_payable_inr?: number | null;
}

interface RedlineClause {
  clause_id: string;
  title: string;
  risk_rating: string;
  playbook_position: string;
  supplier_proposed: string;
  deviation_summary: string;
  fallback_suggestion: string;
  status: string;
}

export default function SpecializedWorkbenchesPage() {
  const [activeTab, setActiveTab] = useState<'KRALJIC' | 'EXPEDITING' | 'SES' | 'REDLINE'>('KRALJIC');
  
  // Data States
  const [kraljicData, setKraljicData] = useState<any>(null);
  const [expeditingItems, setExpeditingItems] = useState<ExpeditingItem[]>([]);
  const [sesItems, setSesItems] = useState<ServiceEntrySheet[]>([]);
  const [redlineData, setRedlineData] = useState<any>(null);
  
  // Modals & Action States
  const [selectedExpediteItem, setSelectedExpediteItem] = useState<ExpeditingItem | null>(null);
  const [escalationTier, setEscalationTier] = useState<string>('TIER_1_STANDARD');
  const [escalateMessage, setEscalateMessage] = useState<string>('');
  const [revisedEta, setRevisedEta] = useState<string>('');
  
  const [selectedSes, setSelectedSes] = useState<ServiceEntrySheet | null>(null);
  const [sesApproverActor, setSesApproverActor] = useState<string>('u:project.manager.site');
  
  const [toast, setToast] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4500);
  };

  const loadAllWorkbenchData = async () => {
    try {
      // 1. Kraljic
      const resK = await fetch('http://127.0.0.1:8080/api/v1/workbenches/kraljic');
      if (resK.ok) setKraljicData(await resK.json());

      // 2. Expediting
      const resE = await fetch('http://127.0.0.1:8080/api/v1/workbenches/expediting');
      if (resE.ok) {
        const dE = await resE.json();
        setExpeditingItems(dE.expediting_items || []);
      }

      // 3. SES
      const resS = await fetch('http://127.0.0.1:8080/api/v1/workbenches/service-entries');
      if (resS.ok) {
        const dS = await resS.json();
        setSesItems(dS.service_entries || []);
      }

      // 4. Redline
      const resR = await fetch('http://127.0.0.1:8080/api/v1/workbenches/clause-redline/SA-5520');
      if (resR.ok) {
        const dR = await resR.json();
        setRedlineData(dR.redline_workspace || null);
      }
    } catch (e) {
      console.error("Error loading workbench data", e);
    }
  };

  useEffect(() => {
    loadAllWorkbenchData();
  }, []);

  // Expediting Escalation Handler
  const handleExecuteEscalation = async () => {
    if (!selectedExpediteItem) return;
    setActionLoading(true);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/workbenches/expediting/${selectedExpediteItem.po_number}/escalate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          escalation_tier: escalationTier,
          contact_email: `supply-chain@${selectedExpediteItem.supplier_id.toLowerCase()}.com`,
          message: escalateMessage || `Urgent expediting notice dispatched for ${selectedExpediteItem.po_number}.`,
          requested_revised_eta: revisedEta || selectedExpediteItem.promised_date,
          actor: 'u:buyer.hosur'
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(data.message);
        setSelectedExpediteItem(null);
        await loadAllWorkbenchData();
      } else {
        showToast("Failed to dispatch escalation notice.");
      }
    } catch {
      showToast("Network error submitting escalation.");
    } finally {
      setActionLoading(false);
    }
  };

  // SES Approval Handler with SOD-03 Test
  const handleSesDecision = async (sesId: string, decision: 'APPROVE' | 'REJECT', actor: string) => {
    setActionLoading(true);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/workbenches/service-entries/${sesId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: decision,
          actor: actor,
          comments: `SES ${decision} certified via RCV-03 Console`,
          measured_work_quality: 'SATISFACTORY'
        })
      });
      const data = await res.json();
      if (res.ok) {
        showToast(data.message);
        setSelectedSes(null);
        await loadAllWorkbenchData();
      } else {
        showToast(`Blocked: ${data.detail || 'SoD Conflict'}`);
      }
    } catch {
      showToast("Error processing Service Entry Sheet.");
    } finally {
      setActionLoading(false);
    }
  };

  // Clause Redline Decision Handler
  const handleClauseDecision = async (clauseId: string, decision: string) => {
    setActionLoading(true);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/workbenches/clause-redline/SA-5520/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clause_id: clauseId,
          decision: decision,
          actor: 'u:legal.counsel.corporate',
          justification: `Decision ${decision} recorded via CLM-02 Redline Studio`
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(data.message);
        await loadAllWorkbenchData();
      } else {
        showToast("Error recording clause decision.");
      }
    } catch {
      showToast("Network error updating clause.");
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 flex flex-col font-sans">
      {/* Toast Notification */}
      {toast && (
        <div className="fixed top-6 right-6 z-50 bg-cyan-950 border border-cyan-500/60 text-cyan-200 px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 text-xs font-semibold animate-fade-in">
          <Sparkles className="w-4 h-4 text-cyan-400 animate-spin" />
          <span>{toast}</span>
        </div>
      )}

      {/* Header Bar */}
      <div className="bg-[#0B1528] border-b border-slate-800/80 px-8 py-6 shrink-0">
        <div className="max-w-[1700px] mx-auto flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-cyan-400 font-bold mb-1">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
              <span>AlphaHelion Strategic & Operational Modules</span>
              <span className="text-slate-600">•</span>
              <span>Blueprint Section 30 Screen Catalogue</span>
            </div>
            <h1 className="text-2xl lg:text-3xl font-bold font-mono text-white tracking-tight flex items-center gap-3">
              Specialized High-Impact Workbenches
              <span className="text-xs font-sans font-bold bg-purple-500/10 text-purple-300 border border-purple-500/30 px-3 py-1 rounded-full">
                4 Specialist Consoles
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-3xl">
              Enterprise workbenches delivering Kraljic portfolio matrix optimization, predictive PO expediting, 
              governed Service Entry Sheet (SES) approvals, and AI-powered contract redline review.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/command-centre"
              className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-700/80 hover:border-cyan-500/50 text-xs font-bold text-slate-300 hover:text-white transition flex items-center gap-2"
            >
              <span>📡</span> CPO Command Centre
            </Link>
            <Link
              href="/industry-templates"
              className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-700/80 hover:border-blue-500/50 text-xs font-bold text-slate-300 hover:text-white transition flex items-center gap-2"
            >
              <span>🏭</span> Industry Packs
            </Link>
          </div>
        </div>

        {/* WORKBENCH TAB SELECTOR */}
        <div className="max-w-[1700px] mx-auto mt-6 pt-3 border-t border-slate-800/80 flex items-center gap-3 overflow-x-auto">
          {[
            { id: 'KRALJIC', label: 'SPD-07: Kraljic Portfolio Matrix', icon: '📊', sub: 'Category Strategy & Levers' },
            { id: 'EXPEDITING', label: 'PO-04: Predictive Expediting', icon: '⏱️', sub: 'ML Late Risk & Escalations' },
            { id: 'SES', label: 'RCV-03: Service Entry Sheets (SES)', icon: '📝', sub: 'Timesheets, Milestones & SoD' },
            { id: 'REDLINE', label: 'CLM-02: AI Clause Redline Studio', icon: '⚖️', sub: 'Playbook Deviation & Fallbacks' }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-4 py-2.5 rounded-xl text-left transition-all border shrink-0 flex items-center gap-3 ${
                activeTab === tab.id
                  ? 'bg-gradient-to-r from-cyan-950 to-blue-950 border-cyan-400 text-white shadow-lg shadow-cyan-950/40 ring-1 ring-cyan-400'
                  : 'bg-slate-900/60 hover:bg-slate-800/80 border-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              <span className="text-xl p-1 bg-slate-950/60 rounded-lg border border-slate-800">{tab.icon}</span>
              <div>
                <div className={`text-xs font-bold font-mono ${activeTab === tab.id ? 'text-cyan-300' : 'text-slate-200'}`}>
                  {tab.label}
                </div>
                <div className="text-[10px] text-slate-400 font-sans">
                  {tab.sub}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 p-6 lg:p-8 max-w-[1700px] mx-auto w-full flex flex-col gap-6">

        {/* ==================================================================== */}
        {/* TAB 1: SPD-07 KRALJIC PORTFOLIO MATRIX & STRATEGY WORKBENCH          */}
        {/* ==================================================================== */}
        {activeTab === 'KRALJIC' && (
          <div className="space-y-6">
            {/* Top Summary Banner */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-5 bg-[#0B1528] border border-slate-800 rounded-2xl flex flex-col justify-between">
                <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Spend Under Management</span>
                <div className="text-2xl font-black font-mono text-cyan-300 mt-2">
                  ₹{kraljicData?.portfolio_summary?.total_spend_under_management_cr || 117.79} Cr
                </div>
                <span className="text-[10px] text-slate-400 mt-1 font-mono">Aggregated across all 4 procurement quadrants</span>
              </div>
              <div className="p-5 bg-[#0B1528] border border-slate-800 rounded-2xl flex flex-col justify-between">
                <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Targeted Portfolio Savings</span>
                <div className="text-2xl font-black font-mono text-emerald-400 mt-2">
                  ₹{kraljicData?.portfolio_summary?.total_target_savings_cr || 3.34} Cr
                </div>
                <span className="text-[10px] text-emerald-300/80 mt-1 font-mono">Governed sourcing pipeline (Wave 1 to Wave 3)</span>
              </div>
              <div className="p-5 bg-[#0B1528] border border-slate-800 rounded-2xl flex flex-col justify-between">
                <span className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Tracked Categories</span>
                <div className="text-2xl font-black font-mono text-purple-300 mt-2">
                  {kraljicData?.portfolio_summary?.total_categories_tracked || 4} Core Commodities
                </div>
                <span className="text-[10px] text-purple-400/80 mt-1 font-mono">Dual-dimension: Supply Risk vs Profit Impact</span>
              </div>
            </div>

            {/* 2x2 KRALJIC MATRIX GRID */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              
              {/* QUADRANT 1: STRATEGIC (High Spend, High Risk) */}
              <div className="p-6 bg-[#0B1528] border-2 border-red-500/40 rounded-2xl flex flex-col justify-between relative overflow-hidden">
                <div className="absolute top-0 right-0 px-3 py-1 bg-red-500/20 text-red-300 border-b border-l border-red-500/40 text-[10px] font-mono font-bold rounded-bl-xl uppercase">
                  Strategic (High Risk • High Impact)
                </div>
                <div>
                  <div className="text-xs font-mono font-bold text-red-400 uppercase tracking-wider mb-1">
                    Quadrant A • Collaborative Partnership
                  </div>
                  <h3 className="text-lg font-bold text-white mb-2">
                    Die-Cast Aluminium Motor Housings (41-CASTINGS)
                  </h3>
                  <div className="flex items-center gap-4 text-xs font-mono text-slate-300 mb-4">
                    <span>Spend: <strong className="text-cyan-300 font-bold">₹43.29 Cr</strong></span>
                    <span>•</span>
                    <span>Risk: <strong className="text-red-400 font-bold">88/100</strong></span>
                    <span>•</span>
                    <span>Impact: <strong className="text-red-400 font-bold">94/100</strong></span>
                  </div>

                  <div className="space-y-3">
                    <div className="text-[11px] font-bold text-slate-300 uppercase font-mono">Core Strategic Levers:</div>
                    <ul className="space-y-1.5 text-xs text-slate-300">
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-red-400 shrink-0" />
                        <span>Long-term Scheduling Agreement SA-5520 with quarterly LME deadband</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-red-400 shrink-0" />
                        <span>MIP-optimized 60/40 capacity dual sourcing (Trichy Forge + Kovai Diecast)</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-red-400 shrink-0" />
                        <span>Continuous machine IIoT digital twin surveillance</span>
                      </li>
                    </ul>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between text-xs">
                  <span className="text-slate-400">Target Savings: <strong className="text-emerald-400 font-mono">₹0.99 Cr/yr</strong></span>
                  <Link href="/sourcing" className="text-cyan-400 font-bold hover:underline flex items-center gap-1">
                    <span>Open Sourcing MIP</span> <ChevronRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>

              {/* QUADRANT 2: LEVERAGE (High Spend, Low Risk) */}
              <div className="p-6 bg-[#0B1528] border-2 border-emerald-500/40 rounded-2xl flex flex-col justify-between relative overflow-hidden">
                <div className="absolute top-0 right-0 px-3 py-1 bg-emerald-500/20 text-emerald-300 border-b border-l border-emerald-500/40 text-[10px] font-mono font-bold rounded-bl-xl uppercase">
                  Leverage (Low Risk • High Impact)
                </div>
                <div>
                  <div className="text-xs font-mono font-bold text-emerald-400 uppercase tracking-wider mb-1">
                    Quadrant B • Competitive Bidding & Aggregation
                  </div>
                  <h3 className="text-lg font-bold text-white mb-2">
                    Primary Aluminium Ingots EN AC-46000 (10-RAW-METALS)
                  </h3>
                  <div className="flex items-center gap-4 text-xs font-mono text-slate-300 mb-4">
                    <span>Spend: <strong className="text-cyan-300 font-bold">₹61.50 Cr</strong></span>
                    <span>•</span>
                    <span>Risk: <strong className="text-emerald-400 font-bold">32/100</strong></span>
                    <span>•</span>
                    <span>Impact: <strong className="text-emerald-400 font-bold">89/100</strong></span>
                  </div>

                  <div className="space-y-3">
                    <div className="text-[11px] font-bold text-slate-300 uppercase font-mono">Core Strategic Levers:</div>
                    <ul className="space-y-1.5 text-xs text-slate-300">
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                        <span>Multi-round electronic reverse auctions across primary smelters</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                        <span>Volume pooling between Hosur (P100) and Chennai (P200) plants</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                        <span>Cash discount payment optimization (2/10 Net 30)</span>
                      </li>
                    </ul>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between text-xs">
                  <span className="text-slate-400">Target Savings: <strong className="text-emerald-400 font-mono">₹1.85 Cr/yr</strong></span>
                  <Link href="/spend/cube" className="text-cyan-400 font-bold hover:underline flex items-center gap-1">
                    <span>Explore Spend Cube</span> <ChevronRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>

              {/* QUADRANT 3: BOTTLENECK (Low Spend, High Risk) */}
              <div className="p-6 bg-[#0B1528] border-2 border-amber-500/40 rounded-2xl flex flex-col justify-between relative overflow-hidden">
                <div className="absolute top-0 right-0 px-3 py-1 bg-amber-500/20 text-amber-300 border-b border-l border-amber-500/40 text-[10px] font-mono font-bold rounded-bl-xl uppercase">
                  Bottleneck (High Risk • Low Impact)
                </div>
                <div>
                  <div className="text-xs font-mono font-bold text-amber-400 uppercase tracking-wider mb-1">
                    Quadrant C • Security of Supply & Substitution
                  </div>
                  <h3 className="text-lg font-bold text-white mb-2">
                    High-Temp Neodymium Rotor Magnets (48-MAGNETS)
                  </h3>
                  <div className="flex items-center gap-4 text-xs font-mono text-slate-300 mb-4">
                    <span>Spend: <strong className="text-cyan-300 font-bold">₹4.80 Cr</strong></span>
                    <span>•</span>
                    <span>Risk: <strong className="text-amber-400 font-bold">92/100</strong></span>
                    <span>•</span>
                    <span>Impact: <strong className="text-amber-400 font-bold">38/100</strong></span>
                  </div>

                  <div className="space-y-3">
                    <div className="text-[11px] font-bold text-slate-300 uppercase font-mono">Core Strategic Levers:</div>
                    <ul className="space-y-1.5 text-xs text-slate-300">
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                        <span>Safety buffer expansion from 2 to 6 weeks on-hand stock</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                        <span>Engineering R&D substitution to reduce dysprosium content</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                        <span>Supplier co-investment in custom sintered tooling</span>
                      </li>
                    </ul>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between text-xs">
                  <span className="text-slate-400">Target Savings: <strong className="text-emerald-400 font-mono">₹0.15 Cr/yr</strong></span>
                  <Link href="/development" className="text-cyan-400 font-bold hover:underline flex items-center gap-1">
                    <span>Supplier Development</span> <ChevronRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>

              {/* QUADRANT 4: ROUTINE (Low Spend, Low Risk) */}
              <div className="p-6 bg-[#0B1528] border-2 border-blue-500/40 rounded-2xl flex flex-col justify-between relative overflow-hidden">
                <div className="absolute top-0 right-0 px-3 py-1 bg-blue-500/20 text-blue-300 border-b border-l border-blue-500/40 text-[10px] font-mono font-bold rounded-bl-xl uppercase">
                  Routine (Low Risk • Low Impact)
                </div>
                <div>
                  <div className="text-xs font-mono font-bold text-blue-400 uppercase tracking-wider mb-1">
                    Quadrant D • Process Automation & Catalogues
                  </div>
                  <h3 className="text-lg font-bold text-white mb-2">
                    Standard Metric High-Tensile Fasteners (52-FASTENERS)
                  </h3>
                  <div className="flex items-center gap-4 text-xs font-mono text-slate-300 mb-4">
                    <span>Spend: <strong className="text-cyan-300 font-bold">₹8.20 Cr</strong></span>
                    <span>•</span>
                    <span>Risk: <strong className="text-blue-400 font-bold">15/100</strong></span>
                    <span>•</span>
                    <span>Impact: <strong className="text-blue-400 font-bold">22/100</strong></span>
                  </div>

                  <div className="space-y-3">
                    <div className="text-[11px] font-bold text-slate-300 uppercase font-mono">Core Strategic Levers:</div>
                    <ul className="space-y-1.5 text-xs text-slate-300">
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                        <span>Hosted e-catalogues with punch-out cart integration</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                        <span>Touchless PO release below ₹25,000 threshold (DMN-02)</span>
                      </li>
                      <li className="flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                        <span>Automated 2-way invoice matching and monthly consolidated bills</span>
                      </li>
                    </ul>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between text-xs">
                  <span className="text-slate-400">Target Savings: <strong className="text-emerald-400 font-mono">₹0.35 Cr/yr</strong></span>
                  <Link href="/p2p" className="text-cyan-400 font-bold hover:underline flex items-center gap-1">
                    <span>Guided Buying Cockpit</span> <ChevronRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>

            </div>
          </div>
        )}

        {/* ==================================================================== */}
        {/* TAB 2: PO-04 PREDICTIVE EXPEDITING COCKPIT                            */}
        {/* ==================================================================== */}
        {activeTab === 'EXPEDITING' && (
          <div className="space-y-6">
            <div className="p-5 bg-[#0B1528] border border-slate-800 rounded-2xl flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold font-mono text-white flex items-center gap-2">
                  <Clock className="w-4 h-4 text-cyan-400" />
                  <span>PO-04: Predictive Open Order Expediting Queue</span>
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  Machine learning model tracks late-delivery probability based on supplier OTIF history, GPS corridors, and customs clearance status.
                </p>
              </div>
              <div className="text-xs font-mono text-cyan-400 bg-cyan-950/80 border border-cyan-500/40 px-3 py-1.5 rounded-xl font-bold">
                Algorithm: ML Classifier (Late Prob &gt; 30% Escalation Gate)
              </div>
            </div>

            {/* Expediting Table */}
            <div className="bg-[#0B1528] border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-900/90 text-slate-400 font-mono uppercase text-[10px] border-b border-slate-800">
                    <tr>
                      <th className="p-3.5">PO & Line</th>
                      <th className="p-3.5">Item & Description</th>
                      <th className="p-3.5">Supplier & Plant</th>
                      <th className="p-3.5">Need Date</th>
                      <th className="p-3.5">Late Risk Prob</th>
                      <th className="p-3.5">Transit & Corridor</th>
                      <th className="p-3.5">Escalation Status</th>
                      <th className="p-3.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/80">
                    {expeditingItems.map((item) => (
                      <tr key={item.id} className="hover:bg-slate-900/50 transition-colors">
                        <td className="p-3.5 font-mono font-bold text-cyan-300">
                          {item.po_number}
                          <span className="text-[10px] text-slate-500 block">Line #{item.line_no}</span>
                        </td>
                        <td className="p-3.5 font-medium text-white max-w-[220px]">
                          {item.item_description}
                          <span className="text-[10px] text-slate-400 block font-mono">Qty: {item.ordered_qty} {item.unit}</span>
                        </td>
                        <td className="p-3.5 text-slate-300">
                          {item.supplier_name}
                          <span className="text-[10px] text-slate-500 block font-mono">{item.plant}</span>
                        </td>
                        <td className="p-3.5 font-mono text-slate-300">
                          {item.need_date}
                          <span className="text-[10px] text-amber-400 block">Promised: {item.promised_date}</span>
                        </td>
                        <td className="p-3.5 font-mono">
                          <div className="flex items-center gap-2">
                            <span className={`font-bold ${
                              item.late_delivery_prob >= 0.50 ? 'text-red-400' :
                              item.late_delivery_prob >= 0.30 ? 'text-amber-400' : 'text-emerald-400'
                            }`}>
                              {(item.late_delivery_prob * 100).toFixed(0)}%
                            </span>
                            <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                              item.risk_level.includes('CRITICAL') ? 'bg-red-500/20 text-red-300 border border-red-500/40' :
                              item.risk_level.includes('MODERATE') ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' :
                              'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                            }`}>
                              {item.risk_level}
                            </span>
                          </div>
                        </td>
                        <td className="p-3.5 text-xs text-slate-300 max-w-[200px]">
                          <span className="font-bold text-white block">{item.transit_status}</span>
                          <span className="text-[10px] text-slate-400 block truncate">{item.gps_corridor}</span>
                        </td>
                        <td className="p-3.5 font-mono text-[11px]">
                          <span className="text-cyan-300 font-bold bg-slate-900 px-2 py-1 rounded border border-slate-800">
                            {item.escalation_status}
                          </span>
                        </td>
                        <td className="p-3.5 text-right">
                          <button
                            onClick={() => {
                              setSelectedExpediteItem(item);
                              setRevisedEta(item.promised_date);
                            }}
                            className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-amber-600 to-red-600 hover:from-amber-500 hover:to-red-500 text-white font-bold text-xs shadow-md transition flex items-center gap-1.5 ml-auto"
                          >
                            <Send className="w-3 h-3" />
                            <span>Escalate</span>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Escalation Modal */}
            {selectedExpediteItem && (
              <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                <div className="bg-[#0B1528] border border-slate-700 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4 animate-fade-in">
                  <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="w-5 h-5 text-amber-400" />
                      <h3 className="text-base font-bold text-white font-mono">
                        Expedite Order {selectedExpediteItem.po_number}
                      </h3>
                    </div>
                    <button onClick={() => setSelectedExpediteItem(null)} className="text-slate-400 hover:text-white">
                      <X className="w-5 h-5" />
                    </button>
                  </div>

                  <div className="text-xs text-slate-300 space-y-2">
                    <div>Supplier: <strong className="text-white">{selectedExpediteItem.supplier_name}</strong></div>
                    <div>Item: <strong className="text-cyan-300">{selectedExpediteItem.item_description}</strong></div>
                    <div>Late Probability: <strong className="text-red-400 font-mono">{(selectedExpediteItem.late_delivery_prob * 100).toFixed(0)}%</strong></div>
                  </div>

                  <div>
                    <label className="text-[11px] font-bold text-slate-400 uppercase font-mono block mb-1">
                      Escalation Severity Tier
                    </label>
                    <select
                      value={escalationTier}
                      onChange={(e) => setEscalationTier(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white"
                    >
                      <option value="TIER_1_STANDARD">Tier 1: Standard Expedite Notice to Dispatcher</option>
                      <option value="TIER_2_EXECUTIVE">Tier 2: Executive Escalation to VP of Operations</option>
                      <option value="TIER_3_CARRIER_SWAP">Tier 3: Emergency Air-Freight / Carrier Swap</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-[11px] font-bold text-slate-400 uppercase font-mono block mb-1">
                      Requested Commitment Date (Revised ETA)
                    </label>
                    <input
                      type="date"
                      value={revisedEta}
                      onChange={(e) => setRevisedEta(e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white font-mono"
                    />
                  </div>

                  <div>
                    <label className="text-[11px] font-bold text-slate-400 uppercase font-mono block mb-1">
                      Escalation Directive & Context
                    </label>
                    <textarea
                      rows={3}
                      value={escalateMessage}
                      onChange={(e) => setEscalateMessage(e.target.value)}
                      placeholder="Specify critical plant production impact, customs hold documentation, or carrier priority..."
                      className="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-xs text-white"
                    />
                  </div>

                  <div className="pt-3 border-t border-slate-800 flex items-center justify-end gap-3">
                    <button
                      onClick={() => setSelectedExpediteItem(null)}
                      className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-xs font-bold text-slate-300"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleExecuteEscalation}
                      disabled={actionLoading}
                      className="px-5 py-2 rounded-xl bg-gradient-to-r from-amber-600 to-red-600 hover:from-amber-500 text-xs font-bold text-white shadow-lg flex items-center gap-2"
                    >
                      <Send className="w-3.5 h-3.5" />
                      <span>{actionLoading ? 'Dispatching...' : 'Dispatch Expedite Notice'}</span>
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ==================================================================== */}
        {/* TAB 3: RCV-03 SERVICE ENTRY SHEET (SES) CONSOLE                      */}
        {/* ==================================================================== */}
        {activeTab === 'SES' && (
          <div className="space-y-6">
            <div className="p-5 bg-[#0B1528] border border-slate-800 rounded-2xl flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold font-mono text-white flex items-center gap-2">
                  <FileCheck2 className="w-4 h-4 text-emerald-400" />
                  <span>RCV-03: Service Entry Sheet (SES) Approval Console</span>
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  Enforces SOD-03 variant: Service Entry approver must be an independent service owner, strictly distinct from PO creator and vendor.
                </p>
              </div>
              <div className="text-xs font-mono text-emerald-400 bg-emerald-950/80 border border-emerald-500/40 px-3 py-1.5 rounded-xl font-bold">
                Principle P08 &amp; P09: Governed Service Milestone Certification
              </div>
            </div>

            {/* SES List Cards */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {sesItems.map((ses) => (
                <div key={ses.ses_id} className="p-6 bg-[#0B1528] border border-slate-800 rounded-2xl flex flex-col justify-between space-y-4 shadow-xl">
                  <div>
                    <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                      <div>
                        <span className="text-xs font-mono font-bold text-cyan-300">{ses.ses_id}</span>
                        <span className="text-[10px] text-slate-500 ml-2 font-mono">against {ses.po_number} (Line #{ses.po_line_no})</span>
                      </div>
                      <span className={`text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-full ${
                        ses.status === 'APPROVED' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' :
                        'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      }`}>
                        {ses.status}
                      </span>
                    </div>

                    <div className="mt-3">
                      <h4 className="text-base font-bold text-white">{ses.service_title}</h4>
                      <p className="text-xs text-slate-400 mt-0.5">Vendor: <strong className="text-slate-200">{ses.vendor_name}</strong></p>
                    </div>

                    {/* Financial & Milestone Breakdown */}
                    <div className="grid grid-cols-2 gap-3 mt-4 text-xs">
                      <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800">
                        <span className="text-slate-500 block text-[10px] font-mono">COMPENSATION MODEL</span>
                        <span className="font-bold text-white">{ses.compensation_type}</span>
                        {ses.timesheet_hours_billed && (
                          <span className="text-[11px] text-cyan-300 block mt-0.5">
                            {ses.timesheet_hours_billed} Hours @ ₹{ses.contracted_rate_inr_hr}/hr
                          </span>
                        )}
                        {ses.progress_pct && (
                          <span className="text-[11px] text-cyan-300 block mt-0.5">
                            Certified Progress: {ses.progress_pct}%
                          </span>
                        )}
                      </div>

                      <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800">
                        <span className="text-slate-500 block text-[10px] font-mono">GROSS BILLED VALUE</span>
                        <span className="text-base font-mono font-black text-white">
                          ₹{ses.total_amount_inr.toLocaleString()}
                        </span>
                        {ses.retention_amount_inr && (
                          <span className="text-[10px] text-amber-400 block mt-0.5 font-mono">
                            Less 5% Retention: -₹{ses.retention_amount_inr.toLocaleString()}
                          </span>
                        )}
                        {ses.net_payable_inr && (
                          <span className="text-[11px] text-emerald-400 font-bold block mt-0.5 font-mono">
                            Net Certified: ₹{ses.net_payable_inr.toLocaleString()}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* SoD Context Information */}
                    <div className="mt-4 p-3 bg-slate-950/80 rounded-xl border border-slate-800 text-xs space-y-1">
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="text-slate-400">PO Creator:</span>
                        <span className="font-mono text-slate-300">{ses.po_creator}</span>
                      </div>
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="text-slate-400">Designated Approver:</span>
                        <span className="font-mono text-cyan-300 font-bold">{ses.candidate_approver}</span>
                      </div>
                      {ses.approved_by && (
                        <div className="flex items-center justify-between text-[11px] text-emerald-400 pt-1 border-t border-slate-800">
                          <span>Certified by:</span>
                          <span className="font-mono font-bold">{ses.approved_by}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Action Bar */}
                  {ses.status === 'PENDING_APPROVAL' ? (
                    <div className="pt-4 border-t border-slate-800 space-y-2">
                      <div className="flex items-center gap-2">
                        <label className="text-[10px] text-slate-400 font-mono">Test Actor Role:</label>
                        <select
                          value={sesApproverActor}
                          onChange={(e) => setSesApproverActor(e.target.value)}
                          className="bg-slate-900 border border-slate-700 text-xs rounded-lg px-2 py-1 text-white font-mono flex-1"
                        >
                          <option value={ses.candidate_approver}>Independent Service Owner ({ses.candidate_approver})</option>
                          <option value={ses.po_creator}>Conflicting PO Creator ({ses.po_creator} - SOD-03 Test)</option>
                        </select>
                      </div>

                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => handleSesDecision(ses.ses_id, 'REJECT', sesApproverActor)}
                          disabled={actionLoading}
                          className="flex-1 py-2 rounded-xl bg-slate-900 hover:bg-red-950/80 border border-red-500/40 text-red-300 text-xs font-bold transition"
                        >
                          Reject SES
                        </button>
                        <button
                          onClick={() => handleSesDecision(ses.ses_id, 'APPROVE', sesApproverActor)}
                          disabled={actionLoading}
                          className="flex-1 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 text-white text-xs font-bold shadow-lg transition flex items-center justify-center gap-1.5"
                        >
                          <Check className="w-3.5 h-3.5" />
                          <span>Certify &amp; Approve SES</span>
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="pt-3 border-t border-slate-800 text-[11px] text-emerald-400 font-mono flex items-center gap-1.5">
                      <CheckCircle2 className="w-4 h-4" />
                      <span>Certified for 3-Way Payables Reconciliation</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ==================================================================== */}
        {/* TAB 4: CLM-02 AI CLAUSE REVIEW & REDLINE STUDIO                      */}
        {/* ==================================================================== */}
        {activeTab === 'REDLINE' && (
          <div className="space-y-6">
            <div className="p-5 bg-[#0B1528] border border-slate-800 rounded-2xl flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold font-mono text-white flex items-center gap-2">
                  <Scale className="w-4 h-4 text-purple-400" />
                  <span>CLM-02: AI Clause Review &amp; Redline Studio ({redlineData?.contract_id || 'SA-5520'})</span>
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  Automated comparison of supplier counter-proposals against corporate playbook with risk ratings and compromise positions.
                </p>
              </div>
              <div className="text-xs font-mono text-purple-400 bg-purple-950/80 border border-purple-500/40 px-3 py-1.5 rounded-xl font-bold">
                Playbook: {redlineData?.playbook_version || 'AHG-LEGAL-2026.2'}
              </div>
            </div>

            {/* Clauses List */}
            <div className="space-y-4">
              {redlineData?.clauses?.map((clause: RedlineClause) => (
                <div key={clause.clause_id} className="p-6 bg-[#0B1528] border border-slate-800 rounded-2xl space-y-4 shadow-xl">
                  <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-mono font-bold text-cyan-300">{clause.clause_id}</span>
                      <h4 className="text-sm font-bold text-white">{clause.title}</h4>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full ${
                        clause.risk_rating === 'HIGH' ? 'bg-red-500/20 text-red-300 border border-red-500/40' :
                        clause.risk_rating === 'MEDIUM' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' :
                        'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      }`}>
                        {clause.risk_rating} RISK
                      </span>
                      <span className="text-[10px] font-mono bg-slate-900 text-slate-400 px-2 py-0.5 rounded border border-slate-800">
                        {clause.status}
                      </span>
                    </div>
                  </div>

                  {/* Side-by-Side Comparison */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs">
                    {/* Playbook Standard */}
                    <div className="p-4 bg-slate-900/90 rounded-xl border border-slate-800/80 space-y-1.5">
                      <div className="flex items-center gap-1.5 text-[10px] font-mono font-bold text-emerald-400 uppercase">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Corporate Playbook Standard Position</span>
                      </div>
                      <p className="text-slate-200 leading-relaxed">
                        {clause.playbook_position}
                      </p>
                    </div>

                    {/* Supplier Proposed Markup */}
                    <div className="p-4 bg-red-950/20 rounded-xl border border-red-500/30 space-y-1.5">
                      <div className="flex items-center gap-1.5 text-[10px] font-mono font-bold text-red-400 uppercase">
                        <FileWarning className="w-3.5 h-3.5" />
                        <span>Supplier Proposed Revision</span>
                      </div>
                      <p className="text-slate-200 leading-relaxed">
                        {clause.supplier_proposed}
                      </p>
                    </div>
                  </div>

                  {/* AI Deviation & Fallback Recommendation */}
                  <div className="p-4 bg-purple-950/30 rounded-xl border border-purple-500/30 space-y-2">
                    <div className="text-[11px] font-bold text-purple-300 font-mono flex items-center gap-1.5">
                      <Sparkles className="w-4 h-4 text-purple-400" />
                      <span>AI Redline Analysis &amp; Recommended Compromise Position:</span>
                    </div>
                    <div className="text-xs text-slate-300">
                      <strong>Deviation:</strong> {clause.deviation_summary}
                    </div>
                    <div className="text-xs text-cyan-200 bg-slate-900/80 p-2.5 rounded-lg border border-slate-800">
                      <strong>Fallback Language:</strong> {clause.fallback_suggestion}
                    </div>
                  </div>

                  {/* Decision Actions */}
                  {clause.status === 'PENDING_REVIEW' && (
                    <div className="pt-3 border-t border-slate-800 flex items-center justify-end gap-3 text-xs">
                      <button
                        onClick={() => handleClauseDecision(clause.clause_id, 'REJECT_SUPPLIER')}
                        disabled={actionLoading}
                        className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-red-950 text-red-300 border border-red-500/40 font-bold transition"
                      >
                        Reject Supplier Markup
                      </button>
                      <button
                        onClick={() => handleClauseDecision(clause.clause_id, 'APPLY_FALLBACK')}
                        disabled={actionLoading}
                        className="px-4 py-2 rounded-xl bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 text-white font-bold shadow-lg transition flex items-center gap-1.5"
                      >
                        <Scale className="w-3.5 h-3.5" />
                        <span>Apply AI Fallback Compromise</span>
                      </button>
                      <button
                        onClick={() => handleClauseDecision(clause.clause_id, 'ACCEPT_SUPPLIER')}
                        disabled={actionLoading}
                        className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-bold transition"
                      >
                        Accept Supplier Text
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
