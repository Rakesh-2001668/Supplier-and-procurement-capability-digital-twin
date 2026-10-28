"use client";

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  FileText, CheckCircle2, Clock, Truck, ShieldCheck, AlertCircle, 
  ArrowRight, Search, Filter, RefreshCw, ChevronRight, X, 
  Package, Boxes, Building2, User, DollarSign, Calendar, Layers, 
  ExternalLink, BarChart3, ShieldAlert, Award, FileCheck2, ArrowUpRight, Check
} from 'lucide-react';

interface LineItem {
  item_id: string;
  sku: string;
  name: string;
  category: string;
  unit: string;
  qty_ordered: number;
  qty_shipped: number;
  qty_received: number;
  unit_price: number;
  line_total: number;
  inspection_status: string;
}

interface Milestone {
  key: string;
  title: string;
  timestamp: string;
  actor: string;
  completed: boolean;
  details: string;
}

interface PODossier {
  id: string;
  po_number: string;
  status: string;
  total_amount: number;
  currency: string;
  supplier_tenant_id: string;
  supplier_name: string;
  supplier_initials: string;
  supplier_color: string;
  supplier_category: string;
  supplier_email: string;
  supplier_rating: number;
  supplier_facility: string;
  department: string;
  buyer_name: string;
  priority: string;
  cost_center: string;
  payment_terms: string;
  incoterms: string;
  created_at: string;
  target_delivery_date: string;
  approval_tier: string;
  approval_due_date: string;
  sla_status: string;
  budget_limit_check: {
    department_budget: number;
    allocated_to_date: number;
    this_po: number;
    remaining_after: number;
    status: string;
  };
  line_items: LineItem[];
  milestones: Milestone[];
  asn_info?: {
    asn_id: string;
    carrier: string;
    tracking_number: string;
    expected_date: string;
    status: string;
    dispatched_at: string;
  };
  grn_info?: {
    grn_number: string;
    received_at: string;
    dock_bay: string;
    received_by: string;
    packages_verified: number;
    units_accepted: number;
    units_rejected: number;
    quality_pass: boolean;
    cmm_cert: string;
    storage_bin: string;
    lot_number?: string;
  };
  invoice_info?: {
    invoice_number: string;
    invoice_amount: number;
    po_amount: number;
    grn_amount: number;
    variance: number;
    matched: boolean;
    reconciled_at: string;
    status: string;
  };
  three_way_matched: boolean;
  progress_pct: number;
  approvals_audit: Array<{
    approver_id: string;
    status: string;
    comments: string;
    created_at: string;
  }>;
}

interface OverviewKPIs {
  total_pos: number;
  total_spend: number;
  pending_approvals_count: number;
  pending_approvals_value: number;
  in_transit_asns_count: number;
  goods_received_count: number;
  completed_count: number;
  issued_count: number;
  three_way_match_pass_rate: number;
  average_fulfillment_days: number;
  inspection_pass_rate: number;
  status_distribution: Record<string, number>;
}

export default function PurchaseOrdersWorkstationPage() {
  const [overview, setOverview] = useState<OverviewKPIs | null>(null);
  const [purchaseOrders, setPurchaseOrders] = useState<PODossier[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSupplier, setSelectedSupplier] = useState('ALL');
  const [selectedItems, setSelectedItems] = useState<string[]>([]);
  
  // Workstation Drawer state
  const [selectedPO, setSelectedPO] = useState<PODossier | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [drawerTab, setDrawerTab] = useState<'OVERVIEW' | 'ITEMS' | 'FULFILLMENT' | 'AUDIT'>('OVERVIEW');
  const [actionInProgress, setActionInProgress] = useState(false);
  const [successBanner, setSuccessBanner] = useState<string | null>(null);

  // Quick GRN modal state inside workstation
  const [showGRNModal, setShowGRNModal] = useState(false);
  const [grnDockBay, setGrnDockBay] = useState('Receiving Dock 04-B');
  const [grnStorageBin, setGrnStorageBin] = useState('BIN-AERO-W04');
  const [grnLotNumber, setGrnLotNumber] = useState('LOT-2026-X1');

  const fetchData = async () => {
    try {
      setLoading(true);
      const [overviewRes, listRes] = await Promise.all([
        fetch('http://127.0.0.1:8080/api/v1/procurement/purchase-orders/overview'),
        fetch('http://127.0.0.1:8080/api/v1/procurement/purchase-orders/list')
      ]);

      if (overviewRes.ok) {
        const oData = await overviewRes.json();
        setOverview(oData);
      }
      if (listRes.ok) {
        const lData = await listRes.json();
        setPurchaseOrders(lData.purchase_orders || []);
      }
    } catch (err) {
      console.error("Failed to load PO data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const openWorkstation = async (po: PODossier) => {
    setSelectedPO(po);
    setIsDrawerOpen(true);
    setDrawerTab('OVERVIEW');
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/procurement/purchase-orders/fulfillment/${po.po_number}`);
      if (res.ok) {
        const data = await res.json();
        if (data.fulfillment_dossier) {
          setSelectedPO(data.fulfillment_dossier);
        }
      }
    } catch (err) {
      console.error("Failed to fetch PO details:", err);
    }
  };

  const handleStateTransition = async (action: string, extraPayload: any = {}) => {
    if (!selectedPO) return;
    try {
      setActionInProgress(true);
      const payload = {
        action,
        actor_name: "Procurement Lead (Alex Sharma)",
        actor_role: "Operations & Procurement Lead",
        ...extraPayload
      };

      const res = await fetch(`http://127.0.0.1:8080/api/v1/procurement/purchase-orders/${selectedPO.po_number}/transition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const resData = await res.json();
        setSuccessBanner(`PO ${selectedPO.po_number} successfully transitioned to ${resData.new_status}!`);
        setTimeout(() => setSuccessBanner(null), 4500);
        setSelectedPO(resData.dossier);
        setShowGRNModal(false);
        fetchData(); // refresh parent ledger
      } else {
        const err = await res.json();
        alert(`Error executing ${action}: ${err.detail || 'Request failed'}`);
      }
    } catch (err) {
      console.error("Transition error:", err);
    } finally {
      setActionInProgress(false);
    }
  };

  const filteredOrders = purchaseOrders.filter(po => {
    if (activeTab !== 'ALL') {
      if (activeTab === 'SHIPPED' && po.status !== 'SHIPPED') return false;
      if (activeTab === 'PENDING_APPROVAL' && po.status !== 'PENDING_APPROVAL') return false;
      if (activeTab === 'ISSUED' && !['ISSUED', 'ACKNOWLEDGED'].includes(po.status)) return false;
      if (activeTab === 'IN_PRODUCTION' && po.status !== 'IN_PRODUCTION') return false;
      if (activeTab === 'GOODS_RECEIVED' && !['GOODS_RECEIVED', 'QUALITY_INSPECTED'].includes(po.status)) return false;
      if (activeTab === 'COMPLETED' && !['COMPLETED', 'INVOICED'].includes(po.status)) return false;
    }
    if (selectedSupplier !== 'ALL' && po.supplier_name !== selectedSupplier) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const match = (
        po.po_number.toLowerCase().includes(q) ||
        po.supplier_name.toLowerCase().includes(q) ||
        po.department.toLowerCase().includes(q) ||
        po.buyer_name.toLowerCase().includes(q)
      );
      if (!match) return false;
    }
    return true;
  });

  const toggleSelection = (id: string) => {
    setSelectedItems(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);
  };

  const toggleAll = () => {
    if (selectedItems.length > 0) setSelectedItems([]);
    else setSelectedItems(filteredOrders.map(p => p.id));
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'PENDING_APPROVAL':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30">⏳ Pending Approval</span>;
      case 'APPROVED':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">✓ Approved</span>;
      case 'ISSUED':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/30">📡 Issued</span>;
      case 'ACKNOWLEDGED':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-indigo-500/10 text-indigo-400 border border-indigo-500/30">🤝 Acknowledged</span>;
      case 'IN_PRODUCTION':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-purple-500/10 text-purple-400 border border-purple-500/30">⚙️ In Production</span>;
      case 'SHIPPED':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">🚚 Shipped (ASN)</span>;
      case 'GOODS_RECEIVED':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-teal-500/10 text-teal-400 border border-teal-500/30">📦 Dock Received</span>;
      case 'QUALITY_INSPECTED':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">🔬 QA Inspected</span>;
      case 'INVOICED':
      case 'COMPLETED':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/40">✓ 3-Way Reconciled</span>;
      default:
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-slate-800 text-slate-300 border border-slate-700">{status}</span>;
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#070B14] text-slate-100 min-h-screen p-6 font-sans">
      {/* Toast Notification Banner */}
      {successBanner && (
        <div className="fixed top-5 right-5 z-50 bg-gradient-to-r from-emerald-600 to-teal-600 text-white px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3 border border-emerald-400/40 animate-in fade-in slide-in-from-top-4 duration-300">
          <CheckCircle2 size={20} className="text-white shrink-0" />
          <div className="text-sm font-bold">{successBanner}</div>
        </div>
      )}

      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6 pb-5 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-2 text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">
            <span>Procurement Twin</span>
            <span className="text-slate-600">/</span>
            <span className="text-cyan-400">Purchase Orders</span>
            <span className="text-slate-600">/</span>
            <span className="text-slate-300 font-semibold">Lifecycle & Fulfillment Workstation</span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
            Enterprise PO Lifecycle & Fulfillment
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-bold uppercase tracking-wider">
              Live Workstation
            </span>
          </h1>
          <p className="text-xs text-slate-400 mt-1 max-w-3xl">
            Autonomous state machine engine orchestrating end-to-end procurement: Tiered executive authorizations, Advance Ship Notices (ASN), Dock GRN physical check-ins, zero-NCR inspection sign-offs, and 3-way match financial closure.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchData}
            className="p-2.5 rounded-xl bg-slate-900 border border-slate-700/80 text-slate-300 hover:text-white hover:border-slate-600 transition-all shadow-sm"
            title="Refresh Ledger"
          >
            <RefreshCw size={16} className={loading ? "animate-spin text-cyan-400" : ""} />
          </button>
          <Link href="/purchase-orders/pending">
            <button className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500/10 to-orange-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 text-xs font-bold transition-all flex items-center gap-2 shadow-sm">
              <Clock size={15} />
              <span>Approval Matrix ({overview?.pending_approvals_count ?? 1})</span>
            </button>
          </Link>
          <Link href="/purchase-orders/create">
            <button className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 text-white text-xs font-extrabold shadow-lg shadow-cyan-900/30 transition-all flex items-center gap-2">
              <span>+ Create Purchase Order</span>
              <ArrowRight size={14} />
            </button>
          </Link>
        </div>
      </div>

      {/* Real-Time KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3.5 mb-6">
        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Total Orders</span>
            <FileText size={14} className="text-blue-400" />
          </div>
          <div className="text-2xl font-black text-white">{overview?.total_pos ?? 9}</div>
          <div className="text-[10px] text-emerald-400 font-semibold mt-1">100% Traceable Ledger</div>
          <div className="absolute right-0 bottom-0 w-16 h-16 bg-blue-500/5 rounded-full blur-xl pointer-events-none" />
        </div>

        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Active Spend</span>
            <DollarSign size={14} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-black text-cyan-300">
            ${((overview?.total_spend ?? 362233.5) / 1000).toFixed(1)}k
          </div>
          <div className="text-[10px] text-slate-400 font-medium mt-1">CAPEX & Operations</div>
          <div className="absolute right-0 bottom-0 w-16 h-16 bg-cyan-500/5 rounded-full blur-xl pointer-events-none" />
        </div>

        <div className="bg-[#0E1526] border border-amber-900/40 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-amber-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Pending Approvals</span>
            <Clock size={14} className="text-amber-400" />
          </div>
          <div className="text-2xl font-black text-amber-300">
            {overview?.pending_approvals_count ?? 1}
          </div>
          <div className="text-[10px] text-amber-400/80 font-medium mt-1">
            ${((overview?.pending_approvals_value ?? 125000) / 1000).toFixed(0)}k awaiting sign-off
          </div>
          <div className="absolute right-0 bottom-0 w-16 h-16 bg-amber-500/10 rounded-full blur-xl pointer-events-none" />
        </div>

        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>In-Transit (ASNs)</span>
            <Truck size={14} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-black text-cyan-400">
            {overview?.in_transit_asns_count ?? 1}
          </div>
          <div className="text-[10px] text-slate-400 font-medium mt-1">Active GPS Dispatches</div>
          <div className="absolute right-0 bottom-0 w-16 h-16 bg-cyan-500/5 rounded-full blur-xl pointer-events-none" />
        </div>

        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>QA Pass Rate</span>
            <ShieldCheck size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-black text-emerald-400">
            {overview?.inspection_pass_rate ?? 99.2}%
          </div>
          <div className="text-[10px] text-emerald-500/90 font-medium mt-1">Zero NCR Quarantine</div>
          <div className="absolute right-0 bottom-0 w-16 h-16 bg-emerald-500/5 rounded-full blur-xl pointer-events-none" />
        </div>

        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>3-Way Reconciled</span>
            <Award size={14} className="text-purple-400" />
          </div>
          <div className="text-2xl font-black text-purple-300">
            {overview?.three_way_match_pass_rate ?? 98.6}%
          </div>
          <div className="text-[10px] text-purple-400/80 font-medium mt-1">$0.00 Variance Closed</div>
          <div className="absolute right-0 bottom-0 w-16 h-16 bg-purple-500/5 rounded-full blur-xl pointer-events-none" />
        </div>
      </div>

      {/* Main Ledger Workstation Card */}
      <div className="flex-1 bg-[#0E1526] border border-slate-800/90 rounded-2xl shadow-xl flex flex-col overflow-hidden">
        {/* Status Filter Ribbon */}
        <div className="flex items-center justify-between px-6 border-b border-slate-800 overflow-x-auto gap-4 py-1 bg-slate-900/40">
          <div className="flex items-center gap-1.5 shrink-0">
            {[
              { id: 'ALL', label: 'All Orders', count: purchaseOrders.length },
              { id: 'PENDING_APPROVAL', label: 'Pending Approval', count: purchaseOrders.filter(p => p.status === 'PENDING_APPROVAL').length },
              { id: 'ISSUED', label: 'Issued / Ack', count: purchaseOrders.filter(p => ['ISSUED', 'ACKNOWLEDGED'].includes(p.status)).length },
              { id: 'IN_PRODUCTION', label: 'In Production', count: purchaseOrders.filter(p => p.status === 'IN_PRODUCTION').length },
              { id: 'SHIPPED', label: 'In Transit (ASN)', count: purchaseOrders.filter(p => p.status === 'SHIPPED').length },
              { id: 'GOODS_RECEIVED', label: 'Dock Received', count: purchaseOrders.filter(p => ['GOODS_RECEIVED', 'QUALITY_INSPECTED'].includes(p.status)).length },
              { id: 'COMPLETED', label: '3-Way Closed', count: purchaseOrders.filter(p => ['COMPLETED', 'INVOICED'].includes(p.status)).length },
            ].map(tab => {
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-3.5 py-3 text-xs font-bold transition-all border-b-2 flex items-center gap-2 ${
                    active 
                      ? 'border-cyan-400 text-cyan-300 bg-cyan-950/20' 
                      : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full ${active ? 'bg-cyan-500/20 text-cyan-300 font-extrabold' : 'bg-slate-800 text-slate-400'}`}>
                    {tab.count}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="text-xs text-slate-400 hidden xl:flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span>Autonomous State Machine Active</span>
          </div>
        </div>

        {/* Filter Toolbar */}
        <div className="p-4 bg-slate-900/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3 flex-1 min-w-[280px]">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3.5 top-2.5 text-slate-400" size={15} />
              <input 
                type="text" 
                placeholder="Search PO number, supplier, part description, or buyer..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-[#070B14] border border-slate-700/80 rounded-xl pl-9 pr-4 py-2 text-xs text-slate-200 placeholder:text-slate-500 outline-none focus:border-cyan-500 transition-colors"
              />
            </div>

            <div className="w-56">
              <select
                value={selectedSupplier}
                onChange={(e) => setSelectedSupplier(e.target.value)}
                className="w-full bg-[#070B14] border border-slate-700/80 rounded-xl px-3 py-2 text-xs text-slate-200 outline-none focus:border-cyan-500"
              >
                <option value="ALL">All Qualified Suppliers</option>
                <option value="Apex Precision Machining Ltd">Apex Precision Machining Ltd</option>
                <option value="Lawrence LLC">Lawrence LLC (Avionics)</option>
                <option value="James-Hampton Ltd">James-Hampton Ltd (Turbines)</option>
                <option value="Jones & Stephenson">Jones & Stephenson</option>
                <option value="Gonzalez Inc">Gonzalez Inc</option>
                <option value="Morrison PLC">Morrison PLC</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span>Showing <strong className="text-white">{filteredOrders.length}</strong> purchase orders</span>
            {selectedItems.length > 0 && (
              <span className="bg-cyan-500/20 text-cyan-300 px-2 py-0.5 rounded font-bold">
                {selectedItems.length} selected
              </span>
            )}
          </div>
        </div>

        {/* Orders Table */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="p-16 flex flex-col items-center justify-center text-slate-400 gap-3">
              <RefreshCw size={28} className="animate-spin text-cyan-400" />
              <p className="text-xs font-semibold">Synchronizing with live enterprise procurement engine...</p>
            </div>
          ) : filteredOrders.length === 0 ? (
            <div className="p-16 text-center text-slate-400">
              <Package size={36} className="mx-auto mb-2 text-slate-600" />
              <p className="text-sm font-bold text-slate-300">No Purchase Orders Found</p>
              <p className="text-xs text-slate-500 mt-1">Try adjusting your filters or create a new purchase order.</p>
            </div>
          ) : (
            <table className="w-full text-left border-collapse text-xs">
              <thead className="sticky top-0 bg-[#0B101E] border-b border-slate-800 text-[11px] font-bold uppercase tracking-wider text-slate-400 z-10">
                <tr>
                  <th className="py-3.5 px-4 w-10">
                    <input 
                      type="checkbox" 
                      checked={selectedItems.length > 0 && selectedItems.length === filteredOrders.length}
                      onChange={toggleAll}
                      className="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0 cursor-pointer"
                    />
                  </th>
                  <th className="py-3.5 px-3">PO Number</th>
                  <th className="py-3.5 px-3">Supplier Organization</th>
                  <th className="py-3.5 px-3">Department / Buyer</th>
                  <th className="py-3.5 px-3 text-right">Total Amount</th>
                  <th className="py-3.5 px-3 text-center">Lifecycle State</th>
                  <th className="py-3.5 px-3">Fulfillment Progress</th>
                  <th className="py-3.5 px-3">Carrier / Tracking</th>
                  <th className="py-3.5 px-4 text-center">Workstation Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-medium">
                {filteredOrders.map(po => {
                  const isChecked = selectedItems.includes(po.id);
                  return (
                    <tr 
                      key={po.id} 
                      className={`hover:bg-slate-800/40 transition-colors group cursor-pointer ${
                        isChecked ? 'bg-cyan-950/20' : ''
                      }`}
                      onClick={() => openWorkstation(po)}
                    >
                      <td className="py-3 px-4" onClick={(e) => e.stopPropagation()}>
                        <input 
                          type="checkbox" 
                          checked={isChecked}
                          onChange={() => toggleSelection(po.id)}
                          className="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0 cursor-pointer"
                        />
                      </td>

                      <td className="py-3 px-3">
                        <div className="font-extrabold text-cyan-400 group-hover:underline flex items-center gap-1.5">
                          <span>{po.po_number}</span>
                          <ArrowUpRight size={12} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                        </div>
                        <div className="text-[10px] text-slate-500 mt-0.5">{po.created_at}</div>
                      </td>

                      <td className="py-3 px-3">
                        <div className="flex items-center gap-2.5">
                          <div className={`w-6 h-6 rounded-lg text-white flex items-center justify-center text-[10px] font-black ${po.supplier_color || 'bg-cyan-600'}`}>
                            {po.supplier_initials || 'AP'}
                          </div>
                          <div>
                            <div className="font-bold text-white leading-tight">{po.supplier_name}</div>
                            <div className="text-[10px] text-slate-400 flex items-center gap-1 mt-0.5">
                              <span>⭐ {po.supplier_rating}% Rating</span>
                              <span>•</span>
                              <span>{po.supplier_category}</span>
                            </div>
                          </div>
                        </div>
                      </td>

                      <td className="py-3 px-3">
                        <div className="text-slate-300 font-semibold">{po.department}</div>
                        <div className="text-[10px] text-slate-500">{po.buyer_name}</div>
                      </td>

                      <td className="py-3 px-3 text-right">
                        <div className="font-mono font-bold text-slate-200">
                          ${po.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </div>
                        <div className="text-[10px] text-slate-500 uppercase">{po.payment_terms}</div>
                      </td>

                      <td className="py-3 px-3 text-center">
                        {getStatusBadge(po.status)}
                      </td>

                      <td className="py-3 px-3 w-40">
                        <div className="flex items-center justify-between text-[10px] mb-1">
                          <span className="text-slate-400">{po.approval_tier?.split(' ')[0] || 'Level 1'}</span>
                          <span className="font-bold text-cyan-400">{po.progress_pct}%</span>
                        </div>
                        <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                          <div 
                            className={`h-full rounded-full transition-all duration-500 ${
                              po.status === 'COMPLETED' ? 'bg-gradient-to-r from-emerald-500 to-teal-400' :
                              po.status === 'SHIPPED' ? 'bg-gradient-to-r from-blue-500 to-cyan-400' :
                              po.status === 'PENDING_APPROVAL' ? 'bg-gradient-to-r from-amber-500 to-orange-400' :
                              'bg-cyan-500'
                            }`}
                            style={{ width: `${po.progress_pct}%` }}
                          />
                        </div>
                      </td>

                      <td className="py-3 px-3">
                        {po.asn_info ? (
                          <div>
                            <div className="text-slate-300 font-bold flex items-center gap-1.5">
                              <Truck size={12} className="text-cyan-400" />
                              <span>{po.asn_info.carrier.split(' ')[0]}</span>
                            </div>
                            <div className="text-[10px] text-cyan-400/90 font-mono mt-0.5">{po.asn_info.tracking_number}</div>
                          </div>
                        ) : po.grn_info ? (
                          <div>
                            <div className="text-teal-300 font-bold flex items-center gap-1.5">
                              <ShieldCheck size={12} className="text-teal-400" />
                              <span>{po.grn_info.grn_number}</span>
                            </div>
                            <div className="text-[10px] text-slate-400 mt-0.5">{po.grn_info.dock_bay}</div>
                          </div>
                        ) : (
                          <span className="text-[11px] text-slate-500 italic">Pre-transit stage</span>
                        )}
                      </td>

                      <td className="py-3 px-4 text-center" onClick={(e) => e.stopPropagation()}>
                        <button 
                          onClick={() => openWorkstation(po)}
                          className="px-3 py-1.5 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-[11px] font-bold transition-all flex items-center gap-1.5 mx-auto"
                        >
                          <span>Launch Workstation</span>
                          <ChevronRight size={12} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ========================================================================= */}
      {/* INTERACTIVE FULFILLMENT WORKSTATION DRAWER */}
      {/* ========================================================================= */}
      {isDrawerOpen && selectedPO && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
          <div 
            className="w-full max-w-3xl bg-[#090E1A] border-l border-slate-800 text-slate-100 flex flex-col h-full shadow-2xl animate-in slide-in-from-right duration-300 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drawer Header */}
            <div className="p-5 bg-[#0D1527] border-b border-slate-800/90 flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-xl font-black text-white">{selectedPO.po_number}</span>
                  {getStatusBadge(selectedPO.status)}
                  <span className="text-xs px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-bold">
                    {selectedPO.approval_tier}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-xs text-slate-400 mt-1">
                  <span>Supplier: <strong className="text-white">{selectedPO.supplier_name}</strong></span>
                  <span>•</span>
                  <span>Buyer: <strong className="text-white">{selectedPO.buyer_name}</strong></span>
                  <span>•</span>
                  <span>Delivery: <strong className="text-white">{selectedPO.target_delivery_date}</strong></span>
                </div>
              </div>

              <button 
                onClick={() => setIsDrawerOpen(false)}
                className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Workstation Action Banner (Dynamic based on state) */}
            <div className="p-4 bg-gradient-to-r from-slate-900 to-[#0e172a] border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-cyan-500/10 text-cyan-400 flex items-center justify-center font-bold">
                  ⚡
                </div>
                <div>
                  <div className="text-xs font-bold text-white">Next Operational Action</div>
                  <div className="text-[11px] text-slate-400">
                    {selectedPO.status === 'PENDING_APPROVAL' && "Executive sign-off required before PO issuance."}
                    {selectedPO.status === 'ISSUED' && "Dispatched to supplier. Awaiting acknowledgment."}
                    {selectedPO.status === 'ACKNOWLEDGED' && "Order confirmed. Trigger shopfloor manufacturing."}
                    {selectedPO.status === 'IN_PRODUCTION' && "Fabrication underway. Awaiting carrier ASN dispatch."}
                    {selectedPO.status === 'SHIPPED' && "Carrier in-transit. Ready for dock Goods Receipt Note (GRN)."}
                    {selectedPO.status === 'GOODS_RECEIVED' && "Dock check-in complete. Perform quality metrology verification."}
                    {selectedPO.status === 'QUALITY_INSPECTED' && "Zero NCR verified. Finalize 3-way match & close PO."}
                    {['INVOICED', 'COMPLETED'].includes(selectedPO.status) && "Order closed & archived in enterprise finance ledger."}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {selectedPO.status === 'PENDING_APPROVAL' && (
                  <>
                    <button 
                      disabled={actionInProgress}
                      onClick={() => handleStateTransition('REJECT')}
                      className="px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 rounded-lg text-xs font-bold transition-all"
                    >
                      Reject
                    </button>
                    <button 
                      disabled={actionInProgress}
                      onClick={() => handleStateTransition('APPROVE')}
                      className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-extrabold shadow-md transition-all flex items-center gap-1.5"
                    >
                      <Check size={14} />
                      <span>Executive Sign-Off & Issue</span>
                    </button>
                  </>
                )}

                {selectedPO.status === 'ISSUED' && (
                  <button 
                    disabled={actionInProgress}
                    onClick={() => handleStateTransition('ACKNOWLEDGE')}
                    className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-extrabold shadow-md transition-all"
                  >
                    Simulate Supplier Acknowledge
                  </button>
                )}

                {selectedPO.status === 'ACKNOWLEDGED' && (
                  <button 
                    disabled={actionInProgress}
                    onClick={() => handleStateTransition('START_PRODUCTION')}
                    className="px-4 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-lg text-xs font-extrabold shadow-md transition-all"
                  >
                    Start Production Milling
                  </button>
                )}

                {selectedPO.status === 'IN_PRODUCTION' && (
                  <button 
                    disabled={actionInProgress}
                    onClick={() => handleStateTransition('SHIPPED')}
                    className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-extrabold shadow-md transition-all flex items-center gap-1.5"
                  >
                    <Truck size={14} />
                    <span>Generate Carrier ASN Dispatch</span>
                  </button>
                )}

                {selectedPO.status === 'SHIPPED' && (
                  <button 
                    disabled={actionInProgress}
                    onClick={() => setShowGRNModal(true)}
                    className="px-4 py-1.5 bg-gradient-to-r from-teal-600 to-emerald-600 hover:from-teal-500 hover:to-emerald-500 text-white rounded-lg text-xs font-extrabold shadow-md transition-all flex items-center gap-1.5"
                  >
                    <Package size={14} />
                    <span>Record Dock Receipt (GRN)</span>
                  </button>
                )}

                {selectedPO.status === 'GOODS_RECEIVED' && (
                  <button 
                    disabled={actionInProgress}
                    onClick={() => handleStateTransition('INSPECT_QUALITY')}
                    className="px-4 py-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 text-white rounded-lg text-xs font-extrabold shadow-md transition-all flex items-center gap-1.5"
                  >
                    <ShieldCheck size={14} />
                    <span>Sign-off Metrology (Zero NCR)</span>
                  </button>
                )}

                {selectedPO.status === 'QUALITY_INSPECTED' && (
                  <button 
                    disabled={actionInProgress}
                    onClick={() => handleStateTransition('RECONCILE_3_WAY')}
                    className="px-4 py-1.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 text-white rounded-lg text-xs font-extrabold shadow-md transition-all flex items-center gap-1.5"
                  >
                    <Award size={14} />
                    <span>Reconcile 3-Way Match & Close</span>
                  </button>
                )}

                {['INVOICED', 'COMPLETED'].includes(selectedPO.status) && (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/20 px-3 py-1.5 rounded-lg">
                    <CheckCircle2 size={14} />
                    <span>Order Reconciled ($0.00 Variance)</span>
                  </div>
                )}
              </div>
            </div>

            {/* Quick GRN Receiving Modal Overlay */}
            {showGRNModal && (
              <div className="p-4 bg-teal-950/30 border-b border-teal-500/30 flex flex-col gap-3 animate-in fade-in">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-extrabold text-teal-300 uppercase tracking-wider flex items-center gap-2">
                    <Package size={14} /> Receiving Dock Inspection & GRN Check-In
                  </span>
                  <button onClick={() => setShowGRNModal(false)} className="text-slate-400 hover:text-white text-xs">Cancel</button>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Receiving Dock Bay</label>
                    <select 
                      value={grnDockBay} 
                      onChange={(e) => setGrnDockBay(e.target.value)}
                      className="w-full bg-[#070B14] border border-slate-700 rounded-lg p-2 text-xs text-slate-200 outline-none"
                    >
                      <option value="Receiving Dock 04-B">Receiving Dock 04-B</option>
                      <option value="Receiving Dock 02 (Cryo)">Receiving Dock 02 (Cryo)</option>
                      <option value="Dock 01 High-Bay">Dock 01 High-Bay</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Target Storage Bin</label>
                    <input 
                      type="text" 
                      value={grnStorageBin} 
                      onChange={(e) => setGrnStorageBin(e.target.value)}
                      className="w-full bg-[#070B14] border border-slate-700 rounded-lg p-2 text-xs text-slate-200 outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Batch Lot Number</label>
                    <input 
                      type="text" 
                      value={grnLotNumber} 
                      onChange={(e) => setGrnLotNumber(e.target.value)}
                      className="w-full bg-[#070B14] border border-slate-700 rounded-lg p-2 text-xs text-slate-200 outline-none"
                    />
                  </div>
                </div>
                <div className="flex justify-end gap-2 mt-1">
                  <button 
                    disabled={actionInProgress}
                    onClick={() => handleStateTransition('RECORD_GRN', {
                      dock_bay: grnDockBay,
                      storage_bin: grnStorageBin,
                      batch_lot_number: grnLotNumber,
                      received_quantity: selectedPO.line_items?.[0]?.qty_ordered || 10,
                      quality_pass: true
                    })}
                    className="px-4 py-2 rounded-lg bg-teal-500 hover:bg-teal-400 text-slate-950 text-xs font-black shadow-md flex items-center gap-1.5"
                  >
                    <CheckCircle2 size={14} />
                    <span>Confirm Dock Verification & Update Plant Stock</span>
                  </button>
                </div>
              </div>
            )}

            {/* Workstation Drawer Navigation */}
            <div className="flex items-center gap-4 px-6 border-b border-slate-800 text-xs font-bold bg-[#0B101E]">
              {[
                { id: 'OVERVIEW', label: 'Milestone Timeline' },
                { id: 'ITEMS', label: `Line Items (${selectedPO.line_items?.length || 0})` },
                { id: 'FULFILLMENT', label: 'ASN & Dock Receiving' },
                { id: 'AUDIT', label: '3-Way Match & Audit Trail' },
              ].map(t => (
                <button
                  key={t.id}
                  onClick={() => setDrawerTab(t.id as any)}
                  className={`py-3.5 border-b-2 transition-colors ${
                    drawerTab === t.id 
                      ? 'border-cyan-400 text-cyan-300' 
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Workstation Drawer Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {drawerTab === 'OVERVIEW' && (
                <div className="space-y-6">
                  {/* Financial & Budget Card */}
                  <div className="bg-[#0E1526] border border-slate-800 rounded-xl p-4 grid grid-cols-4 gap-4 text-xs">
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase font-bold">Total Amount</div>
                      <div className="text-xl font-mono font-black text-cyan-300 mt-0.5">
                        ${selectedPO.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5">{selectedPO.payment_terms}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase font-bold">Cost Center</div>
                      <div className="text-sm font-bold text-white mt-0.5">{selectedPO.cost_center}</div>
                      <div className="text-[10px] text-slate-500 mt-0.5">{selectedPO.department}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase font-bold">Incoterms</div>
                      <div className="text-sm font-bold text-slate-200 mt-0.5">{selectedPO.incoterms}</div>
                      <div className="text-[10px] text-emerald-400 mt-0.5">Insurance Covered</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase font-bold">Budget Status</div>
                      <div className="text-sm font-bold text-emerald-400 mt-0.5">{selectedPO.budget_limit_check?.status || 'WITHIN_LIMITS'}</div>
                      <div className="text-[10px] text-slate-500 mt-0.5">Remaining: ${(selectedPO.budget_limit_check?.remaining_after || 33000).toLocaleString()}</div>
                    </div>
                  </div>

                  {/* Complete 8-Milestone Visual Stepper */}
                  <div>
                    <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-4 flex items-center justify-between">
                      <span>End-to-End Lifecycle Milestones</span>
                      <span className="text-[11px] text-cyan-400 font-bold">{selectedPO.progress_pct}% Completed</span>
                    </h3>

                    <div className="relative pl-6 border-l-2 border-slate-800 space-y-6">
                      {selectedPO.milestones?.map((m, idx) => (
                        <div key={idx} className="relative group">
                          {/* Dot indicator */}
                          <div className={`absolute -left-[31px] top-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center text-[9px] ${
                            m.completed 
                              ? 'bg-emerald-500 border-emerald-400 text-slate-950 font-black' 
                              : 'bg-slate-900 border-slate-700 text-slate-500'
                          }`}>
                            {m.completed ? '✓' : idx + 1}
                          </div>

                          <div>
                            <div className="flex items-center justify-between">
                              <h4 className={`text-xs font-extrabold ${m.completed ? 'text-white' : 'text-slate-400'}`}>
                                {m.title}
                              </h4>
                              <span className="text-[10px] text-slate-500 font-mono">{m.timestamp}</span>
                            </div>
                            <div className="text-[11px] text-slate-400 mt-0.5">{m.details}</div>
                            <div className="text-[10px] text-cyan-400/80 font-medium mt-1">Actor: {m.actor}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {drawerTab === 'ITEMS' && (
                <div className="space-y-4">
                  <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider">Line Items Allocation & Counting</h3>
                  <div className="bg-[#0E1526] border border-slate-800 rounded-xl overflow-hidden">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-900/60 border-b border-slate-800 text-[10px] font-bold uppercase text-slate-400">
                        <tr>
                          <th className="py-2.5 px-3">Item SKU / Spec</th>
                          <th className="py-2.5 px-3">Description</th>
                          <th className="py-2.5 px-3 text-center">Ordered</th>
                          <th className="py-2.5 px-3 text-center">Received</th>
                          <th className="py-2.5 px-3 text-right">Unit Price</th>
                          <th className="py-2.5 px-3 text-right">Line Total</th>
                          <th className="py-2.5 px-3 text-center">QA Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {selectedPO.line_items?.map((item, idx) => (
                          <tr key={idx} className="hover:bg-slate-800/30">
                            <td className="py-3 px-3 font-mono font-bold text-cyan-400">{item.sku}</td>
                            <td className="py-3 px-3">
                              <div className="text-white font-semibold">{item.name}</div>
                              <div className="text-[10px] text-slate-500">{item.category}</div>
                            </td>
                            <td className="py-3 px-3 text-center font-bold text-slate-300">{item.qty_ordered} {item.unit}</td>
                            <td className="py-3 px-3 text-center font-bold text-teal-400">{item.qty_received} {item.unit}</td>
                            <td className="py-3 px-3 text-right font-mono">${item.unit_price.toFixed(2)}</td>
                            <td className="py-3 px-3 text-right font-mono font-bold text-white">${item.line_total.toFixed(2)}</td>
                            <td className="py-3 px-3 text-center">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                item.inspection_status === 'PASSED' ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' :
                                item.inspection_status === 'IN_TRANSIT' ? 'bg-cyan-500/20 text-cyan-300' :
                                'bg-slate-800 text-slate-400'
                              }`}>
                                {item.inspection_status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {drawerTab === 'FULFILLMENT' && (
                <div className="space-y-6">
                  {/* ASN Carrier Card */}
                  <div className="bg-[#0E1526] border border-slate-800 rounded-xl p-5 space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <Truck size={18} className="text-cyan-400" />
                        <h4 className="text-xs font-bold text-white uppercase tracking-wider">Advance Ship Notice (ASN) Carrier Telemetry</h4>
                      </div>
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 font-bold">
                        {selectedPO.asn_info?.status || 'Active Shipment'}
                      </span>
                    </div>

                    {selectedPO.asn_info ? (
                      <div className="grid grid-cols-3 gap-4 text-xs">
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-bold">Carrier Organization</div>
                          <div className="text-sm font-bold text-white mt-1">{selectedPO.asn_info.carrier}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-bold">Digital Tracking #</div>
                          <div className="text-sm font-mono font-bold text-cyan-400 mt-1">{selectedPO.asn_info.tracking_number}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-bold">Estimated Spaceport Dock ETA</div>
                          <div className="text-sm font-bold text-emerald-400 mt-1">{selectedPO.asn_info.expected_date}</div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-xs text-slate-400 italic">No ASN dispatch registered yet for this order.</div>
                    )}
                  </div>

                  {/* Dock Goods Receipt (GRN) Card */}
                  <div className="bg-[#0E1526] border border-slate-800 rounded-xl p-5 space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <Package size={18} className="text-teal-400" />
                        <h4 className="text-xs font-bold text-white uppercase tracking-wider">Dock Receipt Note (GRN) Verification</h4>
                      </div>
                      <span className={`text-xs px-2.5 py-0.5 rounded-full font-bold ${
                        selectedPO.grn_info ? 'bg-teal-500/10 text-teal-300 border border-teal-500/20' : 'bg-slate-800 text-slate-500'
                      }`}>
                        {selectedPO.grn_info ? 'Dock Verified' : 'Awaiting Dock Check-In'}
                      </span>
                    </div>

                    {selectedPO.grn_info ? (
                      <div className="grid grid-cols-4 gap-4 text-xs">
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-bold">GRN Number</div>
                          <div className="text-sm font-mono font-bold text-teal-300 mt-1">{selectedPO.grn_info.grn_number}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-bold">Receiving Dock</div>
                          <div className="text-sm font-bold text-white mt-1">{selectedPO.grn_info.dock_bay}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-bold">Storage Bin</div>
                          <div className="text-sm font-mono font-bold text-cyan-400 mt-1">{selectedPO.grn_info.storage_bin}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-bold">CMM Metrology Cert</div>
                          <div className="text-sm font-mono font-bold text-emerald-400 mt-1">{selectedPO.grn_info.cmm_cert}</div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-xs text-slate-400 italic">Awaiting shipment arrival at spaceport dock.</div>
                    )}
                  </div>
                </div>
              )}

              {drawerTab === 'AUDIT' && (
                <div className="space-y-6">
                  {/* 3-Way Match Card */}
                  <div className="bg-[#0E1526] border border-slate-800 rounded-xl p-5 space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                      <div className="flex items-center gap-2">
                        <Award size={18} className="text-purple-400" />
                        <h4 className="text-xs font-bold text-white uppercase tracking-wider">3-Way Match Financial Ledger Reconciler</h4>
                      </div>
                      <span className={`text-xs px-2.5 py-0.5 rounded-full font-bold ${
                        selectedPO.three_way_matched 
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/30' 
                          : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                      }`}>
                        {selectedPO.three_way_matched ? '✓ Reconciled ($0.00 Variance)' : 'Pending Invoice Match'}
                      </span>
                    </div>

                    <div className="grid grid-cols-3 gap-4 text-center">
                      <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
                        <div className="text-[10px] text-slate-400 uppercase font-bold">PO Authorized Amount</div>
                        <div className="text-lg font-mono font-bold text-white mt-1">
                          ${selectedPO.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </div>
                      </div>
                      <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
                        <div className="text-[10px] text-slate-400 uppercase font-bold">GRN Dock Received Value</div>
                        <div className="text-lg font-mono font-bold text-teal-400 mt-1">
                          ${(selectedPO.grn_info ? selectedPO.total_amount : 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </div>
                      </div>
                      <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-800">
                        <div className="text-[10px] text-slate-400 uppercase font-bold">Supplier Tax Invoice</div>
                        <div className="text-lg font-mono font-bold text-purple-400 mt-1">
                          ${(selectedPO.invoice_info ? selectedPO.total_amount : 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Approvals Audit Ledger */}
                  <div>
                    <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-3">Cryptographic Approvals Audit Ledger</h3>
                    <div className="space-y-2">
                      {selectedPO.approvals_audit?.length > 0 ? (
                        selectedPO.approvals_audit.map((app, i) => (
                          <div key={i} className="p-3 bg-slate-900/60 border border-slate-800 rounded-lg text-xs flex items-center justify-between">
                            <div>
                              <div className="font-bold text-white">{app.approver_id}</div>
                              <div className="text-[11px] text-slate-400 mt-0.5">{app.comments}</div>
                            </div>
                            <div className="text-right">
                              <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold text-[10px]">
                                {app.status}
                              </span>
                              <div className="text-[10px] text-slate-500 mt-1">{app.created_at}</div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="text-xs text-slate-500 italic p-3 bg-slate-900/40 rounded-lg border border-slate-800">
                          Auto-authorized under standard Department delegation limits.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
