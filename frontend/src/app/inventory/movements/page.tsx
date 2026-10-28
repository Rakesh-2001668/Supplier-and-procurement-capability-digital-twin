'use client';

import React, { useState, useMemo } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { 
  ArrowLeft, 
  ArrowDownLeft, 
  ArrowUpRight, 
  SlidersHorizontal, 
  Search, 
  Download, 
  RefreshCw, 
  Filter, 
  Calendar, 
  Boxes, 
  Layers, 
  Plus, 
  Minus, 
  X, 
  CheckCircle2, 
  AlertTriangle, 
  Box,
  TrendingUp,
  TrendingDown
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

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

interface InventoryItem {
  id: string;
  sku: string;
  name: string;
  unit: string;
  quantity_on_hand: number;
  location: string;
}

interface AnalyticsData {
  total_inbound_units: number;
  total_outbound_units: number;
  total_skus: number;
}

export default function StockMovementsPage() {
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [selectedRow, setSelectedRow] = useState<StockMovement | null>(null);

  // Modal States
  const [isReceiveModalOpen, setIsReceiveModalOpen] = useState(false);
  const [isIssueModalOpen, setIsIssueModalOpen] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState('');
  const [actionSuccess, setActionSuccess] = useState('');

  // Form States for Receive / Issue
  const [formSku, setFormSku] = useState('');
  const [formQty, setFormQty] = useState(10);
  const [formRef, setFormRef] = useState('');
  const [formNotes, setFormNotes] = useState('');
  const [formDestination, setFormDestination] = useState('Assembly Production');
  const [formStaff, setFormStaff] = useState('Operations Desk');

  // Fetch Movements from Backend
  const { data: movements = [], isLoading: isLoadingMovements, refetch: refetchMovements } = useQuery<StockMovement[]>({
    queryKey: ['inventory', 'movements'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/inventory/movements');
      return res.data || [];
    }
  });

  // Fetch Inventory items for dropdown
  const { data: items = [] } = useQuery<InventoryItem[]>({
    queryKey: ['inventory', 'items'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/inventory/items');
      return res.data || [];
    }
  });

  // Fetch Analytics
  const { data: analytics } = useQuery<AnalyticsData>({
    queryKey: ['inventory', 'analytics'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/inventory/analytics');
      return res.data || { total_inbound_units: 0, total_outbound_units: 0, total_skus: 0 };
    }
  });

  // Filtered movements
  const filteredMovements = useMemo(() => {
    return movements.filter(m => {
      const matchType = typeFilter === 'ALL' || 
        (typeFilter === 'IN' && m.change_quantity > 0) ||
        (typeFilter === 'OUT' && m.change_quantity < 0) ||
        (typeFilter === 'ADJUST' && m.reference_type === 'CYCLE_COUNT_ADJUSTMENT');

      const q = searchTerm.toLowerCase();
      const matchSearch = !searchTerm ||
        m.sku.toLowerCase().includes(q) ||
        m.item_name.toLowerCase().includes(q) ||
        m.reference_id.toLowerCase().includes(q) ||
        m.notes.toLowerCase().includes(q);

      return matchType && matchSearch;
    });
  }, [movements, typeFilter, searchTerm]);

  // Handle Receive Submit
  const handleReceive = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formSku || formQty <= 0) return;
    setActionLoading(true);
    setActionError('');
    setActionSuccess('');
    try {
      const targetItem = items.find(i => i.sku === formSku);
      await apiClient.post('/api/v1/inventory/goods-in', {
        sku: formSku,
        item_name: targetItem?.name || formSku,
        quantity: Number(formQty),
        unit: targetItem?.unit || 'pcs',
        reference_type: 'GOODS_IN',
        reference_id: formRef || `RCV-${Date.now().toString().slice(-6)}`,
        notes: formNotes || 'Direct inbound receipt',
        performed_by: formStaff
      });
      setActionSuccess(`Received +${formQty} units of ${formSku}!`);
      queryClient.invalidateQueries({ queryKey: ['inventory'] });
      setTimeout(() => {
        setIsReceiveModalOpen(false);
        setActionSuccess('');
      }, 1200);
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || err?.message || 'Failed to receive goods');
    } finally {
      setActionLoading(false);
    }
  };

  // Handle Issue Submit
  const handleIssue = async (e: React.FormEvent) => {
    e.preventDefault();
    const targetItem = items.find(i => i.sku === formSku);
    if (!targetItem) {
      setActionError('Please select a valid item.');
      return;
    }
    if (formQty <= 0) {
      setActionError('Quantity must be greater than 0.');
      return;
    }
    if (targetItem.quantity_on_hand < formQty) {
      setActionError(`Insufficient stock! Available: ${targetItem.quantity_on_hand} ${targetItem.unit}`);
      return;
    }
    setActionLoading(true);
    setActionError('');
    setActionSuccess('');
    try {
      await apiClient.post('/api/v1/inventory/goods-out', {
        inventory_item_id: targetItem.id,
        quantity: Number(formQty),
        reference_type: 'GOODS_OUT',
        reference_id: formRef || `DISP-${Date.now().toString().slice(-6)}`,
        destination: formDestination,
        notes: formNotes || `Dispatched to ${formDestination}`,
        performed_by: formStaff
      });
      setActionSuccess(`Dispatched -${formQty} units of ${formSku}!`);
      queryClient.invalidateQueries({ queryKey: ['inventory'] });
      setTimeout(() => {
        setIsIssueModalOpen(false);
        setActionSuccess('');
      }, 1200);
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || err?.message || 'Failed to dispatch goods');
    } finally {
      setActionLoading(false);
    }
  };

  // Export CSV
  const handleExportCSV = () => {
    if (filteredMovements.length === 0) return;
    const headers = ['Date', 'Time', 'SKU', 'Item Name', 'Type', 'Change Quantity', 'Balance After', 'Reference ID', 'Performed By', 'Notes'];
    const rows = filteredMovements.map(m => [
      m.date,
      m.time,
      m.sku,
      `"${m.item_name}"`,
      m.type,
      m.change_quantity,
      m.balance_after,
      m.reference_id,
      `"${m.performed_by}"`,
      `"${m.notes.replace(/"/g, '""')}"`
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `Stock_Movements_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="p-4 sm:p-8 animate-fade-in-up bg-[#f8fafc] min-h-screen">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4 mb-6">
        <div>
          <div className="text-[10px] font-black tracking-widest uppercase text-slate-500 mb-1 flex items-center gap-2">
            <Link href="/inventory" className="hover:text-blue-600 transition-colors flex items-center gap-1">
              <ArrowLeft size={12} /> INVENTORY
            </Link> 
            <span className="text-slate-300">›</span> 
            <span className="text-blue-600 font-bold">STOCK MOVEMENTS LEDGER</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-3">
            <Layers className="text-blue-600" size={28} />
            Stock Movements & Audit Trail
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Real-time chronological record of every inbound delivery, outbound production dispatch, and cycle count adjustment.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => {
              setFormSku(items[0]?.sku || '');
              setFormRef('');
              setFormNotes('');
              setIsReceiveModalOpen(true);
            }}
            style={{ backgroundColor: '#059669', color: '#ffffff' }}
            className="btn-goods-in px-4 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-xl shadow-md transition-all flex items-center gap-1.5"
          >
            <ArrowDownLeft size={15} /> Receive (Goods In)
          </button>
          <button
            onClick={() => {
              setFormSku(items[0]?.sku || '');
              setFormRef('');
              setFormNotes('');
              setIsIssueModalOpen(true);
            }}
            style={{ backgroundColor: '#d97706', color: '#ffffff' }}
            className="btn-goods-out px-4 py-2 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 rounded-xl shadow-md transition-all flex items-center gap-1.5"
          >
            <ArrowUpRight size={15} /> Dispatch (Goods Out)
          </button>
          <button
            onClick={handleExportCSV}
            className="px-4 py-2 text-xs font-bold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-xl shadow-sm transition-all flex items-center gap-1.5"
          >
            <Download size={14} /> Export CSV
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-black shrink-0">
            <Boxes size={22} />
          </div>
          <div>
            <div className="text-xl font-black text-[#0B2550]">{movements.length}</div>
            <div className="text-xs font-bold text-slate-500">Total Transactions</div>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-black shrink-0">
            <TrendingUp size={22} />
          </div>
          <div>
            <div className="text-xl font-black text-emerald-600">+{analytics?.total_inbound_units || 0}</div>
            <div className="text-xs font-bold text-slate-500">Total Goods In (Units)</div>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-red-50 text-red-600 flex items-center justify-center font-black shrink-0">
            <TrendingDown size={22} />
          </div>
          <div>
            <div className="text-xl font-black text-red-600">-{analytics?.total_outbound_units || 0}</div>
            <div className="text-xs font-bold text-slate-500">Total Goods Out (Units)</div>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center font-black shrink-0">
            <Layers size={22} />
          </div>
          <div>
            <div className="text-xl font-black text-purple-600">
              {((analytics?.total_inbound_units || 0) - (analytics?.total_outbound_units || 0)) > 0 ? '+' : ''}
              {(analytics?.total_inbound_units || 0) - (analytics?.total_outbound_units || 0)}
            </div>
            <div className="text-xs font-bold text-slate-500">Net Stock Flow (Units)</div>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          {['ALL', 'IN', 'OUT', 'ADJUST'].map((tab) => (
            <button
              key={tab}
              onClick={() => setTypeFilter(tab)}
              className={`px-3.5 py-1.5 text-xs font-bold rounded-xl transition-all ${
                typeFilter === tab
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {tab === 'ALL' && 'All Types'}
              {tab === 'IN' && 'Goods In (Inbound)'}
              {tab === 'OUT' && 'Goods Out (Dispatched)'}
              {tab === 'ADJUST' && 'Cycle Count Adjustments'}
            </button>
          ))}
        </div>

        <div className="relative min-w-[260px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search SKU, reference, notes..."
            className="w-full pl-9 pr-4 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:border-blue-500 outline-none transition-all"
          />
        </div>
      </div>

      {/* Transactions Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="bg-slate-50 text-slate-500 font-extrabold uppercase tracking-wider border-b border-slate-100">
              <tr>
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4">Item & SKU</th>
                <th className="py-3 px-3 text-center">Movement Type</th>
                <th className="py-3 px-3 text-center">Quantity Delta</th>
                <th className="py-3 px-3 text-center">Balance After</th>
                <th className="py-3 px-4">Reference ID</th>
                <th className="py-3 px-4">Operator / Location</th>
                <th className="py-3 px-4">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoadingMovements ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-slate-400">
                    <RefreshCw className="animate-spin inline-block mr-2" size={16} />
                    Loading stock movements ledger...
                  </td>
                </tr>
              ) : filteredMovements.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-slate-400">
                    No stock movement records match your filter criteria.
                  </td>
                </tr>
              ) : (
                filteredMovements.map((tx) => {
                  const isIn = tx.change_quantity > 0;
                  const isAdjust = tx.reference_type === 'CYCLE_COUNT_ADJUSTMENT';

                  return (
                    <tr
                      key={tx.id}
                      onClick={() => setSelectedRow(tx)}
                      className="hover:bg-blue-50/40 cursor-pointer transition-colors"
                    >
                      <td className="py-3 px-4 font-mono text-[11px] text-slate-500">
                        <div className="font-bold text-slate-700">{tx.date}</div>
                        <div className="text-[10px] text-slate-400">{tx.time}</div>
                      </td>

                      <td className="py-3 px-4">
                        <div className="font-mono text-xs font-bold text-blue-600">{tx.sku}</div>
                        <div className="font-medium text-slate-800 truncate max-w-[180px]">{tx.item_name}</div>
                      </td>

                      <td className="py-3 px-3 text-center">
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-extrabold ${
                            isAdjust
                              ? 'bg-amber-50 text-amber-700 border border-amber-200'
                              : isIn
                              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                              : 'bg-red-50 text-red-700 border border-red-200'
                          }`}
                        >
                          {isAdjust ? '⚖️ Adjustment' : isIn ? '↓ Goods In' : '↑ Goods Out'}
                        </span>
                      </td>

                      <td className="py-3 px-3 text-center">
                        <span
                          className={`font-mono font-black text-xs ${
                            isIn ? 'text-emerald-600' : 'text-red-600'
                          }`}
                        >
                          {isIn ? `+${tx.change_quantity}` : tx.change_quantity} {tx.unit}
                        </span>
                      </td>

                      <td className="py-3 px-3 text-center font-mono font-bold text-slate-800">
                        {tx.balance_after} {tx.unit}
                      </td>

                      <td className="py-3 px-4 font-mono font-semibold text-slate-600">
                        {tx.reference_id}
                      </td>

                      <td className="py-3 px-4">
                        <div className="font-semibold text-slate-700">{tx.performed_by}</div>
                        <div className="text-[10px] text-slate-400">{tx.location}</div>
                      </td>

                      <td className="py-3 px-4 text-slate-500 truncate max-w-[200px]" title={tx.notes}>
                        {tx.notes}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      
      {/* Floating Sticky Quick Action Bar */}
      <div className="fixed bottom-6 right-6 z-40 bg-white/95 backdrop-blur-md border border-slate-200 shadow-2xl rounded-2xl p-2.5 flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-4 duration-300 ring-1 ring-slate-900/5">
        <button
          onClick={() => {
            setFormSku(items[0]?.sku || '');
            setFormRef('');
            setFormNotes('');
            setIsReceiveModalOpen(true);
          }}
          style={{ backgroundColor: '#059669', color: '#ffffff' }}
          className="btn-goods-in bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-xl font-black text-xs shadow-md shadow-emerald-600/20 transition-all flex items-center gap-1.5 active:scale-95"
        >
          <ArrowDownLeft className="w-4 h-4 text-white" />
          <span>Receive (Goods In)</span>
        </button>
        <button
          onClick={() => {
            setFormSku(items[0]?.sku || '');
            setFormRef('');
            setFormNotes('');
            setIsIssueModalOpen(true);
          }}
          style={{ backgroundColor: '#d97706', color: '#ffffff' }}
          className="btn-goods-out bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 rounded-xl font-black text-xs shadow-md shadow-amber-600/20 transition-all flex items-center gap-1.5 active:scale-95"
        >
          <ArrowUpRight className="w-4 h-4 text-white" />
          <span>Dispatch (Goods Out)</span>
        </button>
      </div>

      {/* Receive Modal (Strict fit-to-screen) */}
      {isReceiveModalOpen && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm p-3 sm:p-6 flex items-center justify-center">
          <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[85vh] sm:max-h-[88vh] overflow-hidden my-auto">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between bg-gradient-to-r from-emerald-50 to-white shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center">
                  <ArrowDownLeft size={20} />
                </div>
                <div>
                  <h3 className="font-black text-slate-900 text-base">Receive Inbound Goods</h3>
                  <p className="text-xs text-slate-500">Increments inventory quantity on hand</p>
                </div>
              </div>
              <button
                onClick={() => setIsReceiveModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 p-1.5 rounded-lg hover:bg-slate-100"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleReceive} className="flex-1 min-h-0 overflow-y-auto p-5 space-y-4">
              {actionError && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-center gap-2">
                  <AlertTriangle size={16} />
                  <span>{actionError}</span>
                </div>
              )}
              {actionSuccess && (
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-xs text-emerald-700 flex items-center gap-2">
                  <CheckCircle2 size={16} />
                  <span>{actionSuccess}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Select Item / SKU *</label>
                <select
                  value={formSku}
                  onChange={(e) => setFormSku(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-semibold text-slate-800 bg-white outline-none focus:border-emerald-500"
                  required
                >
                  {items.map((i) => (
                    <option key={i.id} value={i.sku}>
                      {i.sku} — {i.name} (Current: {i.quantity_on_hand} {i.unit})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Quantity Received *</label>
                <input
                  type="number"
                  min="1"
                  value={formQty}
                  onChange={(e) => setFormQty(parseInt(e.target.value) || 0)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-bold text-slate-800 outline-none focus:border-emerald-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Reference ID (PO / GRN)</label>
                <input
                  type="text"
                  placeholder="e.g. GRN-998822 or PO-2025-001"
                  value={formRef}
                  onChange={(e) => setFormRef(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Performed By</label>
                <input
                  type="text"
                  value={formStaff}
                  onChange={(e) => setFormStaff(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Notes</label>
                <textarea
                  rows={2}
                  value={formNotes}
                  onChange={(e) => setFormNotes(e.target.value)}
                  placeholder="Delivery remarks or inspector comments..."
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-emerald-500 resize-none"
                ></textarea>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center justify-center gap-2"
                 style={{ backgroundColor: "#059669", color: "#ffffff" }}>
                  {actionLoading ? <RefreshCw className="animate-spin" size={15} /> : <CheckCircle2 size={16} />}
                  Confirm Inbound Receipt (+Stock)
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Issue Modal (Strict fit-to-screen) */}
      {isIssueModalOpen && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm p-3 sm:p-6 flex items-center justify-center">
          <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[85vh] sm:max-h-[88vh] overflow-hidden my-auto">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between bg-gradient-to-r from-red-50 to-white shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-red-100 text-red-700 flex items-center justify-center">
                  <ArrowUpRight size={20} />
                </div>
                <div>
                  <h3 className="font-black text-slate-900 text-base">Issue / Dispatch Goods</h3>
                  <p className="text-xs text-slate-500">Decrements inventory quantity on hand</p>
                </div>
              </div>
              <button
                onClick={() => setIsIssueModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 p-1.5 rounded-lg hover:bg-slate-100"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleIssue} className="flex-1 min-h-0 overflow-y-auto p-5 space-y-4">
              {actionError && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-center gap-2">
                  <AlertTriangle size={16} />
                  <span>{actionError}</span>
                </div>
              )}
              {actionSuccess && (
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-xs text-emerald-700 flex items-center gap-2">
                  <CheckCircle2 size={16} />
                  <span>{actionSuccess}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Select Item / SKU *</label>
                <select
                  value={formSku}
                  onChange={(e) => setFormSku(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-semibold text-slate-800 bg-white outline-none focus:border-red-500"
                  required
                >
                  {items.map((i) => (
                    <option key={i.id} value={i.sku}>
                      {i.sku} — {i.name} (Available: {i.quantity_on_hand} {i.unit})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Quantity to Dispatch *</label>
                <input
                  type="number"
                  min="1"
                  value={formQty}
                  onChange={(e) => setFormQty(parseInt(e.target.value) || 0)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-bold text-slate-800 outline-none focus:border-red-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Destination / Department *</label>
                <input
                  type="text"
                  value={formDestination}
                  onChange={(e) => setFormDestination(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-red-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Reference ID (SO / Dispatch Slip)</label>
                <input
                  type="text"
                  placeholder="e.g. SO-2025-081"
                  value={formRef}
                  onChange={(e) => setFormRef(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-red-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Notes</label>
                <textarea
                  rows={2}
                  value={formNotes}
                  onChange={(e) => setFormNotes(e.target.value)}
                  placeholder="Dispatch purpose, recipient name..."
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-red-500 resize-none"
                ></textarea>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={actionLoading}
                  style={{ backgroundColor: '#d97706', color: '#ffffff' }}
                  className="btn-goods-out w-full py-2.5 bg-amber-600 hover:bg-amber-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center justify-center gap-2"
                >
                  {actionLoading ? <RefreshCw className="animate-spin" size={15} /> : <CheckCircle2 size={16} />}
                  Confirm Dispatch (-Stock)
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
