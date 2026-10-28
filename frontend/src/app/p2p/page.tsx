'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  ShoppingCart, FileText, CheckCircle2, AlertTriangle, 
  ArrowRight, Search, RefreshCw, Plus, Layers, Zap, 
  BarChart3, Clock, ChevronRight, ShieldCheck, ShieldAlert, 
  Send, Database, Award, ArrowLeftRight, Activity, DollarSign,
  Truck, CheckCheck, Sparkles, Building2, ExternalLink, X, FileCheck
} from 'lucide-react';
import axios from 'axios';

interface LineageData {
  root_document: { type: string; id: string };
  lineage_sequence: string[];
  total_links: number;
}

export default function P2PCockpitPage() {
  const [activeTab, setActiveTab] = useState<'overview' | 'requisitions' | 'orders' | 'receiving' | 'invoices' | 'lineage'>('overview');
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Live P2P Data States
  const [requisitions, setRequisitions] = useState<any[]>([]);
  const [orders, setOrders] = useState<any[]>([]);
  const [invoices, setInvoices] = useState<any[]>([]);
  const [lineage, setLineage] = useState<LineageData | null>(null);

  // Guided Buying Search State
  const [searchQuery, setSearchQuery] = useState('DC-330');
  const [searchResults, setSearchResults] = useState<any>(null);
  const [searching, setSearching] = useState(false);

  // Modals & Action States
  const [showCreditNoteModal, setShowCreditNoteModal] = useState(false);
  const [creditNoteNumber, setCreditNoteNumber] = useState('CN-TF-221');
  const [creditNoteAmount, setCreditNoteAmount] = useState(7960.0);
  const [resolvingException, setResolvingException] = useState(false);
  const [postingToErp, setPostingToErp] = useState(false);
  const [erpDocResult, setErpDocResult] = useState<any>(null);

  const triggerToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4500);
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [reqRes, poRes, invRes, linRes] = await Promise.all([
        axios.get('http://127.0.0.1:8080/api/v1/p2p/requisitions'),
        axios.get('http://127.0.0.1:8080/api/v1/p2p/purchase-orders'),
        axios.get('http://127.0.0.1:8080/api/v1/p2p/invoices'),
        axios.get('http://127.0.0.1:8080/api/v1/p2p/lineage/INVOICE/INV-TF-8812')
      ]);

      if (reqRes.data.status === 'success') setRequisitions(reqRes.data.requisitions || []);
      if (poRes.data.status === 'success') setOrders(poRes.data.purchase_orders || []);
      if (invRes.data.status === 'success') setInvoices(invRes.data.invoices || []);
      if (linRes.data.status === 'success') setLineage(linRes.data.lineage || null);
    } catch (err) {
      console.error('Failed to load P2P data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    handleSearch('DC-330');
  }, []);

  const handleSearch = async (query: string) => {
    setSearching(true);
    try {
      const res = await axios.post('http://127.0.0.1:8080/api/v1/p2p/guided-buying/search', {
        query: query,
        tenant_id: 'axion-mobility'
      });
      if (res.data.status === 'success') {
        setSearchResults(res.data.results);
      }
    } catch (err) {
      console.error('Guided search failed:', err);
    } finally {
      setSearching(false);
    }
  };

  const handleResolveException = async () => {
    setResolvingException(true);
    try {
      const res = await axios.post('http://127.0.0.1:8080/api/v1/p2p/invoices/INV-TF-8812/resolve-exception', {
        resolution_type: 'CREDIT_NOTE',
        credit_note_number: creditNoteNumber,
        credit_note_amount_inr: creditNoteAmount,
        notes: `Credit note ${creditNoteNumber} received for 20 rejected aluminium housings @ ₹398.`,
        actor: 'u:ap.clerk.2'
      });
      if (res.data.status === 'success') {
        triggerToast('Invoice exception resolved with Credit Note! Status is now MATCHED.');
        setShowCreditNoteModal(false);
        loadData();
      }
    } catch (err: any) {
      alert(`Exception resolution failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setResolvingException(false);
    }
  };

  const handlePostToErp = async () => {
    setPostingToErp(true);
    try {
      const res = await axios.post(
        'http://127.0.0.1:8080/api/v1/p2p/invoices/INV-TF-8812/post',
        {},
        {
          headers: { 'Idempotency-Key': 'AXN|1000|TF001|INV-TF-8812' }
        }
      );
      setErpDocResult(res.data);
      triggerToast(`Invoice successfully posted to SAP S/4HANA (Doc #${res.data.erpDocument})!`);
      loadData();
    } catch (err: any) {
      alert(`ERP posting failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setPostingToErp(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 md:p-8 space-y-8 font-sans">
      
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-3 bg-emerald-950/90 border border-emerald-500/50 text-emerald-200 px-5 py-3.5 rounded-xl shadow-2xl backdrop-blur-md animate-in fade-in duration-300">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
        </div>
      )}

      {/* Header Banner: Axion Mobility Systems Signature Cockpit */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#0B1528] via-[#0F1E38] to-[#070B14] border border-slate-800/80 p-8 shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="px-3 py-1 text-xs font-bold tracking-widest uppercase bg-cyan-950/80 text-cyan-400 border border-cyan-800/80 rounded-full flex items-center gap-1.5 shadow-sm">
                <Sparkles className="w-3.5 h-3.5" /> AlphaHelion Purchasing Intelligence Cloud
              </span>
              <span className="px-2.5 py-0.5 text-xs font-semibold bg-blue-950/60 text-blue-300 border border-blue-800/50 rounded-full">
                Manufacturing Pack · Axion Mobility Systems
              </span>
            </div>
            <h1 className="text-3xl lg:text-4xl font-extrabold tracking-tight text-white flex items-center gap-3">
              Operational Procure-to-Pay (P2P) Cockpit
            </h1>
            <p className="text-slate-400 max-w-3xl text-sm md:text-base leading-relaxed">
              Governed end-to-end procurement execution: from MRP netting and 4-tier guided buying to touchless PO release, 3-way match, and idempotent SAP S/4HANA posting.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button 
              onClick={() => setActiveTab('lineage')}
              className="px-4 py-2.5 rounded-xl text-sm font-semibold bg-cyan-600 hover:bg-cyan-500 text-white shadow-lg shadow-cyan-900/40 flex items-center gap-2 transition-all duration-200 border border-cyan-400/30"
            >
              <Layers className="w-4 h-4" /> View End-to-End Lineage
            </button>
            <button 
              onClick={loadData}
              disabled={loading}
              className="p-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 transition-colors"
              title="Refresh Data"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
            </button>
          </div>
        </div>

        {/* 14-Stage Lifecycle Progression Strip */}
        <div className="mt-8 pt-6 border-t border-slate-800/60">
          <span className="text-[11px] font-bold uppercase tracking-widest text-slate-400 block mb-3">
            Signature Document Chain: DC-330 Aluminium Die-Cast Housing (P100 Hosur)
          </span>
          <div className="flex items-center gap-2 overflow-x-auto pb-2 text-xs">
            <span className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 flex items-center gap-1.5 shrink-0">
              <span className="font-mono text-cyan-400">MR-1043</span>
              <span className="text-slate-500">MRP Net 9,000</span>
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
            <span className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 flex items-center gap-1.5 shrink-0">
              <span className="font-mono text-cyan-400">REQ-2311</span>
              <span className="text-slate-500">PR Approved</span>
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
            <span className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 flex items-center gap-1.5 shrink-0">
              <span className="font-mono text-cyan-400">SA-5520</span>
              <span className="text-slate-500">Contract ₹398</span>
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
            <span className="px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-800/80 text-emerald-300 flex items-center gap-1.5 shrink-0 font-semibold">
              <span className="font-mono">PO-77410</span>
              <span>Risk 18 · Touchless</span>
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
            <span className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 flex items-center gap-1.5 shrink-0">
              <span className="font-mono text-cyan-400">GR-90231</span>
              <span className="text-slate-500">5,380 Acc / 20 Rej</span>
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
            <span className="px-3 py-1.5 rounded-lg bg-amber-950/60 border border-amber-800/80 text-amber-300 flex items-center gap-1.5 shrink-0 font-semibold">
              <span className="font-mono">INV-TF-8812</span>
              <span>3-Way +20 Exception</span>
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
            <span className="px-3 py-1.5 rounded-lg bg-purple-950/60 border border-purple-800/80 text-purple-300 flex items-center gap-1.5 shrink-0">
              <span className="font-mono">CN-TF-221</span>
              <span>Credit Note 20 pcs</span>
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-slate-600 shrink-0" />
            <span className="px-3 py-1.5 rounded-lg bg-emerald-950/80 border border-emerald-500/80 text-emerald-200 flex items-center gap-1.5 shrink-0 font-bold shadow-sm">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              <span>SAP #5100004421</span>
            </span>
          </div>
        </div>
      </div>

      {/* KPI Cards Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        
        {/* KPI 1 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg group hover:border-cyan-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Touchless PO Rate</span>
            <span className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              <Zap className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-white">41.2%</div>
          <div className="mt-2 text-xs text-emerald-400 font-semibold">Target &gt; 30% met</div>
          <div className="text-[11px] text-slate-400 mt-0.5">DMN-02 L4 Agent Released</div>
        </div>

        {/* KPI 2 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg group hover:border-emerald-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">First-Pass Match</span>
            <span className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <CheckCheck className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-white">86.4%</div>
          <div className="mt-2 text-xs text-emerald-400 font-semibold">Target &gt; 80% met</div>
          <div className="text-[11px] text-slate-400 mt-0.5">DMN-03 Tolerances Applied</div>
        </div>

        {/* KPI 3 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg group hover:border-purple-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Avg PO Risk Score</span>
            <span className="p-2 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20">
              <BarChart3 className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-purple-300">18.0 / 100</div>
          <div className="mt-2 text-xs text-purple-400 font-semibold">Low Risk Band (&lt;30)</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Explainable Additive Model</div>
        </div>

        {/* KPI 4 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg group hover:border-amber-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Exception Cycle Time</span>
            <span className="p-2 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <Clock className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-white">0.8 Days</div>
          <div className="mt-2 text-xs text-emerald-400 font-semibold">-64% vs benchmark</div>
          <div className="text-[11px] text-slate-400 mt-0.5">Credit note fast-path</div>
        </div>

        {/* KPI 5 */}
        <div className="bg-[#0B1528]/80 backdrop-blur-sm border border-slate-800/90 rounded-2xl p-5 shadow-lg group hover:border-blue-500/40 transition-all duration-300">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Realised P&L Savings</span>
            <span className="p-2 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <DollarSign className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-black text-white">₹6.3 Cr</div>
          <div className="mt-2 text-xs text-cyan-400 font-semibold">Principle P12 Compliant</div>
          <div className="text-[11px] text-slate-400 mt-0.5">From posted invoices only</div>
        </div>

      </div>

      {/* Workspace Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800/80 pb-3 overflow-x-auto text-xs font-bold">
        <button 
          onClick={() => setActiveTab('overview')}
          className={`px-4 py-2 rounded-xl transition-colors flex items-center gap-2 whitespace-nowrap ${
            activeTab === 'overview' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Activity className="w-3.5 h-3.5" /> P2P Overview & Signature Case
        </button>
        <button 
          onClick={() => setActiveTab('requisitions')}
          className={`px-4 py-2 rounded-xl transition-colors flex items-center gap-2 whitespace-nowrap ${
            activeTab === 'requisitions' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <FileText className="w-3.5 h-3.5" /> Guided Buying & PRs (M04)
        </button>
        <button 
          onClick={() => setActiveTab('orders')}
          className={`px-4 py-2 rounded-xl transition-colors flex items-center gap-2 whitespace-nowrap ${
            activeTab === 'orders' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <ShoppingCart className="w-3.5 h-3.5" /> Purchase Orders & Touchless (M08)
        </button>
        <button 
          onClick={() => setActiveTab('receiving')}
          className={`px-4 py-2 rounded-xl transition-colors flex items-center gap-2 whitespace-nowrap ${
            activeTab === 'receiving' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Truck className="w-3.5 h-3.5" /> Goods Receipt & Quality Hold (M09)
        </button>
        <button 
          onClick={() => setActiveTab('invoices')}
          className={`px-4 py-2 rounded-xl transition-colors flex items-center gap-2 whitespace-nowrap ${
            activeTab === 'invoices' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <DollarSign className="w-3.5 h-3.5 text-amber-400" /> 3-Way Match & Invoicing (M10)
        </button>
        <button 
          onClick={() => setActiveTab('lineage')}
          className={`px-4 py-2 rounded-xl transition-colors flex items-center gap-2 whitespace-nowrap ${
            activeTab === 'lineage' ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40' : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
          }`}
        >
          <Layers className="w-3.5 h-3.5 text-purple-400" /> End-to-End Lineage (P10)
        </button>
      </div>

      {/* Main Tab Content */}
      <div className="space-y-6">

        {/* TAB 1: Overview */}
        {activeTab === 'overview' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            
            {/* Left: Signature Walkthrough Card (7 cols) */}
            <div className="lg:col-span-7 bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-cyan-400" />
                  <h2 className="text-lg font-bold text-white">Signature P2P Execution: DC-330 Housing</h2>
                </div>
                <span className="text-xs px-2.5 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800 font-mono">
                  Plant P100 Hosur
                </span>
              </div>

              <div className="space-y-3 text-xs">
                <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                  <div className="flex items-center justify-between text-slate-400 font-bold">
                    <span>1. MRP Netting (MR-1043)</span>
                    <span className="text-cyan-400">Net: 9,000 Units</span>
                  </div>
                  <p className="text-slate-300 text-[11px]">
                    Gross Demand: 12,000 − On-hand: 1,400 − Open PO: 1,200 − In-transit: 600 + Safety Stock: 200 = <strong>9,000 units net requirement</strong>.
                  </p>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                  <div className="flex items-center justify-between text-slate-400 font-bold">
                    <span>2. Sourcing Award & Contract Allocation</span>
                    <span className="text-emerald-400">Dual-Source 60/40</span>
                  </div>
                  <p className="text-slate-300 text-[11px]">
                    Trichy Forge Works (60% share @ ₹398 under Scheduling Agreement <strong>SA-5520</strong>) and Kovai Diecast (40% share @ ₹405).
                  </p>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                  <div className="flex items-center justify-between text-slate-400 font-bold">
                    <span>3. Touchless Purchase Order (PO-77410)</span>
                    <span className="text-cyan-300">Risk Score: 18/100 (Pass)</span>
                  </div>
                  <p className="text-slate-300 text-[11px]">
                    Quantity: 5,400 units released against SA-5520. Late-delivery probability = 0.22 (18 pts). All touchless criteria satisfied $\implies$ auto-released by L4 Agent.
                  </p>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                  <div className="flex items-center justify-between text-slate-400 font-bold">
                    <span>4. Goods Receipt & Quality Non-Conformance (GR-90231)</span>
                    <span className="text-amber-400">20 Rejections (Porosity)</span>
                  </div>
                  <p className="text-slate-300 text-[11px]">
                    5,400 received $\implies$ 5,380 accepted into inventory, 20 rejected under Quality Inspection <strong>QL-2210</strong>.
                  </p>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1">
                  <div className="flex items-center justify-between text-slate-400 font-bold">
                    <span>5. 3-Way Match Exception & Credit Note Resolution</span>
                    <span className="text-purple-400">Credit Note CN-TF-221</span>
                  </div>
                  <p className="text-slate-300 text-[11px]">
                    Invoice INV-TF-8812 billed for full 5,400 units. 3-way match flagged +20 quantity variance. Resolved via Credit Note <strong>CN-TF-221</strong> for ₹7,960.
                  </p>
                </div>

                <div className="p-3.5 rounded-xl bg-emerald-950/30 border border-emerald-800/60 space-y-1">
                  <div className="flex items-center justify-between text-emerald-300 font-bold">
                    <span>6. Exactly-Once SAP S/4HANA Posting</span>
                    <span className="text-emerald-400 font-mono">Doc #5100004421</span>
                  </div>
                  <p className="text-emerald-200/80 text-[11px]">
                    Posted with idempotency key <code>AXN|1000|TF001|INV-TF-8812</code>. Verified idempotent with zero duplicate financial postings.
                  </p>
                </div>
              </div>
            </div>

            {/* Right: Quick Action Hub & SoD Matrix (5 cols) */}
            <div className="lg:col-span-5 space-y-5">
              
              <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
                <h3 className="font-bold text-white text-sm flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-emerald-400" />
                  Segregation of Duties (SoD) Active Status
                </h3>
                <div className="space-y-2 text-xs">
                  <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">SOD-01: Supplier Creator ≠ PO Creator</span>
                    <span className="text-[10px] font-bold text-emerald-400 px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-800">ENFORCED</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">SOD-02: Bank Changer ≠ Invoice Poster</span>
                    <span className="text-[10px] font-bold text-emerald-400 px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-800">ENFORCED</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">SOD-03: PO Creator ≠ GR / SES Receiver</span>
                    <span className="text-[10px] font-bold text-emerald-400 px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-800">ENFORCED</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">SOD-04: PO Creator ≠ Invoice Resolver</span>
                    <span className="text-[10px] font-bold text-emerald-400 px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-800">ENFORCED</span>
                  </div>
                </div>
              </div>

              <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
                <h3 className="font-bold text-white text-sm flex items-center gap-2">
                  <Zap className="w-4 h-4 text-cyan-400" />
                  Direct Action Shortcuts
                </h3>
                <div className="space-y-2 text-xs">
                  <button 
                    onClick={() => setActiveTab('requisitions')}
                    className="w-full text-left p-3 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-cyan-500/40 text-slate-200 transition-colors flex items-center justify-between"
                  >
                    <span>Guided Buying Requisition Form (M04)</span>
                    <ArrowRight className="w-3.5 h-3.5 text-slate-500" />
                  </button>
                  <button 
                    onClick={() => setActiveTab('orders')}
                    className="w-full text-left p-3 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-cyan-500/40 text-slate-200 transition-colors flex items-center justify-between"
                  >
                    <span>PO Validation & Touchless Risk Score (M08)</span>
                    <ArrowRight className="w-3.5 h-3.5 text-slate-500" />
                  </button>
                  <button 
                    onClick={() => setActiveTab('invoices')}
                    className="w-full text-left p-3 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-amber-500/40 text-slate-200 transition-colors flex items-center justify-between"
                  >
                    <span>3-Way Match & Exception Resolver (M10)</span>
                    <ArrowRight className="w-3.5 h-3.5 text-slate-500" />
                  </button>
                  <button 
                    onClick={() => setActiveTab('lineage')}
                    className="w-full text-left p-3 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-purple-500/40 text-slate-200 transition-colors flex items-center justify-between"
                  >
                    <span>Traverse Lineage Model (P10)</span>
                    <ArrowRight className="w-3.5 h-3.5 text-slate-500" />
                  </button>
                </div>
              </div>

            </div>

          </div>
        )}

        {/* TAB 2: Guided Buying & Requisitions (M04) */}
        {activeTab === 'requisitions' && (
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <FileText className="w-5 h-5 text-cyan-400" />
                  Guided Buying & Requisitions (REQ-01..04)
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Principle P03 Enforced Order: <strong>Contract Item $\to$ Internal Catalogue $\to$ Material Master $\to$ Free-Text</strong>.
                </p>
              </div>

              {/* Search Bar */}
              <div className="flex items-center gap-2">
                <div className="relative w-64">
                  <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input 
                    type="text" 
                    placeholder="Search 'DC-330' or 'M8 Bolt'..."
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      handleSearch(e.target.value);
                    }}
                    className="w-full pl-8 pr-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                  />
                </div>
              </div>
            </div>

            {/* Guided Search Results Display */}
            {searchResults && (
              <div className="space-y-4">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider block">
                  Channel Hierarchy Matching Results
                </span>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  
                  {/* Priority 1: Contract Item */}
                  <div className="p-4 rounded-xl bg-cyan-950/20 border border-cyan-800/60 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 uppercase">
                        Priority 1: Contract
                      </span>
                      <span className="text-xs font-bold text-emerald-400">Preferred</span>
                    </div>
                    {searchResults.contract_items.length > 0 ? (
                      searchResults.contract_items.map((it: any, idx: number) => (
                        <div key={idx} className="space-y-1 text-xs pt-1">
                          <div className="font-bold text-white">{it.name}</div>
                          <div className="text-slate-400 text-[11px]">Contract: <strong className="text-cyan-300 font-mono">{it.contract_ref}</strong></div>
                          <div className="text-slate-400 text-[11px]">Supplier: {it.supplier_name}</div>
                          <div className="text-sm font-bold text-cyan-300 mt-2">₹{it.unit_price_inr.toFixed(2)} / {it.uom}</div>
                        </div>
                      ))
                    ) : (
                      <div className="text-slate-500 text-xs py-4">No active contract item found.</div>
                    )}
                  </div>

                  {/* Priority 2: Catalogue Item */}
                  <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 uppercase">
                      Priority 2: Catalogue
                    </span>
                    {searchResults.catalogue_items.length > 0 ? (
                      searchResults.catalogue_items.map((it: any, idx: number) => (
                        <div key={idx} className="space-y-1 text-xs pt-1">
                          <div className="font-bold text-white">{it.name}</div>
                          <div className="text-slate-400 text-[11px]">SKU: {it.sku}</div>
                          <div className="text-sm font-bold text-slate-200 mt-2">₹{it.unit_price_inr.toFixed(2)} / {it.uom}</div>
                        </div>
                      ))
                    ) : (
                      <div className="text-slate-500 text-xs py-4">No catalogue match found.</div>
                    )}
                  </div>

                  {/* Priority 3 & 4: Material Master / Free-Text */}
                  <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 uppercase">
                      Priority 3/4: Material / Free-Text
                    </span>
                    <p className="text-xs text-slate-400 leading-relaxed pt-1">
                      Free-text items allowed for one-off buys with material group. Reusable items automatically spawn parallel MDM steward request (P05).
                    </p>
                    <button className="mt-2 text-xs font-semibold text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
                      <span>Create Free-Text Line</span> <ArrowRight className="w-3 h-3" />
                    </button>
                  </div>

                </div>
              </div>
            )}

            {/* Requisitions List Table */}
            <div className="space-y-3 pt-4 border-t border-slate-800">
              <span className="text-xs font-bold text-slate-400 uppercase tracking-wider block">
                Active Requisitions in Tenant Axion Mobility
              </span>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 text-[11px] font-bold text-slate-400 uppercase bg-slate-900/40">
                      <th className="py-3 px-4">PR Number</th>
                      <th className="py-3 px-4">Origin & Purpose</th>
                      <th className="py-3 px-4">Requester</th>
                      <th className="py-3 px-4">Plant & Location</th>
                      <th className="py-3 px-4">Status</th>
                      <th className="py-3 px-4">DMN-01 Approval Route</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {requisitions.map((req) => (
                      <tr key={req.id} className="hover:bg-slate-900/60 transition-colors">
                        <td className="py-3 px-4 font-bold text-white font-mono">{req.id}</td>
                        <td className="py-3 px-4">
                          <span className="font-semibold text-cyan-300">{req.origin}</span>
                          <span className="text-slate-500 text-[11px] block">{req.purpose_code}</span>
                        </td>
                        <td className="py-3 px-4 text-slate-300">{req.requester}</td>
                        <td className="py-3 px-4 text-slate-400">{req.plant}</td>
                        <td className="py-3 px-4">
                          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                            {req.status}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-[11px] text-slate-400">
                          {req.approvals?.map((a: any) => a.role).join(' → ')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        )}

        {/* TAB 3: Purchase Orders & Touchless (M08) */}
        {activeTab === 'orders' && (
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <ShoppingCart className="w-5 h-5 text-cyan-400" />
                  Purchase Orders & DMN-02 Touchless Evaluation (PO-01..04)
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Evaluates the additive explainable PO Risk Score formula and auto-releases low-risk contract orders.
                </p>
              </div>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800 font-mono">
                L4 Touchless PO Policy
              </span>
            </div>

            {/* PO-77410 Deep Dive Card */}
            <div className="p-5 rounded-xl bg-[#070B14]/90 border border-slate-800 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-lg font-mono font-bold text-white">PO-77410</span>
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                    RELEASED · TOUCHLESS
                  </span>
                  <span className="text-xs text-slate-400">Version: 1</span>
                </div>
                <div className="text-sm font-bold text-cyan-300">
                  Total Value: ₹2,149,200.00 INR
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs bg-slate-900/60 p-3 rounded-lg border border-slate-800">
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase font-bold">Supplier</span>
                  <span className="text-slate-200 font-medium">Trichy Forge Works (TF001)</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase font-bold">Contract Reference</span>
                  <span className="text-cyan-300 font-mono">SA-5520 (Scheduling Agt)</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase font-bold">Payment & Incoterms</span>
                  <span className="text-slate-200">N60 · FCA Trichy</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase font-bold">PO Risk Score</span>
                  <span className="text-emerald-400 font-bold font-mono">18 / 100 (Low Risk)</span>
                </div>
              </div>

              {/* DMN-02 Touchless Criteria Checklist */}
              <div className="space-y-2 pt-2">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider block">
                  DMN-02 Touchless Policy Verification Checklist
                </span>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                  <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-800/40 flex items-center gap-2 text-emerald-300">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>Price source is active contract SA-5520 (₹398.00)</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-800/40 flex items-center gap-2 text-emerald-300">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>Supplier status is Qualified for automotive die casting</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-800/40 flex items-center gap-2 text-emerald-300">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>Total value (₹21.49 L) within plant single-release band</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-800/40 flex items-center gap-2 text-emerald-300">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>AI late delivery risk probability = 0.22 (&lt; 0.30 threshold)</span>
                  </div>
                </div>
              </div>
            </div>

          </div>
        )}

        {/* TAB 4: Goods Receipt & Quality Hold (M09) */}
        {activeTab === 'receiving' && (
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Truck className="w-5 h-5 text-cyan-400" />
                  Fulfilment, Goods Receipt & Quality Results (RCV-01..04)
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Captures actual arrivals against ASN, executes ultrasonic quality inspection, and blocks over-delivery.
                </p>
              </div>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-amber-950 text-amber-300 border border-amber-800 font-mono">
                Quality Inspection Active
              </span>
            </div>

            {/* GR-90231 Inspection Card */}
            <div className="p-5 rounded-xl bg-[#070B14]/90 border border-slate-800 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-lg font-mono font-bold text-white">GR-90231</span>
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-950 text-amber-300 border border-amber-800">
                    ACCEPTED WITH REJECTIONS
                  </span>
                  <span className="text-xs text-slate-400">PO: <strong>PO-77410</strong></span>
                </div>
                <div className="text-xs font-mono text-slate-400">
                  Inspection Doc: <strong className="text-cyan-300">QL-2210</strong>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4 text-center">
                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
                  <span className="text-slate-400 text-xs block">Total Arrived</span>
                  <span className="text-2xl font-black text-white">5,400</span>
                  <span className="text-[10px] text-slate-500 block mt-1">Units from ASN-61208</span>
                </div>
                <div className="p-4 rounded-xl bg-emerald-950/30 border border-emerald-800/60">
                  <span className="text-emerald-300 text-xs block">Accepted to Stock</span>
                  <span className="text-2xl font-black text-emerald-400">5,380</span>
                  <span className="text-[10px] text-emerald-500 block mt-1">Passed CMM Metrology</span>
                </div>
                <div className="p-4 rounded-xl bg-rose-950/30 border border-rose-800/60">
                  <span className="text-rose-300 text-xs block">Rejected (Quarantined)</span>
                  <span className="text-2xl font-black text-rose-400">20</span>
                  <span className="text-[10px] text-rose-500 block mt-1">Gas Porosity Non-Conformance</span>
                </div>
              </div>

              <div className="p-3.5 rounded-lg bg-rose-950/20 border border-rose-800/40 text-xs flex items-center justify-between text-rose-300">
                <span><strong>Defect Note:</strong> 20 castings exhibited internal gas porosity exceeding ASTM E505 Category B. Return delivery and credit note required.</span>
                <span className="font-semibold px-2 py-0.5 rounded bg-rose-950 border border-rose-800 text-[10px]">FEED SCORECARD</span>
              </div>
            </div>

          </div>
        )}

        {/* TAB 5: 3-Way Match & Invoicing (M10) */}
        {activeTab === 'invoices' && (
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <DollarSign className="w-5 h-5 text-amber-400" />
                  3-Way Match & Exception Resolver (INV-01..04)
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Compares PO $\times$ Accepted Goods Receipt $\times$ Supplier Invoice using DMN-03 tolerances.
                </p>
              </div>

              {invoices.length > 0 && invoices[0].status === 'EXCEPTION' ? (
                <button 
                  onClick={() => setShowCreditNoteModal(true)}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-amber-600 hover:bg-amber-500 text-white shadow-lg shadow-amber-900/40 flex items-center gap-2 transition-all"
                >
                  <Plus className="w-4 h-4" /> Resolve with Credit Note
                </button>
              ) : (
                <button 
                  onClick={handlePostToErp}
                  disabled={postingToErp || invoices[0]?.status === 'POSTED'}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-900/40 flex items-center gap-2 transition-all"
                >
                  <Send className="w-4 h-4" /> {postingToErp ? 'Posting...' : (invoices[0]?.status === 'POSTED' ? 'Posted in SAP' : 'Post to SAP S/4HANA')}
                </button>
              )}
            </div>

            {/* Side-by-Side 3-Way Reconciliation Card */}
            <div className="p-5 rounded-xl bg-[#070B14]/90 border border-slate-800 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-lg font-mono font-bold text-white">INV-TF-8812</span>
                  <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold border ${
                    invoices[0]?.status === 'POSTED' ? 'bg-emerald-950 text-emerald-300 border-emerald-800' :
                    invoices[0]?.status === 'MATCHED' ? 'bg-blue-950 text-blue-300 border-blue-800' : 'bg-amber-950 text-amber-300 border-amber-800'
                  }`}>
                    {invoices[0]?.status}
                  </span>
                </div>
                <div className="text-xs font-mono text-slate-400">
                  GST IRN: <strong className="text-white">9a38f72c10b83e47a988d01124f</strong>
                </div>
              </div>

              {/* Side-by-Side Grid */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                
                {/* 1. Purchase Order */}
                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2 text-xs">
                  <div className="flex justify-between text-slate-400 font-bold">
                    <span>1. PURCHASE ORDER</span>
                    <span className="font-mono text-cyan-300">PO-77410</span>
                  </div>
                  <div className="text-xl font-bold text-white">5,400 EA</div>
                  <div className="text-slate-400">Price: ₹398.00 / EA</div>
                  <div className="text-slate-400">Total: ₹21,49,200.00</div>
                </div>

                {/* 2. Goods Receipt */}
                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2 text-xs">
                  <div className="flex justify-between text-slate-400 font-bold">
                    <span>2. ACCEPTED GR</span>
                    <span className="font-mono text-cyan-300">GR-90231</span>
                  </div>
                  <div className="text-xl font-bold text-emerald-400">5,380 EA</div>
                  <div className="text-slate-400">20 Rejected (Porosity)</div>
                  <div className="text-slate-400">Accepted Value: ₹21,41,240.00</div>
                </div>

                {/* 3. Supplier Invoice */}
                <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2 text-xs">
                  <div className="flex justify-between text-slate-400 font-bold">
                    <span>3. INVOICE BILLED</span>
                    <span className="font-mono text-amber-300">INV-TF-8812</span>
                  </div>
                  <div className="text-xl font-bold text-amber-400">5,400 EA</div>
                  <div className="text-rose-400 font-semibold">+20 Quantity Variance</div>
                  <div className="text-slate-400">Billed: ₹21,49,200 + GST</div>
                </div>

              </div>

              {/* Resolution Banner */}
              {invoices[0]?.credit_note_ref && (
                <div className="p-3.5 rounded-lg bg-emerald-950/30 border border-emerald-800/60 text-xs flex items-center justify-between text-emerald-300">
                  <span>
                    <strong>Resolved with Credit Note:</strong> {invoices[0].credit_note_ref} received for 20 units (₹7,960.00). Invoice is balanced and ready for SAP posting.
                  </span>
                  <span className="font-mono font-bold text-emerald-400">NET ZERO VARIANCE</span>
                </div>
              )}

              {/* ERP Document Result Banner */}
              {erpDocResult && (
                <div className="p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/60 text-xs space-y-2 text-emerald-200">
                  <div className="flex items-center justify-between">
                    <span className="font-bold flex items-center gap-1.5">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      SAP S/4HANA Exactly-Once Accounting Document
                    </span>
                    <span className="font-mono font-bold text-emerald-300">Doc #{erpDocResult.erpDocument}</span>
                  </div>
                  <div className="text-[11px] text-slate-300">
                    Idempotency Key: <code>AXN|1000|TF001|INV-TF-8812</code> • Replayed Flag: <strong>{String(erpDocResult.replayed)}</strong>
                  </div>
                </div>
              )}

            </div>

          </div>
        )}

        {/* TAB 6: End-to-End Lineage Explorer (P10) */}
        {activeTab === 'lineage' && (
          <div className="bg-[#0B1528]/80 backdrop-blur-md border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Layers className="w-5 h-5 text-purple-400" />
                  Immutable Lineage Traversal Model (Principle P10)
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Complete graph traversal through the <code>document_link</code> table connecting all upstream and downstream artifacts.
                </p>
              </div>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-purple-950 text-purple-300 border border-purple-800 font-mono">
                {lineage?.total_links || 10} Explicit Typed Links
              </span>
            </div>

            {/* Visual Node Graph */}
            <div className="p-6 rounded-xl bg-[#070B14]/90 border border-slate-800 space-y-6">
              <span className="text-xs font-bold text-slate-400 uppercase tracking-wider block">
                Ancestry & Descendant Document Trail
              </span>

              <div className="flex flex-wrap items-center gap-3 text-xs">
                {lineage?.lineage_sequence.map((node, idx) => (
                  <React.Fragment key={idx}>
                    <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-700/80 hover:border-cyan-500/40 transition-colors shadow-md flex flex-col items-center min-w-[120px]">
                      <span className="text-[10px] text-slate-500 uppercase font-bold">Step {idx + 1}</span>
                      <span className="font-mono text-cyan-300 font-bold mt-0.5">{node}</span>
                    </div>
                    {idx < lineage.lineage_sequence.length - 1 && (
                      <ArrowRight className="w-4 h-4 text-cyan-500/60 shrink-0" />
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>

          </div>
        )}

      </div>

      {/* Credit Note Modal */}
      {showCreditNoteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-[#0B1528] border border-slate-700 rounded-2xl w-full max-w-md p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <FileCheck className="w-4 h-4 text-amber-400" /> Attach Credit Note for Rejection
              </h3>
              <button onClick={() => setShowCreditNoteModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <p className="text-slate-300">
                Trichy Forge Works issued a credit note for the 20 rejected aluminium die-cast housings (QL-2210).
              </p>
              
              <div className="space-y-1">
                <label className="text-slate-400 font-semibold">Credit Note Number</label>
                <input 
                  type="text" 
                  value={creditNoteNumber}
                  onChange={(e) => setCreditNoteNumber(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-semibold">Credit Amount (INR)</label>
                <input 
                  type="number" 
                  value={creditNoteAmount}
                  onChange={(e) => setCreditNoteAmount(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
              <button 
                onClick={() => setShowCreditNoteModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 text-xs font-semibold"
              >
                Cancel
              </button>
              <button 
                onClick={handleResolveException}
                disabled={resolvingException}
                className="px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-amber-900/40"
              >
                {resolvingException ? 'Resolving...' : 'Confirm Credit Note'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
