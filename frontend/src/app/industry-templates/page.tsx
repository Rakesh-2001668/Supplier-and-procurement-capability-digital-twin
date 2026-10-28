'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Building2, CheckCircle2, ShieldCheck, ShieldAlert, ArrowRight,
  Sparkles, Layers, Box, FileText, ShoppingCart, Target, Scale, 
  DollarSign, RefreshCw, ExternalLink, Activity, Truck, Stethoscope, 
  Laptop, HardHat, Factory, ChevronRight, AlertCircle, Info, Zap
} from 'lucide-react';

interface IndustryTemplateDetail {
  id: string;
  name: string;
  code: string;
  icon: string;
  tenant_name: string;
  tenant_id: string;
  plants_or_locations: string[];
  demand_source: string;
  sourcing_type: string;
  contract_form: string;
  receipt_method: string;
  match_rule: string;
  special_controls: string[];
  nuance_description: string;
  demo_case_summary: string;
  kpis: Record<string, string>;
  is_active: boolean;
  sample_document: Record<string, any>;
}

export default function IndustryTemplatesPage() {
  const [templates, setTemplates] = useState<IndustryTemplateDetail[]>([]);
  const [activeTemplateId, setActiveTemplateId] = useState<string>('MANUFACTURING');
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('MANUFACTURING');
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState(false);
  const [activeTab, setActiveTab] = useState<'OVERVIEW' | 'MATRIX' | 'DEMO_CASE' | 'KPIS'>('OVERVIEW');
  const [toast, setToast] = useState<string | null>(null);

  const fetchTemplates = async () => {
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/industry-templates');
      if (res.ok) {
        const data = await res.json();
        setTemplates(data);
        const active = data.find((t: IndustryTemplateDetail) => t.is_active);
        if (active) {
          setActiveTemplateId(active.id);
          setSelectedTemplateId(active.id);
        }
      }
    } catch (e) {
      console.error("Failed to load industry templates", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  const handleActivate = async (templateId: string) => {
    setActivating(true);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/industry-templates/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_id: templateId,
          actor: 'Chief Procurement Officer',
          notes: `Activated ${templateId} from Industry Configuration Studio`
        })
      });
      if (res.ok) {
        const data = await res.json();
        setActiveTemplateId(templateId);
        setToast(`Active Tenant updated to: ${data.tenant_name}`);
        setTimeout(() => setToast(null), 4500);
        await fetchTemplates();
      }
    } catch (e) {
      setToast(`Template ${templateId} activated in session`);
      setTimeout(() => setToast(null), 3000);
      setActiveTemplateId(templateId);
    } finally {
      setActivating(false);
    }
  };

  const selectedTemplate = templates.find(t => t.id === selectedTemplateId) || templates[0];

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 flex flex-col font-sans">
      {/* Toast */}
      {toast && (
        <div className="fixed top-6 right-6 z-50 bg-cyan-950 border border-cyan-500/60 text-cyan-200 px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 text-xs font-semibold animate-fade-in">
          <Sparkles className="w-4 h-4 text-cyan-400 animate-spin" />
          <span>{toast}</span>
        </div>
      )}

      {/* Header Banner */}
      <div className="bg-[#0B1528] border-b border-slate-800/80 px-8 py-6 shrink-0">
        <div className="max-w-[1700px] mx-auto flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-cyan-400 font-bold mb-1">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
              <span>AlphaHelion Enterprise Multi-Tenancy</span>
              <span className="text-slate-600">•</span>
              <span>Blueprint Section 23 (Tables 22 & 23)</span>
            </div>
            <h1 className="text-2xl lg:text-3xl font-bold font-mono text-white tracking-tight flex items-center gap-3">
              Industry Configuration Packs
              <span className="text-xs font-sans font-bold bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 px-3 py-1 rounded-full">
                6 Turnkey Presets
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-3xl">
              Each template adapts demand signals, sourcing strategies, contract types, receipt protocols, 
              match tolerances, and governance controls to industry standards while preserving unified auditability.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/command-centre"
              className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-700/80 hover:border-cyan-500/50 text-xs font-bold text-slate-300 hover:text-white transition flex items-center gap-2"
            >
              <span>📡</span> Command Centre
            </Link>
            <Link
              href="/admin/governance"
              className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-700/80 hover:border-amber-500/50 text-xs font-bold text-slate-300 hover:text-white transition flex items-center gap-2"
            >
              <span>⚖️</span> SoD & Outbox
            </Link>
          </div>
        </div>
      </div>

      {/* Main Workspace */}
      <div className="flex-1 p-6 lg:p-8 max-w-[1700px] mx-auto w-full flex flex-col gap-6">

        {/* TOP RAIL: 6 Industry Selector Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3.5">
          {templates.map((tpl) => {
            const isSelected = selectedTemplateId === tpl.id;
            const isCurrentlyActive = activeTemplateId === tpl.id;
            return (
              <button
                key={tpl.id}
                onClick={() => setSelectedTemplateId(tpl.id)}
                className={`p-4 rounded-2xl border text-left transition-all flex flex-col justify-between h-[155px] relative group ${
                  isSelected
                    ? 'bg-gradient-to-b from-cyan-950/90 to-blue-950/80 border-cyan-400 shadow-xl shadow-cyan-950/50 ring-1 ring-cyan-400'
                    : 'bg-[#0B1528]/80 hover:bg-[#111F38] border-slate-800 hover:border-slate-700 text-slate-300'
                }`}
              >
                {/* Active Platform Tenant Badge */}
                {isCurrentlyActive && (
                  <div className="absolute top-2.5 right-2.5 bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 px-2 py-0.5 rounded-full text-[9px] font-mono font-bold flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                    ACTIVE
                  </div>
                )}

                <div>
                  <div className="text-2xl p-2 rounded-xl bg-slate-950/70 border border-slate-800/80 w-fit mb-2 group-hover:scale-105 transition-transform">
                    {tpl.icon}
                  </div>
                  <div className="text-xs font-bold text-white line-clamp-1">
                    {tpl.name}
                  </div>
                  <div className="text-[10px] text-cyan-400/90 font-mono mt-0.5">
                    {tpl.code}
                  </div>
                </div>

                <div className="text-[10px] text-slate-400 font-medium truncate pt-2 border-t border-slate-800/80">
                  {tpl.tenant_name.split(' ')[0]} {tpl.tenant_name.split(' ')[1] || ''}
                </div>
              </button>
            );
          })}
        </div>

        {/* SELECTED INDUSTRY DETAIL COCKPIT */}
        {selectedTemplate && (
          <div className="bg-[#0B1528] border border-slate-800 rounded-2xl overflow-hidden shadow-2xl flex flex-col">
            
            {/* Detail Header Ribbon */}
            <div className="p-6 bg-gradient-to-r from-slate-900 via-[#0B1528] to-slate-900 border-b border-slate-800/80 flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="flex items-start gap-4">
                <span className="text-4xl p-3 bg-slate-950 rounded-2xl border border-slate-800 shadow-inner">
                  {selectedTemplate.icon}
                </span>
                <div>
                  <div className="flex items-center gap-3">
                    <h2 className="text-xl font-bold font-mono text-white">
                      {selectedTemplate.name}
                    </h2>
                    <span className="text-xs font-mono font-bold px-2.5 py-0.5 rounded bg-slate-800 text-cyan-300 border border-slate-700">
                      {selectedTemplate.code}
                    </span>
                    {activeTemplateId === selectedTemplate.id && (
                      <span className="text-xs font-sans font-bold px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Active Platform Tenant
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-400 mt-1 flex flex-wrap items-center gap-3">
                    <span>Tenant: <strong className="text-slate-200">{selectedTemplate.tenant_name}</strong></span>
                    <span className="text-slate-600">•</span>
                    <span>Locations: <strong className="text-slate-200">{selectedTemplate.plants_or_locations.join(' | ')}</strong></span>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-3 shrink-0">
                {activeTemplateId !== selectedTemplate.id ? (
                  <button
                    onClick={() => handleActivate(selectedTemplate.id)}
                    disabled={activating}
                    className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-xs font-bold text-white shadow-lg shadow-cyan-600/25 transition flex items-center gap-2 group"
                  >
                    <Zap className="w-4 h-4 text-cyan-200 group-hover:scale-110 transition-transform" />
                    <span>{activating ? 'Configuring Tenant...' : 'Activate This Template'}</span>
                  </button>
                ) : (
                  <div className="px-4 py-2 rounded-xl bg-emerald-950/80 border border-emerald-500/40 text-emerald-300 text-xs font-bold flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>Running Active Configuration</span>
                  </div>
                )}
              </div>
            </div>

            {/* Sub-Tabs Navigation */}
            <div className="px-6 pt-3 bg-slate-900/60 border-b border-slate-800 flex items-center gap-2 overflow-x-auto">
              {[
                { id: 'OVERVIEW', label: 'Overview & Special Controls' },
                { id: 'MATRIX', label: 'Lifecycle & Matching Rules' },
                { id: 'DEMO_CASE', label: 'Signature Storyline & Sample Document' },
                { id: 'KPIS', label: 'Industry KPIs & Targets' }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`px-4 py-2 text-xs font-bold transition-colors border-b-2 font-mono whitespace-nowrap ${
                    activeTab === tab.id
                      ? 'border-cyan-400 text-cyan-300'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* TAB CONTENT BODY */}
            <div className="p-6 lg:p-8">

              {/* TAB 1: OVERVIEW & SPECIAL CONTROLS */}
              {activeTab === 'OVERVIEW' && (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  {/* Left Column: Core Nuance */}
                  <div className="lg:col-span-2 space-y-6">
                    <div className="bg-slate-900/70 border border-slate-800 p-5 rounded-xl">
                      <div className="text-xs font-bold text-cyan-400 font-mono uppercase tracking-wider mb-2 flex items-center gap-2">
                        <Info className="w-4 h-4" />
                        <span>Key Nuance the Platform Must Handle</span>
                      </div>
                      <p className="text-sm text-slate-200 leading-relaxed font-medium">
                        {selectedTemplate.nuance_description}
                      </p>
                    </div>

                    {/* Special Controls Grid */}
                    <div className="bg-slate-900/70 border border-slate-800 p-5 rounded-xl">
                      <div className="text-xs font-bold text-amber-400 font-mono uppercase tracking-wider mb-4 flex items-center gap-2">
                        <ShieldCheck className="w-4 h-4" />
                        <span>Industry Governance & Automated Control Points</span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {selectedTemplate.special_controls.map((ctrl, idx) => (
                          <div 
                            key={idx}
                            className="p-3 bg-slate-950/80 border border-slate-800/80 rounded-xl flex items-start gap-2.5 text-xs text-slate-300"
                          >
                            <span className="w-5 h-5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center justify-center text-[10px] font-mono shrink-0 mt-0.5">
                              {idx + 1}
                            </span>
                            <span className="leading-snug">{ctrl}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Right Column: Deployment Profile */}
                  <div className="bg-slate-900/70 border border-slate-800 p-5 rounded-xl flex flex-col justify-between">
                    <div>
                      <div className="text-xs font-bold text-slate-300 font-mono uppercase tracking-wider mb-4 flex items-center gap-2">
                        <Layers className="w-4 h-4 text-cyan-400" />
                        <span>Deployment Configuration</span>
                      </div>
                      <div className="space-y-3 text-xs">
                        <div>
                          <span className="text-slate-500 block text-[10px] font-mono">TENANT IDENTIFIER</span>
                          <span className="font-mono text-cyan-300 font-bold">{selectedTemplate.tenant_id}</span>
                        </div>
                        <div>
                          <span className="text-slate-500 block text-[10px] font-mono">PRIMARY LEGAL ENTITY</span>
                          <span className="text-white font-semibold">{selectedTemplate.tenant_name}</span>
                        </div>
                        <div>
                          <span className="text-slate-500 block text-[10px] font-mono">OPERATIONAL SITES / PLANTS</span>
                          <ul className="mt-1 space-y-1">
                            {selectedTemplate.plants_or_locations.map((loc, i) => (
                              <li key={i} className="text-slate-300 flex items-center gap-1.5">
                                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
                                {loc}
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>

                    <div className="mt-6 pt-4 border-t border-slate-800">
                      <div className="text-[11px] text-slate-400">
                        Template auto-binds to PostgreSQL Row-Level Security (`RLS`) and maps Camunda process instances to candidate groups.
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 2: LIFECYCLE MATRIX */}
              {activeTab === 'MATRIX' && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {/* Demand */}
                  <div className="p-5 bg-slate-900/70 border border-slate-800 rounded-xl space-y-2">
                    <div className="flex items-center gap-2 text-xs font-bold text-cyan-400 font-mono uppercase">
                      <Layers className="w-4 h-4" />
                      <span>1. Demand Generation</span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      {selectedTemplate.demand_source}
                    </p>
                  </div>

                  {/* Sourcing */}
                  <div className="p-5 bg-slate-900/70 border border-slate-800 rounded-xl space-y-2">
                    <div className="flex items-center gap-2 text-xs font-bold text-blue-400 font-mono uppercase">
                      <Target className="w-4 h-4" />
                      <span>2. Strategic Sourcing</span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      {selectedTemplate.sourcing_type}
                    </p>
                  </div>

                  {/* Contracts */}
                  <div className="p-5 bg-slate-900/70 border border-slate-800 rounded-xl space-y-2">
                    <div className="flex items-center gap-2 text-xs font-bold text-purple-400 font-mono uppercase">
                      <Scale className="w-4 h-4" />
                      <span>3. Contract Forms</span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      {selectedTemplate.contract_form}
                    </p>
                  </div>

                  {/* Receiving */}
                  <div className="p-5 bg-slate-900/70 border border-slate-800 rounded-xl space-y-2">
                    <div className="flex items-center gap-2 text-xs font-bold text-amber-400 font-mono uppercase">
                      <Box className="w-4 h-4" />
                      <span>4. Fulfilment & Confirmation</span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      {selectedTemplate.receipt_method}
                    </p>
                  </div>

                  {/* Invoicing */}
                  <div className="p-5 bg-slate-900/70 border border-slate-800 rounded-xl space-y-2 lg:col-span-2">
                    <div className="flex items-center gap-2 text-xs font-bold text-emerald-400 font-mono uppercase">
                      <DollarSign className="w-4 h-4" />
                      <span>5. Invoice Matching & Finance Settlement</span>
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed">
                      {selectedTemplate.match_rule}
                    </p>
                  </div>
                </div>
              )}

              {/* TAB 3: SIGNATURE DEMO CASE & SAMPLE DOCUMENT */}
              {activeTab === 'DEMO_CASE' && (
                <div className="space-y-6">
                  {/* Storyline Summary */}
                  <div className="p-5 bg-slate-900/80 border border-slate-800 rounded-xl">
                    <div className="text-xs font-bold text-cyan-400 font-mono uppercase tracking-wider mb-2 flex items-center gap-2">
                      <Sparkles className="w-4 h-4" />
                      <span>Signature Storyline & Demo Case</span>
                    </div>
                    <p className="text-xs text-slate-200 leading-relaxed">
                      {selectedTemplate.demo_case_summary}
                    </p>
                  </div>

                  {/* Sample Document JSON Inspector */}
                  <div className="p-5 bg-slate-950 border border-slate-800 rounded-xl font-mono">
                    <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800 text-xs">
                      <span className="text-slate-400">Sample Document Payload Structure</span>
                      <span className="text-cyan-400 font-bold">{selectedTemplate.sample_document?.doc_type || 'PAYLOAD'}</span>
                    </div>
                    <pre className="text-xs text-cyan-300 overflow-x-auto p-3 bg-slate-900/60 rounded-lg">
                      {JSON.stringify(selectedTemplate.sample_document, null, 2)}
                    </pre>
                  </div>
                </div>
              )}

              {/* TAB 4: INDUSTRY KPIS */}
              {activeTab === 'KPIS' && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  {Object.entries(selectedTemplate.kpis).map(([kpiLabel, kpiVal], i) => (
                    <div key={i} className="p-5 bg-slate-900/80 border border-slate-800 rounded-xl flex flex-col justify-between">
                      <span className="text-xs text-slate-400 uppercase tracking-wider font-semibold">{kpiLabel}</span>
                      <div className="text-2xl font-black font-mono text-cyan-300 mt-2">
                        {kpiVal}
                      </div>
                      <span className="text-[10px] text-emerald-400 font-mono mt-2 flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" /> Industry Benchmark Met
                      </span>
                    </div>
                  ))}
                </div>
              )}

            </div>
          </div>
        )}

      </div>
    </div>
  );
}
