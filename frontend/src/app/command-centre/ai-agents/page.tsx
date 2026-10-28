'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Bot, ShieldAlert, AlertTriangle, ArrowRight, Search, 
  RefreshCw, Power, CheckCircle2, XCircle, Sliders, 
  Sparkles, Layers, ShieldCheck, ExternalLink, Zap,
  Send, HelpCircle, Activity, Award, Box
} from 'lucide-react';
import axios from 'axios';

interface AIAgent {
  id: string;
  name: string;
  module: string;
  autonomy_level: string;
  description: string;
  status: string;
  kill_switch_engaged: boolean;
  actions_today: number;
  last_active: string;
}

interface Citation {
  document_id: string;
  doc_type: string;
  url: string;
  snippet: string;
}

interface NextAction {
  action_id: string;
  title: string;
  endpoint: string;
  payload: any;
  requires_approval: boolean;
  approver_role: string;
}

interface AnswerContract {
  answer_summary: string;
  citations: Citation[];
  confidence_score: number;
  assumptions_made: string[];
  sod_check_result: {
    rule_id: string;
    status: string;
    explanation: string;
  };
  recommended_next_actions: NextAction[];
}

export default function AIAgentsCommandConsole() {
  const [agents, setAgents] = useState<AIAgent[]>([]);
  const [globalStop, setGlobalStop] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Copilot Query State (Principle P11)
  const [queryInput, setQueryInput] = useState('What is the status and savings lineage of DC-330 aluminium housing at Hosur P100?');
  const [answerContract, setAnswerContract] = useState<AnswerContract | null>(null);
  const [querying, setQuerying] = useState(false);

  const fetchAgents = async () => {
    setLoading(true);
    try {
      const res = await axios.get('http://localhost:8080/api/v1/agents/registry');
      if (res.data && res.data.status === 'success') {
        setAgents(res.data.agents || []);
        setGlobalStop(res.data.global_emergency_stop || false);
      }
    } catch (err) {
      console.error('Failed to load AI agents:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAgents();
  }, []);

  const handleToggleKillSwitch = async (agentId: string) => {
    try {
      const res = await axios.post(`http://localhost:8080/api/v1/agents/${agentId}/toggle-kill-switch?actor=u:security.admin`);
      if (res.data && res.data.status === 'success') {
        setToastMessage(res.data.message);
        fetchAgents();
      }
    } catch (err) {
      console.error('Toggle kill switch error:', err);
    }
  };

  const handleGlobalEmergencyStop = async () => {
    try {
      const res = await axios.post('http://localhost:8080/api/v1/agents/global-emergency-stop?actor=u:cpo.executive');
      if (res.data && res.data.status === 'success') {
        setToastMessage(res.data.message);
        setGlobalStop(res.data.global_emergency_stop);
        fetchAgents();
      }
    } catch (err) {
      console.error('Global stop error:', err);
    }
  };

  const handleExecuteCopilotQuery = async () => {
    setQuerying(true);
    try {
      const res = await axios.post('http://localhost:8080/api/v1/agents/copilot/query', {
        query: queryInput,
        tenant_id: 'axion-mobility',
        actor: 'u:cpo.executive',
        plant: 'P100 Hosur'
      });
      setAnswerContract(res.data);
    } catch (err) {
      console.error('Copilot query error:', err);
    } finally {
      setQuerying(false);
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
            <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold tracking-wider uppercase bg-purple-500/10 text-purple-400 border border-purple-500/20">
              Module M12 • AIX-01..03
            </span>
            <span className="text-xs text-slate-400 font-mono">Governed Agentic AI Architecture</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Governed AI Agents Command Console & Answer Contract
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Real-time management of 14 autonomous agents across L0..L4 autonomy levels with individual and global emergency kill switches.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchAgents}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-slate-700/60 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button 
            onClick={handleGlobalEmergencyStop}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition shadow-lg ${
              globalStop 
                ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-600/30' 
                : 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-600/30 ring-2 ring-rose-500/40 animate-pulse'
            }`}
          >
            <Power className="w-3.5 h-3.5" />
            {globalStop ? 'Disengage Emergency Stop' : 'Global Emergency Stop'}
          </button>
        </div>
      </div>

      {/* Emergency Status Banner if active */}
      {globalStop && (
        <div className="p-4 rounded-xl bg-rose-950/80 border border-rose-500 text-rose-200 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldAlert className="w-6 h-6 text-rose-400 shrink-0" />
            <div>
              <h4 className="font-bold text-sm">GLOBAL EMERGENCY STOP ACTIVE</h4>
              <p className="text-xs text-rose-300">All 14 autonomous agents are temporarily halted from executing actions.</p>
            </div>
          </div>
          <button 
            onClick={handleGlobalEmergencyStop}
            className="px-3 py-1.5 rounded-lg bg-rose-800 hover:bg-rose-700 text-xs font-bold text-white"
          >
            Resume Operations
          </button>
        </div>
      )}

      {/* 14 Governed AI Agents Grid */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Active Agent Fleet ({agents.length} Governed Micro-Agents)
          </h3>
          <span className="text-[11px] font-mono text-cyan-400">Autonomy Matrix L0..L4</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {agents.map((agent) => {
            const isSuspended = agent.kill_switch_engaged || globalStop;
            return (
              <div 
                key={agent.id}
                className={`p-4 rounded-2xl border transition relative flex flex-col justify-between ${
                  isSuspended 
                    ? 'bg-rose-950/20 border-rose-500/40' 
                    : 'bg-[#0B1528] border-slate-800 hover:border-slate-700'
                }`}
              >
                <div>
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <span className="font-mono text-[10px] font-bold text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-500/30">
                      {agent.id}
                    </span>
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                      isSuspended
                        ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                        : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                    }`}>
                      {isSuspended ? 'SUSPENDED' : 'ACTIVE'}
                    </span>
                  </div>

                  <h4 className="text-sm font-bold text-white leading-snug mb-1">
                    {agent.name}
                  </h4>
                  <span className="text-[10px] text-slate-400 font-mono block mb-2">
                    {agent.module} • {agent.autonomy_level}
                  </span>

                  <p className="text-xs text-slate-400 leading-relaxed line-clamp-2">
                    {agent.description}
                  </p>
                </div>

                <div className="pt-3 mt-3 border-t border-slate-800/80 flex items-center justify-between">
                  <span className="text-[10px] text-slate-500 font-mono">
                    Actions: <strong className="text-slate-300">{agent.actions_today}</strong>
                  </span>
                  <button
                    onClick={() => handleToggleKillSwitch(agent.id)}
                    className={`px-2.5 py-1 rounded-lg text-[10px] font-bold font-mono transition ${
                      agent.kill_switch_engaged
                        ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                        : 'bg-rose-950/60 hover:bg-rose-900/60 text-rose-300 border border-rose-500/40'
                    }`}
                  >
                    {agent.kill_switch_engaged ? 'Release Kill' : 'Engage Kill'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Principle P11 Copilot Answer Contract Interactive Explorer */}
      <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                Principle P11 • Explainable AI
              </span>
              <span className="text-xs text-slate-400">Strict 6-Field Answer Contract Schema</span>
            </div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <Bot className="w-5 h-5 text-cyan-400" />
              Governed Copilot Answer Contract Verification
            </h3>
          </div>
          <button
            onClick={handleExecuteCopilotQuery}
            disabled={querying}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-xs font-bold text-white shadow-lg shadow-cyan-600/20 disabled:opacity-50 transition"
          >
            <Send className="w-3.5 h-3.5" />
            {querying ? 'Verifying Answer Contract...' : 'Test Query Execution'}
          </button>
        </div>

        {/* Query Input Box */}
        <div className="flex gap-3">
          <input
            type="text"
            value={queryInput}
            onChange={(e) => setQueryInput(e.target.value)}
            className="flex-1 px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-xl font-mono text-cyan-300 text-xs focus:outline-none focus:border-cyan-500"
            placeholder="Type query to test Answer Contract..."
          />
        </div>

        {/* 6-Field Answer Contract Result Display */}
        {answerContract && (
          <div className="space-y-4 pt-2">
            {/* Field 1: Answer Summary */}
            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
              <span className="text-[10px] font-semibold uppercase text-cyan-400 tracking-wider">
                Field 1 • Executive Answer Summary
              </span>
              <p className="text-xs text-slate-200 leading-relaxed font-sans">
                {answerContract.answer_summary}
              </p>
            </div>

            {/* Field 2: Grounded Document Citations */}
            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2">
              <span className="text-[10px] font-semibold uppercase text-emerald-400 tracking-wider">
                Field 2 • Grounded Citations ({answerContract.citations.length} Verified Documents)
              </span>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                {answerContract.citations.map((cite) => (
                  <Link
                    key={cite.document_id}
                    href={cite.url}
                    className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80 hover:border-cyan-500/40 hover:bg-slate-950 transition flex items-start justify-between group"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[10px] font-bold text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded">
                          {cite.document_id}
                        </span>
                        <span className="text-[10px] text-slate-400 uppercase font-mono">{cite.doc_type}</span>
                      </div>
                      <p className="text-[11px] text-slate-300 mt-1 line-clamp-1">{cite.snippet}</p>
                    </div>
                    <ExternalLink className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-400 shrink-0 ml-2" />
                  </Link>
                ))}
              </div>
            </div>

            {/* Field 3, 4, 5 Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {/* Field 3: Confidence Score */}
              <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                <span className="text-[10px] font-semibold uppercase text-purple-400 tracking-wider">
                  Field 3 • Confidence Score
                </span>
                <div className="text-2xl font-bold text-purple-400 font-mono mt-0.5">
                  {(answerContract.confidence_score * 100).toFixed(1)}%
                </div>
                <span className="text-[10px] text-slate-500 font-mono">Calibrated LLM RAG Score</span>
              </div>

              {/* Field 4: Operational Assumptions */}
              <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                <span className="text-[10px] font-semibold uppercase text-amber-400 tracking-wider">
                  Field 4 • Explicit Assumptions ({answerContract.assumptions_made.length})
                </span>
                <ul className="text-[11px] text-slate-300 space-y-1 list-disc pl-4 pt-1">
                  {answerContract.assumptions_made.map((assump, idx) => (
                    <li key={idx} className="line-clamp-1">{assump}</li>
                  ))}
                </ul>
              </div>

              {/* Field 5: SoD Command-Time Check */}
              <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                <span className="text-[10px] font-semibold uppercase text-blue-400 tracking-wider">
                  Field 5 • SoD Validation
                </span>
                <div className="flex items-center gap-2 mt-1">
                  <span className="font-mono text-xs font-bold text-blue-300 bg-blue-950/60 px-2 py-0.5 rounded border border-blue-500/30">
                    {answerContract.sod_check_result.rule_id}
                  </span>
                  <span className="text-xs font-bold text-emerald-400">
                    {answerContract.sod_check_result.status}
                  </span>
                </div>
                <p className="text-[10px] text-slate-400 mt-1 line-clamp-2">
                  {answerContract.sod_check_result.explanation}
                </p>
              </div>
            </div>

            {/* Field 6: Recommended Next Actions with Role Authorization */}
            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2">
              <span className="text-[10px] font-semibold uppercase text-cyan-400 tracking-wider">
                Field 6 • Recommended Governed Next Actions ({answerContract.recommended_next_actions.length})
              </span>
              <div className="flex flex-wrap gap-2 pt-1">
                {answerContract.recommended_next_actions.map((act) => (
                  <div
                    key={act.action_id}
                    className="p-3 rounded-lg bg-slate-950/80 border border-slate-800 flex items-center justify-between gap-4 text-xs"
                  >
                    <div>
                      <div className="font-bold text-white">{act.title}</div>
                      <span className="text-[10px] text-cyan-400 font-mono">Role: {act.approver_role}</span>
                    </div>
                    <button
                      onClick={() => setToastMessage(`Action ${act.action_id} triggered for role ${act.approver_role}.`)}
                      className="px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-[11px] shadow-sm transition"
                    >
                      Authorize Action
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
