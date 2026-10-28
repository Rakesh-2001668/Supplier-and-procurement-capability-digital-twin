'use client';

import React, { useState, useMemo } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { 
  ArrowLeft, 
  AlertTriangle, 
  Package, 
  ArrowDownLeft, 
  RefreshCw, 
  CheckCircle2, 
  X, 
  TrendingDown, 
  Building2, 
  ShieldAlert, 
  ShoppingCart,
  Boxes,
  Plus
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

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
}

export default function LowStockAlertsPage() {
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  
  // Quick Restock Modal State
  const [restockItem, setRestockItem] = useState<InventoryItem | null>(null);
  const [restockQty, setRestockQty] = useState(50);
  const [restockRef, setRestockRef] = useState('');
  const [restockNotes, setRestockNotes] = useState('');
  const [isRestocking, setIsRestocking] = useState(false);
  const [actionError, setActionError] = useState('');
  const [actionSuccess, setActionSuccess] = useState('');

  // Fetch all items from inventory backend
  const { data: allItems = [], isLoading } = useQuery<InventoryItem[]>({
    queryKey: ['inventory', 'items'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/inventory/items');
      return res.data || [];
    }
  });

  // Filter low stock and out of stock items
  const alertItems = useMemo(() => {
    return allItems.filter(item => {
      const isAlert = item.quantity_on_hand <= item.min_threshold || item.status !== 'IN_STOCK';
      const matchSearch = !searchTerm || 
        item.sku.toLowerCase().includes(searchTerm.toLowerCase()) || 
        item.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        item.category.toLowerCase().includes(searchTerm.toLowerCase());
      return isAlert && matchSearch;
    });
  }, [allItems, searchTerm]);

  const outOfStockCount = allItems.filter(i => i.quantity_on_hand <= 0).length;
  const lowStockCount = allItems.filter(i => i.quantity_on_hand > 0 && i.quantity_on_hand <= i.min_threshold).length;
  const healthyCount = allItems.filter(i => i.quantity_on_hand > i.min_threshold).length;

  const handleRestockSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!restockItem || restockQty <= 0) return;
    setIsRestocking(true);
    setActionError('');
    setActionSuccess('');

    try {
      await apiClient.post('/api/v1/inventory/goods-in', {
        inventory_item_id: restockItem.id,
        sku: restockItem.sku,
        item_name: restockItem.name,
        quantity: Number(restockQty),
        unit: restockItem.unit,
        location: restockItem.location,
        reference_type: 'URGENT_RESTOCK',
        reference_id: restockRef || `RESTOCK-${Date.now().toString().slice(-6)}`,
        notes: restockNotes || `Replenished deficit of ${restockQty} ${restockItem.unit}`,
        performed_by: 'Emergency Procurement Dispatch'
      });
      setActionSuccess(`Successfully received +${restockQty} ${restockItem.unit} for ${restockItem.sku}!`);
      queryClient.invalidateQueries({ queryKey: ['inventory'] });
      setTimeout(() => {
        setRestockItem(null);
        setActionSuccess('');
      }, 1200);
    } catch (err: any) {
      setActionError(err?.response?.data?.detail || err?.message || 'Failed to restock item');
    } finally {
      setIsRestocking(false);
    }
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
            <span className="text-amber-600 font-bold">LOW STOCK & CRITICAL ALERTS</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-3">
            <ShieldAlert className="text-amber-500" size={28} />
            Inventory Stock Alerts
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Proactively monitor items at or below minimum buffer safety thresholds to prevent production bottlenecks.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/inventory/receipt"
            className="px-4 py-2 text-xs font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-xl shadow-md transition-all flex items-center gap-1.5"
          >
            <ArrowDownLeft size={15} /> Receive Shipment (GRN)
          </Link>
          <Link
            href="/inventory"
            className="px-4 py-2 text-xs font-bold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-xl shadow-sm transition-all"
          >
            ← Master Inventory
          </Link>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-2xl border border-red-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-red-50 text-red-600 flex items-center justify-center font-black shrink-0">
            <AlertTriangle size={24} />
          </div>
          <div>
            <div className="text-2xl font-black text-red-600">{outOfStockCount}</div>
            <div className="text-xs font-bold text-slate-500">Critical (0 Stock)</div>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-amber-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center font-black shrink-0">
            <TrendingDown size={24} />
          </div>
          <div>
            <div className="text-2xl font-black text-amber-600">{lowStockCount}</div>
            <div className="text-xs font-bold text-slate-500">Low Stock Warning</div>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-emerald-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center font-black shrink-0">
            <CheckCircle2 size={24} />
          </div>
          <div>
            <div className="text-2xl font-black text-emerald-600">{healthyCount}</div>
            <div className="text-xs font-bold text-slate-500">Healthy Stock SKUs</div>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center font-black shrink-0">
            <Boxes size={24} />
          </div>
          <div>
            <div className="text-2xl font-black text-[#0B2550]">{allItems.length}</div>
            <div className="text-xs font-bold text-slate-500">Total Catalog Items</div>
          </div>
        </div>
      </div>

      {/* Alerts Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <h2 className="text-sm font-black text-[#0B2550] flex items-center gap-2">
            <AlertTriangle className="text-amber-500" size={16} />
            Items Requiring Replenishment ({alertItems.length})
          </h2>

          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search alert items..."
            className="px-3.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:border-blue-500 outline-none min-w-[220px]"
          />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="bg-slate-50 text-slate-500 font-extrabold uppercase tracking-wider border-b border-slate-100">
              <tr>
                <th className="py-3 px-4">Item & SKU</th>
                <th className="py-3 px-4">Category & Location</th>
                <th className="py-3 px-4 text-center">Current Stock</th>
                <th className="py-3 px-4 text-center">Safety Threshold</th>
                <th className="py-3 px-4 text-center">Deficit</th>
                <th className="py-3 px-4 text-center">Status</th>
                <th className="py-3 px-4 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    <RefreshCw className="animate-spin inline-block mr-2" size={16} />
                    Checking inventory stock levels...
                  </td>
                </tr>
              ) : alertItems.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    <CheckCircle2 size={32} className="mx-auto text-emerald-500 mb-2" />
                    <div className="font-bold text-slate-700">All Stock Levels are Healthy!</div>
                    <div className="text-[11px] text-slate-400">No items are currently below minimum buffer thresholds.</div>
                  </td>
                </tr>
              ) : (
                alertItems.map((item) => {
                  const isOut = item.quantity_on_hand <= 0;
                  const deficit = Math.max(0, item.min_threshold - item.quantity_on_hand);
                  const suggestedReorder = deficit > 0 ? deficit + 50 : 50;

                  return (
                    <tr key={item.id} className="hover:bg-slate-50/60 transition-colors">
                      <td className="py-3.5 px-4 font-bold text-slate-800">
                        <div className="font-mono text-xs text-blue-600">{item.sku}</div>
                        <div className="text-slate-900">{item.name}</div>
                      </td>

                      <td className="py-3.5 px-4">
                        <div className="text-slate-700 font-medium">{item.category}</div>
                        <div className="text-[10px] text-slate-400">{item.location}</div>
                      </td>

                      <td className="py-3.5 px-4 text-center">
                        <span className={`font-mono font-black text-sm ${isOut ? 'text-red-600' : 'text-amber-600'}`}>
                          {item.quantity_on_hand} {item.unit}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 text-center font-mono font-semibold text-slate-600">
                        {item.min_threshold} {item.unit}
                      </td>

                      <td className="py-3.5 px-4 text-center font-mono font-bold text-red-600">
                        {deficit > 0 ? `-${deficit} ${item.unit}` : 'At Buffer'}
                      </td>

                      <td className="py-3.5 px-4 text-center">
                        <span className={`inline-block px-2.5 py-0.5 rounded-full text-[10px] font-extrabold ${
                          isOut ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                        }`}>
                          {isOut ? 'OUT OF STOCK' : 'LOW STOCK'}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 text-center">
                        <button
                          onClick={() => {
                            setRestockItem(item);
                            setRestockQty(suggestedReorder);
                            setRestockRef(`RESTOCK-${item.sku}`);
                            setRestockNotes(`Emergency restock to restore safety threshold.`);
                          }}
                          style={{ backgroundColor: "#059669", color: "#ffffff" }}
                          className="btn-goods-in px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-[11px] rounded-xl shadow-sm transition-all flex items-center gap-1 mx-auto"
                        >
                          <Plus size={13} /> Quick Restock
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Quick Restock Modal (Strict fit-to-screen) */}
      {restockItem && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm p-3 sm:p-6 flex items-center justify-center">
          <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[85vh] sm:max-h-[88vh] overflow-hidden my-auto">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between bg-gradient-to-r from-emerald-50 to-white shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center">
                  <ArrowDownLeft size={20} />
                </div>
                <div>
                  <h3 className="font-black text-slate-900 text-base">Quick Restock / Goods In</h3>
                  <p className="text-xs text-slate-500 font-mono">{restockItem.sku} • {restockItem.name}</p>
                </div>
              </div>
              <button
                onClick={() => setRestockItem(null)}
                className="text-slate-400 hover:text-slate-600 p-1.5 rounded-lg hover:bg-slate-100"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleRestockSubmit} className="flex-1 min-h-0 overflow-y-auto p-5 space-y-4">
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

              <div className="bg-slate-50 p-3 rounded-xl border border-slate-200 grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="text-slate-400 block font-bold text-[10px]">Current On-Hand</span>
                  <span className="font-mono font-black text-slate-800">{restockItem.quantity_on_hand} {restockItem.unit}</span>
                </div>
                <div>
                  <span className="text-slate-400 block font-bold text-[10px]">Safety Min Threshold</span>
                  <span className="font-mono font-bold text-slate-800">{restockItem.min_threshold} {restockItem.unit}</span>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Quantity to Receive *</label>
                <input
                  type="number"
                  min="1"
                  value={restockQty}
                  onChange={(e) => setRestockQty(parseInt(e.target.value) || 0)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-bold text-slate-800 outline-none focus:border-emerald-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Reference ID (PO / GRN)</label>
                <input
                  type="text"
                  value={restockRef}
                  onChange={(e) => setRestockRef(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Restock Notes</label>
                <textarea
                  rows={2}
                  value={restockNotes}
                  onChange={(e) => setRestockNotes(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none focus:border-emerald-500 resize-none"
                ></textarea>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isRestocking}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center justify-center gap-2"
                 style={{ backgroundColor: "#059669", color: "#ffffff" }}>
                  {isRestocking ? <RefreshCw className="animate-spin" size={15} /> : <CheckCircle2 size={16} />}
                  Add to Inventory (+Stock)
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
