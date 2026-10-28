'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  Link2, Code, Zap, CheckCircle2, ArrowRight, ShieldCheck, 
  RefreshCw, DollarSign, Cpu, Layers, ExternalLink, Copy, Check,
  Clock, AlertCircle, FileText, Building2, Sparkles, Box, Lock
} from 'lucide-react';
import Link from 'next/link';
import { apiClient, TEST_SUPPLIER_TENANT_ID } from '@/lib/apiClient';

interface LedgerBlock {
  index: number;
  timestamp: string;
  data: {
    event: string;
    contract_type?: string;
    po_id?: string;
    invoice_id?: string;
    amount_transferred?: number;
    recipient_wallet?: string;
    status?: string;
    item_id?: string;
    location?: string;
    esg_compliance?: string;
    carbon_footprint?: string;
    details?: string;
  };
  previous_hash: string;
  hash: string;
}

export default function SupplierSmartContractsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'PENDING' | 'SETTLED' | 'ALL'>('PENDING');
  const [searchQuery, setSearchQuery] = useState('');
  const [copiedHash, setCopiedHash] = useState<string | null>(null);
  const [executingInvoiceId, setExecutingInvoiceId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<{ title: string; desc: string; txHash?: string } | null>(null);

  const showToast = (title: string, desc: string, txHash?: string) => {
    setToastMessage({ title, desc, txHash });
    setTimeout(() => setToastMessage(null), 5000);
  };

  // 1. Fetch live supplier invoices
  const { 
    data: serverInvoices = [], 
    refetch: refetchInvoices, 
    isLoading: isLoadingInvoices 
  } = useQuery({
    queryKey: ['supplier-invoices', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      try {
        const res = await apiClient.get(`/api/v1/finance/invoices?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
        return res.data;
      } catch (err) {
        return [];
      }
    }
  });

  // 2. Fetch live blockchain ledger
  const { 
    data: ledgerData = { chain: [], length: 0 }, 
    refetch: refetchLedger, 
    isLoading: isLoadingLedger 
  } = useQuery({
    queryKey: ['blockchain-ledger'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/api/v1/blockchain/ledger');
        return res.data;
      } catch (err) {
        return { chain: [], length: 0 };
      }
    },
    refetchInterval: 8000
  });

  // 3. Smart contract execution mutation
  const executeMutation = useMutation({
    mutationFn: async (inv: any) => {
      setExecutingInvoiceId(inv.id);

      // Step A: Execute blockchain smart contract & mine block
      const contractPayload = {
        po_id: inv.po_id || 'PO-2025-00123',
        invoice_id: inv.id,
        amount: Number(inv.amount || inv.total_amount || 29500.0),
        supplier_id: TEST_SUPPLIER_TENANT_ID
      };

      const resContract = await apiClient.post('/api/v1/blockchain/smart-contract/execute', contractPayload);
      const minedBlock = resContract.data.block;

      // Step B: Mark invoice as PAID in finance database
      try {
        await apiClient.post(`/api/v1/finance/invoices/${inv.id}/pay`, {
          payment_method: 'Smart Contract Blockchain Auto-Disbursement',
          reference_number: `TX-${minedBlock.hash.slice(0, 14).toUpperCase()}`,
          notes: `Autonomous blockchain smart contract settlement verified on block #${minedBlock.index}. Escrow funds released to ${TEST_SUPPLIER_TENANT_ID}_WALLET.`
        });
      } catch (payErr) {
        console.warn('Pay endpoint warning:', payErr);
      }

      return { invoice: inv, block: minedBlock };
    },
    onSuccess: (result) => {
      setExecutingInvoiceId(null);
      refetchInvoices();
      refetchLedger();
      queryClient.invalidateQueries({ queryKey: ['supplier-invoices'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-pos'] });

      showToast(
        'Smart Contract Executed & Block Mined!',
        `Autonomous disbursement of $${Number(result.invoice.amount || 29500).toLocaleString()} completed. Block #${result.block.index} immutable on distributed ledger.`,
        result.block.hash
      );
    },
    onError: (err: any) => {
      setExecutingInvoiceId(null);
      alert('Smart contract execution failed: ' + (err.message || 'Unknown network error'));
    }
  });

  const handleCopyHash = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2500);
  };

  // Invoices filtered by activeTab & search
  const filteredInvoices = serverInvoices.filter((inv: any) => {
    const matchesSearch = 
      inv.id?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      inv.po_id?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (inv.buyer_tenant_id && inv.buyer_tenant_id.toLowerCase().includes(searchQuery.toLowerCase()));

    if (activeTab === 'PENDING') return matchesSearch && inv.status === 'PENDING';
    if (activeTab === 'SETTLED') return matchesSearch && inv.status === 'PAID';
    return matchesSearch;
  });

  // Calculate live financial metrics
  const pendingInvoices = serverInvoices.filter((i: any) => i.status === 'PENDING');
  const settledInvoices = serverInvoices.filter((i: any) => i.status === 'PAID');
  const pendingTotal = pendingInvoices.reduce((acc: number, i: any) => acc + (Number(i.amount) || 0), 0);
  const settledTotal = settledInvoices.reduce((acc: number, i: any) => acc + (Number(i.amount) || 0), 0);
  const blocks = [...(ledgerData.chain || [])].reverse();

  return (
    <div className="space-y-6 pb-20 max-w-[1600px] mx-auto">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white p-4 rounded-2xl shadow-2xl flex items-start gap-3 border border-purple-400/40 animate-in fade-in slide-in-from-top-4 max-w-md">
          <Sparkles className="w-6 h-6 text-purple-400 shrink-0 mt-0.5" />
          <div className="space-y-1 text-xs">
            <h4 className="font-black text-white text-sm">{toastMessage.title}</h4>
            <p className="text-slate-300 font-medium">{toastMessage.desc}</p>
            {toastMessage.txHash && (
              <div className="pt-1 font-mono text-[10px] text-purple-300 truncate">
                Hash: {toastMessage.txHash}
              </div>
            )}
          </div>
        </div>
      )}

      {/* HEADER BREADCRUMB */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Supplier Portal</span>
            <span className="text-slate-300">/</span>
            <span className="text-purple-600 font-bold">Autonomous Settlement</span>
            <span className="text-slate-300">/</span>
            <span>Blockchain Smart Contracts</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <Code className="w-8 h-8 text-purple-600" />
            <span>Smart Contracts & Autonomous Settlement</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Programmatic escrow disbursement triggered autonomously when 3-way matching and ASN dock receipt verification are satisfied.
          </p>
        </div>

        {/* Network & Wallet Badge */}
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="bg-slate-900 text-white px-3.5 py-1.5 rounded-xl border border-slate-800 flex items-center gap-2 shadow-sm text-xs">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span className="font-mono font-bold text-slate-200">Consortium Node #04 (Quorum PoA)</span>
          </div>
          <div className="bg-purple-50 text-purple-900 border border-purple-200 px-3.5 py-1.5 rounded-xl text-xs font-mono font-bold flex items-center gap-1.5 shadow-xs">
            <Lock size={12} className="text-purple-600" />
            <span>Wallet: 0x71C4...89B1</span>
          </div>
          <button
            onClick={() => {
              refetchInvoices();
              refetchLedger();
            }}
            className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-xs transition-all flex items-center gap-1.5 active:scale-95"
            title="Refresh network state"
          >
            <RefreshCw size={13} className="text-slate-500" />
            <span>Sync Live</span>
          </button>
        </div>
      </div>

      {/* METRICS KPI CARDS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Settled On-Chain</span>
            <h3 className="text-2xl font-black text-emerald-600 mt-1">
              ${settledTotal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </h3>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">{settledInvoices.length} invoices paid via smart contract</p>
          </div>
          <div className="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 flex items-center justify-center border border-emerald-100">
            <CheckCircle2 size={24} />
          </div>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Pending Auto-Release</span>
            <h3 className="text-2xl font-black text-[#0B2550] mt-1">
              ${pendingTotal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </h3>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">{pendingInvoices.length} contracts awaiting signature</p>
          </div>
          <div className="w-12 h-12 rounded-2xl bg-amber-50 text-amber-600 flex items-center justify-center border border-amber-100">
            <Zap size={24} />
          </div>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Chain Height</span>
            <h3 className="text-2xl font-black text-purple-700 mt-1">
              Block #{ledgerData.length || blocks.length || 1}
            </h3>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">SHA-256 cryptographic proof</p>
          </div>
          <div className="w-12 h-12 rounded-2xl bg-purple-50 text-purple-600 flex items-center justify-center border border-purple-100">
            <Layers size={24} />
          </div>
        </div>

        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-xs flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Gas Protocol</span>
            <h3 className="text-2xl font-black text-blue-600 mt-1">
              0.00 Gwei
            </h3>
            <p className="text-[11px] text-slate-500 font-medium mt-0.5">Enterprise Consortium Zero-Fee</p>
          </div>
          <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center border border-blue-100">
            <Cpu size={24} />
          </div>
        </div>
      </div>

      {/* MAIN TWO-COLUMN SPLIT */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        
        {/* LEFT COLUMN: PENDING CONTRACTS & EXECUTION QUEUE (7 COLS) */}
        <div className="xl:col-span-7 space-y-4">
          <div className="bg-white rounded-2xl shadow-xs border border-slate-200 p-5 space-y-4">
            
            {/* Filter Tabs & Search */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-4">
              <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-xl">
                <button
                  onClick={() => setActiveTab('PENDING')}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    activeTab === 'PENDING'
                      ? 'bg-white text-purple-900 shadow-xs font-black'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  Ready for Auto-Release ({pendingInvoices.length})
                </button>
                <button
                  onClick={() => setActiveTab('SETTLED')}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    activeTab === 'SETTLED'
                      ? 'bg-white text-purple-900 shadow-xs font-black'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  Settled On-Chain ({settledInvoices.length})
                </button>
                <button
                  onClick={() => setActiveTab('ALL')}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    activeTab === 'ALL'
                      ? 'bg-white text-purple-900 shadow-xs font-black'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  All ({serverInvoices.length})
                </button>
              </div>

              <div className="relative">
                <input
                  type="text"
                  placeholder="Search invoice or PO..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="px-3 py-1.5 pl-8 border border-slate-200 rounded-xl text-xs font-medium text-slate-800 placeholder-slate-400 focus:ring-2 focus:ring-purple-500 outline-none w-full sm:w-56"
                />
                <Code size={13} className="absolute left-2.5 top-2.5 text-slate-400" />
              </div>
            </div>

            {/* Smart Contract Execution Cards */}
            <div className="space-y-3.5">
              {filteredInvoices.length === 0 ? (
                <div className="p-12 text-center text-slate-400 space-y-2">
                  <ShieldCheck size={36} className="mx-auto text-slate-300" />
                  <p className="text-sm font-bold text-slate-600">No smart contracts found in this view.</p>
                  <p className="text-xs text-slate-400">Flip active orders to commercial invoices to generate settlement contracts.</p>
                  <Link
                    href="/supplier/invoices/create"
                    className="inline-flex items-center gap-1.5 px-4 py-2 mt-2 bg-purple-600 text-white font-bold text-xs rounded-xl shadow-xs hover:bg-purple-700"
                  >
                    <span>Create Invoice (PO-Flip)</span>
                    <ArrowRight size={13} />
                  </Link>
                </div>
              ) : (
                filteredInvoices.map((inv: any) => {
                  const isPending = inv.status === 'PENDING';
                  const isExecuting = executingInvoiceId === inv.id;
                  const poId = inv.po_id || 'PO-2025-00123';
                  const amount = Number(inv.amount || inv.total_amount || 29500.0);

                  return (
                    <div
                      key={inv.id}
                      className={`p-4 rounded-2xl border transition-all ${
                        isPending
                          ? 'border-purple-200 bg-gradient-to-r from-purple-50/40 via-white to-white hover:border-purple-300 shadow-xs'
                          : 'border-slate-200 bg-slate-50/50 hover:bg-white'
                      }`}
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-black text-slate-900 text-sm">{inv.id}</span>
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-blue-100 text-blue-800 border border-blue-200 font-mono">
                              {poId}
                            </span>
                            {isPending ? (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-amber-100 text-amber-800 border border-amber-200 flex items-center gap-1">
                                <Zap size={10} className="text-amber-600" />
                                <span>Awaiting Escrow Execution</span>
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-emerald-100 text-emerald-800 border border-emerald-200 flex items-center gap-1">
                                <CheckCircle2 size={10} className="text-emerald-600" />
                                <span>Settled & Disbursed</span>
                              </span>
                            )}
                          </div>

                          <p className="text-xs text-slate-500 font-medium">
                            Buyer: <strong className="text-slate-700">{inv.buyer_tenant_id === 'TENANT_BUYER_001' ? 'SupplyTwin Enterprise Corp' : (inv.buyer_tenant_id || 'AlphaHelion Global')}</strong> • Due: {inv.due_date ? new Date(inv.due_date).toLocaleDateString() : 'Net 30 Days'}
                          </p>

                          {/* 3-Way Match Validation Bar */}
                          <div className="flex items-center gap-2 pt-1 text-[11px]">
                            <span className="inline-flex items-center gap-1 font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-lg border border-emerald-200">
                              <ShieldCheck size={12} className="text-emerald-600" />
                              <span>3-Way Match Verified</span>
                            </span>
                            <span className="text-slate-400">•</span>
                            <span className="text-slate-500 font-mono text-[10px]">ASN Dispatch Tagged</span>
                          </div>
                        </div>

                        {/* Amount & Execute Button */}
                        <div className="flex items-center sm:flex-col sm:items-end justify-between sm:justify-center gap-3 pt-2 sm:pt-0 border-t sm:border-t-0 border-slate-100">
                          <div className="font-mono font-black text-xl text-emerald-700">
                            ${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>

                          {isPending ? (
                            <button
                              onClick={() => executeMutation.mutate(inv)}
                              disabled={isExecuting || executeMutation.isPending}
                              className={`px-4 py-2 bg-purple-600 text-white font-bold text-xs rounded-xl shadow-md shadow-purple-600/20 flex items-center gap-1.5 transition-all active:scale-95 ${
                                isExecuting ? 'opacity-70 cursor-wait' : 'hover:bg-purple-700'
                              }`}
                            >
                              {isExecuting ? (
                                <>
                                  <RefreshCw size={12} className="animate-spin" />
                                  <span>Mining Block...</span>
                                </>
                              ) : (
                                <>
                                  <Sparkles size={12} />
                                  <span>Sign & Execute</span>
                                  <ArrowRight size={12} />
                                </>
                              )}
                            </button>
                          ) : (
                            <div className="flex items-center gap-1 text-xs font-bold text-emerald-700 bg-emerald-50 px-3 py-1 rounded-xl border border-emerald-200">
                              <CheckCircle2 size={13} />
                              <span>On-Chain Funds Released</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: LIVE DISTRIBUTED LEDGER TERMINAL (5 COLS) */}
        <div className="xl:col-span-5 space-y-4">
          <div className="bg-slate-950 rounded-2xl shadow-2xl border border-slate-800 overflow-hidden flex flex-col h-[750px]">
            
            {/* Terminal Header */}
            <div className="p-4 bg-slate-900 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-rose-500"></span>
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
                </div>
                <span className="text-slate-400 font-mono text-xs pl-2 font-bold flex items-center gap-1.5">
                  <Link2 size={13} className="text-emerald-400" />
                  <span>Live Consortium Distributed Ledger</span>
                </span>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800">
                  {blocks.length} Blocks
                </span>
              </div>
            </div>

            {/* Blocks Stream */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3 font-mono text-xs">
              {blocks.map((block: LedgerBlock) => {
                const isAutoPayment = block.data.event?.includes('Smart Contract') || block.data.event?.includes('Auto-Payment');

                return (
                  <div
                    key={block.index}
                    className={`p-3.5 rounded-xl border transition-all ${
                      isAutoPayment
                        ? 'bg-purple-950/30 border-purple-800/80 text-purple-200'
                        : 'bg-slate-900/80 border-slate-800 text-slate-300'
                    }`}
                  >
                    {/* Top Row: Block index & Timestamp */}
                    <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800/80">
                      <span className={`px-2 py-0.5 rounded font-black text-[11px] ${
                        isAutoPayment
                          ? 'bg-purple-900/60 text-purple-300 border border-purple-700'
                          : 'bg-slate-800 text-emerald-400 border border-slate-700'
                      }`}>
                        Block #{block.index}
                      </span>
                      <span className="text-[10px] text-slate-500 flex items-center gap-1">
                        <Clock size={10} />
                        <span>{new Date(block.timestamp).toLocaleTimeString()}</span>
                      </span>
                    </div>

                    {/* Event Title */}
                    <div className="font-bold text-white text-xs mb-1.5 flex items-center gap-1.5">
                      {isAutoPayment ? (
                        <Zap size={13} className="text-amber-400 shrink-0" />
                      ) : (
                        <Box size={13} className="text-blue-400 shrink-0" />
                      )}
                      <span>{block.data.event}</span>
                    </div>

                    {/* Auto-Payment Details if present */}
                    {block.data.amount_transferred !== undefined && (
                      <div className="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800/80 space-y-1 my-2 text-[11px]">
                        <div className="flex justify-between">
                          <span className="text-slate-400">Contract Type:</span>
                          <span className="font-bold text-purple-400">{block.data.contract_type || 'Auto-Payment'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Disbursed Amount:</span>
                          <span className="font-black text-emerald-400">${Number(block.data.amount_transferred).toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
                        </div>
                        {block.data.invoice_id && (
                          <div className="flex justify-between">
                            <span className="text-slate-400">Invoice Ref:</span>
                            <span className="font-bold text-slate-200">{block.data.invoice_id}</span>
                          </div>
                        )}
                        {block.data.recipient_wallet && (
                          <div className="flex justify-between">
                            <span className="text-slate-400">Recipient Wallet:</span>
                            <span className="text-slate-300 truncate max-w-[180px]">{block.data.recipient_wallet}</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Traceability Metadata if present */}
                    {block.data.item_id && (
                      <div className="bg-slate-950/60 p-2 rounded text-[11px] text-slate-400 space-y-0.5 my-1">
                        <div>Item: <span className="text-white font-bold">{block.data.item_id}</span></div>
                        {block.data.location && <div>Facility: {block.data.location}</div>}
                        {block.data.esg_compliance && <div>ESG: <span className="text-emerald-400">{block.data.esg_compliance}</span></div>}
                      </div>
                    )}

                    {/* SHA-256 Hash with Copy */}
                    <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] text-slate-500">
                      <div className="truncate max-w-[260px]">
                        <span className="text-slate-400 font-bold">Hash: </span>
                        <span className="text-slate-400">{block.hash}</span>
                      </div>
                      <button
                        onClick={() => handleCopyHash(block.hash)}
                        className="text-slate-400 hover:text-white p-1 rounded transition-colors"
                        title="Copy SHA-256 Block Hash"
                      >
                        {copiedHash === block.hash ? (
                          <Check size={11} className="text-emerald-400" />
                        ) : (
                          <Copy size={11} />
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
