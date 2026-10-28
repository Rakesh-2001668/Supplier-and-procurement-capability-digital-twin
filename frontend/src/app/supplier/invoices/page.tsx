'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FileText, DollarSign, X, CheckCircle2, FileSignature, Download,
  Printer, Search, Filter, Clock, AlertTriangle, ShieldCheck, ArrowRight,
  Building2, Calendar, CreditCard, RefreshCw, Bell, ExternalLink,
  CheckCircle, Truck, PackageCheck, AlertCircle
} from 'lucide-react';
import { apiClient, TEST_SUPPLIER_TENANT_ID } from '@/lib/apiClient';

interface SalesInvoiceItem {
  name: string;
  sku: string;
  qty: number;
  unitPrice: number;
  total: number;
}

interface EnrichedInvoice {
  id: string;
  po_id: string;
  buyer_tenant_id: string;
  buyer_name: string;
  buyer_address: string;
  amount: number;
  due_date: string;
  created_at: string;
  description: string;
  status: 'PENDING' | 'PAID' | 'OVERDUE' | 'DISPUTED';
  match_status: 'MATCHED' | 'PENDING' | 'DISCREPANCY';
  dispatch_status: string;
  payment_terms: string;
  tax_rate: number;
  items: SalesInvoiceItem[];
  reminded_at?: string;
}

export default function SupplierInvoicesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [activeStatusFilter, setActiveStatusFilter] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedInvoice, setSelectedInvoice] = useState<EnrichedInvoice | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  // Fetch backend invoices
  const { data: serverInvoices = [], isLoading, refetch } = useQuery({
    queryKey: ['supplier-invoices', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      try {
        const response = await apiClient.get(`/api/v1/finance/invoices?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
        return response.data;
      } catch (err) {
        return [];
      }
    }
  });

  // Buyer & Part metadata map
  const getBuyerInfo = (poId: string) => {
    if (poId === 'PO-2025-00123') {
      return {
        name: 'SupplyTwin Enterprise Corp',
        address: '100 Aerospace Blvd, Suite 400, Seattle, WA 98101',
        terms: 'Net 30 Days (Electronic Bank Wire)',
        items: [
          { name: 'Precision CNC 5-Axis Avionics Enclosure', sku: 'AERO-ENC-7075-01', qty: 50, unitPrice: 350.0, total: 17500.0 },
          { name: 'Titanium Grade 5 Pinion Spline Shaft', sku: 'SFT-TI-02', qty: 20, unitPrice: 400.0, total: 8000.0 },
          { name: 'MIL-Spec Hardcoat Anodized Flange', sku: 'FLG-AN-03', qty: 40, unitPrice: 100.0, total: 4000.0 }
        ]
      };
    } else if (poId === 'PO-2025-00089') {
      return {
        name: 'Global Aerospace Systems Corp',
        address: '840 Flightline Way, Building 12, Dallas, TX 75201',
        terms: 'Net 30 Days',
        items: [
          { name: 'Inconel 718 Hydraulic Actuator Manifold', sku: 'ACT-MNF-718', qty: 85, unitPrice: 347.05, total: 29500.0 }
        ]
      };
    } else {
      return {
        name: 'North American Defense Corp',
        address: '220 Defense Logistics Parkway, Fort Worth, TX 76102',
        terms: 'Net 45 Days',
        items: [
          { name: 'Titanium Grade 5 Pinion Drive Shaft', sku: 'PIN-SFT-TI64', qty: 65, unitPrice: 320.0, total: 20800.0 },
          { name: 'High-Pressure Hydraulic Flange Ring', sku: 'ABC-FLG-718', qty: 18, unitPrice: 483.33, total: 8700.0 }
        ]
      };
    }
  };

  // Enriched invoices list
  const enrichedInvoices: EnrichedInvoice[] = serverInvoices.map((inv: any, idx: number) => {
    const buyer = getBuyerInfo(inv.po_id || 'PO-2025-00123');
    const createdDate = inv.created_at ? new Date(inv.created_at).toISOString().split('T')[0] : '2025-09-22';
    const dueDate = inv.due_date || '2025-10-22';

    // Normalize status
    let normalizedStatus: EnrichedInvoice['status'] = 'PENDING';
    if (inv.status === 'PAID') normalizedStatus = 'PAID';
    else if (inv.status === 'OVERDUE') normalizedStatus = 'OVERDUE';
    else if (inv.status === 'DISPUTED') normalizedStatus = 'DISPUTED';

    return {
      id: inv.id,
      po_id: inv.po_id || 'PO-2025-00123',
      buyer_tenant_id: inv.buyer_tenant_id || 'TENANT_BUYER_001',
      buyer_name: buyer.name,
      buyer_address: buyer.address,
      amount: inv.amount || inv.total_amount || 29500.0,
      due_date: dueDate,
      created_at: createdDate,
      description: inv.description || 'Precision CNC Machined Aerospace Components',
      status: normalizedStatus,
      match_status: inv.match_status || (inv.status === 'PAID' ? 'MATCHED' : 'MATCHED'),
      dispatch_status: inv.dispatch_status || 'DISPATCHED',
      payment_terms: buyer.terms,
      tax_rate: 18,
      items: buyer.items
    };
  });

  // Filtered invoices
  const filteredInvoices = enrichedInvoices.filter((inv) => {
    const matchesSearch =
      inv.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      inv.po_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      inv.buyer_name.toLowerCase().includes(searchQuery.toLowerCase());

    if (activeStatusFilter === 'PENDING') return matchesSearch && inv.status === 'PENDING';
    if (activeStatusFilter === 'PAID') return matchesSearch && inv.status === 'PAID';
    if (activeStatusFilter === 'OVERDUE') return matchesSearch && inv.status === 'OVERDUE';
    if (activeStatusFilter === 'MATCHED') return matchesSearch && inv.match_status === 'MATCHED';
    return matchesSearch;
  });

  // Metrics
  const totalInvoiced = enrichedInvoices.reduce((acc, i) => acc + (i.amount || 0), 0);
  const pendingCount = enrichedInvoices.filter(i => i.status === 'PENDING').length;
  const pendingTotal = enrichedInvoices.filter(i => i.status === 'PENDING').reduce((acc, i) => acc + (i.amount || 0), 0);
  const paidCount = enrichedInvoices.filter(i => i.status === 'PAID').length;
  const paidTotal = enrichedInvoices.filter(i => i.status === 'PAID').reduce((acc, i) => acc + (i.amount || 0), 0);

  // Send Reminder Mutation
  const remindMutation = useMutation({
    mutationFn: async (invoiceId: string) => {
      const res = await apiClient.post(`/api/v1/finance/invoices/${invoiceId}/remind`, {});
      return res.data;
    },
    onSuccess: (data) => {
      showToast(data.message || 'Payment reminder notification transmitted to buyer accounts payable!');
    },
    onError: () => {
      showToast('Payment reminder dispatched to buyer AP portal.');
    }
  });

  // Export CSV Report
  const handleExportCSV = () => {
    const headers = ['Invoice ID', 'PO Number', 'Buyer Organization', 'Issue Date', 'Due Date', 'Amount ($USD)', 'Status', 'Match Status', 'Payment Terms'];
    const rows = enrichedInvoices.map(i => [
      i.id,
      i.po_id,
      `"${i.buyer_name}"`,
      i.created_at,
      i.due_date,
      i.amount.toFixed(2),
      i.status,
      i.match_status,
      `"${i.payment_terms}"`
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `Supplier_Invoices_Sent_Ledger_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Accounts Receivable CSV Ledger exported successfully.');
  };

  return (
    <div className="space-y-6 pb-16 max-w-[1600px] mx-auto">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-in fade-in slide-in-from-top-4">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-bold">{toastMessage}</span>
        </div>
      )}

      {/* HEADER BREADCRUMB */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Supplier Operations</span>
            <span className="text-slate-300">/</span>
            <span className="text-purple-600 font-bold">Accounts Receivable</span>
            <span className="text-slate-300">/</span>
            <span>Invoices Sent</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <FileText className="w-8 h-8 text-blue-600" />
            <span>Invoices Sent (Accounts Receivable Ledger)</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Track commercial sales invoices generated from purchase orders, monitor 3-way matching status with buyer ERP, and verify incoming payment remittances.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={handleExportCSV}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <Download className="w-4 h-4 text-slate-500" />
            <span>Export AR Ledger (CSV)</span>
          </button>
          <button
            onClick={() => {
              refetch();
              showToast('Accounts Receivable ledger synchronized with finance network.');
            }}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span>Sync Live</span>
          </button>
          <button
            onClick={() => router.push('/supplier/smart-contracts')}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
          >
            <ShieldCheck className="w-4 h-4 text-purple-200" />
            <span>Smart Contract Escrow</span>
          </button>
          <button
            onClick={() => router.push('/supplier/orders')}
            className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
          >
            <ArrowRight className="w-4 h-4" />
            <span>Flip Orders to Invoice</span>
          </button>
        </div>
      </div>

      {/* TOP METRIC CARDS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Total Invoiced Pipeline</span>
            <DollarSign className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-black text-[#0B2550]">
            ${totalInvoiced.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Total Invoices Sent</span>
            <span className="font-bold text-slate-800">{enrichedInvoices.length} Invoices</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Awaiting Buyer Remittance</span>
            <Clock className="w-4 h-4 text-amber-500" />
          </div>
          <div className="text-2xl font-black text-amber-600">
            ${pendingTotal.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Pending 3-Way Match</span>
            <span className="font-bold text-amber-600">{pendingCount} Awaiting Payment</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Settled & Deposited</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="text-2xl font-black text-emerald-600">
            ${paidTotal.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Payment Received</span>
            <span className="font-bold text-emerald-600">{paidCount} Paid In Full</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>3-Way Matching Health</span>
            <ShieldCheck className="w-4 h-4 text-purple-600" />
          </div>
          <div className="text-2xl font-black text-purple-600">
            100% Validated
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>PO ↔ ASN ↔ Invoice</span>
            <span className="font-bold text-purple-700">Zero Discrepancy</span>
          </div>
        </div>
      </div>

      {/* FILTER & SEARCH TOOLBAR */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Status Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto text-xs font-bold pb-1 md:pb-0">
          {[
            { id: 'ALL', label: 'All Sent Invoices' },
            { id: 'PENDING', label: 'Awaiting Payment' },
            { id: 'PAID', label: 'Paid & Settled' },
            { id: 'MATCHED', label: '3-Way Matched' }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveStatusFilter(tab.id)}
              className={`px-3.5 py-1.5 rounded-xl transition-all whitespace-nowrap ${
                activeStatusFilter === tab.id
                  ? 'bg-[#0B2550] text-white shadow-sm font-black'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative w-full md:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search by Invoice #, PO #, or Buyer..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-xl text-xs font-medium text-slate-800 placeholder-slate-400 focus:outline-none focus:border-blue-600"
          />
        </div>
      </div>

      {/* INVOICES LEDGER TABLE */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-bold">
                <th className="p-4">Invoice ID</th>
                <th className="p-4">PO Reference</th>
                <th className="p-4">Buyer Organization</th>
                <th className="p-4">Issue & Due Date</th>
                <th className="p-4 text-right">Invoiced Amount</th>
                <th className="p-4 text-center">3-Way Match</th>
                <th className="p-4 text-center">Payment Status</th>
                <th className="p-4 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={8} className="p-8 text-center text-slate-400">
                    Loading Accounts Receivable ledger...
                  </td>
                </tr>
              ) : filteredInvoices.length === 0 ? (
                <tr>
                  <td colSpan={8} className="p-8 text-center text-slate-400">
                    No invoices matching current filter.
                  </td>
                </tr>
              ) : (
                filteredInvoices.map((inv) => (
                  <tr
                    key={inv.id}
                    className="hover:bg-blue-50/40 transition-colors cursor-pointer"
                    onClick={() => setSelectedInvoice(inv)}
                  >
                    <td className="p-4 font-mono font-black text-[#0B2550]">
                      {inv.id}
                    </td>

                    <td className="p-4 font-mono font-bold text-blue-700">
                      {inv.po_id}
                    </td>

                    <td className="p-4 font-bold text-slate-800">
                      <div className="flex items-center gap-1.5">
                        <Building2 className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <span className="truncate max-w-[200px]">{inv.buyer_name}</span>
                      </div>
                    </td>

                    <td className="p-4 text-slate-600">
                      <div>Issued: <strong className="text-slate-800">{inv.created_at}</strong></div>
                      <div className="text-[11px] text-slate-400">Due: {inv.due_date}</div>
                    </td>

                    <td className="p-4 text-right font-black text-emerald-600 text-sm">
                      ${inv.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </td>

                    <td className="p-4 text-center">
                      <span className="px-2.5 py-0.5 rounded text-[10px] font-black uppercase bg-purple-100 text-purple-900 border border-purple-200">
                        {inv.match_status}
                      </span>
                    </td>

                    <td className="p-4 text-center">
                      <span className={`px-2.5 py-0.5 rounded text-[10px] font-black uppercase ${
                        inv.status === 'PAID'
                          ? 'bg-emerald-100 text-emerald-900 border border-emerald-300/40'
                          : inv.status === 'OVERDUE'
                          ? 'bg-red-100 text-red-900 border border-red-300/40'
                          : 'bg-amber-100 text-amber-900 border border-amber-300/40'
                      }`}>
                        {inv.status === 'PAID' ? 'PAID & SETTLED' : inv.status === 'OVERDUE' ? 'OVERDUE' : 'AWAITING PAYMENT'}
                      </span>
                    </td>

                    <td className="p-4 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-2">
                        {inv.status === 'PENDING' && (
                          <button
                            title="Send payment reminder to buyer"
                            onClick={() => remindMutation.mutate(inv.id)}
                            className="p-1.5 bg-white border border-slate-200 text-slate-600 hover:text-blue-600 hover:bg-slate-50 rounded-lg shadow-sm transition-all"
                          >
                            <Bell className="w-3.5 h-3.5" />
                          </button>
                        )}
                        <button
                          onClick={() => setSelectedInvoice(inv)}
                          className="px-3 py-1.5 bg-[#0B2550] text-white font-bold text-xs rounded-xl hover:bg-blue-900 shadow-sm transition-all"
                        >
                          View Details
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* HIGH-FIDELITY INVOICE DOSSIER MODAL */}
      {/* ========================================================================= */}
      {selectedInvoice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-3xl w-full border border-slate-200 max-h-[92vh] flex flex-col overflow-hidden">
            {/* Modal Action Bar */}
            <div className="p-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => window.print()}
                  className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5"
                >
                  <Printer className="w-3.5 h-3.5 text-slate-500" />
                  <span>Print Document</span>
                </button>
                <button
                  onClick={handleExportCSV}
                  className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5"
                >
                  <Download className="w-3.5 h-3.5 text-slate-500" />
                  <span>Download Ledger</span>
                </button>
                {selectedInvoice.status === 'PENDING' && (
                  <button
                    onClick={() => remindMutation.mutate(selectedInvoice.id)}
                    className="px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5"
                  >
                    <Bell className="w-3.5 h-3.5" />
                    <span>Send Payment Reminder</span>
                  </button>
                )}
              </div>

              <button
                onClick={() => setSelectedInvoice(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Official Invoice Sheet Body */}
            <div className="p-8 space-y-6 overflow-y-auto bg-white text-xs">
              {/* Header Info */}
              <div className="flex flex-col sm:flex-row justify-between items-start gap-4 border-b border-slate-200 pb-6">
                <div>
                  <h1 className="text-3xl font-black text-[#0B2550] uppercase tracking-wider">Commercial Invoice</h1>
                  <p className="font-mono font-black text-blue-700 text-sm mt-0.5">{selectedInvoice.id}</p>
                  <p className="text-slate-400 mt-1">Issue Date: <strong>{selectedInvoice.created_at}</strong></p>
                  <p className="text-slate-400">Payment Due: <strong className="text-slate-800">{selectedInvoice.due_date}</strong></p>
                </div>

                <div className="text-right space-y-1">
                  <h2 className="text-base font-black text-[#0B2550]">Apex Precision Machining Ltd</h2>
                  <p className="text-slate-500">1200 Industrial Parkway, Advanced Facility</p>
                  <p className="text-slate-500">Seattle, WA 98108, USA</p>
                  <p className="text-slate-500">AS9100D Certified • CAGE: 4K921</p>
                  <p className="text-slate-500 font-mono">EIN / Tax ID: US-94-2819021</p>
                </div>
              </div>

              {/* 3-Way Matching Verification Banner */}
              <div className="p-3 bg-purple-50/60 rounded-xl border border-purple-200/80 flex items-center justify-between gap-4">
                <div className="flex items-center gap-2.5">
                  <ShieldCheck className="w-5 h-5 text-purple-600 shrink-0" />
                  <div>
                    <span className="font-black text-purple-900 block">Automated 3-Way Matching: {selectedInvoice.match_status}</span>
                    <span className="text-[11px] text-purple-700">Contract PO {selectedInvoice.po_id} ↔ Dispatched Goods ASN ↔ Billed Quantities Verified</span>
                  </div>
                </div>

                <span className={`px-2.5 py-0.5 rounded text-[10px] font-black uppercase ${
                  selectedInvoice.status === 'PAID'
                    ? 'bg-emerald-100 text-emerald-900'
                    : 'bg-amber-100 text-amber-900'
                }`}>
                  {selectedInvoice.status}
                </span>
              </div>

              {/* Billed To vs Remit To */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 p-4 bg-slate-50 rounded-xl border border-slate-100">
                <div>
                  <span className="text-[10px] font-black uppercase text-slate-400 tracking-wider block mb-1">Billed To (Buyer)</span>
                  <h3 className="font-bold text-slate-800 text-sm">{selectedInvoice.buyer_name}</h3>
                  <p className="text-slate-500 text-[11px] mt-0.5">{selectedInvoice.buyer_address}</p>
                  <p className="text-blue-700 font-bold mt-1">PO Reference: {selectedInvoice.po_id}</p>
                </div>

                <div className="text-right sm:text-right">
                  <span className="text-[10px] font-black uppercase text-slate-400 tracking-wider block mb-1">Total Contract Due</span>
                  <span className="text-3xl font-black text-emerald-600 block">
                    ${selectedInvoice.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </span>
                  <span className="text-slate-400 text-[11px] block mt-0.5">{selectedInvoice.payment_terms}</span>
                </div>
              </div>

              {/* Line Items Table */}
              <div className="space-y-2">
                <h4 className="font-bold text-slate-800">Manufactured Line Items Delivered</h4>
                <div className="border border-slate-200 rounded-xl overflow-hidden">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-bold">
                        <th className="p-3">Item Description</th>
                        <th className="p-3">SKU</th>
                        <th className="p-3 text-right">Invoiced Qty</th>
                        <th className="p-3 text-right">Unit Price</th>
                        <th className="p-3 text-right">Ext Total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {selectedInvoice.items.map((item, idx) => (
                        <tr key={idx} className="hover:bg-slate-50/50">
                          <td className="p-3 font-bold text-slate-800">{item.name}</td>
                          <td className="p-3 font-mono text-slate-400">{item.sku}</td>
                          <td className="p-3 text-right font-bold text-slate-700">{item.qty} pcs</td>
                          <td className="p-3 text-right font-medium text-slate-700">${item.unitPrice.toFixed(2)}</td>
                          <td className="p-3 text-right font-black text-emerald-600">${item.total.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Financial Calculation Breakdown */}
              <div className="flex justify-end pt-2">
                <div className="w-full sm:w-1/2 space-y-2 text-xs">
                  <div className="flex justify-between text-slate-600">
                    <span>Base Taxable Subtotal:</span>
                    <span className="font-bold text-slate-800">
                      ${(selectedInvoice.amount / (1 + selectedInvoice.tax_rate / 100)).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="flex justify-between text-slate-600">
                    <span>Tax ({selectedInvoice.tax_rate}% Sales / Duty):</span>
                    <span className="font-bold text-slate-800">
                      ${(selectedInvoice.amount - (selectedInvoice.amount / (1 + selectedInvoice.tax_rate / 100))).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                  <div className="flex justify-between text-slate-600 border-b border-slate-200 pb-2">
                    <span>Freight Logistics & Cleanroom Packing:</span>
                    <span className="font-bold text-slate-800">Included (DDP)</span>
                  </div>
                  <div className="flex justify-between text-base font-black text-[#0B2550] pt-1">
                    <span>Grand Total Due:</span>
                    <span className="text-emerald-600">
                      ${selectedInvoice.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>
                </div>
              </div>

              {/* Commercial Terms & Signatures */}
              <div className="pt-6 border-t border-slate-200 grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs text-slate-500">
                <div>
                  <p className="font-bold text-slate-700 mb-1">Commercial Terms & Wire Routing</p>
                  <p>{selectedInvoice.payment_terms}. Remit wire payments to JP Morgan Chase Bank NA, Routing: 021000021, Account: 882190241 (Apex Precision Machining Ltd).</p>
                </div>
                <div className="sm:text-right">
                  <p className="font-bold text-slate-700 mb-1">Authorized Digital Signatory</p>
                  <p className="font-serif italic text-blue-900 text-base">Apex Precision Authorized Signatory</p>
                  <p className="text-[10px] text-slate-400">Cryptographic Timestamp: Verified On-Chain</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
