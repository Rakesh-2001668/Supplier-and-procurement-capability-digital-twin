'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  FileText, ShieldCheck, Zap, Lock, Database, Check, Clock, 
  AlertTriangle, RefreshCw, Sparkles, ExternalLink, ArrowRight,
  TrendingUp, Award, Building2, CheckCircle2, Copy, Send, Code,
  Sliders, ChevronRight, FileCheck
} from 'lucide-react';

interface ContractClause {
  clause_id: string;
  title: string;
  clause_text: string;
  ai_rationale: string;
}

interface SLACommitments {
  target_otif_pct: number;
  current_otif_pct: number;
  max_defect_ppm: number;
  current_defect_ppm: number;
  liquidated_damages_per_day_delay_pct: number;
  max_liquidated_damages_cap_pct: number;
  remedy_window_hours: number;
}

interface ContractDetail {
  id: string;
  name: string;
  contract_type: string;
  category: string;
  supplier_id: string;
  supplier_name: string;
  supplier_location: string;
  buyer_name: string;
  status: string;
  start_date: string;
  end_date: string;
  days_remaining: number;
  total_value_usd: number;
  annual_run_rate_usd: number;
  payment_terms: string;
  escrow_linked: boolean;
  escrow_contract_id?: string;
  sla_commitments: SLACommitments;
  dynamic_clauses: ContractClause[];
  document_content: string;
  buyer_signature?: string | null;
  buyer_signed_by?: string | null;
  buyer_signed_at?: string | null;
  supplier_signature?: string | null;
  supplier_signed_by?: string | null;
  supplier_signed_at?: string | null;
  ledger_tx_hash?: string | null;
  ledger_block_height?: number | null;
  is_ledger_deployed?: boolean;
  audit_trail?: Array<{
    timestamp: string;
    action: string;
    actor: string;
    notes?: string;
  }>;
}

export default function SmartContractsPage() {
  const [selectedContractId, setSelectedContractId] = useState<string>('MSA-2026-081');
  const [contract, setContract] = useState<ContractDetail | null>(null);
  const [contractsList, setContractsList] = useState<ContractDetail[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [activeClauseId, setActiveClauseId] = useState<string>('CLAUSE-SLA-01');
  const [simulatedDelayDays, setSimulatedDelayDays] = useState<number>(3);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const fetchContracts = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/contracts/list');
      if (res.ok) {
        const data = await res.json();
        setContractsList(data.contracts || []);
        const found = (data.contracts || []).find((c: ContractDetail) => c.id === selectedContractId);
        setContract(found || data.contracts[0] || null);
      }
    } catch (err) {
      console.error('Failed to load contracts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContracts();
  }, [selectedContractId]);

  const handleSelectContract = (id: string) => {
    setSelectedContractId(id);
    const found = contractsList.find(c => c.id === id);
    if (found) setContract(found);
  };

  // Deploy smart contract to ledger
  const handleDeployLedger = async () => {
    if (!contract) return;
    setActionLoading('deploy');
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/contracts/${contract.id}/deploy-ledger`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Smart Contract SLA sealed on block #${data.block_height}!`);
        await fetchContracts();
      }
    } catch (err) {
      console.error(err);
      showToast('Error deploying contract to ledger.');
    } finally {
      setActionLoading(null);
    }
  };

  // Sign contract
  const handleSignContract = async (role: 'buyer' | 'supplier') => {
    if (!contract) return;
    setActionLoading(`sign-${role}`);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/contracts/${contract.id}/sign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          signature_name: role === 'buyer' ? 'Alex Sharma (VP Global Sourcing)' : contract.supplier_name + ' Executive',
          signer_role: role,
          notes: 'Hardware cryptographic security token validated.'
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Contract ${contract.id} signed successfully as ${role.toUpperCase()}!`);
        await fetchContracts();
      }
    } catch (err) {
      console.error(err);
      showToast('Error signing contract.');
    } finally {
      setActionLoading(null);
    }
  };

  // Calculated penalty
  const calculatedPenaltyPct = contract ? Math.min(
    contract.sla_commitments.max_liquidated_damages_cap_pct,
    simulatedDelayDays * contract.sla_commitments.liquidated_damages_per_day_delay_pct
  ) : 0;
  const calculatedPenaltyUsd = contract ? (contract.total_value_usd * (calculatedPenaltyPct / 100)) : 0;

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
            <Code className="w-4 h-4 text-blue-400" />
            <span>Agentic Smart Contracts & SLA Lifecycle Engine</span>
          </div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20">
                <FileCheck className="w-5 h-5" />
              </div>
              Smart Contract Blueprint
            </h1>
            <span className="px-2.5 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[11px] font-bold">
              Dynamic Telemetry SLA
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            AI-generated legal agreements with auto-adjusting SLA clauses grounded in live supplier digital twin telemetry and smart escrow penalties.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Contract Selector */}
          <select
            value={selectedContractId}
            onChange={(e) => handleSelectContract(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-white font-bold outline-none focus:border-blue-500"
          >
            {contractsList.map(c => (
              <option key={c.id} value={c.id}>
                {c.id} - {c.supplier_name}
              </option>
            ))}
          </select>

          <Link
            href="/contracts/create"
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-blue-500/20 transition-all flex items-center gap-1.5"
          >
            + Create Contract
          </Link>
        </div>
      </div>

      {/* Sub-navigation Tabs */}
      <div className="border-b border-slate-800/80 bg-slate-900/40 px-8 flex items-center gap-6 text-xs font-bold">
        <Link href="/contracts" className="py-3 text-blue-400 border-b-2 border-blue-500 transition-colors flex items-center gap-1.5">
          <Code className="w-3.5 h-3.5" />
          Smart Blueprint & SLA
        </Link>
        <Link href="/contracts/view" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <FileText className="w-3.5 h-3.5" />
          All Contracts ({contractsList.length || 5})
        </Link>
        <Link href="/contracts/pending-renewals" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5 text-amber-400" />
          Pending Renewals
        </Link>
        <Link href="/contracts/templates" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <Copy className="w-3.5 h-3.5" />
          Contract Templates
        </Link>
      </div>

      {/* Main Grid Content */}
      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-6">
        
        {/* Quick KPI Ribbon */}
        {contract && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 shrink-0">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-500/10 text-blue-400 flex items-center justify-center shrink-0">
                <FileText className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Contract Value</div>
                <div className="text-lg font-black text-white">${contract.total_value_usd.toLocaleString()}</div>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center shrink-0">
                <CheckCircle2 className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Target OTIF SLA</div>
                <div className="text-lg font-black text-emerald-400">{contract.sla_commitments.target_otif_pct}%</div>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-purple-500/10 text-purple-400 flex items-center justify-center shrink-0">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Max Defect PPM</div>
                <div className="text-lg font-black text-purple-400">{contract.sla_commitments.max_defect_ppm} PPM</div>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-amber-500/10 text-amber-400 flex items-center justify-center shrink-0">
                <Clock className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Days Remaining</div>
                <div className="text-lg font-black text-amber-400">{contract.days_remaining} Days</div>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center shrink-0">
                <Database className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Ledger Anchor</div>
                <div className="text-xs font-mono font-bold text-indigo-300">
                  {contract.is_ledger_deployed ? `Block #${contract.ledger_block_height}` : 'Pending Seal'}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 2-Column Main Workspace */}
        {contract && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            
            {/* Left 2 Cols: Master Contract Blueprint */}
            <div className="xl:col-span-2 space-y-5">
              <div className="bg-slate-900/90 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl flex flex-col h-[750px]">
                
                {/* Contract Blueprint Toolbar */}
                <div className="p-4 border-b border-slate-800 bg-slate-950/60 flex flex-wrap justify-between items-center gap-3 shrink-0">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-9 h-9 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20 flex items-center justify-center shrink-0">
                      <FileText className="w-5 h-5" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="font-black text-sm text-white truncate">{contract.name}</h3>
                      <p className="text-[11px] text-slate-400 truncate">
                        ID: <span className="font-mono text-slate-300 font-bold">{contract.id}</span> • Party: <span className="text-blue-400 font-semibold">{contract.supplier_name}</span>
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-1 bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold rounded-lg flex items-center gap-1">
                      <Sparkles className="w-3 h-3 text-amber-300" />
                      AI Dynamic SLA
                    </span>
                    <span className={`px-2.5 py-1 rounded-lg text-[10px] font-bold border ${
                      contract.status === 'FULLY_SIGNED' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' :
                      contract.status === 'SENT_FOR_SIGNATURE' ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' :
                      'bg-slate-800 text-slate-300 border-slate-700'
                    }`}>
                      {contract.status}
                    </span>
                  </div>
                </div>

                {/* Contract Body Document Text */}
                <div className="p-8 flex-1 overflow-y-auto space-y-6 text-xs text-slate-300 leading-relaxed font-sans bg-slate-950/40">
                  <div className="text-center pb-4 border-b border-slate-800">
                    <div className="text-xs uppercase font-mono tracking-widest text-blue-400 font-bold mb-1">
                      ALPHAHELION GLOBAL PROCUREMENT PROTOCOL
                    </div>
                    <h1 className="text-xl font-black text-white">{contract.name}</h1>
                    <div className="text-[11px] text-slate-400 mt-1 font-mono">
                      Contract Ref: {contract.id} • Term: {contract.start_date} to {contract.end_date}
                    </div>
                  </div>

                  {/* Section 1 */}
                  <section className="space-y-2">
                    <h2 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
                      <span className="text-blue-400">1.</span> Scope of Supply & Deliverables
                    </h2>
                    <p className="text-slate-300">
                      This Master Agreement is entered into by and between <strong>{contract.buyer_name}</strong> ("Buyer") and <strong>{contract.supplier_name}</strong> ("Supplier"), located at {contract.supplier_location}. Supplier agrees to manufacture, precision-inspect, and deliver components under category <strong>{contract.category}</strong> adhering strictly to specifications, CAD dimensional tolerances, and milestone purchase orders released under this framework.
                    </p>
                  </section>

                  {/* Section 2: AI Dynamic SLA Clauses */}
                  <section className="space-y-3">
                    <h2 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
                      <span className="text-blue-400">2.</span> Dynamic Service Level Agreement (SLA) & Liquidated Damages
                    </h2>

                    <div className="space-y-3">
                      {contract.dynamic_clauses.map((clause) => {
                        const isCurrentActive = activeClauseId === clause.clause_id;
                        return (
                          <div
                            key={clause.clause_id}
                            onClick={() => setActiveClauseId(clause.clause_id)}
                            className={`p-4 rounded-xl border transition-all cursor-pointer ${
                              isCurrentActive
                                ? 'bg-blue-600/10 border-blue-500/50 ring-1 ring-blue-500/30'
                                : 'bg-slate-900/80 border-slate-800 hover:border-slate-700'
                            }`}
                          >
                            <div className="flex items-center justify-between mb-1.5">
                              <div className="flex items-center gap-2">
                                <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                                <span className="font-bold text-xs text-white">{clause.title}</span>
                              </div>
                              <span className="text-[10px] font-mono text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
                                {clause.clause_id}
                              </span>
                            </div>
                            <p className="text-slate-200 text-xs leading-relaxed font-mono bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/80">
                              "{clause.clause_text}"
                            </p>
                            <div className="mt-2 text-[11px] text-amber-300/90 flex items-start gap-1.5 bg-amber-500/5 p-2 rounded border border-amber-500/20">
                              <span className="font-bold text-amber-400 shrink-0">Digital Twin Rationale:</span>
                              <span>{clause.ai_rationale}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </section>

                  {/* Section 3: Smart Escrow & Commercial Settlement */}
                  <section className="space-y-2">
                    <h2 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
                      <span className="text-blue-400">3.</span> Commercial Settlement & Smart Escrow Architecture
                    </h2>
                    <p className="text-slate-300">
                      Payment terms shall operate on <strong>{contract.payment_terms}</strong>. Where escrow integration is active (Contract: <span className="font-mono text-blue-400">{contract.escrow_contract_id || 'ESC-MULTI-SIG'}</span>), milestone payments are programmatically escrowed upon Purchase Order release and automatically liquidated to Supplier's wallet upon cryptographic confirmation of Advanced Shipping Notice (ASN) and receiving CMM inspection clearance.
                    </p>
                  </section>

                  {/* Section 4: Force Majeure & Choke Point Buffer */}
                  <section className="space-y-2">
                    <h2 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
                      <span className="text-blue-400">4.</span> Geopolitical Disruption & Transit Buffer
                    </h2>
                    <p className="text-slate-300">
                      Unexcused customs delays are subject to a {contract.sla_commitments.remedy_window_hours}-hour cure window before liquidated damages deduct {contract.sla_commitments.liquidated_damages_per_day_delay_pct}% per diem up to a maximum ceiling of {contract.sla_commitments.max_liquidated_damages_cap_pct}%.
                    </p>
                  </section>

                  {/* Digital Signature Execution Block */}
                  <section className="pt-6 border-t border-slate-800 space-y-4">
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
                      Cryptographic Execution & Signatures
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Buyer Signature Box */}
                      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
                        <div className="flex justify-between items-center text-xs">
                          <span className="text-slate-400 font-semibold">Buyer Signatory:</span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                            Executed
                          </span>
                        </div>
                        <div className="text-xs font-bold text-white">{contract.buyer_signed_by || 'Alex Sharma'}</div>
                        <div className="font-mono text-[10px] text-slate-400 break-all select-all bg-slate-950 p-2 rounded border border-slate-800">
                          {contract.buyer_signature || '0x7a89b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0'}
                        </div>
                        <div className="text-[10px] text-slate-500">{contract.buyer_signed_at || '2026-10-01T14:30:00Z'}</div>
                      </div>

                      {/* Supplier Signature Box */}
                      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
                        <div className="flex justify-between items-center text-xs">
                          <span className="text-slate-400 font-semibold">Supplier Signatory:</span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                            contract.supplier_signature 
                              ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' 
                              : 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                          }`}>
                            {contract.supplier_signature ? 'Executed' : 'Pending Signature'}
                          </span>
                        </div>
                        <div className="text-xs font-bold text-white">
                          {contract.supplier_signed_by || contract.supplier_name + ' Officer'}
                        </div>
                        <div className="font-mono text-[10px] text-slate-400 break-all select-all bg-slate-950 p-2 rounded border border-slate-800">
                          {contract.supplier_signature || 'Signature awaited from authorized representative.'}
                        </div>
                        <div className="text-[10px] text-slate-500">
                          {contract.supplier_signed_at || 'Pending digital certificate presentation'}
                        </div>
                      </div>
                    </div>
                  </section>
                </div>

                {/* Blueprint Footer Controls */}
                <div className="p-4 border-t border-slate-800 bg-slate-950/80 flex flex-wrap justify-between items-center gap-3 shrink-0">
                  <div className="flex items-center gap-2">
                    {!contract.supplier_signature && (
                      <button
                        onClick={() => handleSignContract('supplier')}
                        disabled={actionLoading === 'sign-supplier'}
                        className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs shadow-md transition-all flex items-center gap-1.5"
                      >
                        <Lock className="w-3.5 h-3.5" />
                        Execute Counter-Signature
                      </button>
                    )}
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      onClick={handleDeployLedger}
                      disabled={contract.is_ledger_deployed || actionLoading === 'deploy'}
                      className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 shadow-lg ${
                        contract.is_ledger_deployed
                          ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 cursor-default'
                          : 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white shadow-blue-500/20'
                      }`}
                    >
                      {contract.is_ledger_deployed ? (
                        <>
                          <Check className="w-4 h-4 text-emerald-400" />
                          Sealed on Ledger (#{contract.ledger_block_height})
                        </>
                      ) : actionLoading === 'deploy' ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Deploying to Block Header...
                        </>
                      ) : (
                        <>
                          <Zap className="w-4 h-4 text-amber-300" />
                          Deploy SLA to Blockchain Ledger
                        </>
                      )}
                    </button>
                  </div>
                </div>

              </div>
            </div>

            {/* Right 1 Col: SLA Simulator & Digital Twin Guardrails */}
            <div className="space-y-5">
              
              {/* Interactive SLA Penalty Simulator */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-bold text-white">
                    <Sliders className="w-4 h-4 text-amber-400" />
                    <span>SLA Penalty Calculator</span>
                  </div>
                  <span className="text-[10px] text-slate-400 font-mono">Live Escrow Logic</span>
                </div>

                <div>
                  <div className="flex justify-between text-xs mb-1.5">
                    <span className="text-slate-400">Simulate Delay:</span>
                    <span className="font-bold text-white">{simulatedDelayDays} Days</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="15"
                    value={simulatedDelayDays}
                    onChange={(e) => setSimulatedDelayDays(Number(e.target.value))}
                    className="w-full accent-blue-500 cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] text-slate-500 mt-1">
                    <span>On-Time (0d)</span>
                    <span>Grace (2d)</span>
                    <span>Max Delay (15d)</span>
                  </div>
                </div>

                <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 space-y-2 text-xs">
                  <div className="flex justify-between items-center">
                    <span className="text-slate-400">Rate per Day:</span>
                    <span className="font-bold text-amber-400 font-mono">
                      {contract.sla_commitments.liquidated_damages_per_day_delay_pct}% / day
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-400">Applied Penalty:</span>
                    <span className="font-bold text-rose-400 font-mono">{calculatedPenaltyPct.toFixed(1)}%</span>
                  </div>
                  <div className="flex justify-between items-center pt-2 border-t border-slate-800">
                    <span className="text-slate-300 font-bold">Escrow Deduction:</span>
                    <span className="text-base font-black text-rose-400 font-mono">
                      -${calculatedPenaltyUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })} USD
                    </span>
                  </div>
                </div>

                <p className="text-[10px] text-slate-500 leading-relaxed">
                  Penalties are programmatically withheld in smart contract escrow and automatically credited back to Buyer's operating account.
                </p>
              </div>

              {/* Digital Twin Telemetry Feeds */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-3">
                <div className="flex items-center gap-2 text-xs font-bold text-white">
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                  <span>Digital Twin SLA Telemetry</span>
                </div>

                <div className="space-y-2.5 text-xs">
                  <div className="p-2.5 bg-slate-950 rounded-xl border border-slate-800 flex justify-between items-center">
                    <span className="text-slate-400">Current OTIF Performance:</span>
                    <span className="font-black text-emerald-400 font-mono">
                      {contract.sla_commitments.current_otif_pct}%
                    </span>
                  </div>
                  <div className="p-2.5 bg-slate-950 rounded-xl border border-slate-800 flex justify-between items-center">
                    <span className="text-slate-400">Current Defect Rate:</span>
                    <span className="font-black text-purple-400 font-mono">
                      {contract.sla_commitments.current_defect_ppm} PPM
                    </span>
                  </div>
                  <div className="p-2.5 bg-slate-950 rounded-xl border border-slate-800 flex justify-between items-center">
                    <span className="text-slate-400">Escrow Contract Anchor:</span>
                    <span className="font-mono text-blue-400 font-bold text-[11px]">
                      {contract.escrow_contract_id || 'ESC-MULTI-SIG'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Audit Trail Timeline */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-3">
                <div className="text-xs font-bold text-white">Lifecycle Event Audit Trail</div>
                <div className="space-y-3 relative before:absolute before:inset-0 before:left-3.5 before:w-0.5 before:bg-slate-800">
                  {(contract.audit_trail || []).map((ev, iIdx) => (
                    <div key={iIdx} className="relative flex items-start gap-3 pl-7 text-xs">
                      <div className="absolute left-2 top-1.5 w-3 h-3 rounded-full bg-blue-500 ring-4 ring-slate-900 shrink-0" />
                      <div className="bg-slate-950 p-2.5 rounded-xl border border-slate-800 flex-1">
                        <div className="flex justify-between items-center mb-0.5">
                          <span className="font-bold text-white text-[11px]">{ev.action}</span>
                          <span className="text-[9px] text-slate-500 font-mono">
                            {new Date(ev.timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                          </span>
                        </div>
                        <div className="text-[10px] text-slate-400">Actor: <span className="text-slate-200">{ev.actor}</span></div>
                        {ev.notes && <div className="text-[10px] text-slate-400 italic mt-0.5">"{ev.notes}"</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>

          </div>
        )}

      </div>
    </div>
  );
}
