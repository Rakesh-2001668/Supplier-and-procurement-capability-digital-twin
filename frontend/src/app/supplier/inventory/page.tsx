'use client';

import React, { useState, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import {
  Factory,
  Package,
  Boxes,
  Truck,
  ArrowDownLeft,
  ArrowUpRight,
  Search,
  Filter,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Layers,
  Wrench,
  ShieldCheck,
  Plus,
  Send,
  Eye,
  Copy,
  Check,
  SlidersHorizontal,
  Flame,
  FileCheck,
  ChevronRight,
  TrendingUp,
  Cpu,
  BarChart3,
  X
} from 'lucide-react';
import { apiClient, TEST_SUPPLIER_TENANT_ID } from '@/lib/apiClient';

interface InventoryItem {
  id: string;
  sku: string;
  name: string;
  category: string;
  unit: string;
  quantity_on_hand: number;
  unit_price: number;
  total_value: number;
  min_threshold: number;
  max_capacity: number;
  location: string;
  status: string;
  tenant_id?: string;
  created_at?: string;
  updated_at?: string;
}

interface StockMovement {
  id: string;
  date: string;
  time: string;
  timestamp?: string;
  item_id: string;
  sku: string;
  item_name: string;
  unit: string;
  type: string;
  reference_type: string;
  reference_id: string;
  change_quantity: number;
  balance_after: number;
  notes: string;
  performed_by: string;
  location: string;
}

interface InventoryAnalytics {
  total_skus: number;
  total_units_on_hand: number;
  total_valuation_usd: number;
  low_stock_alerts: number;
  out_of_stock_count: number;
  total_inbound_units: number;
  total_outbound_units: number;
  inventory_health_score: number;
  categories: Record<string, { count: number; units: number; value: number }>;
}

export default function SupplierInventoryPage() {
  const queryClient = useQueryClient();

  // Navigation Tabs
  const [activeTab, setActiveTab] = useState<'CATALOG' | 'FINISHED_GOODS' | 'WIP' | 'RAW_TOOLING' | 'MOVEMENTS'>('CATALOG');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [selectedStatus, setSelectedStatus] = useState<string>('ALL');

  // Modals
  const [showProductionPassModal, setShowProductionPassModal] = useState<boolean>(false);
  const [showCustomerDispatchModal, setShowCustomerDispatchModal] = useState<boolean>(false);
  const [showShopFloorIssueModal, setShowShopFloorIssueModal] = useState<boolean>(false);
  const [showReceiveMillModal, setShowReceiveMillModal] = useState<boolean>(false);
  const [showAdjustModal, setShowAdjustModal] = useState<boolean>(false);

  // Form States - Production Pass to Finished Goods (Goods In)
  const [prodItemId, setProdItemId] = useState<string>('');
  const [prodQty, setProdQty] = useState<string>('50');
  const [prodWorkOrder, setProdWorkOrder] = useState<string>('WO-APEX-9920');
  const [prodCmmCert, setProdCmmCert] = useState<string>('CMM-ZEISS-2026-881');
  const [prodLocation, setProdLocation] = useState<string>('Finished Goods Depot - Bay FG-01');
  const [prodOperator, setProdOperator] = useState<string>('QA Metrology Director');

  // Form States - Customer Dispatch (Goods Out)
  const [dispItemId, setDispItemId] = useState<string>('');
  const [dispQty, setDispQty] = useState<string>('25');
  const [dispBuyer, setDispBuyer] = useState<string>('AlphaHelion Global Aerospace');
  const [dispPoRef, setDispPoRef] = useState<string>('PO-2025-00123');
  const [dispCarrier, setDispCarrier] = useState<string>('FedEx Aerospace Freight');
  const [dispNotes, setDispNotes] = useState<string>('Shipped with Certificate of Conformance (CoC) and AS9100 inspection report');
  const [dispOperator, setDispOperator] = useState<string>('Shipping & Logistics Lead');

  // Form States - Issue Stock to Machine Cell (Goods Out)
  const [issueItemId, setIssueItemId] = useState<string>('');
  const [issueQty, setIssueQty] = useState<string>('20');
  const [issueTargetCell, setIssueTargetCell] = useState<string>('5-Axis CNC Cell 1 - DMG Mori');
  const [issueWorkOrder, setIssueWorkOrder] = useState<string>('WO-APEX-4450');
  const [issueNotes, setIssueNotes] = useState<string>('Allocated for high-precision turbine impeller machining run');
  const [issueOperator, setIssueOperator] = useState<string>('Shop Floor Dispatch Lead');

  // Form States - Receive Mill Stock (Goods In)
  const [millItemId, setMillItemId] = useState<string>('');
  const [millQty, setMillQty] = useState<string>('250');
  const [millHeatNumber, setMillHeatNumber] = useState<string>('HEAT-TI-9941');
  const [millVendor, setMillVendor] = useState<string>('Allegheny Technologies Titanium Mill');
  const [millLocation, setMillLocation] = useState<string>('Raw Material Yard - Bay RM-01');
  const [millNotes, setMillNotes] = useState<string>('Certified Mill Test Report (MTR) verified to AMS 4928 Grade 5');
  const [millOperator, setMillOperator] = useState<string>('Receiving Metallurgist Inspector');

  // Form States - Audit Variance / Scrap Adjustment
  const [adjustItemId, setAdjustItemId] = useState<string>('');
  const [adjustCount, setAdjustCount] = useState<string>('');
  const [adjustReason, setAdjustReason] = useState<string>('Shop Floor Defect Scrap Reconciliation');
  const [adjustNotes, setAdjustNotes] = useState<string>('Machining defect identified during roughing cycle count');
  const [adjustOperator, setAdjustOperator] = useState<string>('Materials Quality Auditor');

  // UI Feedback
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string>('');
  const [copiedSku, setCopiedSku] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(''), 4500);
  };

  // Copy helper
  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSku(text);
    setTimeout(() => setCopiedSku(null), 2000);
  };

  // 1. Fetch Supplier Inventory Items
  const {
    data: items = [],
    isLoading: itemsLoading,
    isRefetching: itemsRefetching,
    refetch: refetchItems
  } = useQuery<InventoryItem[]>({
    queryKey: ['supplier-inventory-items', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/inventory/items?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
      return res.data;
    }
  });

  // 2. Fetch Supplier Stock Movements
  const {
    data: movements = [],
    isLoading: movementsLoading,
    refetch: refetchMovements
  } = useQuery<StockMovement[]>({
    queryKey: ['supplier-inventory-movements', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/inventory/movements?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
      return res.data;
    }
  });

  // 3. Fetch Supplier Inventory Analytics
  const {
    data: analytics,
    isLoading: analyticsLoading,
    refetch: refetchAnalytics
  } = useQuery<InventoryAnalytics>({
    queryKey: ['supplier-inventory-analytics', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/inventory/analytics?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
      return res.data;
    }
  });

  // Refresh All Data
  const handleRefresh = async () => {
    await Promise.all([refetchItems(), refetchMovements(), refetchAnalytics()]);
    showToast('Supplier shop floor inventory synced with digital twin');
  };

  // Categorized breakdown lists
  const finishedGoodsList = useMemo(() => items.filter(it => it.category === 'Finished Goods'), [items]);
  const wipList = useMemo(() => items.filter(it => it.category === 'Work In Progress'), [items]);
  const rawAndToolingList = useMemo(() => items.filter(it => it.category === 'Raw Materials' || it.category === 'Tooling & Fixtures'), [items]);

  // Tab Filtering & Query
  const filteredItems = useMemo(() => {
    return items.filter(it => {
      // Tab filter
      if (activeTab === 'FINISHED_GOODS' && it.category !== 'Finished Goods') return false;
      if (activeTab === 'WIP' && it.category !== 'Work In Progress') return false;
      if (activeTab === 'RAW_TOOLING' && it.category !== 'Raw Materials' && it.category !== 'Tooling & Fixtures') return false;

      // Category filter dropdown
      if (selectedCategory !== 'ALL' && it.category !== selectedCategory) return false;

      // Status filter dropdown
      if (selectedStatus !== 'ALL' && it.status !== selectedStatus) return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const mSku = it.sku.toLowerCase().includes(q);
        const mName = it.name.toLowerCase().includes(q);
        const mLoc = it.location.toLowerCase().includes(q);
        const mCat = it.category.toLowerCase().includes(q);
        if (!mSku && !mName && !mLoc && !mCat) return false;
      }

      return true;
    });
  }, [items, activeTab, selectedCategory, selectedStatus, searchQuery]);

  // Handler: Log Production Output / QA Pass to Finished Goods (Goods In)
  const handleProductionPassSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prodItemId) {
      showToast('Please select an item to receive into Finished Goods.');
      return;
    }
    const qty = parseInt(prodQty, 10);
    if (isNaN(qty) || qty <= 0) {
      showToast('Quantity must be greater than 0.');
      return;
    }

    try {
      setActionLoading(true);
      await apiClient.post('/api/v1/inventory/goods-in', {
        inventory_item_id: prodItemId,
        quantity: qty,
        reference_type: 'GOODS_IN',
        reference_id: prodWorkOrder || 'QA-PASS-AUTO',
        location: prodLocation,
        notes: `Production Completed: Passed CMM inspection [${prodCmmCert}]. Placed in Finished Goods Depot.`,
        performed_by: prodOperator || 'QA Metrology Director',
        tenant_id: TEST_SUPPLIER_TENANT_ID
      });

      showToast(`Logged production pass: +${qty} units transferred to Finished Goods Depot.`);
      setShowProductionPassModal(false);
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-items'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-movements'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-analytics'] });
    } catch (err: any) {
      console.error(err);
      showToast(err.response?.data?.detail || 'Failed to log production receipt.');
    } finally {
      setActionLoading(false);
    }
  };

  // Handler: Customer Dispatch against Customer PO (Goods Out)
  const handleCustomerDispatchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!dispItemId) {
      showToast('Please select a finished goods SKU to dispatch.');
      return;
    }
    const qty = parseInt(dispQty, 10);
    if (isNaN(qty) || qty <= 0) {
      showToast('Dispatch quantity must be greater than 0.');
      return;
    }

    try {
      setActionLoading(true);
      await apiClient.post('/api/v1/inventory/goods-out', {
        inventory_item_id: dispItemId,
        quantity: qty,
        reference_type: 'GOODS_OUT',
        reference_id: `DISP-${dispPoRef}`,
        destination: `${dispBuyer} (${dispCarrier})`,
        notes: `Customer Order Dispatch for ${dispPoRef}. Notes: ${dispNotes}`,
        performed_by: dispOperator || 'Shipping & Logistics Lead',
        tenant_id: TEST_SUPPLIER_TENANT_ID
      });

      showToast(`Dispatched ${qty} units to ${dispBuyer} against PO ${dispPoRef}.`);
      setShowCustomerDispatchModal(false);
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-items'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-movements'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-analytics'] });
    } catch (err: any) {
      console.error(err);
      showToast(err.response?.data?.detail || 'Failed to dispatch customer order.');
    } finally {
      setActionLoading(false);
    }
  };

  // Handler: Issue Raw Material or Tooling to Machine Cell (Goods Out)
  const handleShopFloorIssueSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!issueItemId) {
      showToast('Please select an item to issue to the shop floor.');
      return;
    }
    const qty = parseInt(issueQty, 10);
    if (isNaN(qty) || qty <= 0) {
      showToast('Issue quantity must be greater than 0.');
      return;
    }

    try {
      setActionLoading(true);
      await apiClient.post('/api/v1/inventory/goods-out', {
        inventory_item_id: issueItemId,
        quantity: qty,
        reference_type: 'GOODS_OUT',
        reference_id: issueWorkOrder || 'WO-ISSUE',
        destination: issueTargetCell,
        notes: `Issued to ${issueTargetCell} for ${issueWorkOrder}. Notes: ${issueNotes}`,
        performed_by: issueOperator || 'Shop Floor Dispatch Lead',
        tenant_id: TEST_SUPPLIER_TENANT_ID
      });

      showToast(`Issued ${qty} units to ${issueTargetCell}.`);
      setShowShopFloorIssueModal(false);
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-items'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-movements'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-analytics'] });
    } catch (err: any) {
      console.error(err);
      showToast(err.response?.data?.detail || 'Failed to issue item to shop floor.');
    } finally {
      setActionLoading(false);
    }
  };

  // Handler: Receive Raw Stock Delivery from Mill (Goods In)
  const handleReceiveMillSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!millItemId) {
      showToast('Please select a raw material or tooling SKU.');
      return;
    }
    const qty = parseInt(millQty, 10);
    if (isNaN(qty) || qty <= 0) {
      showToast('Quantity must be greater than 0.');
      return;
    }

    try {
      setActionLoading(true);
      await apiClient.post('/api/v1/inventory/goods-in', {
        inventory_item_id: millItemId,
        quantity: qty,
        reference_type: 'GOODS_IN',
        reference_id: millHeatNumber || 'MILL-IN',
        location: millLocation,
        notes: `Raw Stock Inbound from ${millVendor}. Heat #${millHeatNumber}. Notes: ${millNotes}`,
        performed_by: millOperator || 'Receiving Metallurgist Inspector',
        tenant_id: TEST_SUPPLIER_TENANT_ID
      });

      showToast(`Received ${qty} units from mill into ${millLocation}.`);
      setShowReceiveMillModal(false);
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-items'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-movements'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-analytics'] });
    } catch (err: any) {
      console.error(err);
      showToast(err.response?.data?.detail || 'Failed to receive raw material stock.');
    } finally {
      setActionLoading(false);
    }
  };

  // Handler: Reconcile Physical Stock / Scrap Defect
  const handleAdjustSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adjustItemId) {
      showToast('Please select an item to adjust.');
      return;
    }
    const count = parseInt(adjustCount, 10);
    if (isNaN(count) || count < 0) {
      showToast('Physical count must be a non-negative number.');
      return;
    }

    try {
      setActionLoading(true);
      await apiClient.post('/api/v1/inventory/adjust', {
        inventory_item_id: adjustItemId,
        physical_count: count,
        reason: adjustReason,
        notes: adjustNotes,
        performed_by: adjustOperator || 'Materials Quality Auditor',
        tenant_id: TEST_SUPPLIER_TENANT_ID
      });

      showToast(`Stock verified and adjusted. New balance: ${count} units.`);
      setShowAdjustModal(false);
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-items'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-movements'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-inventory-analytics'] });
    } catch (err: any) {
      console.error(err);
      showToast(err.response?.data?.detail || 'Failed to adjust stock count.');
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-xl shadow-2xl border border-blue-400/30 flex items-center gap-3 animate-slide-up">
          <CheckCircle2 size={18} className="text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
          <button onClick={() => setToastMessage('')} className="ml-2 text-slate-400 hover:text-white">
            <X size={15} />
          </button>
        </div>
      )}

      {/* Header Banner */}
      <div className="bg-gradient-to-r from-[#0B2550] via-[#12366b] to-[#1a4480] text-white rounded-2xl p-7 shadow-lg border border-blue-900/40 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-2 text-blue-200 text-xs font-semibold uppercase tracking-wider mb-1">
              <Factory size={14} className="text-blue-300" />
              Supplier Capability Twin &bull; Plant Floor Logistics
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
              Supplier Inventory Twin
            </h1>
            <p className="text-blue-100/80 text-sm mt-1 max-w-2xl">
              Real-time synchronization between CNC manufacturing cells, shop floor WIP buffers, raw titanium/alloy reserves, and finished goods ready for customer dispatch.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={itemsRefetching}
              className="px-3.5 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg text-sm font-medium flex items-center gap-2 backdrop-blur-sm border border-white/10 transition-all shadow-sm"
              title="Sync with physical shop floor IoT & CMM cells"
            >
              <RefreshCw size={15} className={itemsRefetching ? 'animate-spin' : ''} />
              {itemsRefetching ? 'Syncing...' : 'Sync Shop Floor'}
            </button>

            <button
              onClick={() => {
                const fg = finishedGoodsList[0] || items[0];
                if (fg) setProdItemId(fg.id);
                setShowProductionPassModal(true);
              }}
              className="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-semibold flex items-center gap-1.5 shadow-md transition-all"
            >
              <FileCheck size={16} />
              Log Production Pass
            </button>

            <button
              onClick={() => {
                const fg = finishedGoodsList[0] || items[0];
                if (fg) setDispItemId(fg.id);
                setShowCustomerDispatchModal(true);
              }}
              className="px-3.5 py-2 bg-blue-500 hover:bg-blue-400 text-white rounded-lg text-sm font-semibold flex items-center gap-1.5 shadow-md transition-all"
            >
              <Truck size={16} />
              Dispatch Order
            </button>
          </div>
        </div>
      </div>

      {/* Supplier Operations Quick Actions Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <button
          onClick={() => {
            const raw = rawAndToolingList[0] || items[0];
            if (raw) setMillItemId(raw.id);
            setShowReceiveMillModal(true);
          }}
          className="p-3.5 bg-white rounded-xl border border-slate-200/80 hover:border-blue-400 hover:shadow-md transition-all flex items-center gap-3 text-left group"
        >
          <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-700 flex items-center justify-center group-hover:bg-blue-600 group-hover:text-white transition-colors">
            <ArrowDownLeft size={18} />
          </div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Mill Inbound</div>
            <div className="text-sm font-bold text-slate-800">Receive Raw Stock</div>
          </div>
        </button>

        <button
          onClick={() => {
            const raw = rawAndToolingList[0] || items[0];
            if (raw) setIssueItemId(raw.id);
            setShowShopFloorIssueModal(true);
          }}
          className="p-3.5 bg-white rounded-xl border border-slate-200/80 hover:border-purple-400 hover:shadow-md transition-all flex items-center gap-3 text-left group"
        >
          <div className="w-10 h-10 rounded-lg bg-purple-50 text-purple-700 flex items-center justify-center group-hover:bg-purple-600 group-hover:text-white transition-colors">
            <ArrowUpRight size={18} />
          </div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Shop Floor</div>
            <div className="text-sm font-bold text-slate-800">Issue to CNC Cell</div>
          </div>
        </button>

        <button
          onClick={() => {
            const fg = finishedGoodsList[0] || items[0];
            if (fg) setProdItemId(fg.id);
            setShowProductionPassModal(true);
          }}
          className="p-3.5 bg-white rounded-xl border border-slate-200/80 hover:border-emerald-400 hover:shadow-md transition-all flex items-center gap-3 text-left group"
        >
          <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center group-hover:bg-emerald-600 group-hover:text-white transition-colors">
            <ShieldCheck size={18} />
          </div>
          <div>
            <div className="text-xs text-slate-500 font-medium">QA / Metrology</div>
            <div className="text-sm font-bold text-slate-800">CMM Output to FGI</div>
          </div>
        </button>

        <button
          onClick={() => {
            if (items[0]) setAdjustItemId(items[0].id);
            setShowAdjustModal(true);
          }}
          className="p-3.5 bg-white rounded-xl border border-slate-200/80 hover:border-amber-400 hover:shadow-md transition-all flex items-center gap-3 text-left group"
        >
          <div className="w-10 h-10 rounded-lg bg-amber-50 text-amber-700 flex items-center justify-center group-hover:bg-amber-600 group-hover:text-white transition-colors">
            <SlidersHorizontal size={18} />
          </div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Cycle Count</div>
            <div className="text-sm font-bold text-slate-800">Scrap & Audit Count</div>
          </div>
        </button>
      </div>

      {/* Executive KPI Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Valuation */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-sm flex flex-col justify-between hover:shadow-md transition-shadow">
          <div className="flex justify-between items-start">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Plant Inventory Value</span>
            <span className="p-2 bg-blue-50 text-blue-700 rounded-lg">
              <Boxes size={18} />
            </span>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-black text-slate-900">
              ${(analytics?.total_valuation_usd || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className="text-xs text-slate-500 mt-1 flex items-center gap-1.5">
              <span className="font-semibold text-slate-700">{analytics?.total_skus || 0} active SKUs</span>
              <span>&bull;</span>
              <span>{(analytics?.total_units_on_hand || 0).toLocaleString()} total units</span>
            </div>
          </div>
        </div>

        {/* Finished Goods Ready to Ship */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-sm flex flex-col justify-between hover:shadow-md transition-shadow">
          <div className="flex justify-between items-start">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Finished Goods (FGI)</span>
            <span className="p-2 bg-emerald-50 text-emerald-700 rounded-lg">
              <Package size={18} />
            </span>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-black text-emerald-700">
              {(analytics?.categories?.['Finished Goods']?.units || 0).toLocaleString()} <span className="text-sm font-semibold text-slate-500">units</span>
            </div>
            <div className="text-xs text-slate-500 mt-1 flex items-center gap-1.5">
              <span>Valuation:</span>
              <span className="font-bold text-slate-700">
                ${(analytics?.categories?.['Finished Goods']?.value || 0).toLocaleString()}
              </span>
              <span>&bull;</span>
              <span className="text-emerald-600 font-medium">Ready to dispatch</span>
            </div>
          </div>
        </div>

        {/* Shop Floor WIP Buffers */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-sm flex flex-col justify-between hover:shadow-md transition-shadow">
          <div className="flex justify-between items-start">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Work In Progress (WIP)</span>
            <span className="p-2 bg-purple-50 text-purple-700 rounded-lg">
              <Cpu size={18} />
            </span>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-black text-purple-700">
              {(analytics?.categories?.['Work In Progress']?.units || 0).toLocaleString()} <span className="text-sm font-semibold text-slate-500">units</span>
            </div>
            <div className="text-xs text-slate-500 mt-1 flex items-center gap-1.5">
              <span>Machining value:</span>
              <span className="font-bold text-slate-700">
                ${(analytics?.categories?.['Work In Progress']?.value || 0).toLocaleString()}
              </span>
              <span>&bull;</span>
              <span className="text-purple-600 font-medium">In machine cells</span>
            </div>
          </div>
        </div>

        {/* Raw Materials & Tooling */}
        <div className="bg-white p-5 rounded-xl border border-slate-200/90 shadow-sm flex flex-col justify-between hover:shadow-md transition-shadow">
          <div className="flex justify-between items-start">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Raw Stock & Tooling</span>
            <span className="p-2 bg-amber-50 text-amber-700 rounded-lg">
              <Wrench size={18} />
            </span>
          </div>
          <div className="mt-3">
            <div className="text-2xl font-black text-slate-800">
              {((analytics?.categories?.['Raw Materials']?.units || 0) + (analytics?.categories?.['Tooling & Fixtures']?.units || 0)).toLocaleString()}{' '}
              <span className="text-sm font-semibold text-slate-500">kg/units</span>
            </div>
            <div className="text-xs text-slate-500 mt-1 flex items-center gap-1.5">
              {analytics?.low_stock_alerts ? (
                <span className="text-amber-600 font-semibold flex items-center gap-1">
                  <AlertTriangle size={12} /> {analytics.low_stock_alerts} low stock alert
                </span>
              ) : (
                <span className="text-emerald-600 font-semibold flex items-center gap-1">
                  <CheckCircle2 size={12} /> Tooling levels healthy
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex border-b border-slate-200 bg-white px-4 rounded-xl shadow-sm">
        <button
          onClick={() => setActiveTab('CATALOG')}
          className={`py-4 px-4 font-semibold text-sm flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'CATALOG'
              ? 'border-[#0B2550] text-[#0B2550]'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Boxes size={16} />
          Complete Plant Catalog ({items.length})
        </button>

        <button
          onClick={() => setActiveTab('FINISHED_GOODS')}
          className={`py-4 px-4 font-semibold text-sm flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'FINISHED_GOODS'
              ? 'border-emerald-600 text-emerald-700 font-bold'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Package size={16} />
          Finished Goods Depot ({finishedGoodsList.length})
        </button>

        <button
          onClick={() => setActiveTab('WIP')}
          className={`py-4 px-4 font-semibold text-sm flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'WIP'
              ? 'border-purple-600 text-purple-700 font-bold'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Cpu size={16} />
          Shop Floor WIP ({wipList.length})
        </button>

        <button
          onClick={() => setActiveTab('RAW_TOOLING')}
          className={`py-4 px-4 font-semibold text-sm flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'RAW_TOOLING'
              ? 'border-amber-600 text-amber-700 font-bold'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Wrench size={16} />
          Raw Stock & Tooling ({rawAndToolingList.length})
        </button>

        <button
          onClick={() => setActiveTab('MOVEMENTS')}
          className={`py-4 px-4 font-semibold text-sm flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'MOVEMENTS'
              ? 'border-blue-600 text-blue-700 font-bold'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Clock size={16} />
          Movement Ledger ({movements.length})
        </button>
      </div>

      {/* TAB CONTENT: CATALOG / FINISHED GOODS / WIP / RAW_TOOLING */}
      {activeTab !== 'MOVEMENTS' && (
        <div className="space-y-4">
          {/* Search & Filter Bar */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-white p-3.5 rounded-xl border border-slate-200/90 shadow-sm">
            <div className="relative w-full sm:w-80">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search SKU, component name, machine cell..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-sm bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto">
              <select
                value={selectedCategory}
                onChange={e => setSelectedCategory(e.target.value)}
                className="px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 font-medium focus:outline-none"
              >
                <option value="ALL">All Categories</option>
                <option value="Finished Goods">Finished Goods</option>
                <option value="Work In Progress">Work In Progress</option>
                <option value="Raw Materials">Raw Materials</option>
                <option value="Tooling & Fixtures">Tooling & Fixtures</option>
              </select>

              <select
                value={selectedStatus}
                onChange={e => setSelectedStatus(e.target.value)}
                className="px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 font-medium focus:outline-none"
              >
                <option value="ALL">All Statuses</option>
                <option value="IN_STOCK">In Stock</option>
                <option value="LOW_STOCK">Low Stock</option>
                <option value="OUT_OF_STOCK">Out of Stock</option>
              </select>
            </div>
          </div>

          {/* Items Table */}
          <div className="bg-white rounded-xl border border-slate-200/90 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="bg-slate-50/80 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                    <th className="py-3 px-4">Part / SKU</th>
                    <th className="py-3 px-4">Category</th>
                    <th className="py-3 px-4">Physical Location</th>
                    <th className="py-3 px-4 text-right">On-Hand Quantity</th>
                    <th className="py-3 px-4 text-right">Unit Price</th>
                    <th className="py-3 px-4 text-right">Total Valuation</th>
                    <th className="py-3 px-4 text-center">Status</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {itemsLoading ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-400">
                        <RefreshCw size={24} className="animate-spin mx-auto mb-2 text-blue-500" />
                        Loading plant inventory from digital twin...
                      </td>
                    </tr>
                  ) : filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-400">
                        No inventory items found matching your filters.
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map(item => {
                      const isLowStock = item.status === 'LOW_STOCK';
                      const isOutOfStock = item.status === 'OUT_OF_STOCK';

                      return (
                        <tr key={item.id} className="hover:bg-slate-50/70 transition-colors">
                          <td className="py-3.5 px-4">
                            <div className="font-semibold text-slate-900">{item.name}</div>
                            <div className="flex items-center gap-1.5 mt-0.5">
                              <span className="font-mono text-xs text-blue-600 font-medium">{item.sku}</span>
                              <button
                                onClick={() => handleCopy(item.sku)}
                                className="text-slate-400 hover:text-slate-600"
                                title="Copy SKU"
                              >
                                {copiedSku === item.sku ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
                              </button>
                            </div>
                          </td>

                          <td className="py-3.5 px-4">
                            <span
                              className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                                item.category === 'Finished Goods'
                                  ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/60'
                                  : item.category === 'Work In Progress'
                                  ? 'bg-purple-50 text-purple-700 border border-purple-200/60'
                                  : item.category === 'Raw Materials'
                                  ? 'bg-blue-50 text-blue-700 border border-blue-200/60'
                                  : 'bg-amber-50 text-amber-700 border border-amber-200/60'
                              }`}
                            >
                              {item.category === 'Finished Goods' && <Package size={10} />}
                              {item.category === 'Work In Progress' && <Cpu size={10} />}
                              {item.category === 'Raw Materials' && <Layers size={10} />}
                              {item.category === 'Tooling & Fixtures' && <Wrench size={10} />}
                              {item.category}
                            </span>
                          </td>

                          <td className="py-3.5 px-4">
                            <div className="text-xs font-medium text-slate-700">{item.location}</div>
                            <div className="text-[11px] text-slate-400">
                              Threshold: {item.min_threshold} {item.unit}
                            </div>
                          </td>

                          <td className="py-3.5 px-4 text-right">
                            <div className="font-bold text-slate-900 text-base">
                              {item.quantity_on_hand.toLocaleString()} <span className="text-xs font-normal text-slate-500">{item.unit}</span>
                            </div>
                            {item.category === 'Finished Goods' && (
                              <div className="text-[11px] text-emerald-600 font-medium">
                                ATP: {item.quantity_on_hand.toLocaleString()} {item.unit}
                              </div>
                            )}
                          </td>

                          <td className="py-3.5 px-4 text-right font-medium text-slate-600">
                            ${item.unit_price.toFixed(2)}
                          </td>

                          <td className="py-3.5 px-4 text-right font-bold text-slate-900">
                            ${(item.quantity_on_hand * item.unit_price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>

                          <td className="py-3.5 px-4 text-center">
                            <span
                              className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-bold ${
                                isOutOfStock
                                  ? 'bg-rose-100 text-rose-800'
                                  : isLowStock
                                  ? 'bg-amber-100 text-amber-800'
                                  : 'bg-emerald-100 text-emerald-800'
                              }`}
                            >
                              {item.status.replace('_', ' ')}
                            </span>
                          </td>

                          <td className="py-3.5 px-4 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              {item.category === 'Finished Goods' ? (
                                <button
                                  onClick={() => {
                                    setDispItemId(item.id);
                                    setShowCustomerDispatchModal(true);
                                  }}
                                  className="px-2.5 py-1 text-xs font-semibold bg-blue-50 text-blue-700 hover:bg-blue-100 rounded-md transition-colors"
                                  title="Dispatch against Customer Purchase Order"
                                >
                                  Dispatch
                                </button>
                              ) : (
                                <button
                                  onClick={() => {
                                    setIssueItemId(item.id);
                                    setShowShopFloorIssueModal(true);
                                  }}
                                  className="px-2.5 py-1 text-xs font-semibold bg-purple-50 text-purple-700 hover:bg-purple-100 rounded-md transition-colors"
                                  title="Issue to CNC Cell"
                                >
                                  Issue
                                </button>
                              )}

                              <button
                                onClick={() => {
                                  setAdjustItemId(item.id);
                                  setAdjustCount(String(item.quantity_on_hand));
                                  setShowAdjustModal(true);
                                }}
                                className="p-1 text-slate-400 hover:text-slate-700 rounded-md"
                                title="Adjust physical stock / defect count"
                              >
                                <SlidersHorizontal size={14} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB CONTENT: MOVEMENTS LEDGER */}
      {activeTab === 'MOVEMENTS' && (
        <div className="bg-white rounded-xl border border-slate-200/90 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
            <div>
              <h3 className="font-bold text-slate-800">Shop Floor & Logistics Audit Ledger</h3>
              <p className="text-xs text-slate-500">Immutable trail of mill deliveries, shop floor allocations, QA completions, and customer dispatches.</p>
            </div>
            <button
              onClick={() => refetchMovements()}
              className="text-xs font-medium text-blue-600 hover:underline flex items-center gap-1"
            >
              <RefreshCw size={12} /> Refresh Ledger
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="bg-slate-50/80 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  <th className="py-3 px-4">Date & Time</th>
                  <th className="py-3 px-4">Movement Type</th>
                  <th className="py-3 px-4">Part / SKU</th>
                  <th className="py-3 px-4">Reference & Lot</th>
                  <th className="py-3 px-4 text-right">Quantity Delta</th>
                  <th className="py-3 px-4 text-right">Balance After</th>
                  <th className="py-3 px-4">Handled By</th>
                  <th className="py-3 px-4">Operation Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {movementsLoading ? (
                  <tr>
                    <td colSpan={8} className="py-12 text-center text-slate-400">
                      Loading movements ledger...
                    </td>
                  </tr>
                ) : movements.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-12 text-center text-slate-400">
                      No stock movement records found for this supplier twin.
                    </td>
                  </tr>
                ) : (
                  movements.map(m => {
                    const isPositive = m.change_quantity > 0;
                    return (
                      <tr key={m.id} className="hover:bg-slate-50/70 transition-colors">
                        <td className="py-3 px-4 whitespace-nowrap">
                          <div className="font-medium text-slate-800">{m.date}</div>
                          <div className="text-[11px] text-slate-400">{m.time}</div>
                        </td>

                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold ${
                              m.type === 'Goods In'
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/60'
                                : m.type === 'Goods Out'
                                ? 'bg-blue-50 text-blue-700 border border-blue-200/60'
                                : 'bg-amber-50 text-amber-700 border border-amber-200/60'
                            }`}
                          >
                            {m.type === 'Goods In' && <ArrowDownLeft size={11} />}
                            {m.type === 'Goods Out' && <ArrowUpRight size={11} />}
                            {m.type === 'Adjustment' && <SlidersHorizontal size={11} />}
                            {m.type}
                          </span>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-semibold text-slate-800">{m.item_name}</div>
                          <div className="text-xs font-mono text-blue-600">{m.sku}</div>
                        </td>

                        <td className="py-3 px-4 font-mono text-xs text-slate-600">
                          {m.reference_id || 'N/A'}
                        </td>

                        <td className="py-3 px-4 text-right">
                          <span
                            className={`font-black text-sm ${
                              isPositive ? 'text-emerald-600' : 'text-slate-800'
                            }`}
                          >
                            {isPositive ? `+${m.change_quantity}` : m.change_quantity} {m.unit}
                          </span>
                        </td>

                        <td className="py-3 px-4 text-right font-medium text-slate-600">
                          {m.balance_after} {m.unit}
                        </td>

                        <td className="py-3 px-4 text-xs font-medium text-slate-700">
                          {m.performed_by || 'Plant Staff'}
                        </td>

                        <td className="py-3 px-4 text-xs text-slate-500 max-w-xs truncate" title={m.notes}>
                          {m.notes || '-'}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* MODAL 1: LOG PRODUCTION RUN / QA PASS TO FINISHED GOODS */}
      {showProductionPassModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 animate-in fade-in zoom-in duration-150">
            <div className="flex justify-between items-center pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2 text-emerald-700 font-bold text-lg">
                <FileCheck size={20} />
                Log Production Pass to Finished Goods
              </div>
              <button onClick={() => setShowProductionPassModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleProductionPassSubmit} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Target Finished Product</label>
                <select
                  value={prodItemId}
                  onChange={e => setProdItemId(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-800 font-medium focus:ring-2 focus:ring-emerald-500"
                  required
                >
                  <option value="">-- Select Finished Product SKU --</option>
                  {items.map(it => (
                    <option key={it.id} value={it.id}>
                      {it.sku} &bull; {it.name} ({it.quantity_on_hand} {it.unit} on-hand)
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Pass Quantity</label>
                  <input
                    type="number"
                    min="1"
                    value={prodQty}
                    onChange={e => setProdQty(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Work Order Ref</label>
                  <input
                    type="text"
                    value={prodWorkOrder}
                    onChange={e => setProdWorkOrder(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">CMM Metrology Inspection Cert #</label>
                <input
                  type="text"
                  value={prodCmmCert}
                  onChange={e => setProdCmmCert(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                  placeholder="e.g. CMM-ZEISS-2026-990"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Staging Depot Location</label>
                <input
                  type="text"
                  value={prodLocation}
                  onChange={e => setProdLocation(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowProductionPassModal(false)}
                  className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-5 py-2 text-sm font-bold bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg shadow flex items-center gap-2"
                >
                  {actionLoading ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={16} />}
                  Confirm & Transfer to FGI
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 2: CUSTOMER DISPATCH AGAINST PO */}
      {showCustomerDispatchModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 animate-in fade-in zoom-in duration-150">
            <div className="flex justify-between items-center pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2 text-blue-700 font-bold text-lg">
                <Truck size={20} />
                Customer Order Dispatch (Goods Out)
              </div>
              <button onClick={() => setShowCustomerDispatchModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCustomerDispatchSubmit} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Select Finished Good SKU</label>
                <select
                  value={dispItemId}
                  onChange={e => setDispItemId(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-800 font-medium focus:ring-2 focus:ring-blue-500"
                  required
                >
                  <option value="">-- Select SKU --</option>
                  {items.map(it => (
                    <option key={it.id} value={it.id}>
                      {it.sku} &bull; {it.name} ({it.quantity_on_hand} {it.unit} on-hand)
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Dispatch Quantity</label>
                  <input
                    type="number"
                    min="1"
                    value={dispQty}
                    onChange={e => setDispQty(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase mb-1 flex justify-between items-center">
                    <span>Customer PO Ref</span>
                    <span className="text-[10px] text-blue-600 font-semibold">Active POs available</span>
                  </label>
                  <input
                    type="text"
                    list="active-po-list"
                    value={dispPoRef}
                    onChange={e => {
                      const val = e.target.value;
                      setDispPoRef(val);
                      if (val.includes('00123')) setDispBuyer('SupplyTwin Enterprise Corp');
                      else if (val.includes('00089')) setDispBuyer('Global Aerospace Systems Corp');
                      else if (val.includes('00045')) setDispBuyer('North American Defense Corp');
                    }}
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm font-mono font-medium"
                    placeholder="e.g. PO-2025-00123"
                  />
                  <datalist id="active-po-list">
                    <option value="PO-2025-00123">SupplyTwin Enterprise Corp</option>
                    <option value="PO-2025-00089">Global Aerospace Systems Corp</option>
                    <option value="PO-2025-00045">North American Defense Corp</option>
                  </datalist>
                </div>
              </div>

              <div className="bg-blue-50/60 p-2.5 rounded-lg border border-blue-200/60 text-[11px] text-blue-800 flex items-center gap-1.5">
                <CheckCircle2 size={13} className="text-blue-600 shrink-0" />
                <span>Dispatching against this PO will automatically update the PO status to <strong>SHIPPED</strong> and register an Advance Ship Notice (ASN).</span>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Customer Organization</label>
                <input
                  type="text"
                  value={dispBuyer}
                  onChange={e => setDispBuyer(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Carrier / Logistics Provider</label>
                <input
                  type="text"
                  value={dispCarrier}
                  onChange={e => setDispCarrier(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Shipping & CoC Notes</label>
                <textarea
                  rows={2}
                  value={dispNotes}
                  onChange={e => setDispNotes(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowCustomerDispatchModal(false)}
                  className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-5 py-2 text-sm font-bold bg-blue-600 hover:bg-blue-500 text-white rounded-lg shadow flex items-center gap-2"
                >
                  {actionLoading ? <RefreshCw size={14} className="animate-spin" /> : <Send size={16} />}
                  Confirm Dispatch & Decrement Stock
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 3: ISSUE RAW STOCK TO MACHINE CELL */}
      {showShopFloorIssueModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 animate-in fade-in zoom-in duration-150">
            <div className="flex justify-between items-center pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2 text-purple-700 font-bold text-lg">
                <Cpu size={20} />
                Issue to CNC Machine Cell
              </div>
              <button onClick={() => setShowShopFloorIssueModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleShopFloorIssueSubmit} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Select Raw Stock or Tooling</label>
                <select
                  value={issueItemId}
                  onChange={e => setIssueItemId(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-800 font-medium focus:ring-2 focus:ring-purple-500"
                  required
                >
                  <option value="">-- Select Material / Tooling --</option>
                  {items.map(it => (
                    <option key={it.id} value={it.id}>
                      {it.sku} &bull; {it.name} ({it.quantity_on_hand} {it.unit} on-hand)
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Issue Quantity</label>
                  <input
                    type="number"
                    min="1"
                    value={issueQty}
                    onChange={e => setIssueQty(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Target CNC Cell</label>
                  <input
                    type="text"
                    value={issueTargetCell}
                    onChange={e => setIssueTargetCell(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Production Work Order</label>
                <input
                  type="text"
                  value={issueWorkOrder}
                  onChange={e => setIssueWorkOrder(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowShopFloorIssueModal(false)}
                  className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-5 py-2 text-sm font-bold bg-purple-600 hover:bg-purple-500 text-white rounded-lg shadow flex items-center gap-2"
                >
                  {actionLoading ? <RefreshCw size={14} className="animate-spin" /> : <ArrowUpRight size={16} />}
                  Issue Material to Cell
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 4: RECEIVE RAW MATERIAL FROM MILL */}
      {showReceiveMillModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 animate-in fade-in zoom-in duration-150">
            <div className="flex justify-between items-center pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2 text-blue-700 font-bold text-lg">
                <ArrowDownLeft size={20} />
                Receive Raw Stock Inbound (Mill Delivery)
              </div>
              <button onClick={() => setShowReceiveMillModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleReceiveMillSubmit} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Raw Material SKU</label>
                <select
                  value={millItemId}
                  onChange={e => setMillItemId(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-800 font-medium focus:ring-2 focus:ring-blue-500"
                  required
                >
                  <option value="">-- Select Material / Alloy --</option>
                  {items.map(it => (
                    <option key={it.id} value={it.id}>
                      {it.sku} &bull; {it.name} ({it.quantity_on_hand} {it.unit} on-hand)
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Delivered Quantity</label>
                  <input
                    type="number"
                    min="1"
                    value={millQty}
                    onChange={e => setMillQty(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Heat / MTR Lot #</label>
                  <input
                    type="text"
                    value={millHeatNumber}
                    onChange={e => setMillHeatNumber(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Mill Supplier Origin</label>
                <input
                  type="text"
                  value={millVendor}
                  onChange={e => setMillVendor(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Staging Yard Bay</label>
                <input
                  type="text"
                  value={millLocation}
                  onChange={e => setMillLocation(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowReceiveMillModal(false)}
                  className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-5 py-2 text-sm font-bold bg-blue-600 hover:bg-blue-500 text-white rounded-lg shadow flex items-center gap-2"
                >
                  {actionLoading ? <RefreshCw size={14} className="animate-spin" /> : <ArrowDownLeft size={16} />}
                  Receive Stock & Log MTR
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 5: AUDIT VARIANCE / DEFECT SCRAP ADJUSTMENT */}
      {showAdjustModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-200 animate-in fade-in zoom-in duration-150">
            <div className="flex justify-between items-center pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2 text-amber-700 font-bold text-lg">
                <SlidersHorizontal size={20} />
                Physical Stock Reconciliation / Scrap
              </div>
              <button onClick={() => setShowAdjustModal(false)} className="text-slate-400 hover:text-slate-600">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleAdjustSubmit} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Select SKU to Reconcile</label>
                <select
                  value={adjustItemId}
                  onChange={e => {
                    setAdjustItemId(e.target.value);
                    const it = items.find(i => i.id === e.target.value);
                    if (it) setAdjustCount(String(it.quantity_on_hand));
                  }}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-800 font-medium focus:ring-2 focus:ring-amber-500"
                  required
                >
                  <option value="">-- Select SKU --</option>
                  {items.map(it => (
                    <option key={it.id} value={it.id}>
                      {it.sku} &bull; {it.name} (Current: {it.quantity_on_hand} {it.unit})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">New Verified Physical Balance</label>
                <input
                  type="number"
                  min="0"
                  value={adjustCount}
                  onChange={e => setAdjustCount(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Reconciliation Reason</label>
                <select
                  value={adjustReason}
                  onChange={e => setAdjustReason(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs"
                >
                  <option value="Shop Floor Defect Scrap Reconciliation">Shop Floor Defect Scrap Reconciliation</option>
                  <option value="CMM Metrology Geometric Reject">CMM Metrology Geometric Reject</option>
                  <option value="Routine Plant Physical Cycle Count">Routine Plant Physical Cycle Count</option>
                  <option value="Tool Wear Replaced / Scrapped">Tool Wear Replaced / Scrapped</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase mb-1">Audit Details & Quality Notes</label>
                <textarea
                  rows={2}
                  value={adjustNotes}
                  onChange={e => setAdjustNotes(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowAdjustModal(false)}
                  className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-5 py-2 text-sm font-bold bg-amber-600 hover:bg-amber-500 text-white rounded-lg shadow flex items-center gap-2"
                >
                  {actionLoading ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={16} />}
                  Confirm Reconciled Balance
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
