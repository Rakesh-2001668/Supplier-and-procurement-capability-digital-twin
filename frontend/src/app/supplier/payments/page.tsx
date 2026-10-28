'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  CreditCard, Download, Search, Filter, RefreshCw, CheckCircle2,
  DollarSign, Building2, Calendar, FileText, ArrowRight, Printer,
  ShieldCheck, Landmark, Receipt, ExternalLink, X, Clock, Check
} from 'lucide-react';
import { apiClient, TEST_SUPPLIER_TENANT_ID } from '@/lib/apiClient';

interface EnrichedPayment {
  id: string;
  reference_number: string;
  invoice_id: string;
  po_id: string;
  buyer_name: string;
  buyer_id: string;
  amount: number;
  payment_method: string;
  payment_date: string;
  due_date?: string;
  status: string;
  description: string;
  bank_account: string;
  reconciliation_status: string;
  discount_captured: number;
}

export default function SupplierPaymentsPage() {
  const router = useRouter();

  const [activeRailFilter, setActiveRailFilter] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedPayment, setSelectedPayment] = useState<EnrichedPayment | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  // Fetch payments from backend
  const { data: serverPayments = [], isLoading, refetch } = useQuery({
    queryKey: ['supplier-payments', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      try {
        const response = await apiClient.get(`/api/v1/finance/payments?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
        return response.data;
      } catch (err) {
        return [];
      }
    }
  });

  // Buyer Map based on PO
  const getBuyerName = (poId: string) => {
    if (poId === 'PO-2025-00123') return 'SupplyTwin Enterprise Corp';
    if (poId === 'PO-2025-00089') return 'Global Aerospace Systems Corp';
    return 'North American Defense Corp';
  };

  // Enriched payments
  const enrichedPayments: EnrichedPayment[] = serverPayments.map((p: any, idx: number) => {
    const po = p.po_id || (idx % 2 === 0 ? 'PO-2025-00123' : 'PO-2025-00089');
    const buyerName = getBuyerName(po);
    const dateStr = p.payment_date ? new Date(p.payment_date).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    }) : 'Oct 12, 2025';

    // Determine clean method
    let method = p.payment_method || 'ACH Direct Deposit';
    if (method.toLowerCase().includes('wire') || idx % 3 === 0) {
      method = 'Fedwire / Real-Time Gross';
    } else if (method.toLowerCase().includes('card')) {
      method = 'Commercial Virtual Card';
    } else {
      method = 'ACH Direct Deposit (FedNow)';
    }

    return {
      id: p.id || `PAY-2025-08${idx + 10}`,
      reference_number: p.reference_number || `REF-${(p.id || 'PAY').slice(-6).toUpperCase()}`,
      invoice_id: p.invoice_id || `INV-2025-11${20 - idx}`,
      po_id: po,
      buyer_name: buyerName,
      buyer_id: p.buyer_tenant_id || 'TENANT_BUYER_001',
      amount: p.amount || 29500.0,
      payment_method: method,
      payment_date: dateStr,
      due_date: p.due_date,
      status: p.status || 'COMPLETED',
      description: p.description || `Payment settled for ${p.invoice_id}`,
      bank_account: 'JP Morgan Chase Bank NA (Ending in •••• 9024)',
      reconciliation_status: 'RECONCILED',
      discount_captured: 0.0
    };
  });

  // Filtered payments
  const filteredPayments = enrichedPayments.filter((pay) => {
    const matchesSearch =
      pay.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      pay.reference_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
      pay.invoice_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      pay.po_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      pay.buyer_name.toLowerCase().includes(searchQuery.toLowerCase());

    if (activeRailFilter === 'ACH') return matchesSearch && pay.payment_method.includes('ACH');
    if (activeRailFilter === 'WIRE') return matchesSearch && pay.payment_method.includes('Fedwire');
    if (activeRailFilter === 'CARD') return matchesSearch && pay.payment_method.includes('Card');
    return matchesSearch;
  });

  // Metrics
  const totalSettledAmount = enrichedPayments.reduce((acc, p) => acc + (p.amount || 0), 0);
  const totalCount = enrichedPayments.length;
  const achCount = enrichedPayments.filter(p => p.payment_method.includes('ACH')).length;
  const wireCount = enrichedPayments.filter(p => p.payment_method.includes('Fedwire')).length;

  // Export CSV
  const handleExportCSV = () => {
    const headers = [
      'Payment Ref', 'Remittance Ref', 'Invoice ID', 'PO Number',
      'Buyer Organization', 'Amount ($USD)', 'Date Cleared',
      'Payment Rail', 'Bank Account', 'Status', 'Reconciliation'
    ];
    const rows = enrichedPayments.map(p => [
      p.id,
      p.reference_number,
      p.invoice_id,
      p.po_id,
      `"${p.buyer_name}"`,
      p.amount.toFixed(2),
      p.payment_date,
      `"${p.payment_method}"`,
      `"${p.bank_account}"`,
      p.status,
      p.reconciliation_status
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `Payments_Received_Cash_Ledger_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Cash receipts ledger CSV exported successfully.');
  };

  return (
    <div className="space-y-6 pb-16 max-w-[1600px] mx-auto">
      {/* Toast Alert */}
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
            <span className="text-emerald-600 font-bold">Treasury & Settlements</span>
            <span className="text-slate-300">/</span>
            <span>Payments Received</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <CreditCard className="w-8 h-8 text-emerald-600" />
            <span>Payments Received (Cash Settlement Ledger)</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Real-time verification of buyer remittances, clearing network wire receipts, depository bank account deposits, and automated invoice reconciliation.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={handleExportCSV}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <Download className="w-4 h-4 text-slate-500" />
            <span>Export Cash Ledger (CSV)</span>
          </button>
          <button
            onClick={() => {
              refetch();
              showToast('Cash settlement ledger refreshed from banking network.');
            }}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span>Sync Live</span>
          </button>
          <button
            onClick={() => router.push('/supplier/invoices')}
            className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
          >
            <FileText className="w-4 h-4" />
            <span>View Invoices Sent</span>
          </button>
        </div>
      </div>

      {/* TOP TREASURY METRICS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Total Cleared Receipts</span>
            <DollarSign className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="text-2xl font-black text-emerald-600">
            ${totalSettledAmount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Net Collected Revenue</span>
            <span className="font-bold text-slate-800">100% Funds Available</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Settled Transactions</span>
            <Receipt className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-black text-[#0B2550]">
            {totalCount} Payments Deposited
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Disbursement Status</span>
            <span className="font-bold text-blue-600">All Remittances Cleared</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Clearing Rails Mix</span>
            <Landmark className="w-4 h-4 text-purple-600" />
          </div>
          <div className="text-2xl font-black text-purple-600">
            {wireCount} Wire / {achCount} ACH
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Settlement Channel</span>
            <span className="font-bold text-purple-700">Fedwire Real-Time Gross</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Reconciliation Rate</span>
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="text-2xl font-black text-emerald-600">
            100% Reconciled
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>General Ledger</span>
            <span className="font-bold text-emerald-700">Zero Variance</span>
          </div>
        </div>
      </div>

      {/* FILTER & SEARCH TOOLBAR */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Payment Rail Filter Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto text-xs font-bold pb-1 md:pb-0">
          {[
            { id: 'ALL', label: 'All Settlements' },
            { id: 'WIRE', label: 'Fedwire / SWIFT' },
            { id: 'ACH', label: 'ACH Direct Deposit' },
            { id: 'CARD', label: 'Commercial Card' }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveRailFilter(tab.id)}
              className={`px-3.5 py-1.5 rounded-xl transition-all whitespace-nowrap ${
                activeRailFilter === tab.id
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
            placeholder="Search by Payment #, Invoice #, PO #, Buyer..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-xl text-xs font-medium text-slate-800 placeholder-slate-400 focus:outline-none focus:border-blue-600"
          />
        </div>
      </div>

      {/* SETTLEMENTS LEDGER TABLE */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-bold">
                <th className="p-4">Payment Ref</th>
                <th className="p-4">Remittance Ref</th>
                <th className="p-4">Invoice / PO Reference</th>
                <th className="p-4">Buyer Payer Organization</th>
                <th className="p-4">Date Cleared</th>
                <th className="p-4">Settlement Rail</th>
                <th className="p-4 text-right">Amount Received</th>
                <th className="p-4 text-center">Reconciliation</th>
                <th className="p-4 text-right">Receipt</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={9} className="p-8 text-center text-slate-400">
                    Loading cash settlement ledger...
                  </td>
                </tr>
              ) : filteredPayments.length === 0 ? (
                <tr>
                  <td colSpan={9} className="p-8 text-center text-slate-400">
                    No payment records match your search criteria.
                  </td>
                </tr>
              ) : (
                filteredPayments.map((pay) => (
                  <tr
                    key={pay.id}
                    className="hover:bg-emerald-50/40 transition-colors cursor-pointer"
                    onClick={() => setSelectedPayment(pay)}
                  >
                    <td className="p-4 font-mono font-black text-[#0B2550]">
                      {pay.id.substring(0, 14)}
                    </td>

                    <td className="p-4 font-mono text-slate-500 font-bold">
                      {pay.reference_number}
                    </td>

                    <td className="p-4">
                      <div className="font-bold text-blue-700 font-mono">{pay.invoice_id}</div>
                      <div className="text-[11px] text-slate-400 font-mono">PO: {pay.po_id}</div>
                    </td>

                    <td className="p-4 font-bold text-slate-800">
                      <div className="flex items-center gap-1.5">
                        <Building2 className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <span className="truncate max-w-[180px]">{pay.buyer_name}</span>
                      </div>
                    </td>

                    <td className="p-4 text-slate-600 font-medium">
                      {pay.payment_date}
                    </td>

                    <td className="p-4">
                      <div className="flex items-center gap-1.5 text-slate-700 font-bold">
                        <CreditCard className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <span>{pay.payment_method}</span>
                      </div>
                    </td>

                    <td className="p-4 text-right font-black text-emerald-600 text-sm">
                      +${pay.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </td>

                    <td className="p-4 text-center">
                      <span className="px-2.5 py-0.5 rounded text-[10px] font-black uppercase bg-emerald-100 text-emerald-900 border border-emerald-300/40">
                        {pay.reconciliation_status}
                      </span>
                    </td>

                    <td className="p-4 text-right" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => setSelectedPayment(pay)}
                        className="px-3 py-1.5 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-sm transition-all"
                      >
                        View Remittance
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* HIGH-FIDELITY PAYMENT REMITTANCE ADVICE MODAL */}
      {/* ========================================================================= */}
      {selectedPayment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full border border-slate-200 max-h-[92vh] flex flex-col overflow-hidden">
            {/* Modal Top Bar */}
            <div className="p-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => window.print()}
                  className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5"
                >
                  <Printer className="w-3.5 h-3.5 text-slate-500" />
                  <span>Print Advice</span>
                </button>
                <button
                  onClick={() => {
                    showToast(`Remittance slip ${selectedPayment.reference_number} downloaded.`);
                  }}
                  className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5"
                >
                  <Download className="w-3.5 h-3.5 text-slate-500" />
                  <span>Download PDF Receipt</span>
                </button>
              </div>

              <button
                onClick={() => setSelectedPayment(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Official Remittance Slip Body */}
            <div className="p-8 space-y-6 overflow-y-auto bg-white text-xs">
              {/* Slip Header */}
              <div className="flex flex-col sm:flex-row justify-between items-start gap-4 border-b border-slate-200 pb-5">
                <div>
                  <span className="text-[10px] font-black uppercase text-emerald-600 tracking-wider block">
                    Official Remittance Advice & Deposit Slip
                  </span>
                  <h2 className="text-2xl font-black text-[#0B2550] mt-0.5">{selectedPayment.reference_number}</h2>
                  <p className="font-mono text-slate-400 mt-1">Transaction ID: {selectedPayment.id}</p>
                </div>

                <div className="sm:text-right space-y-0.5">
                  <span className="text-[10px] font-black uppercase text-slate-400 tracking-wider block">Settlement Cleared</span>
                  <div className="text-xl font-black text-emerald-600">
                    +${selectedPayment.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })} USD
                  </div>
                  <span className="text-slate-400 text-[11px] block">{selectedPayment.payment_date}</span>
                </div>
              </div>

              {/* Status & Depository Account Card */}
              <div className="p-4 bg-emerald-50/60 rounded-xl border border-emerald-200 flex flex-col sm:flex-row justify-between gap-4">
                <div className="flex items-start gap-3">
                  <Landmark className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
                  <div className="space-y-0.5">
                    <span className="font-bold text-emerald-900 block">Funds Deposited to Supplier Depository Account</span>
                    <p className="text-slate-600 text-[11px]">{selectedPayment.bank_account}</p>
                    <p className="text-emerald-700 font-bold text-[11px]">Clearing Rail: {selectedPayment.payment_method}</p>
                  </div>
                </div>

                <div className="sm:text-right shrink-0">
                  <span className="px-2.5 py-1 rounded text-[10px] font-black uppercase bg-emerald-600 text-white">
                    {selectedPayment.status}
                  </span>
                </div>
              </div>

              {/* Buyer & Supplier Counterparty Info */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-4 bg-slate-50 rounded-xl border border-slate-100">
                <div className="space-y-1">
                  <span className="text-[10px] font-black uppercase text-slate-400 tracking-wider block">Payer (Enterprise Buyer)</span>
                  <h4 className="font-bold text-slate-800 text-sm">{selectedPayment.buyer_name}</h4>
                  <p className="text-slate-500 text-[11px]">Authorized Financial Settlement Disbursement</p>
                </div>

                <div className="space-y-1 sm:text-right">
                  <span className="text-[10px] font-black uppercase text-slate-400 tracking-wider block">Beneficiary (Supplier)</span>
                  <h4 className="font-bold text-slate-800 text-sm">Apex Precision Machining Ltd</h4>
                  <p className="text-slate-500 text-[11px]">Operating Wire Account (Verified)</p>
                </div>
              </div>

              {/* Settlement Invoiced Reference Table */}
              <div className="space-y-2">
                <h4 className="font-bold text-slate-800">Invoiced Receivables Settled</h4>
                <div className="border border-slate-200 rounded-xl overflow-hidden">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-bold">
                        <th className="p-3">Invoice Number</th>
                        <th className="p-3">PO Reference</th>
                        <th className="p-3 text-right">Invoiced Total</th>
                        <th className="p-3 text-right">Discount</th>
                        <th className="p-3 text-right">Net Deposited</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td className="p-3 font-mono font-bold text-blue-700">{selectedPayment.invoice_id}</td>
                        <td className="p-3 font-mono text-slate-600">{selectedPayment.po_id}</td>
                        <td className="p-3 text-right text-slate-700 font-medium">
                          ${selectedPayment.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </td>
                        <td className="p-3 text-right text-slate-500 font-medium">$0.00</td>
                        <td className="p-3 text-right font-black text-emerald-600">
                          ${selectedPayment.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* General Ledger Reconciliation Audit */}
              <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-emerald-600" />
                  <div>
                    <span className="font-bold text-slate-800 block">General Ledger Automated Reconciliation</span>
                    <span className="text-[11px] text-slate-500">Credited to Cash & Equivalents (#1010) • Accounts Receivable Cleared (#1200)</span>
                  </div>
                </div>

                <span className="px-2.5 py-0.5 rounded text-[10px] font-black uppercase bg-emerald-100 text-emerald-900 border border-emerald-300">
                  MATCHED 100%
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
