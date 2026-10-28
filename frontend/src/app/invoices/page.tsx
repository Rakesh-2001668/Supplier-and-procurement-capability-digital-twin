'use client';

import React, { useState, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import {
  FileText,
  CheckCircle2,
  AlertCircle,
  Clock,
  Download,
  Upload,
  Filter,
  Search,
  ShieldCheck,
  CreditCard,
  Printer,
  RefreshCw,
  ExternalLink,
  ChevronRight,
  X,
  Building2,
  Sparkles,
  ArrowRight,
  DollarSign,
  AlertTriangle,
  Receipt,
  Layers,
  Check,
  History
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

export default function InvoicesPage() {
  const queryClient = useQueryClient();

  // Navigation & View Filters
  const [activeTab, setActiveTab] = useState<string>('All Invoices');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [filterMatchStatus, setFilterMatchStatus] = useState<string>('ALL');
  const [filterSupplier, setFilterSupplier] = useState<string>('ALL');
  const [showFilterDropdown, setShowFilterDropdown] = useState<boolean>(false);

  // Selection
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());

  // Detail Pane Tabs
  const [detailTab, setDetailTab] = useState<'Overview' | '3-Way Match' | 'Line Items' | 'Audit Trail'>('Overview');

  // Modals
  const [showPaymentModal, setShowPaymentModal] = useState<boolean>(false);
  const [showDisputeModal, setShowDisputeModal] = useState<boolean>(false);
  const [showImportModal, setShowImportModal] = useState<boolean>(false);
  const [showVoucherModal, setShowVoucherModal] = useState<boolean>(false);

  // Modal Forms
  const [paymentMethod, setPaymentMethod] = useState<string>('ACH Direct Deposit');
  const [paymentNotes, setPaymentNotes] = useState<string>('Approved via Accounts Payable Workflow');
  const [disputeReason, setDisputeReason] = useState<string>('Price Discrepancy');
  const [disputeNotes, setDisputeNotes] = useState<string>('Unit price on invoice differs from purchase order quotation rate.');

  // Interactive Loading & Notifications
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string>('');

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(''), 4500);
  };

  // Fetch Invoices
  const { data: invoices = [], isLoading, isRefetching, refetch } = useQuery({
    queryKey: ['buyer-invoices'],
    queryFn: async () => {
      const tenant = typeof window !== 'undefined' ? (localStorage.getItem('tenant_id') || 'TENANT_BUYER_001') : 'TENANT_BUYER_001';
      const response = await apiClient.get(`/api/v1/finance/invoices?buyer_tenant_id=${tenant}`);
      return response.data;
    }
  });

  // KPI Calculations
  const kpis = useMemo(() => {
    const total = invoices.length;
    let totalAmt = 0;
    let paidCount = 0;
    let paidAmt = 0;
    let pendingCount = 0;
    let pendingAmt = 0;
    let overdueCount = 0;
    let disputedCount = 0;
    let matchedCount = 0;

    const now = new Date();

    invoices.forEach((inv: any) => {
      const amt = inv.amount || 0;
      totalAmt += amt;

      const st = (inv.status || 'PENDING').toUpperCase();
      const match = (inv.match_status || 'PENDING').toUpperCase();

      if (match === 'MATCHED') matchedCount++;

      if (st === 'PAID') {
        paidCount++;
        paidAmt += amt;
      } else if (st === 'DISPUTED') {
        disputedCount++;
        pendingAmt += amt;
      } else if (st === 'PENDING') {
        pendingCount++;
        pendingAmt += amt;
        if (inv.due_date && new Date(inv.due_date) < now) {
          overdueCount++;
        }
      } else if (st === 'OVERDUE') {
        overdueCount++;
        pendingAmt += amt;
      }
    });

    return { total, totalAmt, paidCount, paidAmt, pendingCount, pendingAmt, overdueCount, disputedCount, matchedCount };
  }, [invoices]);

  // Suppliers List for Filter Dropdown
  const suppliersList = useMemo(() => {
    const sups = new Set<string>();
    invoices.forEach((inv: any) => {
      const name = inv.tenant_id === 'TENANT_SUPPLIER_001' ? 'Apex Tooling Inc.' : (inv.tenant_id || 'Apex Tooling Inc.');
      sups.add(name);
    });
    return Array.from(sups);
  }, [invoices]);

  // Filtered Invoices
  const filteredInvoices = useMemo(() => {
    return invoices.filter((inv: any) => {
      const st = (inv.status || 'PENDING').toUpperCase();
      const matchSt = (inv.match_status || 'PENDING').toUpperCase();
      const supName = inv.tenant_id === 'TENANT_SUPPLIER_001' ? 'Apex Tooling Inc.' : (inv.tenant_id || 'Apex Tooling Inc.');

      // Tab Filter
      if (activeTab === 'Pending Review' && st !== 'PENDING') return false;
      if (activeTab === '3-Way Matched' && matchSt !== 'MATCHED') return false;
      if (activeTab === 'Disputed' && st !== 'DISPUTED' && matchSt !== 'DISCREPANCY') return false;
      if (activeTab === 'Paid' && st !== 'PAID') return false;
      if (activeTab === 'Overdue') {
        const isPastDue = inv.due_date && new Date(inv.due_date) < new Date();
        if (!(st === 'OVERDUE' || (st === 'PENDING' && isPastDue))) return false;
      }

      // Dropdown Match Status
      if (filterMatchStatus !== 'ALL' && matchSt !== filterMatchStatus) return false;

      // Dropdown Supplier
      if (filterSupplier !== 'ALL' && supName !== filterSupplier) return false;

      // Search Query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesId = (inv.id || '').toLowerCase().includes(q);
        const matchesPo = (inv.po_id || '').toLowerCase().includes(q);
        const matchesSup = supName.toLowerCase().includes(q);
        const matchesDesc = (inv.description || '').toLowerCase().includes(q);
        if (!matchesId && !matchesPo && !matchesSup && !matchesDesc) return false;
      }

      return true;
    });
  }, [invoices, activeTab, filterMatchStatus, filterSupplier, searchQuery]);

  // Selected Invoice
  const selectedInvoice = useMemo(() => {
    if (!selectedInvoiceId) return filteredInvoices[0] || invoices[0] || null;
    return invoices.find((inv: any) => inv.id === selectedInvoiceId) || filteredInvoices[0] || invoices[0] || null;
  }, [invoices, filteredInvoices, selectedInvoiceId]);

  // Row Selection Handlers
  const handleSelectAll = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.checked) {
      setSelectedRows(new Set(filteredInvoices.map((i: any) => i.id)));
    } else {
      setSelectedRows(new Set());
    }
  };

  const handleToggleRow = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedRows(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Actions
  const handleRunMatch = async (invoiceId: string) => {
    setActionLoading(true);
    try {
      const res = await fetch(`http://localhost:8080/api/v1/finance/invoices/${invoiceId}/match`, {
        method: 'POST'
      });
      const data = await res.json();
      if (res.ok) {
        await queryClient.invalidateQueries({ queryKey: ['buyer-invoices'] });
        if (data.status === 'MATCHED') {
          showToast(`3-Way Match Verified! PO #${data.details?.po_id || 'PO'} & Goods Receipt reconciled.`);
        } else {
          showToast(`3-Way Match Alert: Discrepancy detected (${data.reason || 'Variance found'})`);
        }
      } else {
        alert(data.detail || 'Failed to run 3-way match.');
      }
    } catch (err) {
      console.error(err);
      alert('Error connecting to finance match API.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleConfirmPayment = async () => {
    if (!selectedInvoice) return;
    setActionLoading(true);
    try {
      const res = await fetch(`http://localhost:8080/api/v1/finance/invoices/${selectedInvoice.id}/pay`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          payment_method: paymentMethod,
          notes: paymentNotes
        })
      });
      const data = await res.json();
      if (res.ok) {
        setShowPaymentModal(false);
        await queryClient.invalidateQueries({ queryKey: ['buyer-invoices'] });
        showToast(`Payment of $${Number(selectedInvoice.amount).toLocaleString()} Authorized & Settled via ${paymentMethod}!`);
      } else {
        alert(data.detail || 'Failed to process payment.');
      }
    } catch (err) {
      console.error(err);
      alert('Error communicating with payment gateway.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleConfirmDispute = async () => {
    if (!selectedInvoice) return;
    setActionLoading(true);
    try {
      const res = await fetch(`http://localhost:8080/api/v1/finance/invoices/${selectedInvoice.id}/dispute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: disputeReason,
          notes: disputeNotes
        })
      });
      const data = await res.json();
      if (res.ok) {
        setShowDisputeModal(false);
        await queryClient.invalidateQueries({ queryKey: ['buyer-invoices'] });
        showToast(`Dispute logged: ${disputeReason}. Supplier notified.`);
      } else {
        alert(data.detail || 'Failed to log dispute.');
      }
    } catch (err) {
      console.error(err);
      alert('Error communicating with backend.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleBatchMatch = async () => {
    if (selectedRows.size === 0) return;
    setActionLoading(true);
    try {
      for (const id of Array.from(selectedRows)) {
        await fetch(`http://localhost:8080/api/v1/finance/invoices/${id}/match`, { method: 'POST' });
      }
      await queryClient.invalidateQueries({ queryKey: ['buyer-invoices'] });
      showToast(`Batch 3-Way Match executed for ${selectedRows.size} invoices.`);
      setSelectedRows(new Set());
    } finally {
      setActionLoading(false);
    }
  };

  const handleBatchPay = async () => {
    if (selectedRows.size === 0) return;
    setActionLoading(true);
    try {
      for (const id of Array.from(selectedRows)) {
        await fetch(`http://localhost:8080/api/v1/finance/invoices/${id}/pay`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ payment_method: 'ACH Direct Deposit', notes: 'Batch Authorized' })
        });
      }
      await queryClient.invalidateQueries({ queryKey: ['buyer-invoices'] });
      showToast(`Batch Payment authorized for ${selectedRows.size} invoices.`);
      setSelectedRows(new Set());
    } finally {
      setActionLoading(false);
    }
  };

  const handleImportSample = async () => {
    setActionLoading(true);
    try {
      const samplePO = `PO-2025-${Math.floor(10000 + Math.random() * 90000)}`;
      const sampleAmt = Math.floor(12000 + Math.random() * 45000);
      const res = await fetch('http://localhost:8080/api/v1/finance/invoices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          po_id: samplePO,
          taxable_amount: sampleAmt * 0.82,
          tax_percent: 18.0,
          total_amount: sampleAmt,
          terms: 'Net 30 Days',
          supplier_tenant_id: 'TENANT_SUPPLIER_001',
          buyer_tenant_id: 'TENANT_BUYER_001',
          description: 'Precision Fabricated Industrial Enclosures & Machined Hardware'
        })
      });
      if (res.ok) {
        setShowImportModal(false);
        await queryClient.invalidateQueries({ queryKey: ['buyer-invoices'] });
        showToast(`Imported external electronic invoice for ${samplePO}!`);
      }
    } finally {
      setActionLoading(false);
    }
  };

  // Export CSV
  const handleExportCSV = () => {
    const headers = ['Invoice ID', 'Supplier', 'PO Number', 'Amount', 'Status', 'Match Status', 'Due Date'];
    const rows = filteredInvoices.map((inv: any) => [
      inv.id,
      inv.tenant_id === 'TENANT_SUPPLIER_001' ? 'Apex Tooling Inc.' : (inv.tenant_id || 'Apex Tooling Inc.'),
      inv.po_id || '',
      inv.amount || 0,
      inv.status || 'PENDING',
      inv.match_status || 'PENDING',
      inv.due_date ? new Date(inv.due_date).toLocaleDateString() : ''
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map((e: any[]) => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `Buyer_Invoices_Report_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Invoice report exported to CSV.');
  };

  // Helper Formatters
  const formatAmt = (amt: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amt || 0);
  const formatDate = (dateStr: string) => dateStr ? new Date(dateStr).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) : 'N/A';

  const getStatusBadge = (st: string) => {
    const status = (st || 'PENDING').toUpperCase();
    if (status === 'PAID') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> PAID
        </span>
      );
    }
    if (status === 'DISPUTED') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-purple-50 text-purple-700 border border-purple-200">
          <span className="w-1.5 h-1.5 rounded-full bg-purple-500"></span> DISPUTED
        </span>
      );
    }
    if (status === 'OVERDUE') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-rose-50 text-rose-700 border border-rose-200">
          <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span> OVERDUE
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-amber-50 text-amber-700 border border-amber-200">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> PENDING
      </span>
    );
  };

  const getMatchBadge = (match: string) => {
    const m = (match || 'PENDING').toUpperCase();
    if (m === 'MATCHED') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-extrabold bg-blue-50 text-blue-700 border border-blue-200">
          <CheckCircle2 className="w-3 h-3 text-blue-600" /> 3-WAY MATCHED
        </span>
      );
    }
    if (m === 'DISCREPANCY') {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-extrabold bg-red-50 text-red-700 border border-red-200">
          <AlertCircle className="w-3 h-3 text-red-600" /> DISCREPANCY
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-extrabold bg-slate-50 text-slate-600 border border-slate-200">
        <Clock className="w-3 h-3 text-slate-400" /> UNVERIFIED
      </span>
    );
  };

  return (
    <div className="p-6 max-w-[1680px] mx-auto space-y-6 animate-fade-in font-sans">

      {/* Floating Toast Alert */}
      {toastMessage && (
        <div className="fixed top-5 right-5 z-50 bg-[#0B2550] text-white px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-bounce">
          <Sparkles className="w-5 h-5 text-amber-400 shrink-0" />
          <span className="text-sm font-semibold">{toastMessage}</span>
        </div>
      )}

      {/* Header & Sub-Nav */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <div>
          <div className="text-[11px] font-extrabold text-blue-600 uppercase tracking-widest mb-1.5 flex items-center gap-2">
            <Link href="/buyer/dashboard" className="hover:underline flex items-center gap-1">
              <Building2 className="w-3.5 h-3.5" /> Buyer Portal
            </Link>
            <ChevronRight className="w-3 h-3 text-slate-400" />
            <span className="text-slate-500 font-bold">Accounts Payable</span>
            <ChevronRight className="w-3 h-3 text-slate-400" />
            <span className="text-[#0B2550] font-black">Invoices</span>
          </div>
          <h1 className="text-2xl md:text-3xl font-black text-[#0B2550] tracking-tight">Buyer Invoice Management & AP Automation</h1>
          <p className="text-sm text-slate-500 font-medium mt-1">
            Review incoming supplier invoices, run automated 3-way matching with POs and Goods Receipts, resolve discrepancies, and authorize payments.
          </p>
        </div>

        {/* Global Toolbar Buttons */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={() => refetch()}
            className="p-2.5 rounded-xl border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-blue-600 transition-colors shadow-sm"
            title="Refresh Invoices"
          >
            <RefreshCw className={`w-4 h-4 ${isRefetching ? 'animate-spin text-blue-600' : ''}`} />
          </button>

          <button
            onClick={handleExportCSV}
            className="px-4 py-2.5 rounded-xl border border-slate-200 bg-white text-slate-700 font-bold text-xs hover:bg-slate-50 transition-colors shadow-sm flex items-center gap-2"
          >
            <Download className="w-4 h-4 text-slate-500" /> Export CSV
          </button>

          <button
            onClick={() => setShowImportModal(true)}
            className="px-5 py-2.5 rounded-xl bg-blue-600 text-white font-bold text-xs hover:bg-blue-700 transition-all shadow-md shadow-blue-500/20 flex items-center gap-2"
          >
            <Upload className="w-4 h-4" /> Import Invoices
          </button>
        </div>
      </div>

      {/* KPI Cards Row (Interactive Filters) */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {/* Total Invoices */}
        <div
          onClick={() => setActiveTab('All Invoices')}
          className={`bg-white rounded-2xl border p-5 shadow-sm cursor-pointer transition-all hover:scale-[1.02] flex flex-col justify-between ${activeTab === 'All Invoices' ? 'ring-2 ring-blue-500 border-blue-500 shadow-blue-500/10' : 'border-slate-200'}`}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Total Invoices</span>
            <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
              <FileText className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-3xl font-black text-[#0B2550]">{kpis.total}</div>
            <div className="text-xs font-semibold text-slate-500 mt-1">{formatAmt(kpis.totalAmt)} total volume</div>
          </div>
        </div>

        {/* 3-Way Matched */}
        <div
          onClick={() => setActiveTab('3-Way Matched')}
          className={`bg-white rounded-2xl border p-5 shadow-sm cursor-pointer transition-all hover:scale-[1.02] flex flex-col justify-between ${activeTab === '3-Way Matched' ? 'ring-2 ring-blue-500 border-blue-500 shadow-blue-500/10' : 'border-slate-200'}`}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">3-Way Matched</span>
            <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
              <ShieldCheck className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-3xl font-black text-blue-600">{kpis.matchedCount}</div>
            <div className="text-xs font-semibold text-slate-500 mt-1">Reconciled with PO & GR</div>
          </div>
        </div>

        {/* Pending Review */}
        <div
          onClick={() => setActiveTab('Pending Review')}
          className={`bg-white rounded-2xl border p-5 shadow-sm cursor-pointer transition-all hover:scale-[1.02] flex flex-col justify-between ${activeTab === 'Pending Review' ? 'ring-2 ring-amber-500 border-amber-500 shadow-amber-500/10' : 'border-slate-200'}`}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Pending Review</span>
            <div className="w-9 h-9 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center font-bold">
              <Clock className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-3xl font-black text-amber-600">{kpis.pendingCount}</div>
            <div className="text-xs font-semibold text-slate-500 mt-1">{formatAmt(kpis.pendingAmt)} awaiting approval</div>
          </div>
        </div>

        {/* Paid & Settled */}
        <div
          onClick={() => setActiveTab('Paid')}
          className={`bg-white rounded-2xl border p-5 shadow-sm cursor-pointer transition-all hover:scale-[1.02] flex flex-col justify-between ${activeTab === 'Paid' ? 'ring-2 ring-emerald-500 border-emerald-500 shadow-emerald-500/10' : 'border-slate-200'}`}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Paid & Settled</span>
            <div className="w-9 h-9 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-bold">
              <CheckCircle2 className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-3xl font-black text-emerald-600">{kpis.paidCount}</div>
            <div className="text-xs font-semibold text-slate-500 mt-1">{formatAmt(kpis.paidAmt)} settled</div>
          </div>
        </div>

        {/* Disputed / Overdue */}
        <div
          onClick={() => setActiveTab('Disputed')}
          className={`bg-white rounded-2xl border p-5 shadow-sm cursor-pointer transition-all hover:scale-[1.02] flex flex-col justify-between ${activeTab === 'Disputed' ? 'ring-2 ring-purple-500 border-purple-500 shadow-purple-500/10' : 'border-slate-200'}`}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Disputes / Flagged</span>
            <div className="w-9 h-9 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center font-bold">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-3xl font-black text-purple-600">{kpis.disputedCount + kpis.overdueCount}</div>
            <div className="text-xs font-semibold text-slate-500 mt-1">{kpis.disputedCount} disputed ? {kpis.overdueCount} overdue</div>
          </div>
        </div>
      </div>

      {/* Main Workspace Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">

        {/* Left Side: Interactive Table (7 Cols) */}
        <div className="lg:col-span-7 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col h-[760px]">

          {/* Table Header Tabs */}
          <div className="border-b border-slate-200 px-5 pt-4 flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-1 sm:gap-4 overflow-x-auto">
              {['All Invoices', 'Pending Review', '3-Way Matched', 'Disputed', 'Paid', 'Overdue'].map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`pb-3.5 px-2 text-xs font-extrabold border-b-2 transition-all whitespace-nowrap ${activeTab === tab ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-200'}`}
                >
                  {tab}
                </button>
              ))}
            </div>

            {/* Quick Count Badge */}
            <span className="text-xs font-bold text-slate-500 pb-3">
              Showing <span className="text-[#0B2550] font-black">{filteredInvoices.length}</span> records
            </span>
          </div>

          {/* Search Bar & Secondary Filters */}
          <div className="p-4 border-b border-slate-100 bg-slate-50/50 flex items-center justify-between gap-3 relative">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search by invoice ID, supplier name, PO number, or items..."
                className="w-full bg-white border border-slate-200 rounded-xl pl-9 pr-8 py-2 text-xs font-medium text-slate-700 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Filters Dropdown Toggle */}
            <div className="relative">
              <button
                onClick={() => setShowFilterDropdown(!showFilterDropdown)}
                className={`px-3.5 py-2 rounded-xl border text-xs font-bold flex items-center gap-2 transition-colors ${showFilterDropdown || filterMatchStatus !== 'ALL' || filterSupplier !== 'ALL' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'}`}
              >
                <Filter className="w-3.5 h-3.5" />
                <span>Filters</span>
                {(filterMatchStatus !== 'ALL' || filterSupplier !== 'ALL') && (
                  <span className="w-2 h-2 rounded-full bg-blue-600"></span>
                )}
              </button>

              {/* Filters Dropdown Menu */}
              {showFilterDropdown && (
                <div className="absolute right-0 top-11 z-30 w-72 bg-white rounded-2xl border border-slate-200 shadow-xl p-4 space-y-4 animate-scale-in">
                  <div className="flex items-center justify-between pb-2 border-b border-slate-100">
                    <span className="text-xs font-black text-[#0B2550] uppercase tracking-wider">Advanced Filters</span>
                    <button
                      onClick={() => {
                        setFilterMatchStatus('ALL');
                        setFilterSupplier('ALL');
                        setShowFilterDropdown(false);
                      }}
                      className="text-[11px] font-bold text-blue-600 hover:underline"
                    >
                      Reset All
                    </button>
                  </div>

                  <div>
                    <label className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1.5">3-Way Match Status</label>
                    <select
                      value={filterMatchStatus}
                      onChange={e => setFilterMatchStatus(e.target.value)}
                      className="w-full text-xs font-semibold p-2 border border-slate-200 rounded-lg outline-none bg-slate-50"
                    >
                      <option value="ALL">All Match States</option>
                      <option value="MATCHED">Matched</option>
                      <option value="DISCREPANCY">Discrepancy</option>
                      <option value="PENDING">Pending / Unverified</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1.5">Supplier Name</label>
                    <select
                      value={filterSupplier}
                      onChange={e => setFilterSupplier(e.target.value)}
                      className="w-full text-xs font-semibold p-2 border border-slate-200 rounded-lg outline-none bg-slate-50"
                    >
                      <option value="ALL">All Suppliers</option>
                      {suppliersList.map(s => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>

                  <button
                    onClick={() => setShowFilterDropdown(false)}
                    className="w-full bg-[#0B2550] text-white py-2 rounded-lg text-xs font-bold hover:bg-slate-800"
                  >
                    Apply Filters
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Bulk Action Bar (if items checked) */}
          {selectedRows.size > 0 && (
            <div className="bg-blue-50 border-b border-blue-200 px-5 py-2.5 flex items-center justify-between text-xs font-bold text-blue-900 animate-fade-in">
              <span className="flex items-center gap-2">
                <Check className="w-4 h-4 text-blue-600" />
                <span>{selectedRows.size} invoice(s) selected</span>
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleBatchMatch}
                  disabled={actionLoading}
                  className="bg-white border border-blue-200 text-blue-700 hover:bg-blue-100 px-3 py-1.5 rounded-lg shadow-sm font-extrabold flex items-center gap-1.5"
                >
                  <ShieldCheck className="w-3.5 h-3.5" /> Batch 3-Way Match
                </button>
                <button
                  onClick={handleBatchPay}
                  disabled={actionLoading}
                  className="bg-blue-600 text-white hover:bg-blue-700 px-3 py-1.5 rounded-lg shadow-sm font-extrabold flex items-center gap-1.5"
                >
                  <CreditCard className="w-3.5 h-3.5" /> Batch Pay
                </button>
                <button
                  onClick={() => setSelectedRows(new Set())}
                  className="text-slate-500 hover:text-slate-700 underline text-[11px] ml-2"
                >
                  Deselect All
                </button>
              </div>
            </div>
          )}

          {/* Table Container */}
          <div className="flex-1 overflow-auto">
            <table className="w-full text-left border-collapse min-w-[700px]">
              <thead className="sticky top-0 bg-white z-10 shadow-sm border-b border-slate-100">
                <tr className="bg-slate-50/70 text-[10px] font-black text-slate-400 uppercase tracking-wider">
                  <th className="py-3 px-4 w-10 text-center">
                    <input
                      type="checkbox"
                      checked={filteredInvoices.length > 0 && selectedRows.size === filteredInvoices.length}
                      onChange={handleSelectAll}
                      className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                  </th>
                  <th className="py-3 px-3">Invoice Details</th>
                  <th className="py-3 px-3">Supplier</th>
                  <th className="py-3 px-3">PO Reference</th>
                  <th className="py-3 px-3">Due Date</th>
                  <th className="py-3 px-3 text-right">Amount (USD)</th>
                  <th className="py-3 px-3 text-center">3-Way Match</th>
                  <th className="py-3 px-3 text-center">Payment Status</th>
                </tr>
              </thead>
              <tbody className="text-xs font-semibold text-slate-700 divide-y divide-slate-100">
                {isLoading ? (
                  <tr>
                    <td colSpan={8} className="p-16 text-center text-slate-500 font-medium">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-blue-600" />
                      Loading buyer accounts payable records...
                    </td>
                  </tr>
                ) : filteredInvoices.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="p-16 text-center text-slate-500 font-medium">
                      <FileText className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                      <p className="font-bold text-[#0B2550]">No matching invoices found</p>
                      <p className="text-xs text-slate-400 mt-1">Try adjusting your filters or importing new supplier invoices.</p>
                    </td>
                  </tr>
                ) : (
                  filteredInvoices.map((inv: any) => {
                    const isSelected = selectedInvoice?.id === inv.id;
                    const isChecked = selectedRows.has(inv.id);
                    const supName = inv.tenant_id === 'TENANT_SUPPLIER_001' ? 'Apex Tooling Inc.' : (inv.tenant_id || 'Apex Tooling Inc.');

                    return (
                      <tr
                        key={inv.id}
                        onClick={() => setSelectedInvoiceId(inv.id)}
                        className={`hover:bg-blue-50/40 cursor-pointer transition-colors ${isSelected ? 'bg-blue-50/70 border-l-4 border-l-blue-600' : ''}`}
                      >
                        <td className="py-3 px-4 text-center" onClick={e => handleToggleRow(inv.id, e)}>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {}}
                            className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                          />
                        </td>
                        <td className="py-3 px-3">
                          <div className="font-mono font-bold text-blue-600 hover:underline">{inv.id}</div>
                          <div className="text-[10px] text-slate-400 font-normal mt-0.5">{formatDate(inv.created_at)}</div>
                        </td>
                        <td className="py-3 px-3">
                          <div className="font-bold text-[#0B2550]">{supName}</div>
                          <div className="text-[10px] text-slate-400">Verified Tier-1</div>
                        </td>
                        <td className="py-3 px-3 font-mono text-slate-600">
                          {inv.po_id || 'N/A'}
                        </td>
                        <td className="py-3 px-3 text-slate-600">
                          <div>{formatDate(inv.due_date)}</div>
                        </td>
                        <td className="py-3 px-3 text-right font-mono font-bold text-[#0B2550]">
                          {formatAmt(inv.amount)}
                        </td>
                        <td className="py-3 px-3 text-center">
                          {getMatchBadge(inv.match_status)}
                        </td>
                        <td className="py-3 px-3 text-center">
                          {getStatusBadge(inv.status)}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Side: Interactive Invoice Detail Pane (5 Cols) */}
        <div className="lg:col-span-5 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col h-[760px]">
          {selectedInvoice ? (
            <>
              {/* Detail Header */}
              <div className="p-5 border-b border-slate-200 bg-slate-50/70">
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div>
                    <div className="text-[10px] font-extrabold text-blue-600 uppercase tracking-widest mb-0.5">Selected Invoice Detail</div>
                    <h2 className="text-xl font-black text-[#0B2550] font-mono break-all">{selectedInvoice.id}</h2>
                    <p className="text-xs font-bold text-slate-600 mt-0.5">
                      {selectedInvoice.tenant_id === 'TENANT_SUPPLIER_001' ? 'Apex Tooling Inc.' : (selectedInvoice.tenant_id || 'Apex Tooling Inc.')}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-1.5 shrink-0">
                    {getStatusBadge(selectedInvoice.status)}
                    {getMatchBadge(selectedInvoice.match_status)}
                  </div>
                </div>

                {/* Detail Tabs */}
                <div className="flex items-center gap-4 border-b border-slate-200 pt-2 -mb-5">
                  {['Overview', '3-Way Match', 'Line Items', 'Audit Trail'].map((tab: any) => (
                    <button
                      key={tab}
                      onClick={() => setDetailTab(tab)}
                      className={`pb-2.5 text-xs font-extrabold border-b-2 transition-all ${detailTab === tab ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-800'}`}
                    >
                      {tab}
                    </button>
                  ))}
                </div>
              </div>

              {/* Detail Tab Content Area */}
              <div className="flex-1 overflow-auto p-5 space-y-6">

                {/* TAB 1: OVERVIEW */}
                {detailTab === 'Overview' && (
                  <div className="space-y-5 animate-fade-in">
                    {/* Primary Grid */}
                    <div className="grid grid-cols-2 gap-4 bg-slate-50/60 p-4 rounded-xl border border-slate-100">
                      <div>
                        <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1">Purchase Order</span>
                        <div className="text-sm font-mono font-bold text-blue-600 flex items-center gap-1">
                          {selectedInvoice.po_id || 'N/A'}
                          <ExternalLink className="w-3 h-3 text-slate-400" />
                        </div>
                      </div>
                      <div>
                        <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1">Payment Terms</span>
                        <div className="text-sm font-bold text-[#0B2550]">Net 30 Days</div>
                      </div>
                      <div>
                        <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1">Invoice Date</span>
                        <div className="text-sm font-semibold text-slate-700">{formatDate(selectedInvoice.created_at)}</div>
                      </div>
                      <div>
                        <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1">Due Date</span>
                        <div className="text-sm font-semibold text-slate-700">{formatDate(selectedInvoice.due_date)}</div>
                      </div>
                    </div>

                    {/* Amount & Financial Breakdown */}
                    <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm space-y-3">
                      <div className="text-xs font-black text-[#0B2550] uppercase tracking-wider border-b border-slate-100 pb-2">Financial Breakdown</div>
                      <div className="flex justify-between text-xs text-slate-600">
                        <span>Taxable Subtotal (Base)</span>
                        <span className="font-mono font-bold text-slate-800">{formatAmt(selectedInvoice.amount * 0.82)}</span>
                      </div>
                      <div className="flex justify-between text-xs text-slate-600">
                        <span>Applicable GST / Sales Tax (18%)</span>
                        <span className="font-mono font-bold text-slate-800">{formatAmt(selectedInvoice.amount * 0.18)}</span>
                      </div>
                      <div className="flex justify-between text-xs text-slate-600">
                        <span>Shipping & Handling</span>
                        <span className="font-mono font-bold text-emerald-600">Included ($0.00)</span>
                      </div>
                      <div className="pt-2 border-t border-slate-100 flex justify-between items-baseline">
                        <span className="text-sm font-black text-[#0B2550]">Total Invoiced Amount</span>
                        <span className="text-xl font-black font-mono text-[#0B2550]">{formatAmt(selectedInvoice.amount)}</span>
                      </div>
                    </div>

                    {/* Invoice Description / Purpose */}
                    <div>
                      <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1.5">Description & Purpose</span>
                      <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-200 text-xs font-medium text-slate-700 leading-relaxed">
                        {selectedInvoice.description || 'Standard electronic invoice generated from approved purchase order.'}
                      </div>
                    </div>

                    {/* Quick 3-Way Match Summary Card */}
                    <div className="p-4 rounded-xl border border-blue-100 bg-blue-50/50 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center font-bold shrink-0">
                          <ShieldCheck className="w-5 h-5" />
                        </div>
                        <div>
                          <div className="text-xs font-black text-[#0B2550]">Automated 3-Way Matching</div>
                          <div className="text-[11px] font-semibold text-slate-500">
                            Reconciles PO, Warehouse GR, and Billed totals.
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => handleRunMatch(selectedInvoice.id)}
                        disabled={actionLoading}
                        className="px-3.5 py-1.5 rounded-lg bg-blue-600 text-white font-extrabold text-xs hover:bg-blue-700 transition shadow-sm shrink-0"
                      >
                        {actionLoading ? 'Reconciling...' : 'Verify Match'}
                      </button>
                    </div>
                  </div>
                )}

                {/* TAB 2: 3-WAY MATCH */}
                {detailTab === '3-Way Match' && (
                  <div className="space-y-5 animate-fade-in">
                    <div className="bg-slate-50/80 p-4 rounded-xl border border-slate-200">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-black text-[#0B2550] uppercase tracking-wider">3-Way Reconciliation Audit</span>
                        {getMatchBadge(selectedInvoice.match_status)}
                      </div>
                      <p className="text-xs text-slate-500">
                        Digital Twin validates contract purchase order limits against warehouse receiving receipts and final billed line items.
                      </p>
                    </div>

                    {/* Comparison Cards Spine */}
                    <div className="space-y-3">
                      {/* 1. PO Card */}
                      <div className="p-3.5 rounded-xl border border-slate-200 bg-white flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-slate-100 text-[#0B2550] flex items-center justify-center font-bold text-xs">PO</div>
                          <div>
                            <div className="text-xs font-bold text-[#0B2550]">Purchase Order ({selectedInvoice.po_id})</div>
                            <div className="text-[11px] text-slate-400 font-medium">Contract Maximum Authorized</div>
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs font-mono font-black text-[#0B2550]">{formatAmt(selectedInvoice.amount)}</div>
                          <div className="text-[10px] text-emerald-600 font-bold">Qty: 100 units</div>
                        </div>
                      </div>

                      {/* 2. Goods Receipt Card */}
                      <div className="p-3.5 rounded-xl border border-slate-200 bg-white flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-blue-100 text-blue-700 flex items-center justify-center font-bold text-xs">GR</div>
                          <div>
                            <div className="text-xs font-bold text-[#0B2550]">Goods Receipt (GR-WAREHOUSE)</div>
                            <div className="text-[11px] text-slate-400 font-medium">Physical Gate Delivery Logged</div>
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs font-mono font-black text-emerald-600">Passed QA</div>
                          <div className="text-[10px] text-emerald-600 font-bold">Qty: 100 received</div>
                        </div>
                      </div>

                      {/* 3. Invoice Card */}
                      <div className="p-3.5 rounded-xl border border-slate-200 bg-white flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-xs">INV</div>
                          <div>
                            <div className="text-xs font-bold text-[#0B2550]">Supplier Billed Invoice</div>
                            <div className="text-[11px] text-slate-400 font-medium">{selectedInvoice.id}</div>
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs font-mono font-black text-[#0B2550]">{formatAmt(selectedInvoice.amount)}</div>
                          <div className="text-[10px] text-slate-600 font-bold">Qty: 100 billed</div>
                        </div>
                      </div>
                    </div>

                    {/* Result Verdict Box */}
                    <div className={`p-4 rounded-xl border ${selectedInvoice.match_status === 'MATCHED' ? 'bg-emerald-50/70 border-emerald-200 text-emerald-900' : selectedInvoice.match_status === 'DISCREPANCY' ? 'bg-rose-50/70 border-rose-200 text-rose-900' : 'bg-amber-50/70 border-amber-200 text-amber-900'}`}>
                      <div className="flex items-center gap-2 font-black text-xs mb-1">
                        {selectedInvoice.match_status === 'MATCHED' ? (
                          <>
                            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                            <span>Three-Way Match Reconciled Successfully</span>
                          </>
                        ) : selectedInvoice.match_status === 'DISCREPANCY' ? (
                          <>
                            <AlertCircle className="w-4 h-4 text-rose-600" />
                            <span>Variance Discrepancy Found</span>
                          </>
                        ) : (
                          <>
                            <Clock className="w-4 h-4 text-amber-600" />
                            <span>Verification Required</span>
                          </>
                        )}
                      </div>
                      <p className="text-xs opacity-90">
                        {selectedInvoice.match_status === 'MATCHED'
                          ? 'Invoiced total matches PO amount and Goods Receipt. This invoice is cleared for payment authorization.'
                          : selectedInvoice.match_status === 'DISCREPANCY'
                          ? 'Pricing or quantity does not match contract specifications. You may raise a formal dispute with the supplier.'
                          : 'Click below to run automated algorithmic verification across purchase and shipment receipts.'}
                      </p>
                    </div>

                    <button
                      onClick={() => handleRunMatch(selectedInvoice.id)}
                      disabled={actionLoading}
                      className="w-full bg-blue-600 text-white py-2.5 rounded-xl font-bold text-xs hover:bg-blue-700 transition flex items-center justify-center gap-2 shadow-md shadow-blue-500/20"
                    >
                      <ShieldCheck className="w-4 h-4" />
                      {actionLoading ? 'Processing Verification...' : 'Run 3-Way Match Verification Now'}
                    </button>
                  </div>
                )}

                {/* TAB 3: LINE ITEMS */}
                {detailTab === 'Line Items' && (
                  <div className="space-y-4 animate-fade-in">
                    <div className="text-xs font-black text-[#0B2550] uppercase tracking-wider mb-2">Itemized Invoice Components</div>
                    <div className="border border-slate-200 rounded-xl overflow-hidden">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-slate-50 text-[10px] font-black text-slate-400 uppercase tracking-wider border-b border-slate-200">
                          <tr>
                            <th className="p-3">Item / Description</th>
                            <th className="p-3 text-center">Qty</th>
                            <th className="p-3 text-right">Unit Price</th>
                            <th className="p-3 text-right">Total</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 font-semibold text-slate-700">
                          <tr>
                            <td className="p-3">
                              <div className="font-bold text-[#0B2550]">Precision Machined Titanium Alloy Bushings</div>
                              <div className="text-[10px] text-slate-400">SKU: PN-TI-8832 ? Spec: ISO 9001</div>
                            </td>
                            <td className="p-3 text-center font-mono">100</td>
                            <td className="p-3 text-right font-mono">{formatAmt((selectedInvoice.amount * 0.82) / 100)}</td>
                            <td className="p-3 text-right font-mono font-bold text-[#0B2550]">{formatAmt(selectedInvoice.amount * 0.82)}</td>
                          </tr>
                          <tr className="bg-slate-50/50">
                            <td colSpan={3} className="p-3 text-right text-slate-500 font-bold">Standard Applicable Tax (18% GST/VAT)</td>
                            <td className="p-3 text-right font-mono font-bold text-slate-800">{formatAmt(selectedInvoice.amount * 0.18)}</td>
                          </tr>
                          <tr className="bg-blue-50/30">
                            <td colSpan={3} className="p-3 text-right font-black text-[#0B2550]">Grand Invoice Total</td>
                            <td className="p-3 text-right font-mono font-black text-blue-600 text-sm">{formatAmt(selectedInvoice.amount)}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* TAB 4: AUDIT TRAIL */}
                {detailTab === 'Audit Trail' && (
                  <div className="space-y-4 animate-fade-in">
                    <div className="text-xs font-black text-[#0B2550] uppercase tracking-wider mb-2">Lifecycle Event Timeline</div>
                    <div className="relative pl-6 space-y-6 before:content-[''] before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200">

                      {/* Event 1 */}
                      <div className="relative">
                        <span className="w-5 h-5 rounded-full bg-blue-600 text-white flex items-center justify-center absolute -left-6 top-0 text-[10px] font-bold">1</span>
                        <div className="font-bold text-xs text-[#0B2550]">Invoice Received & Registered</div>
                        <div className="text-[11px] text-slate-500 mt-0.5">Dispatched from supplier ERP system with digital token verification.</div>
                        <div className="text-[10px] text-slate-400 font-mono mt-1">{formatDate(selectedInvoice.created_at)}</div>
                      </div>

                      {/* Event 2 */}
                      <div className="relative">
                        <span className={`w-5 h-5 rounded-full text-white flex items-center justify-center absolute -left-6 top-0 text-[10px] font-bold ${selectedInvoice.match_status === 'MATCHED' ? 'bg-emerald-600' : 'bg-slate-400'}`}>2</span>
                        <div className="font-bold text-xs text-[#0B2550]">Automated 3-Way Reconciliation</div>
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          Status: <span className="font-bold">{selectedInvoice.match_status || 'PENDING'}</span>
                        </div>
                      </div>

                      {/* Event 3 */}
                      <div className="relative">
                        <span className={`w-5 h-5 rounded-full text-white flex items-center justify-center absolute -left-6 top-0 text-[10px] font-bold ${selectedInvoice.status === 'PAID' ? 'bg-emerald-600' : selectedInvoice.status === 'DISPUTED' ? 'bg-purple-600' : 'bg-slate-400'}`}>3</span>
                        <div className="font-bold text-xs text-[#0B2550]">Payment Authorization & Settlement</div>
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          Current status: <span className="font-bold">{selectedInvoice.status || 'PENDING'}</span>
                        </div>
                      </div>

                    </div>
                  </div>
                )}

              </div>

              {/* Detail Footer Controls */}
              <div className="p-5 border-t border-slate-200 bg-slate-50/70 space-y-2.5">
                {selectedInvoice.status === 'PAID' ? (
                  <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 p-3 rounded-xl flex items-center justify-between text-xs font-bold">
                    <span className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      Invoice Paid & Settled
                    </span>
                    <button onClick={() => setShowVoucherModal(true)} className="underline text-emerald-700 hover:text-emerald-900">
                      View Voucher
                    </button>
                  </div>
                ) : selectedInvoice.status === 'DISPUTED' ? (
                  <div className="space-y-2">
                    <div className="bg-purple-50 border border-purple-200 text-purple-800 p-3 rounded-xl text-xs font-semibold">
                      <div className="font-bold flex items-center gap-2 mb-1">
                        <AlertTriangle className="w-4 h-4 text-purple-600" />
                        Invoice in Formal Dispute
                      </div>
                      Supplier notified. Awaiting revised invoice or credit note.
                    </div>
                    <button
                      onClick={() => setShowPaymentModal(true)}
                      className="w-full bg-blue-600 text-white py-2.5 rounded-xl font-bold text-xs hover:bg-blue-700 transition shadow-md shadow-blue-500/20"
                    >
                      Resolve & Authorize Payment
                    </button>
                  </div>
                ) : (
                  <>
                    <button
                      onClick={() => setShowPaymentModal(true)}
                      className="w-full bg-blue-600 text-white py-2.5 rounded-xl font-bold text-xs hover:bg-blue-700 transition shadow-md shadow-blue-500/20 flex items-center justify-center gap-2"
                    >
                      <CreditCard className="w-4 h-4" />
                      Approve & Process Payment ({formatAmt(selectedInvoice.amount)})
                    </button>

                    <div className="flex gap-2">
                      <button
                        onClick={() => setShowDisputeModal(true)}
                        className="flex-1 bg-white border border-slate-200 text-slate-700 py-2 rounded-xl font-bold text-xs hover:bg-slate-50 transition shadow-sm flex items-center justify-center gap-1.5"
                      >
                        <AlertTriangle className="w-3.5 h-3.5 text-purple-600" /> Raise Dispute
                      </button>

                      <button
                        onClick={() => setShowVoucherModal(true)}
                        className="flex-1 bg-white border border-slate-200 text-slate-700 py-2 rounded-xl font-bold text-xs hover:bg-slate-50 transition shadow-sm flex items-center justify-center gap-1.5"
                      >
                        <Printer className="w-3.5 h-3.5 text-slate-500" /> Print Voucher
                      </button>
                    </div>
                  </>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-slate-50/50">
              <Receipt className="w-12 h-12 text-slate-300 mb-3" />
              <h3 className="font-bold text-[#0B2550] text-base mb-1">No Invoice Selected</h3>
              <p className="text-xs text-slate-500 max-w-xs">Select any row from the left table to inspect details, 3-way match audit, and execute payment.</p>
            </div>
          )}
        </div>

      </div>

      {/* MODAL 1: PAYMENT APPROVAL */}
      {showPaymentModal && selectedInvoice && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm p-3 sm:p-6 flex items-center justify-center animate-fade-in">
          <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[85vh] sm:max-h-[88vh] overflow-hidden my-auto p-6 space-y-5 overflow-y-auto animate-scale-in">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
                  <CreditCard className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-black text-[#0B2550]">Authorize Supplier Payment</h3>
                  <p className="text-xs text-slate-500 font-medium">Reconciled invoice settlement via treasury rails</p>
                </div>
              </div>
              <button onClick={() => setShowPaymentModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-500 font-semibold">Invoice Number:</span>
                <span className="font-mono font-bold text-[#0B2550]">{selectedInvoice.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 font-semibold">Beneficiary Supplier:</span>
                <span className="font-bold text-[#0B2550]">
                  {selectedInvoice.tenant_id === 'TENANT_SUPPLIER_001' ? 'Apex Tooling Inc.' : (selectedInvoice.tenant_id || 'Apex Tooling Inc.')}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 font-semibold">Linked Purchase Order:</span>
                <span className="font-mono font-bold text-slate-700">{selectedInvoice.po_id}</span>
              </div>
              <div className="flex justify-between pt-2 border-t border-slate-200 text-sm">
                <span className="font-extrabold text-[#0B2550]">Authorized Payment Amount:</span>
                <span className="font-mono font-black text-blue-600 text-base">{formatAmt(selectedInvoice.amount)}</span>
              </div>
            </div>

            <div>
              <label className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1.5">Payment Method</label>
              <select
                value={paymentMethod}
                onChange={e => setPaymentMethod(e.target.value)}
                className="w-full text-xs font-semibold p-2.5 border border-slate-200 rounded-xl outline-none bg-slate-50 focus:border-blue-500"
              >
                <option value="ACH Direct Deposit">ACH Direct Deposit (FedNow instant clearing)</option>
                <option value="Fedwire Transfer">Fedwire Transfer (Real-time gross settlement)</option>
                <option value="Corporate Virtual Card">Commercial Virtual Card (1.5% AP Rebate)</option>
              </select>
            </div>

            <div>
              <label className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1.5">Remittance Memo / Notes</label>
              <input
                type="text"
                value={paymentNotes}
                onChange={e => setPaymentNotes(e.target.value)}
                className="w-full text-xs font-semibold p-2.5 border border-slate-200 rounded-xl outline-none bg-slate-50 focus:border-blue-500"
              />
            </div>

            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowPaymentModal(false)}
                className="flex-1 py-2.5 border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50 transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmPayment}
                disabled={actionLoading}
                className="flex-1 py-2.5 bg-blue-600 text-white font-extrabold text-xs rounded-xl hover:bg-blue-700 transition shadow-md shadow-blue-500/20 flex items-center justify-center gap-2"
              >
                {actionLoading ? 'Settling...' : `Confirm Payment (${formatAmt(selectedInvoice.amount)})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 2: DISPUTE LOGGING */}
      {showDisputeModal && selectedInvoice && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm p-3 sm:p-6 flex items-center justify-center animate-fade-in">
          <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[85vh] sm:max-h-[88vh] overflow-hidden my-auto p-6 space-y-5 overflow-y-auto animate-scale-in">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center font-bold">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-black text-[#0B2550]">Raise Invoice Discrepancy Dispute</h3>
                  <p className="text-xs text-slate-500 font-medium">Sends formal notification and locks payment execution</p>
                </div>
              </div>
              <button onClick={() => setShowDisputeModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div>
              <label className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1.5">Primary Discrepancy Reason</label>
              <select
                value={disputeReason}
                onChange={e => setDisputeReason(e.target.value)}
                className="w-full text-xs font-semibold p-2.5 border border-slate-200 rounded-xl outline-none bg-slate-50 focus:border-purple-500"
              >
                <option value="Price Discrepancy">Price Discrepancy (Unit rate exceeds approved PO)</option>
                <option value="Quantity Mismatch">Quantity Mismatch (Invoiced qty exceeds goods received)</option>
                <option value="Damaged / Non-conforming Goods">Damaged / Non-conforming Goods (QA failed)</option>
                <option value="Unapproved Surcharges">Unapproved Surcharges (Unexpected freight/handling fees)</option>
                <option value="Duplicate Invoice Submission">Duplicate Invoice Submission</option>
              </select>
            </div>

            <div>
              <label className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block mb-1.5">Specific Discrepancy Details</label>
              <textarea
                rows={3}
                value={disputeNotes}
                onChange={e => setDisputeNotes(e.target.value)}
                placeholder="Explain the reason for dispute so supplier can rectify..."
                className="w-full text-xs font-semibold p-2.5 border border-slate-200 rounded-xl outline-none bg-slate-50 focus:border-purple-500"
              />
            </div>

            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowDisputeModal(false)}
                className="flex-1 py-2.5 border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50 transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDispute}
                disabled={actionLoading}
                className="flex-1 py-2.5 bg-purple-600 text-white font-extrabold text-xs rounded-xl hover:bg-purple-700 transition shadow-md shadow-purple-500/20"
              >
                {actionLoading ? 'Submitting...' : 'Submit Dispute to Supplier'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 3: IMPORT INVOICES */}
      {showImportModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm p-3 sm:p-6 flex items-center justify-center animate-fade-in">
          <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[85vh] sm:max-h-[88vh] overflow-hidden my-auto p-6 space-y-5 overflow-y-auto animate-scale-in">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-bold">
                  <Upload className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-black text-[#0B2550]">Import Supplier Invoices</h3>
                  <p className="text-xs text-slate-500 font-medium">EDI / XML / CSV ingestion or demo invoice provisioning</p>
                </div>
              </div>
              <button onClick={() => setShowImportModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="border-2 border-dashed border-slate-200 rounded-2xl p-6 text-center bg-slate-50/50 hover:bg-blue-50/20 transition cursor-pointer">
              <Upload className="w-8 h-8 text-blue-500 mx-auto mb-2" />
              <div className="text-xs font-black text-[#0B2550]">Drag & drop invoice files here</div>
              <div className="text-[11px] text-slate-400 mt-1">Supports EDI 810, UBL XML, CSV, and PDF vouchers</div>
            </div>

            <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 space-y-2">
              <div className="text-xs font-bold text-[#0B2550]">Quick Test Data Generator</div>
              <p className="text-xs text-slate-500">
                Generate and import a verified electronic invoice linked to a new Purchase Order from Apex Tooling Inc.
              </p>
              <button
                type="button"
                onClick={handleImportSample}
                disabled={actionLoading}
                className="mt-2 w-full bg-blue-600 text-white py-2 rounded-xl text-xs font-bold hover:bg-blue-700 transition"
              >
                {actionLoading ? 'Importing Sample...' : 'Generate & Import Sample Supplier Invoice'}
              </button>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={() => setShowImportModal(false)}
                className="px-5 py-2.5 border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50 transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 4: INVOICE VOUCHER PREVIEW */}
      {showVoucherModal && selectedInvoice && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm p-3 sm:p-6 flex items-center justify-center animate-fade-in">
          <div className="bg-white rounded-2xl max-w-2xl w-full p-8 space-y-6 shadow-2xl border border-slate-200 animate-scale-in max-h-[90vh] overflow-auto">
            <div className="flex items-center justify-between border-b border-slate-200 pb-4">
              <div>
                <span className="text-[10px] font-extrabold text-blue-600 uppercase tracking-widest">Formal Accounts Payable Voucher</span>
                <h3 className="text-xl font-black text-[#0B2550]">Tax Invoice & Remittance Statement</h3>
              </div>
              <button onClick={() => setShowVoucherModal(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Printable Voucher Paper */}
            <div className="p-6 bg-slate-50/70 rounded-2xl border border-slate-200 space-y-6 font-mono text-xs text-slate-800">
              <div className="flex justify-between items-start border-b border-slate-200 pb-4">
                <div>
                  <div className="text-base font-black text-[#0B2550] font-sans">
                    {selectedInvoice.tenant_id === 'TENANT_SUPPLIER_001' ? 'Apex Tooling Inc.' : (selectedInvoice.tenant_id || 'Apex Tooling Inc.')}
                  </div>
                  <div className="text-[11px] text-slate-500 font-sans mt-0.5">Automotive & Aerospace Precision Engineering</div>
                  <div className="text-[10px] text-slate-400 mt-1">Tax ID: US-TAX-94810293 ? Supplier Reg: SUP-4921</div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-black text-blue-600">{selectedInvoice.id}</div>
                  <div className="text-[11px] text-slate-500 font-sans">Date: {formatDate(selectedInvoice.created_at)}</div>
                  <div className="text-[11px] text-slate-500 font-sans">Due: {formatDate(selectedInvoice.due_date)}</div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 text-xs font-sans">
                <div>
                  <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block">Billed To (Buyer)</span>
                  <div className="font-bold text-[#0B2550] mt-1">SupplyTwin Enterprise Corp</div>
                  <div className="text-slate-500 text-[11px]">Attn: Global Procurement & Accounts Payable</div>
                </div>
                <div>
                  <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block">Order Reference</span>
                  <div className="font-bold text-blue-600 mt-1">PO: {selectedInvoice.po_id || 'N/A'}</div>
                  <div className="text-slate-500 text-[11px]">Payment Terms: Net 30 Days</div>
                </div>
              </div>

              {/* Table */}
              <div className="border border-slate-200 rounded-xl overflow-hidden bg-white">
                <table className="w-full text-left">
                  <thead className="bg-slate-100 text-[10px] font-bold text-slate-500 uppercase border-b border-slate-200">
                    <tr>
                      <th className="p-2.5">Line Description</th>
                      <th className="p-2.5 text-center">Qty</th>
                      <th className="p-2.5 text-right">Rate</th>
                      <th className="p-2.5 text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    <tr>
                      <td className="p-2.5 font-sans font-semibold">Precision Machined Titanium Alloy Components (PO Ref: {selectedInvoice.po_id})</td>
                      <td className="p-2.5 text-center">100</td>
                      <td className="p-2.5 text-right">{formatAmt((selectedInvoice.amount * 0.82) / 100)}</td>
                      <td className="p-2.5 text-right font-bold">{formatAmt(selectedInvoice.amount * 0.82)}</td>
                    </tr>
                    <tr>
                      <td colSpan={3} className="p-2.5 text-right font-sans font-bold text-slate-500">Applicable Tax (18% GST/VAT)</td>
                      <td className="p-2.5 text-right font-bold">{formatAmt(selectedInvoice.amount * 0.18)}</td>
                    </tr>
                    <tr className="bg-slate-50 font-black text-sm text-[#0B2550]">
                      <td colSpan={3} className="p-2.5 text-right font-sans">Total Billed Due (USD)</td>
                      <td className="p-2.5 text-right font-mono text-blue-600">{formatAmt(selectedInvoice.amount)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div className="flex justify-between items-center text-[10px] text-slate-400 pt-2 border-t border-slate-200 font-sans">
                <span>Verification Hash: SHA256-INV-849204A8F9</span>
                <span>Audit Status: {selectedInvoice.status || 'PENDING'}</span>
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowVoucherModal(false)}
                className="px-5 py-2.5 border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50 transition"
              >
                Close
              </button>
              <button
                type="button"
                onClick={() => window.print()}
                className="px-5 py-2.5 bg-blue-600 text-white font-extrabold text-xs rounded-xl hover:bg-blue-700 transition shadow-md flex items-center gap-2"
              >
                <Printer className="w-4 h-4" /> Print / Save PDF
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
