'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Shield, ShieldCheck, ShieldAlert, AlertTriangle, 
  ArrowRight, Search, RefreshCw, Sliders, CheckCircle2, 
  XCircle, Clock, Database, Layers, Sparkles, ExternalLink,
  Zap, Save, Activity, Building2, Terminal
} from 'lucide-react';
import axios from 'axios';

interface SodRule {
  id: string;
  title: string;
  risk: string;
  description: string;
  mitigation: string;
  enforcement_point: string;
  status: string;
}

interface SodViolationLog {
  id: string;
  rule_id: string;
  actor: string;
  attempted_action: string;
  target_object_id: string;
  risk: string;
  reason: string;
  timestamp: string;
  decision: string;
}

interface DmnConfig {
  touchless_po_max_risk_score: number;
  touchless_po_max_value_inr: number;
  metal_indexation_deadband_pct: number;
  invoice_qty_tolerance_pct: number;
  invoice_price_tolerance_pct: number;
  mdm_duplicate_similarity_block_pct: number;
  requisition_auto_approval_limit_inr: number;
  active_plants: { code: string; name: string; status: string }[];
  last_updated: string;
  updated_by: string;
}

interface OutboxMessage {
  msg_id: string;
  tenant_id: string;
  idempotency_key: string;
  target_system: string;
  direction: string;
  object_ref: string;
  payload_hash: string;
  status: string;
  erp_doc_no: string;
  retries: number;
  created_at: string;
  updated_at: string;
}

export default function EnterpriseGovernancePage() {
  const [activeTab, setActiveTab] = useState<'sod' | 'dmn' | 'outbox' | 'lineage'>('sod');
  const [sodRules, setSodRules] = useState<SodRule[]>([]);
  const [violations, setViolations] = useState<SodViolationLog[]>([]);
  const [dmnConfig, setDmnConfig] = useState<DmnConfig | null>(null);
  const [outboxMessages, setOutboxMessages] = useState<OutboxMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Lineage Explorer State
  const [lineageDocId, setLineageDocId] = useState('INV-TF-8812');
  const [lineageResult, setLineageResult] = useState<any>(null);
  const [fetchingLineage, setFetchingLineage] = useState(false);

  // DMN Editing State
  const [editRiskScore, setEditRiskScore] = useState<number>(20);
  const [editDeadband, setEditDeadband] = useState<number>(3.0);
  const [editMdmDuplicate, setEditMdmDuplicate] = useState<number>(92.0);
  const [savingDmn, setSavingDmn] = useState(false);

  const fetchGovernanceData = async () => {
    setLoading(true);
    try {
      const [sodRes, violRes, dmnRes, outboxRes] = await Promise.all([
        axios.get('http://localhost:8080/api/v1/admin/governance/sod-matrix'),
        axios.get('http://localhost:8080/api/v1/admin/governance/sod-violations'),
        axios.get('http://localhost:8080/api/v1/admin/governance/config/dmn-rules'),
        axios.get('http://localhost:8080/api/v1/admin/governance/outbox')
      ]);

      if (sodRes.data?.rules) setSodRules(sodRes.data.rules);
      if (violRes.data?.violations) setViolations(violRes.data.violations);
      if (dmnRes.data?.config) {
        setDmnConfig(dmnRes.data.config);
        setEditRiskScore(dmnRes.data.config.touchless_po_max_risk_score);
        setEditDeadband(dmnRes.data.config.metal_indexation_deadband_pct);
        setEditMdmDuplicate(dmnRes.data.config.mdm_duplicate_similarity_block_pct);
      }
      if (outboxRes.data?.messages) setOutboxMessages(outboxRes.data.messages);
    } catch (err) {
      console.error('Failed to load governance data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGovernanceData();
  }, []);

  const handleSaveDmnConfig = async () => {
    setSavingDmn(true);
    try {
      const res = await axios.put('http://localhost:8080/api/v1/admin/governance/config/dmn-rules', {
        touchless_po_max_risk_score: Number(editRiskScore),
        metal_indexation_deadband_pct: Number(editDeadband),
        mdm_duplicate_similarity_block_pct: Number(editMdmDuplicate),
        actor: 'u:platform.admin'
      });
      if (res.data?.status === 'success') {
        setDmnConfig(res.data.config);
        setToastMessage('DMN business rule parameters calibrated successfully.');
      }
    } catch (err) {
      console.error('Failed to save DMN config:', err);
      setToastMessage('Failed to update DMN parameters.');
    } finally {
      setSavingDmn(false);
    }
  };

  const handleInspectLineage = async () => {
    setFetchingLineage(true);
    try {
      const res = await axios.get(`http://localhost:8080/api/v1/admin/governance/lineage/${lineageDocId.trim()}`);
      if (res.data?.status === 'success') {
        setLineageResult(res.data);
      }
    } catch (err) {
      console.error('Failed to fetch lineage:', err);
      setToastMessage(`Failed to inspect lineage for ${lineageDocId}`);
    } finally {
      setFetchingLineage(false);
    }
  };

  const handleRetryOutbox = async (msgId: string) => {
    try {
      const res = await axios.post(`http://localhost:8080/api/v1/admin/governance/outbox/${msgId}/retry`);
      if (res.data?.status === 'success') {
        setToastMessage(res.data.message);
        fetchGovernanceData();
      }
    } catch (err) {
      console.error('Failed to retry outbox:', err);
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 space-y-6">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="p-4 rounded-xl bg-cyan-950/80 border border-cyan-500/50 text-cyan-200 flex items-center justify-between shadow-xl shadow-cyan-950/30 animate-in fade-in duration-200">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            <span className="font-medium text-sm">{toastMessage}</span>
          </div>
          <button 
            onClick={() => setToastMessage(null)} 
            className="text-xs px-2.5 py-1 rounded-md bg-cyan-900/60 hover:bg-cyan-800 text-cyan-300"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold tracking-wider uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              Module M13 • ADM-01..04
            </span>
            <span className="text-xs text-slate-400 font-mono">Enterprise Governance & SoD</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Governance Console & Segregation of Duties (SoD)
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Command-time conflict enforcement (SOD-01..07), DMN business rule parameter calibrator, transactional outbox & P10 lineage.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchGovernanceData}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-slate-700/60 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <Link
            href="/command-centre/ai-agents"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-purple-400 border border-purple-500/30 transition"
          >
            <Activity className="w-3.5 h-3.5" />
            AI Agents Fleet
          </Link>
          <Link
            href="/p2p"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-xs font-semibold text-white shadow-lg shadow-cyan-600/20 transition"
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            P2P Pipeline
          </Link>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800/80 pb-3">
        <button
          onClick={() => setActiveTab('sod')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'sod'
              ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <ShieldAlert className="w-4 h-4" />
          SoD Conflict Matrix (SOD-01..07)
        </button>

        <button
          onClick={() => setActiveTab('dmn')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'dmn'
              ? 'bg-blue-500/10 text-blue-400 border border-blue-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <Sliders className="w-4 h-4" />
          DMN Business Rule Parameters
        </button>

        <button
          onClick={() => setActiveTab('outbox')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'outbox'
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <Database className="w-4 h-4" />
          Transactional Outbox (P13)
        </button>

        <button
          onClick={() => setActiveTab('lineage')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'lineage'
              ? 'bg-purple-500/10 text-purple-400 border border-purple-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <Layers className="w-4 h-4" />
          Lineage Visualizer (P10)
        </button>
      </div>

      {/* Tab 1: SoD Matrix & Blocked Violations */}
      {activeTab === 'sod' && (
        <div className="space-y-6">
          {/* Rules Catalogue */}
          <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-cyan-400" />
                  Segregation of Duties (SoD) Conflict Catalogue
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Enforces strict action-level role isolation at command time for all users and AI agents (Principle P09).
                </p>
              </div>
              <span className="text-xs font-mono px-2.5 py-1 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-500/30">
                Command-Time Active
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {sodRules.map((rule) => {
                const isCritical = rule.risk === 'Critical';
                const isHigh = rule.risk === 'High';
                return (
                  <div
                    key={rule.id}
                    className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2.5 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs font-bold text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-500/30">
                        {rule.id}
                      </span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                        isCritical
                          ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                          : isHigh
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                          : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                      }`}>
                        {rule.risk} Risk
                      </span>
                    </div>

                    <h4 className="text-sm font-bold text-white leading-snug">
                      {rule.title}
                    </h4>

                    <p className="text-slate-300 leading-relaxed text-[11px]">
                      {rule.description}
                    </p>

                    <div className="pt-2 border-t border-slate-800/80 space-y-1 text-[11px]">
                      <div className="text-slate-400">
                        Mitigation: <strong className="text-slate-200">{rule.mitigation}</strong>
                      </div>
                      <div className="text-slate-400 font-mono text-[10px]">
                        Enforcement: <span className="text-cyan-400">{rule.enforcement_point}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Real-time Blocked Violations Audit Trail */}
          <div className="p-6 rounded-2xl bg-[#0B1528] border border-rose-500/30 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-bold text-rose-300 uppercase tracking-wider flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-rose-400" />
                Real-Time Blocked Violation Audit Log
              </h3>
              <span className="text-xs font-mono text-rose-400 bg-rose-950/60 px-2.5 py-0.5 rounded border border-rose-500/30">
                {violations.length} Interventions Blocked
              </span>
            </div>

            <div className="overflow-x-auto rounded-xl border border-slate-800/80">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-900/80 text-slate-400 font-medium border-b border-slate-800">
                  <tr>
                    <th className="py-2.5 px-3">Rule ID</th>
                    <th className="py-2.5 px-3">Actor</th>
                    <th className="py-2.5 px-3">Attempted Action</th>
                    <th className="py-2.5 px-3">Target Object</th>
                    <th className="py-2.5 px-3">Decision Reason</th>
                    <th className="py-2.5 px-3 text-right">Decision</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {violations.map((v) => (
                    <tr key={v.id} className="hover:bg-slate-800/30">
                      <td className="py-3 px-3 font-bold text-cyan-400">{v.rule_id}</td>
                      <td className="py-3 px-3 text-slate-200">{v.actor}</td>
                      <td className="py-3 px-3 text-amber-300">{v.attempted_action}</td>
                      <td className="py-3 px-3 text-slate-300">{v.target_object_id}</td>
                      <td className="py-3 px-3 text-slate-400 font-sans text-[11px]">{v.reason}</td>
                      <td className="py-3 px-3 text-right">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40">
                          <XCircle className="w-3 h-3" />
                          {v.decision}
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

      {/* Tab 2: DMN Rule Parameters Calibrator */}
      {activeTab === 'dmn' && dmnConfig && (
        <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Sliders className="w-5 h-5 text-blue-400" />
                DMN Business Rule Parameter Calibrator (ADM-02)
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Tune enterprise thresholds for automated touchless processing, metal indexation resets, and fuzzy duplicate guards.
              </p>
            </div>
            <button
              onClick={handleSaveDmnConfig}
              disabled={savingDmn}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-xs font-bold text-white shadow-lg shadow-blue-600/20 disabled:opacity-50 transition"
            >
              <Save className="w-3.5 h-3.5" />
              {savingDmn ? 'Saving Calibration...' : 'Save Parameters'}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
            {/* Touchless PO Max Risk Score */}
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
              <label className="block font-semibold text-slate-200">
                Touchless PO Risk Score Cutoff (DMN-02)
              </label>
              <input
                type="number"
                value={editRiskScore}
                onChange={(e) => setEditRiskScore(parseInt(e.target.value))}
                className="w-full px-3.5 py-2.5 bg-slate-950 border border-slate-700 rounded-xl font-mono text-cyan-300 focus:outline-none focus:border-cyan-500"
              />
              <span className="text-[11px] text-slate-400 block">
                Orders with risk score &le; this value release touchlessly without human intervention.
              </span>
            </div>

            {/* Metal Indexation Deadband Tolerance */}
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
              <label className="block font-semibold text-slate-200">
                LME Aluminium Deadband Tolerance (P14)
              </label>
              <div className="relative">
                <input
                  type="number"
                  step="0.1"
                  value={editDeadband}
                  onChange={(e) => setEditDeadband(parseFloat(e.target.value))}
                  className="w-full px-3.5 py-2.5 bg-slate-950 border border-slate-700 rounded-xl font-mono text-amber-300 focus:outline-none focus:border-cyan-500"
                />
                <span className="absolute right-3.5 top-2.5 text-slate-500 font-mono">&plusmn;%</span>
              </div>
              <span className="text-[11px] text-slate-400 block">
                Price recalibration triggers only when index shifts exceed &plusmn;{editDeadband}%.
              </span>
            </div>

            {/* MDM Duplicate Block Threshold */}
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
              <label className="block font-semibold text-slate-200">
                MDM Duplicate Similarity Cutoff (P03/P05)
              </label>
              <div className="relative">
                <input
                  type="number"
                  step="0.5"
                  value={editMdmDuplicate}
                  onChange={(e) => setEditMdmDuplicate(parseFloat(e.target.value))}
                  className="w-full px-3.5 py-2.5 bg-slate-950 border border-slate-700 rounded-xl font-mono text-emerald-300 focus:outline-none focus:border-cyan-500"
                />
                <span className="absolute right-3.5 top-2.5 text-slate-500 font-mono">%</span>
              </div>
              <span className="text-[11px] text-slate-400 block">
                Similarity &ge;{editMdmDuplicate}% blocks material creation to enforce catalog reuse.
              </span>
            </div>
          </div>

          {/* Active Plants Directory */}
          <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800 space-y-3">
            <h4 className="text-xs font-semibold uppercase text-slate-400 tracking-wider">
              Configured Enterprise Manufacturing Plants
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              {dmnConfig.active_plants.map((plant) => (
                <div key={plant.code} className="p-3.5 rounded-lg bg-slate-950/60 border border-slate-800/80 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Building2 className="w-4 h-4 text-cyan-400" />
                    <div>
                      <div className="font-bold text-white">{plant.name}</div>
                      <span className="text-[10px] text-slate-400 font-mono">Plant Code: {plant.code}</span>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    {plant.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: Transactional Outbox (Principle P13) */}
      {activeTab === 'outbox' && (
        <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Database className="w-5 h-5 text-emerald-400" />
                Transactional Outbox & Exactly-Once ERP Monitor (Principle P13)
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Idempotency-Key guaranteed posting queue to SAP S/4HANA (BAPI_INCOMINGINVOICE_CREATE).
              </p>
            </div>
            <span className="text-xs font-mono text-emerald-400 bg-emerald-950/60 px-2.5 py-1 rounded border border-emerald-500/30">
              SAP S/4HANA Connected
            </span>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-800/80">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/80 text-slate-400 font-medium border-b border-slate-800">
                <tr>
                  <th className="py-2.5 px-3">Message ID</th>
                  <th className="py-2.5 px-3">Idempotency Key</th>
                  <th className="py-2.5 px-3">Target System</th>
                  <th className="py-2.5 px-3">ERP Doc Number</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {outboxMessages.map((msg) => (
                  <tr key={msg.msg_id} className="hover:bg-slate-800/30">
                    <td className="py-3 px-3 text-slate-400">{msg.msg_id.slice(0, 8)}...</td>
                    <td className="py-3 px-3 font-bold text-cyan-400">{msg.idempotency_key}</td>
                    <td className="py-3 px-3 text-slate-300 font-sans">{msg.target_system}</td>
                    <td className="py-3 px-3 font-bold text-emerald-400">Doc #{msg.erp_doc_no}</td>
                    <td className="py-3 px-3">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                        <CheckCircle2 className="w-3 h-3" />
                        {msg.status}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right font-sans">
                      <button
                        onClick={() => handleRetryOutbox(msg.msg_id)}
                        className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 transition"
                      >
                        Re-enqueue
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 4: Bi-directional Lineage Explorer (Principle P10) */}
      {activeTab === 'lineage' && (
        <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Layers className="w-5 h-5 text-purple-400" />
                Lineage Graph Visualizer & Traversal Engine (Principle P10)
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Query full transaction graph across MR-1043 &rarr; PLO-55821 &rarr; REQ-2311 &rarr; RFQ-2231 &rarr; SA-5520 &rarr; PO-77410 &rarr; GR-90231 &rarr; INV-TF-8812 &rarr; 5100004421.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <input
                type="text"
                value={lineageDocId}
                onChange={(e) => setLineageDocId(e.target.value)}
                placeholder="Document ID (e.g. INV-TF-8812)"
                className="px-3.5 py-2 bg-slate-900 border border-slate-700 rounded-xl font-mono text-cyan-300 text-xs focus:outline-none focus:border-cyan-500"
              />
              <button
                onClick={handleInspectLineage}
                disabled={fetchingLineage}
                className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-xs font-bold text-white shadow-lg shadow-purple-600/20 disabled:opacity-50 transition"
              >
                <Search className="w-3.5 h-3.5" />
                {fetchingLineage ? 'Traversing...' : 'Trace'}
              </button>
            </div>
          </div>

          {lineageResult && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>Queried Root: <strong className="text-cyan-400 font-mono">{lineageResult.query_doc_id}</strong></span>
                <span>Graph Nodes: <strong className="text-white font-mono">{lineageResult.lineage_depth} connected artifacts</strong></span>
              </div>

              {/* Node Sequence Chain */}
              <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2">
                <span className="text-[10px] font-semibold uppercase text-slate-400 tracking-wider">
                  Chronological Demand-to-Settlement Sequence
                </span>
                <div className="flex flex-wrap items-center gap-2 pt-1 font-mono text-xs">
                  {lineageResult.lineage_graph?.lineage_sequence?.map((nodeId: string, idx: number) => (
                    <React.Fragment key={nodeId}>
                      <span className="px-2.5 py-1 rounded-lg bg-slate-950 border border-slate-700 text-cyan-300 font-bold shadow-sm">
                        {nodeId}
                      </span>
                      {idx < lineageResult.lineage_graph.lineage_sequence.length - 1 && (
                        <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>

              {/* Typed Links Table */}
              <div className="overflow-x-auto rounded-xl border border-slate-800/80">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-slate-900/80 text-slate-400 font-sans font-medium border-b border-slate-800">
                    <tr>
                      <th className="py-2.5 px-3">From Document</th>
                      <th className="py-2.5 px-3">Relationship (Link Type)</th>
                      <th className="py-2.5 px-3">To Document</th>
                      <th className="py-2.5 px-3 text-right">Timestamp</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {lineageResult.lineage_graph?.upstream_links?.concat(lineageResult.lineage_graph?.downstream_links || []).map((l: any) => (
                      <tr key={l.id} className="hover:bg-slate-800/30">
                        <td className="py-2.5 px-3 font-bold text-slate-200">
                          {l.from_type}: {l.from_id}
                        </td>
                        <td className="py-2.5 px-3 text-cyan-400">
                          &rarr; {l.link_type} &rarr;
                        </td>
                        <td className="py-2.5 px-3 font-bold text-slate-200">
                          {l.to_type}: {l.to_id}
                        </td>
                        <td className="py-2.5 px-3 text-right text-slate-500 font-sans text-[11px]">
                          {l.created_at?.split('T')[0]}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
