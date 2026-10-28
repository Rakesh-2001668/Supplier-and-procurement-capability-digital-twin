'use client';

import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { 
  Send, Bot, User, Sparkles, FileText, AlertTriangle, TrendingUp, 
  Search, CheckCircle, Clock, ArrowRight, Zap, RefreshCw,
  MoreHorizontal, ChevronRight, ShieldCheck, Box, Copy, Check,
  Activity, Award, Building2, ExternalLink, Trash2, Cpu, Globe
} from 'lucide-react';

interface EvidenceCitation {
  source: string;
  entity: string;
  relevance: number;
  deep_link: string;
}

interface ActionRecommendation {
  label: string;
  link: string;
  action_type: string;
}

interface RichPayload {
  widget_type?: string; // "TABLE" | "RISK_CARD" | "EMAIL_DRAFT" | "TELEMETRY_STRIP" | "VAULT_AUDIT"
  data?: Record<string, any>;
}

interface ChatMessage {
  id: string | number;
  role: 'user' | 'assistant';
  content: string;
  confidence?: number;
  model_used?: string;
  evidence?: EvidenceCitation[];
  suggested_actions?: ActionRecommendation[];
  rich_payload?: RichPayload;
  timestamp: string;
}

interface SuggestedPrompt {
  category: string;
  text: string;
  agent_mode: string;
}

interface ContextStats {
  suppliers: number;
  active_orders: number;
  telemetry_machines: number;
  compliance_documents: number;
  tamper_integrity_score: number;
}

export default function GenAICopilot() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'init-1',
      role: 'assistant',
      content: "Hello! I am your **SupplyTwin GenAI Procurement Copilot**, powered by real-time retrieval-augmented generation (RAG) across your supplier capability twins, open purchase orders, live IIoT machine telemetry, and cryptographic compliance vault.\n\nHow can I assist your sourcing operations today?",
      confidence: 0.99,
      model_used: "SupplyTwin-Enterprise-RAG v4.2 (Hybrid Dense+Sparse Graph Retriever)",
      evidence: [
        { source: "SupplyTwin Enterprise Graph", entity: "Global Knowledge Matrix", relevance: 0.99, deep_link: "/network" }
      ],
      suggested_actions: [
        { label: "Find Suppliers with >15% Free Capacity", link: "/buyer/discovery", action_type: "NAVIGATE" },
        { label: "Analyze Port Strikes & Supply Chain Risk", link: "/risk", action_type: "NAVIGATE" },
        { label: "Audit Regulatory Evidence Vault", link: "/evidence", action_type: "NAVIGATE" }
      ],
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState('general');
  const [suggestedPrompts, setSuggestedPrompts] = useState<SuggestedPrompt[]>([]);
  const [contextStats, setContextStats] = useState<ContextStats | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  // Load context stats and suggested prompts from backend
  useEffect(() => {
    const fetchMetadata = async () => {
      try {
        const [promptsRes, statsRes] = await Promise.all([
          fetch('http://127.0.0.1:8080/api/v1/copilot/suggested-prompts'),
          fetch('http://127.0.0.1:8080/api/v1/copilot/context-stats')
        ]);

        if (promptsRes.ok) {
          const pData = await promptsRes.json();
          setSuggestedPrompts(pData.prompts || []);
        }

        if (statsRes.ok) {
          const sData = await statsRes.json();
          setContextStats(sData.indexed_entities || null);
        }
      } catch (err) {
        console.error('Failed to load copilot metadata:', err);
      }
    };

    fetchMetadata();
  }, []);

  const handleSend = async (queryText?: string) => {
    const textToSend = queryText || input;
    if (!textToSend.trim() || isTyping) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsTyping(true);

    try {
      const response = await fetch('http://127.0.0.1:8080/api/v1/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: textToSend,
          agent_mode: selectedAgent,
          session_id: 'enterprise-session-1'
        })
      });

      if (response.ok) {
        const data = await response.json();
        const aiMessage: ChatMessage = {
          id: `ai-${Date.now()}`,
          role: 'assistant',
          content: data.answer,
          confidence: data.confidence,
          model_used: data.model_used,
          evidence: data.evidence || [],
          suggested_actions: data.suggested_actions || [],
          rich_payload: data.rich_payload || undefined,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };
        setMessages(prev => [...prev, aiMessage]);
      } else {
        const fallbackMsg: ChatMessage = {
          id: `ai-err-${Date.now()}`,
          role: 'assistant',
          content: "I encountered a communication delay querying the enterprise knowledge graph. Please verify your connection to the capability engine.",
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };
        setMessages(prev => [...prev, fallbackMsg]);
      }
    } catch (err) {
      console.error('Copilot request failed:', err);
      const fallbackMsg: ChatMessage = {
        id: `ai-err-${Date.now()}`,
        role: 'assistant',
        content: "Error reaching the backend AI agent. Please check that the backend service is running on port 8080.",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages(prev => [...prev, fallbackMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    showToast("Content copied to clipboard!");
    setTimeout(() => setCopiedId(null), 2500);
  };

  const handleClearChat = () => {
    setMessages([
      {
        id: 'init-fresh',
        role: 'assistant',
        content: "Chat session reset. What supply chain or procurement inquiry can I resolve for you?",
        confidence: 0.99,
        model_used: "SupplyTwin-Enterprise-RAG v4.2",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    ]);
    showToast("Session history cleared.");
  };

  const agentModes = [
    { id: 'general', name: 'General Co-Pilot', desc: 'Unified enterprise reasoning', icon: Bot, color: 'text-blue-400 bg-blue-500/10 border-blue-500/30' },
    { id: 'discovery', name: 'Sourcing Scout', desc: 'CNC & available capacity', icon: Search, color: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/30' },
    { id: 'risk', name: 'Risk Sentinel', desc: 'Port strikes & choke points', icon: AlertTriangle, color: 'text-rose-400 bg-rose-500/10 border-rose-500/30' },
    { id: 'compliance', name: 'Evidence Auditor', desc: 'AS9100, ITAR & tamper seal', icon: ShieldCheck, color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
    { id: 'negotiation', name: 'Contract Negotiator', desc: 'Net 45 terms & SLA clauses', icon: FileText, color: 'text-purple-400 bg-purple-500/10 border-purple-500/30' },
    { id: 'telemetry', name: 'Machine Telemetry', desc: 'Spindle vibration & OEE', icon: Activity, color: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30' }
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 bg-blue-600 text-white text-xs font-semibold rounded-xl shadow-2xl border border-blue-400/40 animate-fade-in-up">
          <Sparkles className="w-4 h-4 text-amber-300 animate-pulse" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Top Header */}
      <div className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md px-8 py-4 shrink-0 flex flex-wrap justify-between items-center gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-bold text-blue-400 uppercase tracking-wider mb-1">
            <Sparkles className="w-4 h-4 text-blue-400" />
            <span>GenAI Procurement & Sourcing Co-Pilot</span>
          </div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20">
                <Bot className="w-5 h-5" />
              </div>
              SupplyTwin AI Copilot
            </h1>
            <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[11px] font-bold flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              RAG Engine Live
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Multi-vector semantic intelligence across capability twins, open POs, edge IIoT feeds, and cryptographic evidence vaults.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleClearChat}
            className="px-3 py-2 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs font-bold text-slate-400 hover:text-white transition-all flex items-center gap-1.5"
            title="Reset Chat Session"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Reset Chat
          </button>
        </div>
      </div>

      {/* Main Body */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* Left Sidebar: Specialized Agents & Enterprise Knowledge Graph Index */}
        <div className="w-80 border-r border-slate-800 bg-slate-900/40 hidden md:flex flex-col shrink-0 overflow-y-auto">
          {/* Agent Selection */}
          <div className="p-4 border-b border-slate-800">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
              Specialized Copilot Modes
            </h3>
            <div className="space-y-1.5">
              {agentModes.map(agent => {
                const Icon = agent.icon;
                const isSelected = selectedAgent === agent.id;
                return (
                  <button
                    key={agent.id}
                    onClick={() => {
                      setSelectedAgent(agent.id);
                      showToast(`Switched active mode to ${agent.name}`);
                    }}
                    className={`w-full text-left p-2.5 rounded-xl border transition-all flex items-center gap-3 ${
                      isSelected
                        ? 'bg-blue-600/15 border-blue-500/50 text-white shadow-sm'
                        : 'bg-slate-950/40 border-slate-800/80 text-slate-300 hover:bg-slate-800/40 hover:border-slate-700'
                    }`}
                  >
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border ${agent.color}`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-bold text-xs truncate text-white">{agent.name}</div>
                      <div className="text-[10px] text-slate-400 truncate">{agent.desc}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Real-Time Graph Stats Widget */}
          <div className="p-4 border-b border-slate-800 bg-slate-950/60">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-blue-400" />
              Indexed Enterprise Graph
            </h3>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-slate-900/90 border border-slate-800 p-2.5 rounded-lg">
                <div className="text-[10px] text-slate-500 font-semibold uppercase">Suppliers</div>
                <div className="text-base font-black text-white">{contextStats ? contextStats.suppliers : 6}</div>
              </div>
              <div className="bg-slate-900/90 border border-slate-800 p-2.5 rounded-lg">
                <div className="text-[10px] text-slate-500 font-semibold uppercase">Active POs</div>
                <div className="text-base font-black text-white">{contextStats ? contextStats.active_orders : 3}</div>
              </div>
              <div className="bg-slate-900/90 border border-slate-800 p-2.5 rounded-lg">
                <div className="text-[10px] text-slate-500 font-semibold uppercase">IoT Feeds</div>
                <div className="text-base font-black text-cyan-400">{contextStats ? contextStats.telemetry_machines : 2}</div>
              </div>
              <div className="bg-slate-900/90 border border-slate-800 p-2.5 rounded-lg">
                <div className="text-[10px] text-slate-500 font-semibold uppercase">Vault Docs</div>
                <div className="text-base font-black text-emerald-400">{contextStats ? contextStats.compliance_documents : 1468}</div>
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between text-[10px] text-slate-500">
              <span>Vector Dimension: 3072</span>
              <span className="text-emerald-400 font-bold">100% Ingested</span>
            </div>
          </div>

          {/* Quick Context Hints */}
          <div className="p-4 flex-1">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">
              Capabilities Handled
            </h3>
            <ul className="text-[11px] text-slate-400 space-y-1.5 leading-relaxed">
              <li className="flex items-start gap-1.5">
                <span className="text-blue-400">✓</span>
                <span>Automatic lead time & price estimation</span>
              </li>
              <li className="flex items-start gap-1.5">
                <span className="text-blue-400">✓</span>
                <span>Port strike & geopolitical risk predictions</span>
              </li>
              <li className="flex items-start gap-1.5">
                <span className="text-blue-400">✓</span>
                <span>ITAR & AS9100D credential verification</span>
              </li>
              <li className="flex items-start gap-1.5">
                <span className="text-blue-400">✓</span>
                <span>Draft commercial Net 45/60 addendums</span>
              </li>
              <li className="flex items-start gap-1.5">
                <span className="text-blue-400">✓</span>
                <span>Live spindle vibration & machine OEE alerts</span>
              </li>
            </ul>
          </div>
        </div>

        {/* Center Chat Canvas */}
        <div className="flex-1 flex flex-col bg-slate-950 min-w-0">
          
          {/* Messages Stream */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {messages.map((msg) => (
              <div 
                key={msg.id} 
                className={`flex gap-3.5 max-w-4xl ${msg.role === 'user' ? 'ml-auto flex-row-reverse' : ''}`}
              >
                {/* Avatar */}
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 shadow-md ${
                  msg.role === 'user' 
                    ? 'bg-blue-600 text-white' 
                    : 'bg-gradient-to-tr from-indigo-600 to-blue-600 text-white'
                }`}>
                  {msg.role === 'user' ? <User className="w-4 h-4" /> : <Sparkles className="w-4 h-4 text-amber-300" />}
                </div>

                {/* Message Body */}
                <div className={`flex flex-col gap-2.5 min-w-0 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                  
                  {/* Text Bubble */}
                  <div className={`p-4 rounded-2xl text-xs leading-relaxed shadow-lg max-w-2xl ${
                    msg.role === 'user'
                      ? 'bg-blue-600 text-white rounded-tr-none'
                      : 'bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-none whitespace-pre-wrap'
                  }`}>
                    {msg.content}
                  </div>

                  {/* Model & Confidence Metadata pill */}
                  {msg.role === 'assistant' && msg.confidence && (
                    <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono pl-1">
                      <span className="flex items-center gap-1">
                        <Zap className="w-3 h-3 text-amber-400" />
                        Confidence: {(msg.confidence * 100).toFixed(0)}%
                      </span>
                      <span>•</span>
                      <span className="truncate max-w-[260px]">{msg.model_used}</span>
                      <span>•</span>
                      <span>{msg.timestamp}</span>
                    </div>
                  )}

                  {/* Rich Payloads */}
                  {msg.rich_payload && msg.rich_payload.widget_type === 'TABLE' && msg.rich_payload.data && (
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl w-full max-w-2xl overflow-x-auto">
                      <div className="text-xs font-bold text-white mb-2 flex items-center gap-2">
                        <Award className="w-4 h-4 text-blue-400" />
                        {msg.rich_payload.data.title}
                      </div>
                      <table className="w-full text-left text-[11px]">
                        <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800 text-[10px] uppercase font-bold">
                          <tr>
                            {(msg.rich_payload.data.columns || []).map((col: string, idx: number) => (
                              <th key={idx} className="py-2 px-2.5">{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800 text-slate-200 font-medium">
                          {(msg.rich_payload.data.rows || []).map((row: any, rIdx: number) => (
                            <tr key={rIdx} className="hover:bg-slate-800/40">
                              <td className="py-2 px-2.5 font-bold text-white">{row.supplier}</td>
                              <td className="py-2 px-2.5 text-slate-400">{row.location}</td>
                              <td className="py-2 px-2.5 text-emerald-400 font-mono font-bold">{row.capacity}</td>
                              <td className="py-2 px-2.5 font-mono">{row.oee}</td>
                              <td className="py-2 px-2.5 font-mono">{row.ontime}</td>
                              <td className="py-2 px-2.5">
                                <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[9px] font-bold">
                                  {row.cert}
                                </span>
                              </td>
                              <td className="py-2 px-2.5 text-slate-300 font-mono">{row.risk}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {msg.rich_payload && msg.rich_payload.widget_type === 'RISK_CARD' && msg.rich_payload.data && (
                    <div className="bg-rose-950/30 border border-rose-500/30 rounded-2xl p-4 shadow-xl w-full max-w-2xl text-xs">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2 text-rose-400 font-bold">
                          <AlertTriangle className="w-4 h-4 text-rose-500" />
                          <span>{msg.rich_payload.data.title}</span>
                        </div>
                        <span className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 text-[10px] font-bold">
                          {msg.rich_payload.data.severity}
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-[11px] mb-3">
                        <div className="bg-slate-900/80 p-2 rounded-lg border border-slate-800">
                          <span className="text-slate-400 font-semibold">Affected PO:</span>
                          <span className="font-mono text-white ml-1.5 font-bold">{msg.rich_payload.data.affected_po}</span>
                        </div>
                        <div className="bg-slate-900/80 p-2 rounded-lg border border-slate-800">
                          <span className="text-slate-400 font-semibold">Financial Exposure:</span>
                          <span className="font-mono text-amber-400 ml-1.5 font-bold">{msg.rich_payload.data.financial_exposure}</span>
                        </div>
                      </div>
                      <div className="bg-slate-900/90 p-3 rounded-xl border border-slate-800 mb-3">
                        <div className="text-[10px] font-bold text-amber-400 uppercase tracking-wide mb-1">
                          AI Automated Mitigation Directive
                        </div>
                        <p className="text-slate-300 leading-relaxed text-[11px]">
                          {msg.rich_payload.data.mitigation_plan}
                        </p>
                      </div>
                    </div>
                  )}

                  {msg.rich_payload && msg.rich_payload.widget_type === 'EMAIL_DRAFT' && msg.rich_payload.data && (
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl w-full max-w-2xl text-xs">
                      <div className="flex items-center justify-between mb-2.5 pb-2 border-b border-slate-800">
                        <div className="flex items-center gap-2 text-white font-bold">
                          <FileText className="w-4 h-4 text-purple-400" />
                          <span>Commercial Addendum Draft</span>
                        </div>
                        <button
                          onClick={() => handleCopy(msg.rich_payload?.data?.body || '', `copy-${msg.id}`)}
                          className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-[11px] font-bold flex items-center gap-1.5 transition-all"
                        >
                          {copiedId === `copy-${msg.id}` ? (
                            <>
                              <Check className="w-3 h-3 text-emerald-400" />
                              Copied!
                            </>
                          ) : (
                            <>
                              <Copy className="w-3 h-3" />
                              Copy Text
                            </>
                          )}
                        </button>
                      </div>
                      <div className="text-[11px] text-slate-400 mb-2 font-mono">
                        Subject: <span className="text-slate-200 font-bold">{msg.rich_payload.data.subject}</span>
                      </div>
                      <div className="p-3 bg-slate-950/80 rounded-xl border border-slate-800 font-mono text-[11px] text-slate-300 whitespace-pre-wrap leading-relaxed select-all">
                        {msg.rich_payload.data.body}
                      </div>
                    </div>
                  )}

                  {msg.rich_payload && msg.rich_payload.widget_type === 'TELEMETRY_STRIP' && msg.rich_payload.data && (
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl w-full max-w-2xl">
                      <div className="text-xs font-bold text-white mb-2 flex items-center gap-2">
                        <Activity className="w-4 h-4 text-cyan-400" />
                        Live Machine Telemetry Stream
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        {(msg.rich_payload.data.streams || []).map((stream: any, sIdx: number) => (
                          <div key={sIdx} className="bg-slate-950 p-3 rounded-xl border border-slate-800">
                            <div className="flex justify-between items-center mb-1.5">
                              <span className="font-bold text-white text-xs">{stream.machine}</span>
                              <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${
                                stream.status === 'OPTIMAL' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'
                              }`}>
                                {stream.status}
                              </span>
                            </div>
                            <div className="flex justify-between text-[11px] text-slate-400">
                              <span>Vibration: <span className="font-mono text-slate-200 font-bold">{stream.vibration}</span></span>
                              <span>OEE: <span className="font-mono text-cyan-400 font-bold">{stream.oee}</span></span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {msg.rich_payload && msg.rich_payload.widget_type === 'VAULT_AUDIT' && msg.rich_payload.data && (
                    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl w-full max-w-2xl text-xs">
                      <div className="text-xs font-bold text-white mb-2.5 flex items-center gap-2">
                        <ShieldCheck className="w-4 h-4 text-emerald-400" />
                        Evidence Vault Cryptographic Metrics
                      </div>
                      <div className="grid grid-cols-4 gap-2 mb-3">
                        <div className="bg-slate-950 p-2 rounded-lg border border-slate-800 text-center">
                          <div className="text-[10px] text-slate-500 font-semibold">Total Docs</div>
                          <div className="text-sm font-black text-white">{msg.rich_payload.data.total_docs}</div>
                        </div>
                        <div className="bg-slate-950 p-2 rounded-lg border border-slate-800 text-center">
                          <div className="text-[10px] text-slate-500 font-semibold">Verified</div>
                          <div className="text-sm font-black text-emerald-400">{msg.rich_payload.data.verified}</div>
                        </div>
                        <div className="bg-slate-950 p-2 rounded-lg border border-slate-800 text-center">
                          <div className="text-[10px] text-slate-500 font-semibold">Expiring &lt;90d</div>
                          <div className="text-sm font-black text-amber-400">{msg.rich_payload.data.expiring_90d}</div>
                        </div>
                        <div className="bg-slate-950 p-2 rounded-lg border border-slate-800 text-center">
                          <div className="text-[10px] text-slate-500 font-semibold">Tamper Integrity</div>
                          <div className="text-sm font-black text-indigo-400">{msg.rich_payload.data.tamper_score}</div>
                        </div>
                      </div>
                      <div className="p-2.5 bg-amber-500/10 border border-amber-500/20 rounded-lg text-[11px] text-amber-300 flex items-center gap-2">
                        <Clock className="w-4 h-4 text-amber-400 shrink-0" />
                        <span>Action Due: {msg.rich_payload.data.urgent_renewal}</span>
                      </div>
                    </div>
                  )}

                  {/* Evidence Citations Pills */}
                  {msg.evidence && msg.evidence.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider py-1">Sources Cited:</span>
                      {msg.evidence.map((cit, cIdx) => (
                        <Link
                          key={cIdx}
                          href={cit.deep_link}
                          className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 text-[11px] text-slate-300 hover:text-white transition-all flex items-center gap-1.5 shadow-sm"
                        >
                          <FileText className="w-3 h-3 text-blue-400" />
                          <span className="font-semibold">{cit.source}</span>
                          <span className="text-[10px] text-slate-500 font-mono">({cit.entity})</span>
                          <ExternalLink className="w-2.5 h-2.5 text-slate-500" />
                        </Link>
                      ))}
                    </div>
                  )}

                  {/* Suggested Actions CTA Pills */}
                  {msg.suggested_actions && msg.suggested_actions.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {msg.suggested_actions.map((act, aIdx) => (
                        <Link
                          key={aIdx}
                          href={act.link}
                          className="px-3 py-1.5 rounded-xl bg-gradient-to-r from-blue-600/20 to-indigo-600/20 hover:from-blue-600/30 hover:to-indigo-600/30 border border-blue-500/30 text-blue-300 hover:text-blue-200 text-xs font-bold transition-all flex items-center gap-1.5"
                        >
                          <span>{act.label}</span>
                          <ArrowRight className="w-3 h-3" />
                        </Link>
                      ))}
                    </div>
                  )}

                </div>
              </div>
            ))}

            {/* Typing Indicator */}
            {isTyping && (
              <div className="flex gap-3.5 max-w-4xl">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-blue-600 text-white flex items-center justify-center shrink-0 shadow-md">
                  <Sparkles className="w-4 h-4 text-amber-300 animate-pulse" />
                </div>
                <div className="bg-slate-900 border border-slate-800 p-4 rounded-2xl rounded-tl-none shadow-lg flex items-center gap-2">
                  <span className="text-xs text-slate-400 font-medium">Retrieving enterprise knowledge vectors...</span>
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" />
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }} />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Bottom Control Bar */}
          <div className="p-5 border-t border-slate-800 bg-slate-900/60 backdrop-blur-md shrink-0 space-y-3">
            
            {/* Context Prompt Suggestions */}
            <div className="flex items-center gap-2 overflow-x-auto pb-1 hide-scrollbar">
              <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider shrink-0 flex items-center gap-1">
                <Zap className="w-3 h-3 text-amber-400" />
                Suggested:
              </span>
              {(suggestedPrompts.length > 0 ? suggestedPrompts : [
                { category: "Discovery", text: "Which verified suppliers have >=15% free 5-axis CNC capacity?", agent_mode: "discovery" },
                { category: "Risk", text: "Analyze port strike risk for PO-2025-00441 at Chennai port", agent_mode: "risk" },
                { category: "Compliance", text: "Show me expiring certifications in the evidence vault <90 days", agent_mode: "compliance" },
                { category: "Negotiation", text: "Draft a negotiation email for Net 45 commercial terms", agent_mode: "negotiation" }
              ]).map((pr, pIdx) => (
                <button
                  key={pIdx}
                  onClick={() => {
                    if (pr.agent_mode) setSelectedAgent(pr.agent_mode);
                    handleSend(pr.text);
                  }}
                  className="px-3 py-1 rounded-full bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 text-xs font-semibold text-slate-300 hover:text-white transition-all whitespace-nowrap shrink-0 flex items-center gap-1.5"
                >
                  <span className="text-blue-400 font-bold text-[10px]">#{pr.category}</span>
                  <span>{pr.text}</span>
                </button>
              ))}
            </div>

            {/* Input Bar */}
            <div className="relative flex items-end gap-2 bg-slate-950 border border-slate-800 rounded-2xl p-2.5 focus-within:border-blue-500/60 focus-within:ring-1 focus-within:ring-blue-500/30 transition-all shadow-xl">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder={`Ask ${agentModes.find(a => a.id === selectedAgent)?.name || 'Copilot'} anything about suppliers, orders, telemetry, compliance or risk...`}
                className="flex-1 bg-transparent border-none outline-none resize-none max-h-32 min-h-[44px] py-2 px-2 text-xs text-white placeholder-slate-500"
                rows={1}
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || isTyping}
                className="p-3 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-blue-600/20 shrink-0"
                title="Send query (Enter)"
              >
                {isTyping ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>

            <div className="flex items-center justify-between text-[10px] text-slate-500 px-1">
              <span>Press <strong>Enter</strong> to send • <strong>Shift + Enter</strong> for line break</span>
              <span>Enterprise Graph RAG v4.2 • Zero-hallucination grounded citations</span>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
