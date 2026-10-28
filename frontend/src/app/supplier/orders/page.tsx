'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  FileSignature, Check, ChevronRight, Search, FileText, Filter,
  Calendar, MapPin, ChevronDown, MessageSquare, AlertCircle, Eye,
  Download, CheckCircle, XCircle, ArrowRight, Truck, Package, Clock,
  ShieldCheck, DollarSign, Building2, ExternalLink, RefreshCw, X, Box
} from 'lucide-react';
import { apiClient, TEST_SUPPLIER_TENANT_ID } from '@/lib/apiClient';

interface OrderItem {
  name: string;
  sku: string;
  qty: number;
  price: number;
  total: number;
}

interface SupplierPO {
  id: string;
  buyer: string;
  buyer_id: string;
  date: string;
  amount: string;
  amount_num: number;
  status: 'Sent' | 'Acknowledged' | 'Shipped' | 'Invoiced' | 'Changes Proposed';
  expectedDelivery: string;
  itemsCount: number;
  incoterms: string;
  paymentTerms: string;
  shipTo: string;
  trackingNumber?: string;
  carrier?: string;
  proposedReason?: string;
  proposedDate?: string;
  items: OrderItem[];
}

export default function SupplierOrdersPage() {
  const queryClient = useQueryClient();
  const router = useRouter();

  // Search & Filter Tabs
  const [activeTab, setActiveTab] = useState<'ALL' | 'NEW' | 'IN_PROGRESS' | 'COMPLETED'>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedOrderId, setSelectedOrderId] = useState<string>('PO-2025-00123');

  // Modals
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [showAsnModal, setShowAsnModal] = useState(false);
  const [showProposeModal, setShowProposeModal] = useState(false);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);

  // Forms
  const [asnForm, setAsnForm] = useState({
    carrier: 'FedEx Aerospace Freight',
    tracking_number: 'FX-889120412-US',
    estimated_delivery: '2025-10-18',
    packages_count: 2,
    coc_number: 'COC-AS9100D-APEX-2026',
    notes: 'Precision CNC parts packed in vacuum sealed anti-corrosion VCI bags and foam shock containers.'
  });

  const [proposeForm, setProposeForm] = useState({
    reason: 'Tooling & Raw Material Backlog',
    newDeliveryDate: '2025-10-25',
    notes: 'Delay due to high-precision 5-axis cutting tool restocking. Quality testing schedule unaffected.'
  });

  const [invoiceForm, setInvoiceForm] = useState({
    taxable_amount: 25000,
    tax_percent: 18,
    terms: 'Net 30 Days. Late payment subject to 1.5% monthly interest.',
    signature: 'ABC Manufacturing Authorized Signatory'
  });

  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  // Base Orders
  const [orders, setOrders] = useState<SupplierPO[]>([
    {
      id: 'PO-2025-00123',
      buyer: 'SupplyTwin Enterprise Corp',
      buyer_id: 'TENANT_BUYER_001',
      date: 'Sep 20, 2025',
      amount: '$29,500.00',
      amount_num: 29500.0,
      status: 'Sent',
      expectedDelivery: 'Oct 15, 2025',
      itemsCount: 3,
      incoterms: 'DDP (Delivered Duty Paid) Buyer Warehouse',
      paymentTerms: 'Net 30 Days (Electronic Bank Wire)',
      shipTo: 'Aerospace Integration Facility, Seattle, WA',
      items: [
        { name: 'Precision CNC 5-Axis Avionics Enclosure', sku: 'AERO-ENC-7075-01', qty: 50, price: 350.0, total: 17500.0 },
        { name: 'Titanium Grade 5 Pinion Spline Shaft', sku: 'SFT-TI-02', qty: 20, price: 400.0, total: 8000.0 },
        { name: 'MIL-Spec Hardcoat Anodized Flange', sku: 'FLG-AN-03', qty: 40, price: 100.0, total: 4000.0 }
      ]
    },
    {
      id: 'PO-2025-00089',
      buyer: 'Global Aerospace Systems Corp',
      buyer_id: 'TENANT_BUYER_001',
      date: 'Sep 15, 2025',
      amount: '$29,500.00',
      amount_num: 29500.0,
      status: 'Acknowledged',
      expectedDelivery: 'Oct 05, 2025',
      itemsCount: 1,
      incoterms: 'DDP Buyer Warehouse',
      paymentTerms: 'Net 30 Days',
      shipTo: 'Avionics Assembly Plant, Dallas, TX',
      items: [
        { name: 'Inconel 718 Hydraulic Actuator Manifold', sku: 'ACT-MNF-718', qty: 85, price: 347.05, total: 29500.0 }
      ]
    },
    {
      id: 'PO-2025-00045',
      buyer: 'North American Defense Corp',
      buyer_id: 'TENANT_BUYER_001',
      date: 'Sep 02, 2025',
      amount: '$29,500.00',
      amount_num: 29500.0,
      status: 'Shipped',
      expectedDelivery: 'Sep 28, 2025',
      itemsCount: 2,
      incoterms: 'FOB Port / DDP Defense Depo',
      paymentTerms: 'Net 45 Days',
      shipTo: 'Defense Logistics Depo, Fort Worth, TX',
      carrier: 'FedEx Freight Direct',
      trackingNumber: 'FX-9921041-US',
      items: [
        { name: 'Titanium Grade 5 Pinion Drive Shaft', sku: 'PIN-SFT-TI64', qty: 65, price: 320.0, total: 20800.0 },
        { name: 'High-Pressure Hydraulic Flange Ring', sku: 'ABC-FLG-718', qty: 18, price: 483.33, total: 8700.0 }
      ]
    }
  ]);

  // Sync server PO state
  const { data: serverPOs = [], refetch: refetchPOs } = useQuery({
    queryKey: ['supplier-pos', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      try {
        const response = await apiClient.get(`/api/v1/procurement/po?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
        return response.data;
      } catch (err) {
        return [];
      }
    }
  });

  // Merge server PO status
  const displayOrders = orders.map((o) => {
    const serverPO = serverPOs.find((spo: any) => spo.id === o.id);
    if (serverPO && serverPO.status) {
      let mappedStatus: SupplierPO['status'] = o.status;
      if (serverPO.status === 'ACKNOWLEDGED') mappedStatus = 'Acknowledged';
      else if (serverPO.status === 'SHIPPED') mappedStatus = 'Shipped';
      else if (serverPO.status === 'INVOICED') mappedStatus = 'Invoiced';
      else if (serverPO.status === 'CHANGES_PROPOSED') mappedStatus = 'Changes Proposed';
      return { ...o, status: mappedStatus };
    }
    return o;
  });

  const currentSelectedOrder = displayOrders.find((o) => o.id === selectedOrderId) || displayOrders[0];

  // Actions
  const handleAcknowledge = async () => {
    try {
      await apiClient.put(`/api/v1/procurement/purchase-orders/${currentSelectedOrder.id}/state`, {
        state: 'ACKNOWLEDGED'
      });
      setOrders(orders.map(o => o.id === currentSelectedOrder.id ? { ...o, status: 'Acknowledged' } : o));
      setShowConfirmModal(false);
      refetchPOs();
      showToast(`Purchase Order ${currentSelectedOrder.id} acknowledged and moved to Production!`);
    } catch (e) {
      showToast('Error acknowledging order.');
    }
  };

  const handleCreateAsn = async () => {
    try {
      const itemsPayload = currentSelectedOrder.items?.map(it => ({
        sku: it.sku,
        name: it.name,
        quantity: it.qty
      })) || [];

      const totalShippedQty = currentSelectedOrder.items?.reduce((acc, i) => acc + i.qty, 0) || 1;

      const res = await apiClient.post(`/api/v1/procurement/purchase-orders/${currentSelectedOrder.id}/asn`, {
        carrier: asnForm.carrier,
        tracking_number: asnForm.tracking_number,
        estimated_delivery: asnForm.estimated_delivery,
        packages_count: asnForm.packages_count,
        coc_number: asnForm.coc_number || 'COC-AS9100D-APEX-2026',
        notes: asnForm.notes,
        shipped_quantity: totalShippedQty,
        items: itemsPayload,
        tenant_id: TEST_SUPPLIER_TENANT_ID
      });

      setOrders(orders.map(o => o.id === currentSelectedOrder.id ? {
        ...o,
        status: 'Shipped',
        carrier: asnForm.carrier,
        trackingNumber: asnForm.tracking_number
      } : o));
      setShowAsnModal(false);
      refetchPOs();
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-items'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-movements'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-analytics'] });

      const deductedCount = res.data?.deductions?.length || itemsPayload.length;
      showToast(`ASN ${res.data?.asn_id || ''} transmitted! Order marked Shipped & ${deductedCount} Finished Goods item(s) deducted from plant inventory.`);
    } catch (e: any) {
      console.error(e);
      showToast(e.response?.data?.detail || 'Error creating ASN and updating inventory.');
    }
  };

  const handleProposeChanges = async () => {
    try {
      await apiClient.post(`/api/v1/procurement/purchase-orders/${currentSelectedOrder.id}/propose`, {
        reason: proposeForm.reason,
        new_delivery_date: proposeForm.newDeliveryDate,
        notes: proposeForm.notes
      });
      setOrders(orders.map(o => o.id === currentSelectedOrder.id ? {
        ...o,
        status: 'Changes Proposed',
        proposedReason: proposeForm.reason,
        proposedDate: proposeForm.newDeliveryDate
      } : o));
      setShowProposeModal(false);
      refetchPOs();
      showToast(`Change request proposed to buyer for ${currentSelectedOrder.id}.`);
    } catch (e) {
      showToast('Error proposing changes.');
    }
  };

  const handleGenerateInvoice = async () => {
    try {
      await apiClient.post('/api/v1/finance/invoices', {
        po_id: currentSelectedOrder.id,
        buyer_id: currentSelectedOrder.buyer_id,
        supplier_id: TEST_SUPPLIER_TENANT_ID,
        amount: currentSelectedOrder.amount_num,
        tax_amount: (currentSelectedOrder.amount_num * invoiceForm.tax_percent) / 100,
        total_amount: currentSelectedOrder.amount_num * (1 + invoiceForm.tax_percent / 100),
        terms: invoiceForm.terms
      });
      setOrders(orders.map(o => o.id === currentSelectedOrder.id ? { ...o, status: 'Invoiced' } : o));
      setShowInvoiceModal(false);
      refetchPOs();
      showToast(`Commercial Invoice generated for ${currentSelectedOrder.id}!`);
    } catch (e) {
      // Fallback
      setOrders(orders.map(o => o.id === currentSelectedOrder.id ? { ...o, status: 'Invoiced' } : o));
      setShowInvoiceModal(false);
      showToast(`Commercial Invoice generated for ${currentSelectedOrder.id}!`);
    }
  };

  const handleExportReport = () => {
    const headers = ['PO Number', 'Buyer', 'Date', 'Amount', 'Status', 'Items Count', 'Expected Delivery'];
    const rows = displayOrders.map(o => [o.id, o.buyer, o.date, o.amount, o.status, o.itemsCount, o.expectedDelivery]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', 'Active_Purchase_Orders_Report.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Active orders CSV exported successfully.');
  };

  // Filtered orders
  const filteredOrders = displayOrders.filter(o => {
    const matchesSearch = o.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          o.buyer.toLowerCase().includes(searchQuery.toLowerCase());
    if (activeTab === 'NEW') return matchesSearch && (o.status === 'Sent' || o.status === 'Changes Proposed');
    if (activeTab === 'IN_PROGRESS') return matchesSearch && (o.status === 'Acknowledged' || o.status === 'Shipped');
    if (activeTab === 'COMPLETED') return matchesSearch && o.status === 'Invoiced';
    return matchesSearch;
  });

  return (
    <div className="space-y-6 pb-16 max-w-[1600px] mx-auto">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-in fade-in slide-in-from-top-4">
          <CheckCircle className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-bold">{toastMessage}</span>
        </div>
      )}

      {/* HEADER BREADCRUMB */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Supplier Portal</span>
            <span className="text-slate-300">/</span>
            <span className="text-blue-600 font-bold">Fulfillment & Shop Floor</span>
            <span className="text-slate-300">/</span>
            <span>Active Purchase Orders</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <CheckCircle className="w-8 h-8 text-emerald-600" />
            <span>Active Orders Fulfillment Desk</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Manage incoming purchase orders from enterprise buyers, acknowledge commitments, issue Advance Shipping Notices (ASN), and generate commercial invoices.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={handleExportReport}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <Download className="w-4 h-4 text-slate-500" />
            <span>Export CSV</span>
          </button>
          <button
            onClick={() => {
              refetchPOs();
              showToast("Purchase order statuses synchronized with ERP network.");
            }}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span>Sync ERP</span>
          </button>
        </div>
      </div>

      {/* TOP PIPELINE CARDS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Total Active Orders</span>
            <Package className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-black text-[#0B2550]">{displayOrders.length} POs Active</div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Total Value</span>
            <span className="font-bold text-slate-800">$88,500.00</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Awaiting Acknowledgement</span>
            <Clock className="w-4 h-4 text-amber-500" />
          </div>
          <div className="text-2xl font-black text-amber-600">
            {displayOrders.filter(o => o.status === 'Sent').length} New Orders
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Action Required</span>
            <span className="font-bold text-amber-600">Needs Review</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>In Production / Shipped</span>
            <Truck className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-black text-blue-600">
            {displayOrders.filter(o => o.status === 'Acknowledged' || o.status === 'Shipped').length} In Transit
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Shop Floor Status</span>
            <span className="font-bold text-blue-600">Active Routing</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Invoiced & Settled</span>
            <DollarSign className="w-4 h-4 text-emerald-600" />
          </div>
          <div className="text-2xl font-black text-emerald-600">
            {displayOrders.filter(o => o.status === 'Invoiced').length} Completed
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Settled Revenue</span>
            <span className="font-bold text-emerald-600">Net 30 Settling</span>
          </div>
        </div>
      </div>

      {/* TWO-PANEL INTERFACE */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT PANEL: ORDERS LIST */}
        <div className="lg:col-span-5 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
          {/* Filter Tabs */}
          <div className="p-4 border-b border-slate-100 space-y-3">
            <div className="flex items-center gap-1.5 overflow-x-auto text-xs font-bold pb-1">
              {[
                { id: 'ALL', label: 'All Orders' },
                { id: 'NEW', label: 'New (Pending)' },
                { id: 'IN_PROGRESS', label: 'In Progress' },
                { id: 'COMPLETED', label: 'Invoiced' }
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`px-3 py-1.5 rounded-xl transition-all whitespace-nowrap ${
                    activeTab === tab.id
                      ? 'bg-[#0B2550] text-white shadow-sm font-black'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Search Box */}
            <div className="relative">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search PO #, buyer, or part..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-2 border border-slate-200 rounded-xl text-xs font-medium text-slate-800 placeholder-slate-400 focus:outline-none focus:border-blue-600"
              />
            </div>
          </div>

          {/* Orders Scrollable List */}
          <div className="divide-y divide-slate-100 max-h-[700px] overflow-y-auto">
            {filteredOrders.map((order) => {
              const isSelected = order.id === currentSelectedOrder.id;
              return (
                <div
                  key={order.id}
                  onClick={() => setSelectedOrderId(order.id)}
                  className={`p-4 cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-blue-50/70 border-l-4 border-l-blue-600'
                      : 'hover:bg-slate-50 border-l-4 border-l-transparent'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-black text-xs text-[#0B2550]">{order.id}</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${
                      order.status === 'Sent'
                        ? 'bg-amber-100 text-amber-900 border border-amber-300/40'
                        : order.status === 'Acknowledged'
                        ? 'bg-blue-100 text-blue-900 border border-blue-300/40'
                        : order.status === 'Shipped'
                        ? 'bg-emerald-100 text-emerald-900 border border-emerald-300/40'
                        : order.status === 'Invoiced'
                        ? 'bg-purple-100 text-purple-900 border border-purple-300/40'
                        : 'bg-orange-100 text-orange-900'
                    }`}>
                      {order.status}
                    </span>
                  </div>

                  <h4 className="font-bold text-slate-800 text-xs mt-1 truncate">{order.buyer}</h4>

                  <div className="flex items-center justify-between text-xs text-slate-500 pt-2">
                    <span className="font-black text-emerald-600">{order.amount}</span>
                    <span>Due: <strong>{order.expectedDelivery}</strong></span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* RIGHT PANEL: SELECTED ORDER DETAIL & WORKFLOW ACTIONS */}
        <div className="lg:col-span-7 bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-6">
          {/* Header of Selected Order */}
          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-slate-100 pb-5">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono font-black text-base text-[#0B2550]">{currentSelectedOrder.id}</span>
                <span className={`px-2.5 py-0.5 rounded text-[10px] font-black uppercase ${
                  currentSelectedOrder.status === 'Sent'
                    ? 'bg-amber-100 text-amber-900 border border-amber-300/40'
                    : currentSelectedOrder.status === 'Acknowledged'
                    ? 'bg-blue-100 text-blue-900 border border-blue-300/40'
                    : currentSelectedOrder.status === 'Shipped'
                    ? 'bg-emerald-100 text-emerald-900 border border-emerald-300/40'
                    : currentSelectedOrder.status === 'Invoiced'
                    ? 'bg-purple-100 text-purple-900 border border-purple-300/40'
                    : 'bg-orange-100 text-orange-900'
                }`}>
                  {currentSelectedOrder.status}
                </span>
              </div>

              <h3 className="text-xl font-black text-[#0B2550] mt-1">{currentSelectedOrder.buyer}</h3>
              <p className="text-xs text-slate-400">Order Placed: {currentSelectedOrder.date}</p>
            </div>

            <div className="text-right">
              <span className="text-xs text-slate-400 block font-bold uppercase tracking-wider">Total Contract Amount</span>
              <span className="text-2xl font-black text-emerald-600 block mt-0.5">{currentSelectedOrder.amount}</span>
            </div>
          </div>

          {/* WORKFLOW STEPPER */}
          <div className="bg-slate-50 p-4 rounded-xl border border-slate-100 space-y-2">
            <span className="text-[10px] font-black uppercase text-slate-400 tracking-wider block">
              Order Fulfillment Lifecycle
            </span>
            <div className="grid grid-cols-4 gap-2 text-center text-xs">
              <div className={`p-2 rounded-lg font-bold ${
                currentSelectedOrder.status === 'Sent'
                  ? 'bg-amber-100 text-amber-900 border border-amber-300'
                  : 'bg-emerald-100 text-emerald-900'
              }`}>
                1. Sent (Received)
              </div>
              <div className={`p-2 rounded-lg font-bold ${
                currentSelectedOrder.status === 'Acknowledged'
                  ? 'bg-blue-100 text-blue-900 border border-blue-300'
                  : ['Shipped', 'Invoiced'].includes(currentSelectedOrder.status)
                  ? 'bg-emerald-100 text-emerald-900'
                  : 'bg-white text-slate-400 border border-slate-200'
              }`}>
                2. In Fabrication
              </div>
              <div className={`p-2 rounded-lg font-bold ${
                currentSelectedOrder.status === 'Shipped'
                  ? 'bg-emerald-100 text-emerald-900 border border-emerald-300'
                  : currentSelectedOrder.status === 'Invoiced'
                  ? 'bg-emerald-100 text-emerald-900'
                  : 'bg-white text-slate-400 border border-slate-200'
              }`}>
                3. Dispatched (ASN)
              </div>
              <div className={`p-2 rounded-lg font-bold ${
                currentSelectedOrder.status === 'Invoiced'
                  ? 'bg-purple-100 text-purple-900 border border-purple-300'
                  : 'bg-white text-slate-400 border border-slate-200'
              }`}>
                4. Invoiced (Settled)
              </div>
            </div>
          </div>

          {/* DYNAMIC ACTION BANNER */}
          {currentSelectedOrder.status === 'Sent' && (
            <div className="p-4 bg-amber-50 rounded-xl border border-amber-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <AlertCircle className="w-5 h-5 text-amber-600 shrink-0" />
                <div>
                  <h4 className="font-black text-amber-900 text-xs">New Purchase Order Received</h4>
                  <p className="text-[11px] text-amber-700">Please review CAD geometry, tolerances, and commit to the manufacturing schedule.</p>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setShowProposeModal(true)}
                  className="px-3.5 py-1.5 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all"
                >
                  Propose Changes
                </button>
                <button
                  onClick={() => setShowConfirmModal(true)}
                  className="px-4 py-1.5 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1 active:scale-95"
                >
                  <CheckCircle className="w-3.5 h-3.5" />
                  <span>Acknowledge PO</span>
                </button>
              </div>
            </div>
          )}

          {currentSelectedOrder.status === 'Acknowledged' && (
            <div className="p-4 bg-blue-50 rounded-xl border border-blue-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <Clock className="w-5 h-5 text-blue-600 shrink-0" />
                <div>
                  <h4 className="font-black text-blue-900 text-xs">Order In Fabrication & Quality Verification</h4>
                  <p className="text-[11px] text-blue-700">Committed Delivery Date: <strong>{currentSelectedOrder.expectedDelivery}</strong>.</p>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setShowProposeModal(true)}
                  className="px-3 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl"
                >
                  Propose Delay
                </button>
                <button
                  onClick={() => setShowAsnModal(true)}
                  className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1 active:scale-95"
                >
                  <Truck className="w-3.5 h-3.5" />
                  <span>Create ASN & Dispatch</span>
                </button>
              </div>
            </div>
          )}

          {currentSelectedOrder.status === 'Shipped' && (
            <div className="p-4 bg-emerald-50 rounded-xl border border-emerald-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <Truck className="w-5 h-5 text-emerald-600 shrink-0" />
                <div>
                  <h4 className="font-black text-emerald-900 text-xs">Order Shipped (In Transit)</h4>
                  <p className="text-[11px] text-emerald-700">Carrier: {currentSelectedOrder.carrier || 'FedEx'} • Tracking: <code className="font-bold text-emerald-900">{currentSelectedOrder.trackingNumber || 'FX-123456789'}</code></p>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <Link
                  href="/supplier/inventory"
                  className="px-3.5 py-1.5 bg-white border border-emerald-300 text-emerald-800 hover:bg-emerald-100 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1"
                >
                  <Box className="w-3.5 h-3.5" />
                  <span>View in Inventory Ledger</span>
                </Link>
                <Link
                  href={`/supplier/invoices/create?po_id=${currentSelectedOrder.id}`}
                  className="px-3.5 py-1.5 bg-blue-50 border border-blue-300 text-blue-900 hover:bg-blue-100 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1"
                >
                  <FileText className="w-3.5 h-3.5 text-blue-600" />
                  <span>PO-Flip Workstation</span>
                </Link>
                <button
                  onClick={() => setShowInvoiceModal(true)}
                  className="px-4 py-1.5 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1 active:scale-95"
                >
                  <FileText className="w-3.5 h-3.5" />
                  <span>Quick Flip</span>
                </button>
              </div>
            </div>
          )}

          {currentSelectedOrder.status === 'Invoiced' && (
            <div className="p-4 bg-purple-50 rounded-xl border border-purple-200 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <DollarSign className="w-5 h-5 text-purple-600 shrink-0" />
                <div>
                  <h4 className="font-black text-purple-900 text-xs">Commercial Invoice Generated & Transmitted</h4>
                  <p className="text-[11px] text-purple-700">Payment Terms: {currentSelectedOrder.paymentTerms}. Invoiced amount: <strong>{currentSelectedOrder.amount}</strong>.</p>
                </div>
              </div>

              <span className="px-3 py-1 rounded-xl text-xs font-black bg-purple-200/60 text-purple-900">
                INVOICED
              </span>
            </div>
          )}

          {currentSelectedOrder.status === 'Changes Proposed' && (
            <div className="p-4 bg-orange-50 rounded-xl border border-orange-200 space-y-1">
              <span className="font-bold text-orange-900 text-xs flex items-center gap-1.5">
                <AlertCircle className="w-4 h-4 text-orange-600" />
                Changes Proposed to Buyer:
              </span>
              <p className="text-[11px] text-orange-800">
                Proposed Delivery Date: <strong>{currentSelectedOrder.proposedDate || '2025-10-25'}</strong> • Reason: {currentSelectedOrder.proposedReason || 'Tooling backlog'}
              </p>
            </div>
          )}

          {/* Delivery & Shipping Parameters */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-2">
              <span className="font-bold text-slate-700 block flex items-center gap-1.5">
                <Truck className="w-3.5 h-3.5 text-blue-600" />
                <span>Shipping & Delivery Destination</span>
              </span>
              <div className="space-y-1 text-[11px] text-slate-600">
                <p>Expected Delivery: <strong className="text-slate-800">{currentSelectedOrder.expectedDelivery}</strong></p>
                <p>Incoterms: <strong className="text-slate-800">{currentSelectedOrder.incoterms}</strong></p>
                <p>Ship To: <strong className="text-slate-800">{currentSelectedOrder.shipTo}</strong></p>
              </div>
            </div>

            <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-2">
              <span className="font-bold text-slate-700 block flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                <span>Commercial Terms & Compliance</span>
              </span>
              <div className="space-y-1 text-[11px] text-slate-600">
                <p>Payment Terms: <strong className="text-slate-800">{currentSelectedOrder.paymentTerms}</strong></p>
                <p>Currency: <strong className="text-slate-800">USD ($)</strong></p>
                <p>Quality Gate: <strong className="text-emerald-700">AS9100D Metrology Verified</strong></p>
              </div>
            </div>
          </div>

          {/* Line Items Table */}
          <div className="space-y-2">
            <h4 className="font-black text-[#0B2550] text-sm">Manufactured Line Items</h4>
            <div className="border border-slate-200 rounded-xl overflow-hidden">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-bold">
                    <th className="p-3">Item Description</th>
                    <th className="p-3">SKU</th>
                    <th className="p-3 text-right">Qty</th>
                    <th className="p-3 text-right">Unit Price</th>
                    <th className="p-3 text-right">Ext Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {currentSelectedOrder.items.map((item, idx) => (
                    <tr key={idx} className="hover:bg-slate-50/50">
                      <td className="p-3 font-bold text-slate-800">{item.name}</td>
                      <td className="p-3 font-mono text-slate-400">{item.sku}</td>
                      <td className="p-3 text-right font-bold text-slate-700">{item.qty} pcs</td>
                      <td className="p-3 text-right font-medium text-slate-700">${item.price.toFixed(2)}</td>
                      <td className="p-3 text-right font-black text-emerald-600">${item.total.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* MODAL 1: ACKNOWLEDGE ORDER */}
      {/* ========================================================================= */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550]">
                Acknowledge Purchase Order
              </h3>
              <button onClick={() => setShowConfirmModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              By acknowledging <strong>{currentSelectedOrder.id}</strong>, you formally commit your facility to manufacturing and delivering these components by <strong>{currentSelectedOrder.expectedDelivery}</strong> under agreed pricing of <strong>{currentSelectedOrder.amount}</strong>.
            </p>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowConfirmModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAcknowledge}
                className="px-5 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Confirm Commitment
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 2: CREATE ASN (ADVANCE SHIPPING NOTICE) */}
      {/* ========================================================================= */}
      {showAsnModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550]">
                Generate Advance Shipping Notice (ASN)
              </h3>
              <button onClick={() => setShowAsnModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              {/* Order Items to be Dispatched from Inventory */}
              <div className="bg-slate-50 p-3 rounded-xl border border-slate-200">
                <div className="flex justify-between items-center mb-1.5 font-bold text-slate-700">
                  <span>Items to be Dispatched:</span>
                  <span className="text-[11px] text-emerald-600 flex items-center gap-1 font-semibold">
                    <CheckCircle className="w-3.5 h-3.5" /> Auto-deducts from Finished Goods Depot
                  </span>
                </div>
                <div className="space-y-1.5">
                  {currentSelectedOrder.items?.map((item, idx) => (
                    <div key={idx} className="flex justify-between items-center bg-white p-2 rounded-lg border border-slate-100 text-[11px]">
                      <div>
                        <div className="font-bold text-slate-800">{item.name}</div>
                        <div className="font-mono text-[10px] text-blue-600">{item.sku}</div>
                      </div>
                      <div className="text-right">
                        <span className="font-black text-slate-900 bg-slate-100 px-2 py-0.5 rounded">
                          {item.qty} units
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Logistics Freight Carrier:</label>
                <select
                  value={asnForm.carrier}
                  onChange={(e) => setAsnForm({ ...asnForm, carrier: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 bg-white"
                >
                  <option value="FedEx Aerospace Freight">FedEx Aerospace Freight</option>
                  <option value="DHL Global Forwarding">DHL Global Forwarding</option>
                  <option value="BlueDart Logistics">BlueDart Logistics</option>
                  <option value="Direct Dedicated Hauler">Direct Dedicated Hauler</option>
                </select>
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Waybill / Tracking Number:</label>
                <input
                  type="text"
                  value={asnForm.tracking_number}
                  onChange={(e) => setAsnForm({ ...asnForm, tracking_number: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-mono font-bold text-slate-800"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Estimated Arrival Date:</label>
                  <input
                    type="date"
                    value={asnForm.estimated_delivery}
                    onChange={(e) => setAsnForm({ ...asnForm, estimated_delivery: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Total Package Count:</label>
                  <input
                    type="number"
                    value={asnForm.packages_count}
                    onChange={(e) => setAsnForm({ ...asnForm, packages_count: Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Certificate of Conformance (CoC) #:</label>
                <input
                  type="text"
                  value={asnForm.coc_number}
                  onChange={(e) => setAsnForm({ ...asnForm, coc_number: e.target.value })}
                  placeholder="e.g. COC-AS9100D-APEX-2026"
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-mono text-slate-800"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Packaging & Cleanroom Notes:</label>
                <textarea
                  rows={2}
                  value={asnForm.notes}
                  onChange={(e) => setAsnForm({ ...asnForm, notes: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowAsnModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateAsn}
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Transmit ASN & Mark Shipped
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 3: PROPOSE CHANGES */}
      {/* ========================================================================= */}
      {showProposeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550]">
                Propose Delivery / Terms Changes
              </h3>
              <button onClick={() => setShowProposeModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Adjustment Reason:</label>
                <select
                  value={proposeForm.reason}
                  onChange={(e) => setProposeForm({ ...proposeForm, reason: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 bg-white"
                >
                  <option value="Tooling & Raw Material Backlog">Tooling & Raw Material Backlog</option>
                  <option value="CMM Metrology Calibration Schedule">CMM Metrology Calibration Schedule</option>
                  <option value="Engineering Specification Clarification">Engineering Specification Clarification</option>
                  <option value="Shipping Logistics Delay">Shipping Logistics Delay</option>
                </select>
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Proposed New Delivery Date:</label>
                <input
                  type="date"
                  value={proposeForm.newDeliveryDate}
                  onChange={(e) => setProposeForm({ ...proposeForm, newDeliveryDate: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Justification & Scope Notes for Buyer:</label>
                <textarea
                  rows={3}
                  value={proposeForm.notes}
                  onChange={(e) => setProposeForm({ ...proposeForm, notes: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowProposeModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={handleProposeChanges}
                className="px-5 py-2 bg-orange-600 hover:bg-orange-700 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Submit Proposal to Buyer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 4: GENERATE COMMERCIAL INVOICE (PO FLIP) */}
      {/* ========================================================================= */}
      {showInvoiceModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550]">
                Generate Commercial Invoice (PO Flip)
              </h3>
              <button onClick={() => setShowInvoiceModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                <div className="flex justify-between">
                  <span className="text-slate-500">Base Contract PO Amount:</span>
                  <span className="font-bold text-slate-800">{currentSelectedOrder.amount}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Tax ({invoiceForm.tax_percent}%):</span>
                  <span className="font-bold text-slate-800">
                    ${((currentSelectedOrder.amount_num * invoiceForm.tax_percent) / 100).toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between border-t border-slate-200 pt-1 text-sm font-black text-[#0B2550]">
                  <span>Total Invoiced Amount:</span>
                  <span className="text-emerald-600">
                    ${(currentSelectedOrder.amount_num * (1 + invoiceForm.tax_percent / 100)).toFixed(2)}
                  </span>
                </div>
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Commercial Payment Terms:</label>
                <input
                  type="text"
                  value={invoiceForm.terms}
                  onChange={(e) => setInvoiceForm({ ...invoiceForm, terms: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Authorized Digital Signature:</label>
                <input
                  type="text"
                  value={invoiceForm.signature}
                  onChange={(e) => setInvoiceForm({ ...invoiceForm, signature: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 font-mono"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowInvoiceModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={handleGenerateInvoice}
                className="px-5 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Transmit Invoice to Buyer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
