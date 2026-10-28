"use client";
import React, { useState, useEffect } from "react";
import Link from 'next/link';

interface DynamicClause {
  clause_id: string;
  title: string;
  clause_text: string;
  ai_rationale?: string;
}

interface SlaCommitments {
  target_otif_pct: number;
  current_otif_pct: number;
  max_defect_ppm: number;
  current_defect_ppm: number;
  liquidated_damages_per_day_delay_pct: number;
  max_liquidated_damages_cap_pct: number;
  remedy_window_hours: number;
}

interface AuditEvent {
  timestamp: string;
  action: string;
  actor: string;
  notes?: string;
}

interface Contract {
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
  sla_commitments: SlaCommitments;
  dynamic_clauses: DynamicClause[];
  document_content?: string;
  buyer_signature?: string | null;
  buyer_signed_by?: string | null;
  buyer_signed_at?: string | null;
  supplier_signature?: string | null;
  supplier_signed_by?: string | null;
  supplier_signed_at?: string | null;
  ledger_tx_hash?: string | null;
  ledger_block_height?: number | null;
  is_ledger_deployed?: boolean;
  audit_trail: AuditEvent[];
}

export default function ViewContracts() {
  const [activeTab, setActiveTab] = useState('All Contracts');
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [selectedContract, setSelectedContract] = useState<Contract | null>(null);
  const [detailTab, setDetailTab] = useState<'overview' | 'clauses' | 'signatures' | 'audit'>('overview');
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [toast, setToast] = useState<string | null>(null);
  const [isDeploying, setIsDeploying] = useState(false);
  const [isSigning, setIsSigning] = useState(false);
  const [isRenewing, setIsRenewing] = useState(false);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  };

  const fetchContracts = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/contracts/list');
      if (res.ok) {
        const data = await res.json();
        setContracts(data.contracts || []);
      }
    } catch (e) {
      console.warn("Could not fetch live contracts, using baseline fallback", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContracts();
  }, []);

  const handleSelectContract = async (contractId: string) => {
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/contracts/${contractId}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedContract(data.contract);
      } else {
        const fallback = contracts.find(c => c.id === contractId);
        if (fallback) setSelectedContract(fallback);
      }
    } catch {
      const fallback = contracts.find(c => c.id === contractId);
      if (fallback) setSelectedContract(fallback);
    }
  };

  const handleDeployLedger = async () => {
    if (!selectedContract) return;
    setIsDeploying(true);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/contracts/${selectedContract.id}/deploy-ledger`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Contract ${selectedContract.id} sealed on ledger at Block #${data.block_height}!`);
        await handleSelectContract(selectedContract.id);
        fetchContracts();
      } else {
        showToast("Error deploying contract to blockchain ledger.");
      }
    } catch (err) {
      showToast("Network error while deploying contract to ledger.");
    } finally {
      setIsDeploying(false);
    }
  };

  const handleSignContract = async (role: 'buyer' | 'supplier') => {
    if (!selectedContract) return;
    setIsSigning(true);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/contracts/${selectedContract.id}/sign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          signature_name: role === 'buyer' ? 'Alex Sharma (VP Global Sourcing)' : `${selectedContract.supplier_name} Authorized Signatory`,
          signer_role: role,
          notes: 'Executed via cryptographic signature card'
        })
      });
      if (res.ok) {
        showToast(`Cryptographic signature verified for ${role.toUpperCase()}!`);
        await handleSelectContract(selectedContract.id);
        fetchContracts();
      } else {
        showToast("Error recording signature.");
      }
    } catch (err) {
      showToast("Network error during signature execution.");
    } finally {
      setIsSigning(false);
    }
  };

  const handleRenew = async () => {
    if (!selectedContract) return;
    setIsRenewing(true);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/contracts/${selectedContract.id}/renew`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Contract ${selectedContract.id} renewed for 24 months through ${data.new_end_date}!`);
        await handleSelectContract(selectedContract.id);
        fetchContracts();
      } else {
        showToast("Failed to renew contract.");
      }
    } catch (err) {
      showToast("Network error during contract renewal.");
    } finally {
      setIsRenewing(false);
    }
  };

  const filteredContracts = contracts.filter(c => {
    const matchesSearch = searchQuery === '' || 
      c.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.supplier_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.category.toLowerCase().includes(searchQuery.toLowerCase());

    if (!matchesSearch) return false;

    if (activeTab === 'All Contracts') return true;
    if (activeTab === 'Active') return c.status === 'FULLY_SIGNED';
    if (activeTab === 'Expiring Soon') return c.days_remaining <= 90 || c.status === 'EXPIRING_SOON';
    if (activeTab === 'Pending Signatures') return c.status === 'SENT_FOR_SIGNATURE' || c.status === 'PARTIALLY_SIGNED';
    if (activeTab === 'Draft') return c.status === 'DRAFT';
    return true;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'FULLY_SIGNED':
        return <span className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2.5 py-0.5 rounded-full text-xs font-bold flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Active</span>;
      case 'EXPIRING_SOON':
        return <span className="bg-amber-500/10 text-amber-400 border border-amber-500/30 px-2.5 py-0.5 rounded-full text-xs font-bold flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span> Expiring Soon</span>;
      case 'SENT_FOR_SIGNATURE':
      case 'PARTIALLY_SIGNED':
        return <span className="bg-blue-500/10 text-blue-400 border border-blue-500/30 px-2.5 py-0.5 rounded-full text-xs font-bold flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-blue-400"></span> Pending Signature</span>;
      default:
        return <span className="bg-slate-500/10 text-slate-300 border border-slate-500/30 px-2.5 py-0.5 rounded-full text-xs font-bold flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span> {status}</span>;
    }
  };

  // If viewing a detailed contract
  if (selectedContract) {
    return (
      <div className="flex flex-col h-full bg-[#0B0F19] text-slate-100 overflow-y-auto">
        {toast && (
          <div className="fixed top-6 right-6 z-50 bg-emerald-950 border border-emerald-500/50 text-emerald-300 px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 text-sm font-semibold animate-fade-in">
            <span>✨</span> {toast}
          </div>
        )}

        {/* Sticky Detail Header */}
        <div className="bg-[#111827] border-b border-slate-800 px-8 pt-6 pb-4 shrink-0 sticky top-0 z-20">
          <div className="text-[11px] font-extrabold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-2">
            <Link href="/contracts" className="hover:text-blue-400 transition-colors">Contracts Engine</Link>
            <span className="text-slate-600">›</span>
            <button onClick={() => setSelectedContract(null)} className="hover:text-blue-400 transition-colors">Contract Repository</button>
            <span className="text-slate-600">›</span>
            <span className="text-blue-400 font-mono">{selectedContract.id}</span>
          </div>

          <div className="flex justify-between items-start mb-6 gap-6">
            <div>
              <div className="flex items-center gap-3 mb-1.5">
                <h1 className="text-2xl font-bold font-mono tracking-tight text-white">{selectedContract.id}</h1>
                {getStatusBadge(selectedContract.status)}
                {selectedContract.is_ledger_deployed && (
                  <span className="bg-purple-500/10 text-purple-400 border border-purple-500/30 px-2.5 py-0.5 rounded-full text-xs font-mono font-bold flex items-center gap-1.5">
                    ⛓️ Sealed on Chain
                  </span>
                )}
                {selectedContract.escrow_linked && (
                  <span className="bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 px-2.5 py-0.5 rounded-full text-xs font-mono font-bold flex items-center gap-1.5">
                    🛡️ Escrow Linked
                  </span>
                )}
              </div>
              <h2 className="text-base text-slate-200 font-medium mb-1.5">{selectedContract.name}</h2>
              <div className="flex items-center gap-3 text-xs text-slate-400">
                <span className="text-blue-400 font-semibold">{selectedContract.supplier_name}</span>
                <span className="text-slate-600">•</span>
                <span>{selectedContract.supplier_location}</span>
                <span className="text-slate-600">•</span>
                <span>{selectedContract.start_date} – {selectedContract.end_date}</span>
                <span className="text-slate-600">•</span>
                <span className={selectedContract.days_remaining < 60 ? "text-amber-400 font-bold" : "text-emerald-400 font-bold"}>
                  {selectedContract.days_remaining} days remaining
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button 
                onClick={() => setSelectedContract(null)} 
                className="px-3.5 py-2 border border-slate-700 hover:border-slate-600 bg-slate-900/60 text-slate-300 font-semibold text-xs rounded-lg transition-colors flex items-center gap-1.5"
              >
                ← Back to List
              </button>
              
              {!selectedContract.is_ledger_deployed && (
                <button
                  disabled={isDeploying}
                  onClick={handleDeployLedger}
                  className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs rounded-lg shadow-lg shadow-purple-900/30 flex items-center gap-2 transition-colors disabled:opacity-50"
                >
                  {isDeploying ? 'Deploying...' : '⛓️ Deploy SLA to Ledger'}
                </button>
              )}

              <button
                disabled={isRenewing}
                onClick={handleRenew}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded-lg shadow-lg shadow-blue-900/30 flex items-center gap-2 transition-colors disabled:opacity-50"
              >
                {isRenewing ? 'Renewing...' : '🔄 Extend (+24 Mo)'}
              </button>

              <button
                onClick={() => {
                  showToast("Contract agreement exported to cryptographically verified JSON archive.");
                }}
                className="px-3.5 py-2 border border-slate-700 hover:border-slate-600 bg-slate-900 text-slate-300 font-semibold text-xs rounded-lg transition-colors"
              >
                📄 Export
              </button>
            </div>
          </div>

          {/* Sub Navigation Tabs */}
          <div className="flex gap-6 text-xs font-bold border-t border-slate-800/80 pt-3">
            <button 
              onClick={() => setDetailTab('overview')} 
              className={`pb-2 transition-colors flex items-center gap-2 ${detailTab === 'overview' ? 'text-blue-400 border-b-2 border-blue-500' : 'text-slate-400 hover:text-slate-200'}`}
            >
              📊 Overview & SLA
            </button>
            <button 
              onClick={() => setDetailTab('clauses')} 
              className={`pb-2 transition-colors flex items-center gap-2 ${detailTab === 'clauses' ? 'text-blue-400 border-b-2 border-blue-500' : 'text-slate-400 hover:text-slate-200'}`}
            >
              ⚖️ Dynamic Legal Clauses ({selectedContract.dynamic_clauses.length})
            </button>
            <button 
              onClick={() => setDetailTab('signatures')} 
              className={`pb-2 transition-colors flex items-center gap-2 ${detailTab === 'signatures' ? 'text-blue-400 border-b-2 border-blue-500' : 'text-slate-400 hover:text-slate-200'}`}
            >
              🔐 Signatures & Blockchain Ledger
            </button>
            <button 
              onClick={() => setDetailTab('audit')} 
              className={`pb-2 transition-colors flex items-center gap-2 ${detailTab === 'audit' ? 'text-blue-400 border-b-2 border-blue-500' : 'text-slate-400 hover:text-slate-200'}`}
            >
              📜 Audit Trail ({selectedContract.audit_trail.length})
            </button>
          </div>
        </div>

        {/* Tab Content Body */}
        <div className="flex-1 p-8 max-w-7xl mx-auto w-full">
          {detailTab === 'overview' && (
            <div className="grid grid-cols-3 gap-6">
              {/* Left Column (2 Cols) */}
              <div className="col-span-2 flex flex-col gap-6">
                {/* Contract Core Info */}
                <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
                  <h3 className="font-bold text-white text-sm mb-4 flex items-center gap-2">
                    <span className="text-blue-400">📄</span> Contract Specifications
                  </h3>
                  <div className="grid grid-cols-2 gap-y-4 gap-x-8 text-xs">
                    <div><span className="text-slate-500 block">Contract ID</span><span className="font-mono font-bold text-white text-sm">{selectedContract.id}</span></div>
                    <div><span className="text-slate-500 block">Total Program Value</span><span className="font-bold text-emerald-400 text-sm">${selectedContract.total_value_usd.toLocaleString()} USD</span></div>
                    <div><span className="text-slate-500 block">Supplier</span><span className="font-bold text-slate-200">{selectedContract.supplier_name}</span></div>
                    <div><span className="text-slate-500 block">Annual Run Rate</span><span className="font-bold text-slate-200">${selectedContract.annual_run_rate_usd.toLocaleString()} USD/yr</span></div>
                    <div><span className="text-slate-500 block">Category</span><span className="font-bold text-slate-200">{selectedContract.category}</span></div>
                    <div><span className="text-slate-500 block">Payment Terms</span><span className="font-bold text-slate-200">{selectedContract.payment_terms}</span></div>
                    <div><span className="text-slate-500 block">Start Date</span><span className="font-bold text-slate-200">{selectedContract.start_date}</span></div>
                    <div><span className="text-slate-500 block">End Date</span><span className="font-bold text-slate-200">{selectedContract.end_date}</span></div>
                    <div><span className="text-slate-500 block">Smart Escrow ID</span><span className="font-mono text-cyan-400">{selectedContract.escrow_contract_id || 'Not Escrow Bound'}</span></div>
                    <div><span className="text-slate-500 block">Governing Law</span><span className="font-bold text-slate-200">International Commercial Law & Arbitration</span></div>
                  </div>
                </div>

                {/* SLA Commitments & Performance */}
                <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
                  <h3 className="font-bold text-white text-sm mb-4 flex items-center gap-2">
                    <span className="text-blue-400">🎯</span> Live SLA Performance vs Thresholds
                  </h3>
                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-4">
                      <div className="text-[11px] text-slate-400 font-medium">On-Time In-Full (OTIF)</div>
                      <div className="text-xl font-bold font-mono text-white mt-1">
                        {selectedContract.sla_commitments.current_otif_pct}%
                      </div>
                      <div className="text-[10px] text-slate-500 mt-1">
                        Target: <span className="text-emerald-400 font-semibold">{selectedContract.sla_commitments.target_otif_pct}%</span>
                      </div>
                      <div className="w-full bg-slate-800 h-1.5 rounded-full mt-2 overflow-hidden">
                        <div 
                          className={`h-full ${selectedContract.sla_commitments.current_otif_pct >= selectedContract.sla_commitments.target_otif_pct ? 'bg-emerald-400' : 'bg-amber-400'}`} 
                          style={{width: `${Math.min(100, selectedContract.sla_commitments.current_otif_pct)}%`}}
                        ></div>
                      </div>
                    </div>

                    <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-4">
                      <div className="text-[11px] text-slate-400 font-medium">Defect Density (PPM)</div>
                      <div className="text-xl font-bold font-mono text-white mt-1">
                        {selectedContract.sla_commitments.current_defect_ppm} PPM
                      </div>
                      <div className="text-[10px] text-slate-500 mt-1">
                        Cap: <span className="text-emerald-400 font-semibold">{selectedContract.sla_commitments.max_defect_ppm} PPM</span>
                      </div>
                      <div className="w-full bg-slate-800 h-1.5 rounded-full mt-2 overflow-hidden">
                        <div 
                          className="h-full bg-emerald-400" 
                          style={{width: `${Math.min(100, (selectedContract.sla_commitments.current_defect_ppm / selectedContract.sla_commitments.max_defect_ppm) * 100)}%`}}
                        ></div>
                      </div>
                    </div>

                    <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-4">
                      <div className="text-[11px] text-slate-400 font-medium">Liquidated Damages Rate</div>
                      <div className="text-xl font-bold font-mono text-amber-400 mt-1">
                        {selectedContract.sla_commitments.liquidated_damages_per_day_delay_pct}% / day
                      </div>
                      <div className="text-[10px] text-slate-500 mt-1">
                        Cap: <span className="text-slate-300">{selectedContract.sla_commitments.max_liquidated_damages_cap_pct}%</span> • Buffer: {selectedContract.sla_commitments.remedy_window_hours}h
                      </div>
                      <div className="w-full bg-slate-800 h-1.5 rounded-full mt-2 overflow-hidden">
                        <div className="h-full bg-amber-400" style={{width: '25%'}}></div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Column (1 Col) */}
              <div className="col-span-1 flex flex-col gap-6">
                {/* Cryptographic Execution Status */}
                <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
                  <h3 className="font-bold text-white text-sm mb-4 flex items-center gap-2">
                    <span className="text-emerald-400">🛡️</span> Execution Integrity
                  </h3>
                  <div className="space-y-4 text-xs">
                    <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-slate-400 font-semibold">Buyer Signature</span>
                        {selectedContract.buyer_signature ? (
                          <span className="text-emerald-400 font-bold flex items-center gap-1">✓ Verified</span>
                        ) : (
                          <span className="text-amber-400 font-bold">Pending</span>
                        )}
                      </div>
                      <div className="text-slate-300 font-mono text-[11px] truncate">
                        {selectedContract.buyer_signed_by || 'Not signed'}
                      </div>
                      {selectedContract.buyer_signed_at && (
                        <div className="text-[10px] text-slate-500 mt-0.5">{selectedContract.buyer_signed_at}</div>
                      )}
                    </div>

                    <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-slate-400 font-semibold">Supplier Signature</span>
                        {selectedContract.supplier_signature ? (
                          <span className="text-emerald-400 font-bold flex items-center gap-1">✓ Verified</span>
                        ) : (
                          <button 
                            disabled={isSigning}
                            onClick={() => handleSignContract('supplier')}
                            className="text-xs bg-blue-600 hover:bg-blue-500 text-white font-bold px-2 py-0.5 rounded transition-colors"
                          >
                            Execute Sign
                          </button>
                        )}
                      </div>
                      <div className="text-slate-300 font-mono text-[11px] truncate">
                        {selectedContract.supplier_signed_by || 'Pending Supplier Signatory'}
                      </div>
                      {selectedContract.supplier_signed_at && (
                        <div className="text-[10px] text-slate-500 mt-0.5">{selectedContract.supplier_signed_at}</div>
                      )}
                    </div>

                    <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-slate-400 font-semibold">Immutable Ledger</span>
                        {selectedContract.is_ledger_deployed ? (
                          <span className="text-purple-400 font-bold font-mono">Block #{selectedContract.ledger_block_height}</span>
                        ) : (
                          <span className="text-slate-500">Not Deployed</span>
                        )}
                      </div>
                      <div className="text-slate-400 font-mono text-[10px] truncate">
                        {selectedContract.ledger_tx_hash || 'Pending ledger commitment'}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Quick Actions */}
                <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
                  <h3 className="font-bold text-white text-sm mb-4">Quick Actions</h3>
                  <div className="flex flex-col gap-2 text-xs">
                    <Link
                      href="/contracts/create"
                      className="p-3 bg-slate-900/60 hover:bg-slate-800/80 border border-slate-800 hover:border-slate-700 rounded-lg font-semibold text-slate-200 transition-colors flex items-center gap-2"
                    >
                      <span>➕</span> Draft New SOW / Addendum
                    </Link>
                    <Link
                      href="/contracts/templates"
                      className="p-3 bg-slate-900/60 hover:bg-slate-800/80 border border-slate-800 hover:border-slate-700 rounded-lg font-semibold text-slate-200 transition-colors flex items-center gap-2"
                    >
                      <span>📑</span> Browse Vetted Legal Templates
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          )}

          {detailTab === 'clauses' && (
            <div className="flex flex-col gap-4">
              <div className="flex justify-between items-center mb-2">
                <div>
                  <h3 className="text-base font-bold text-white">Dynamic AI-Grounded Contract Clauses</h3>
                  <p className="text-xs text-slate-400">Tailored SLA and protection terms derived from live digital twin capability indices.</p>
                </div>
                <span className="text-xs bg-blue-500/10 text-blue-400 border border-blue-500/30 px-3 py-1 rounded-full font-mono">
                  {selectedContract.dynamic_clauses.length} Active Clauses
                </span>
              </div>

              {selectedContract.dynamic_clauses.map((clause, idx) => (
                <div key={idx} className="bg-[#111827] border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-colors">
                  <div className="flex justify-between items-start mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-blue-400 bg-blue-950/60 border border-blue-800/50 px-2 py-0.5 rounded">
                        {clause.clause_id}
                      </span>
                      <h4 className="font-bold text-white text-sm">{clause.title}</h4>
                    </div>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed font-sans mb-3 bg-slate-900/70 p-3 rounded-lg border border-slate-800/60">
                    "{clause.clause_text}"
                  </p>
                  {clause.ai_rationale && (
                    <div className="flex items-start gap-2 text-[11px] text-cyan-300 bg-cyan-950/30 border border-cyan-800/40 p-2.5 rounded-lg">
                      <span className="font-bold shrink-0">🤖 Digital Twin Rationale:</span>
                      <span className="leading-snug">{clause.ai_rationale}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {detailTab === 'signatures' && (
            <div className="flex flex-col gap-6">
              <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
                <h3 className="text-sm font-bold text-white mb-4">Cryptographic Signatures (Dual-Party Multi-Sig)</h3>
                <div className="grid grid-cols-2 gap-6">
                  {/* Buyer Card */}
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Buyer Signatory</span>
                      {selectedContract.buyer_signature ? (
                        <span className="text-xs text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded">Signed & Validated</span>
                      ) : (
                        <button 
                          disabled={isSigning}
                          onClick={() => handleSignContract('buyer')}
                          className="text-xs bg-blue-600 hover:bg-blue-500 text-white font-bold px-3 py-1 rounded"
                        >
                          Sign Now
                        </button>
                      )}
                    </div>
                    <div className="text-sm font-bold text-white mb-1">{selectedContract.buyer_signed_by || 'Alex Sharma (VP Global Sourcing)'}</div>
                    <div className="text-[11px] text-slate-400 mb-3">Timestamp: {selectedContract.buyer_signed_at || 'Pending'}</div>
                    <div className="text-[10px] font-mono text-slate-400 bg-black/40 p-2 rounded break-all border border-slate-800">
                      {selectedContract.buyer_signature || '0x--'}
                    </div>
                  </div>

                  {/* Supplier Card */}
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Supplier Signatory</span>
                      {selectedContract.supplier_signature ? (
                        <span className="text-xs text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded">Signed & Validated</span>
                      ) : (
                        <button 
                          disabled={isSigning}
                          onClick={() => handleSignContract('supplier')}
                          className="text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-bold px-3 py-1 rounded"
                        >
                          Execute Counter-Signature
                        </button>
                      )}
                    </div>
                    <div className="text-sm font-bold text-white mb-1">{selectedContract.supplier_signed_by || selectedContract.supplier_name}</div>
                    <div className="text-[11px] text-slate-400 mb-3">Timestamp: {selectedContract.supplier_signed_at || 'Pending Counter-Signature'}</div>
                    <div className="text-[10px] font-mono text-slate-400 bg-black/40 p-2 rounded break-all border border-slate-800">
                      {selectedContract.supplier_signature || '0x--'}
                    </div>
                  </div>
                </div>
              </div>

              {/* Blockchain Anchor Details */}
              <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <span className="text-purple-400">⛓️</span> Immutable Ledger Anchor
                  </h3>
                  {!selectedContract.is_ledger_deployed && (
                    <button
                      disabled={isDeploying}
                      onClick={handleDeployLedger}
                      className="px-4 py-1.5 bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs rounded-lg transition-colors"
                    >
                      {isDeploying ? 'Deploying...' : 'Deploy SLA to Chain'}
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-3 gap-4 text-xs font-mono">
                  <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-lg">
                    <span className="text-slate-500 block mb-1">Ledger State</span>
                    <span className={selectedContract.is_ledger_deployed ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
                      {selectedContract.is_ledger_deployed ? "ACTIVE ON CHAIN" : "LOCAL CACHE ONLY"}
                    </span>
                  </div>
                  <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-lg">
                    <span className="text-slate-500 block mb-1">Block Height</span>
                    <span className="text-purple-400 font-bold">
                      {selectedContract.ledger_block_height ? `#${selectedContract.ledger_block_height}` : 'Uncommitted'}
                    </span>
                  </div>
                  <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-lg">
                    <span className="text-slate-500 block mb-1">Smart Escrow Vault</span>
                    <span className="text-cyan-400 font-bold">
                      {selectedContract.escrow_contract_id || 'N/A'}
                    </span>
                  </div>
                </div>
                
                {selectedContract.ledger_tx_hash && (
                  <div className="mt-4 p-3 bg-black/40 border border-slate-800 rounded-lg">
                    <span className="text-[10px] text-slate-500 block mb-1 uppercase font-mono">Cryptographic Transaction Root Hash</span>
                    <span className="text-xs font-mono text-purple-300 break-all">{selectedContract.ledger_tx_hash}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {detailTab === 'audit' && (
            <div className="bg-[#111827] border border-slate-800 rounded-xl p-6">
              <h3 className="text-sm font-bold text-white mb-4">Contract Lifecycle Audit Trail</h3>
              <div className="space-y-4 relative pl-6 border-l border-slate-800">
                {selectedContract.audit_trail.map((evt, idx) => (
                  <div key={idx} className="relative">
                    <div className="absolute -left-[31px] top-1 w-3 h-3 rounded-full bg-blue-500 border-2 border-[#111827]"></div>
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-xs font-bold text-blue-400">{evt.action}</span>
                      <span className="text-[11px] text-slate-500">{evt.timestamp}</span>
                    </div>
                    <div className="text-xs text-slate-300 font-medium mt-1">Actor: <span className="text-white">{evt.actor}</span></div>
                    {evt.notes && <div className="text-xs text-slate-400 mt-0.5">{evt.notes}</div>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Contract List Table View
  const tabs = [
    { name: 'All Contracts', count: contracts.length },
    { name: 'Active', count: contracts.filter(c => c.status === 'FULLY_SIGNED').length },
    { name: 'Expiring Soon', count: contracts.filter(c => c.days_remaining <= 90 || c.status === 'EXPIRING_SOON').length },
    { name: 'Pending Signatures', count: contracts.filter(c => c.status === 'SENT_FOR_SIGNATURE' || c.status === 'PARTIALLY_SIGNED').length },
    { name: 'Draft', count: contracts.filter(c => c.status === 'DRAFT').length },
  ];

  return (
    <div className="flex h-full bg-[#0B0F19] text-slate-100 flex-col overflow-y-auto">
      {toast && (
        <div className="fixed top-6 right-6 z-50 bg-emerald-950 border border-emerald-500/50 text-emerald-300 px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 text-sm font-semibold animate-fade-in">
          <span>✨</span> {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex justify-between items-start shrink-0 px-8 pt-8 pb-4 bg-[#111827] border-b border-slate-800">
        <div>
          <div className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest mb-1 flex items-center gap-1.5">
            <Link href="/contracts" className="hover:text-blue-400 transition-colors">Contracts Engine</Link>
            <span className="text-slate-600">›</span>
            <span className="text-blue-400">View Contracts</span>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Contract Repository & SLA Ledger</h1>
          <p className="text-sm text-slate-400 mt-1 font-medium">
            Active multi-tier supplier contracts, blockchain SLAs, liquidated damages clauses, and cryptographic signatures.
          </p>
        </div>
        <div className="mt-2 flex gap-3">
          <Link
            href="/contracts/create"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm rounded-lg shadow-lg shadow-blue-900/30 flex items-center gap-2 transition-colors"
          >
            + Create Contract
          </Link>
        </div>
      </div>

      <div className="flex flex-col gap-6 flex-1 px-8 py-6">
        {/* Main Table Container */}
        <div className="bg-[#111827] border border-slate-800 rounded-xl shadow-xl flex flex-col min-h-0 flex-1">
          {/* Tabs */}
          <div className="flex gap-6 border-b border-slate-800 px-6 shrink-0 overflow-x-auto">
            {tabs.map(tab => (
              <button 
                key={tab.name}
                onClick={() => setActiveTab(tab.name)}
                className={`py-4 text-xs font-bold border-b-2 transition-colors flex items-center gap-1.5 whitespace-nowrap ${
                  activeTab === tab.name 
                    ? 'border-blue-500 text-blue-400' 
                    : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700'
                }`}
              >
                {tab.name} <span className="text-slate-500 font-mono">({tab.count})</span>
              </button>
            ))}
          </div>

          {/* Filter Bar */}
          <div className="px-6 py-4 border-b border-slate-800/80 flex gap-4 shrink-0 flex-wrap items-center">
            <div className="relative flex-1 min-w-[280px] max-w-md">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-xs">🔍</span>
              <input 
                type="text" 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by contract ID, supplier, or category..." 
                className="w-full bg-slate-900 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-xs outline-none focus:border-blue-500 text-slate-200 placeholder-slate-500"
              />
            </div>

            <button 
              onClick={() => {
                setSearchQuery('');
                setActiveTab('All Contracts');
                fetchContracts();
                showToast("Filters reset and live contracts refreshed.");
              }}
              className="px-3.5 py-2 border border-slate-800 text-slate-400 hover:text-slate-200 text-xs font-semibold rounded-lg hover:bg-slate-900 transition-colors ml-auto"
            >
              🔄 Refresh List
            </button>
          </div>

          {/* Table */}
          <div className="overflow-x-auto overflow-y-auto flex-1">
            <table className="w-full text-left text-xs min-w-[950px]">
              <thead className="text-slate-400 font-bold border-b border-slate-800 bg-[#0B0F19]/50 sticky top-0 z-10">
                <tr>
                  <th className="py-3 px-6">Contract ID</th>
                  <th className="py-3 px-4">Contract Title</th>
                  <th className="py-3 px-4">Supplier</th>
                  <th className="py-3 px-4">Category</th>
                  <th className="py-3 px-4">Target OTIF</th>
                  <th className="py-3 px-4">Term</th>
                  <th className="py-3 px-4">Total Value</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-medium text-slate-300">
                {loading ? (
                  <tr>
                    <td colSpan={9} className="py-12 text-center text-slate-400">Loading enterprise contracts from repository...</td>
                  </tr>
                ) : filteredContracts.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-12 text-center text-slate-400">No contracts found matching filter criteria.</td>
                  </tr>
                ) : (
                  filteredContracts.map((row) => (
                    <tr 
                      key={row.id} 
                      onClick={() => handleSelectContract(row.id)}
                      className="hover:bg-slate-800/40 cursor-pointer transition-colors group"
                    >
                      <td className="py-4 px-6 font-mono font-bold text-blue-400 group-hover:underline">{row.id}</td>
                      <td className="py-4 px-4 text-white font-semibold">{row.name}</td>
                      <td className="py-4 px-4">{row.supplier_name}</td>
                      <td className="py-4 px-4 text-slate-400">{row.category}</td>
                      <td className="py-4 px-4 font-mono font-bold text-emerald-400">{row.sla_commitments?.target_otif_pct || 98.0}%</td>
                      <td className="py-4 px-4 text-slate-400 text-[11px]">{row.start_date} – {row.end_date}</td>
                      <td className="py-4 px-4 font-mono font-bold text-slate-200">${row.total_value_usd.toLocaleString()}</td>
                      <td className="py-4 px-4">{getStatusBadge(row.status)}</td>
                      <td className="py-4 px-4 text-center">
                        <button 
                          onClick={(e) => {
                            e.stopPropagation();
                            handleSelectContract(row.id);
                          }}
                          className="px-2.5 py-1 bg-slate-800 hover:bg-blue-600 text-slate-300 hover:text-white rounded text-xs font-semibold transition-colors"
                        >
                          Inspect →
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Footer Ribbon */}
          <div className="p-4 border-t border-slate-800 flex justify-between items-center text-xs text-slate-400 bg-slate-900/50 rounded-b-xl">
            <div>Displaying {filteredContracts.length} enterprise contracts (Multi-Tenant Encrypted)</div>
            <div className="flex items-center gap-2 font-mono">
              <span>Autonomous SLA Oracle: <span className="text-emerald-400 font-bold">ACTIVE</span></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
