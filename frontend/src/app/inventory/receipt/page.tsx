'use client';

import React, { useState, useEffect } from 'react';
import { 
  Box, 
  CheckCircle, 
  AlertTriangle, 
  FileText, 
  Camera, 
  Info, 
  Search, 
  ArrowLeft, 
  Plus, 
  Trash2, 
  Layers, 
  Check, 
  ArrowDownLeft, 
  ExternalLink,
  RefreshCw,
  Building2,
  Truck
} from 'lucide-react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';

interface InventoryItem {
  id: string;
  sku: string;
  name: string;
  category: string;
  unit: string;
  quantity_on_hand: number;
  unit_price: number;
  location: string;
  status: string;
}

interface ReceiptLineItem {
  id: string;
  sku: string;
  name: string;
  shipped: number;
  received: number;
  accepted: number;
  rejected: number;
  unit: string;
  rejectionReason?: string;
}

export default function GoodsReceiptNote() {
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successResult, setSuccessResult] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState('');

  // Form Header State
  const [grnNumber, setGrnNumber] = useState(`GRN-${Math.floor(100000 + Math.random() * 900000)}`);
  const [poNumber, setPoNumber] = useState('PO-2025-00123');
  const [supplier, setSupplier] = useState('Apex Precision Machining');
  const [carrier, setCarrier] = useState('BlueDart Express (BD-9988776655)');
  const [receivedBy, setReceivedBy] = useState('Warehouse Receiving Lead (ID: W-042)');
  const [packageCondition, setPackageCondition] = useState('Good / Undamaged');
  const [storageLocation, setStorageLocation] = useState('Warehouse A - Bay 04');
  const [receivingNotes, setReceivingNotes] = useState('Standard inbound delivery received in good order.');

  // Fetch real inventory catalog
  const { data: inventoryItems = [], isLoading: isLoadingItems } = useQuery<InventoryItem[]>({
    queryKey: ['inventory', 'items'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/inventory/items');
      return res.data || [];
    }
  });

  // Receiving Line Items
  const [lineItems, setLineItems] = useState<ReceiptLineItem[]>([
    {
      id: '1',
      sku: 'SKU-TI-001',
      name: 'Titanium Aerospace Fasteners M8',
      shipped: 100,
      received: 100,
      accepted: 100,
      rejected: 0,
      unit: 'pcs'
    },
    {
      id: '2',
      sku: 'SKU-AL-002',
      name: 'Aluminum 6061-T6 Billet Ingots',
      shipped: 50,
      received: 50,
      accepted: 48,
      rejected: 2,
      unit: 'kg',
      rejectionReason: 'Surface oxidation / scratches'
    }
  ]);

  // Selected item to add from catalog
  const [selectedCatalogSku, setSelectedCatalogSku] = useState('');

  const handleAddItem = () => {
    if (!selectedCatalogSku) return;
    const catItem = inventoryItems.find(i => i.sku === selectedCatalogSku);
    if (!catItem) return;

    if (lineItems.some(i => i.sku === catItem.sku)) {
      alert(`Item ${catItem.sku} is already added in this GRN.`);
      return;
    }

    setLineItems(prev => [
      ...prev,
      {
        id: String(Date.now()),
        sku: catItem.sku,
        name: catItem.name,
        shipped: 50,
        received: 50,
        accepted: 50,
        rejected: 0,
        unit: catItem.unit || 'pcs'
      }
    ]);
    setSelectedCatalogSku('');
  };

  const handleRemoveItem = (id: string) => {
    setLineItems(prev => prev.filter(i => i.id !== id));
  };

  const updateItemQuantities = (id: string, field: 'received' | 'accepted' | 'rejected', val: number) => {
    setLineItems(prev => prev.map(item => {
      if (item.id !== id) return item;
      const num = Math.max(0, val);
      if (field === 'received') {
        const acc = Math.min(num, item.accepted);
        return { ...item, received: num, accepted: acc, rejected: num - acc };
      } else if (field === 'accepted') {
        const acc = Math.min(item.received, num);
        return { ...item, accepted: acc, rejected: item.received - acc };
      } else {
        const rej = Math.min(item.received, num);
        return { ...item, rejected: rej, accepted: item.received - rej };
      }
    }));
  };

  // Submit Goods Receipt workflow
  const handleSubmitGRN = async () => {
    if (lineItems.length === 0) {
      alert('Please add at least one line item to receive.');
      return;
    }

    const totalAccepted = lineItems.reduce((acc, curr) => acc + curr.accepted, 0);
    if (totalAccepted <= 0) {
      alert('Total accepted quantity must be greater than 0.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage('');

    try {
      const results: any[] = [];
      // Call backend goods-in endpoint for each accepted item
      for (const item of lineItems) {
        if (item.accepted > 0) {
          const payload = {
            sku: item.sku,
            item_name: item.name,
            quantity: item.accepted,
            unit: item.unit,
            location: storageLocation,
            reference_type: 'GOODS_RECEIPT',
            reference_id: grnNumber,
            performed_by: receivedBy,
            notes: `Received via ${grnNumber} (PO: ${poNumber}). Supplier: ${supplier}. ${item.rejected > 0 ? `Rejected ${item.rejected} units.` : 'Full batch accepted.'} Notes: ${receivingNotes}`,
            tenant_id: 'TENANT_BUYER_001'
          };
          const res = await apiClient.post('/api/v1/inventory/goods-in', payload);
          results.push(res);
        }
      }

      // Invalidate inventory cache
      queryClient.invalidateQueries({ queryKey: ['inventory'] });

      setSuccessResult({
        grnNumber,
        poNumber,
        supplier,
        carrier,
        receivedBy,
        storageLocation,
        lineItems,
        results,
        date: new Date().toLocaleString()
      });
    } catch (err: any) {
      console.error('Failed to submit GRN:', err);
      setErrorMessage(err?.response?.data?.detail || err?.message || 'Failed to generate Goods Receipt Note.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-4 sm:p-8 animate-fade-in-up bg-[#f8fafc] min-h-screen pb-24">
      {/* Top Header & Breadcrumb */}
      <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 mb-6">
        <div>
          <div className="text-[10px] font-black tracking-widest uppercase text-slate-500 mb-1 flex items-center gap-2">
            <Link href="/inventory" className="hover:text-blue-600 transition-colors flex items-center gap-1">
              <ArrowLeft size={12} /> INVENTORY
            </Link> 
            <span className="text-slate-300">›</span> 
            <span className="text-blue-600 font-bold">GOODS RECEIPT NOTE (INBOUND)</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-3">
            <Box className="text-blue-600" size={28} />
            Receive Inbound Goods (GRN)
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Accept supplier deliveries, perform dock inspection, and automatically increment inventory on-hand stock.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/inventory"
            className="px-4 py-2 text-xs font-bold text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 shadow-sm transition-all"
          >
            ← Back to Inventory
          </Link>
          <Link
            href="/inventory/movements"
            className="px-4 py-2 text-xs font-bold text-blue-600 bg-blue-50 border border-blue-200 rounded-xl hover:bg-blue-100 shadow-sm transition-all flex items-center gap-1.5"
          >
            <Layers size={14} /> Stock Movements Audit
          </Link>
        </div>
      </div>

      {/* Error Banner */}
      {errorMessage && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl flex items-center gap-3 text-red-700 text-sm">
          <AlertTriangle size={20} className="shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Success Modal / Banner */}
      {successResult && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-sm p-4 flex items-center justify-center">
          <div className="relative w-full max-w-2xl bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[88vh] overflow-hidden">
            <div className="p-6 bg-gradient-to-r from-emerald-600 to-teal-700 text-white shrink-0">
              <div className="w-12 h-12 rounded-2xl bg-white/20 backdrop-blur-md flex items-center justify-center mb-3">
                <CheckCircle size={28} className="text-white" />
              </div>
              <h2 className="text-2xl font-black">GRN Generated & Stock Updated!</h2>
              <p className="text-xs text-emerald-100 mt-1">
                Receipt Reference: <span className="font-mono font-bold text-white">{successResult.grnNumber}</span> • PO: {successResult.poNumber}
              </p>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              <div className="bg-emerald-50/60 border border-emerald-200 rounded-xl p-4 text-xs text-emerald-900 space-y-1">
                <div className="font-bold text-emerald-800 text-sm mb-1">Stock Ledger Updates Applied:</div>
                {successResult.results.map((r: any, idx: number) => (
                  <div key={idx} className="flex items-center justify-between py-1 border-b border-emerald-100 last:border-b-0 font-medium">
                    <span>{r?.item?.name} ({r?.item?.sku})</span>
                    <span className="font-black text-emerald-700">New On-Hand: {r?.item?.quantity_on_hand} {r?.item?.unit}</span>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-2 gap-4 text-xs bg-slate-50 p-4 rounded-xl border border-slate-200">
                <div>
                  <span className="text-slate-400 block font-bold uppercase text-[10px]">Supplier</span>
                  <span className="font-bold text-slate-800">{successResult.supplier}</span>
                </div>
                <div>
                  <span className="text-slate-400 block font-bold uppercase text-[10px]">Received By</span>
                  <span className="font-bold text-slate-800">{successResult.receivedBy}</span>
                </div>
                <div>
                  <span className="text-slate-400 block font-bold uppercase text-[10px]">Put-Away Location</span>
                  <span className="font-bold text-slate-800">{successResult.storageLocation}</span>
                </div>
                <div>
                  <span className="text-slate-400 block font-bold uppercase text-[10px]">Carrier</span>
                  <span className="font-bold text-slate-800">{successResult.carrier}</span>
                </div>
              </div>
            </div>

            <div className="p-4 bg-slate-50 border-t border-slate-200 flex justify-between items-center shrink-0">
              <button
                onClick={() => {
                  setSuccessResult(null);
                  setGrnNumber(`GRN-${Math.floor(100000 + Math.random() * 900000)}`);
                }}
                className="px-4 py-2.5 text-xs font-bold text-slate-600 bg-white border border-slate-300 rounded-xl hover:bg-slate-100 transition-colors"
              >
                Receive Another Batch
              </button>
              <div className="flex gap-2">
                <Link
                  href="/inventory"
                  className="px-5 py-2.5 text-xs font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-xl shadow-md transition-all flex items-center gap-1.5"
                >
                  <Box size={14} /> Go to Inventory Master
                </Link>
                <Link
                  href="/inventory/movements"
                  className="px-5 py-2.5 text-xs font-bold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-xl shadow-sm transition-all flex items-center gap-1.5"
                >
                  <Layers size={14} /> View Audit Ledger
                </Link>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Two-Column Layout */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Left Column: GRN Metadata & Items Table */}
        <div className="xl:col-span-2 space-y-6">
          {/* GRN Details Card */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
            <h2 className="text-base font-black text-[#0B2550] flex items-center gap-2 mb-4 pb-3 border-b border-slate-100">
              <Box className="text-blue-600" size={18} /> Receipt Metadata & Transport
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold text-slate-600 mb-1">GRN Reference Number *</label>
                <input
                  type="text"
                  value={grnNumber}
                  onChange={(e) => setGrnNumber(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl px-3.5 py-2 text-sm font-bold text-slate-800 bg-slate-50 focus:bg-white focus:border-blue-500 outline-none transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-600 mb-1">Purchase Order (PO) *</label>
                <input
                  type="text"
                  value={poNumber}
                  onChange={(e) => setPoNumber(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl px-3.5 py-2 text-sm font-semibold text-slate-800 focus:border-blue-500 outline-none transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-600 mb-1">Supplier Name *</label>
                <input
                  type="text"
                  value={supplier}
                  onChange={(e) => setSupplier(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl px-3.5 py-2 text-sm font-semibold text-slate-800 focus:border-blue-500 outline-none transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-600 mb-1">Put-Away Warehouse Location *</label>
                <input
                  type="text"
                  value={storageLocation}
                  onChange={(e) => setStorageLocation(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl px-3.5 py-2 text-sm font-semibold text-slate-800 focus:border-blue-500 outline-none transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-600 mb-1">Receiving Inspector / Staff *</label>
                <input
                  type="text"
                  value={receivedBy}
                  onChange={(e) => setReceivedBy(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl px-3.5 py-2 text-sm font-semibold text-slate-800 focus:border-blue-500 outline-none transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-600 mb-1">Packaging Condition</label>
                <select
                  value={packageCondition}
                  onChange={(e) => setPackageCondition(e.target.value)}
                  className="w-full border border-slate-200 rounded-xl px-3.5 py-2 text-sm font-semibold text-slate-800 bg-white focus:border-blue-500 outline-none transition-all"
                >
                  <option value="Good / Undamaged">Good / Undamaged</option>
                  <option value="Minor Seal Wear">Minor Seal Wear</option>
                  <option value="Damaged / Inspected">Damaged / Inspected</option>
                </select>
              </div>
            </div>
          </div>

          {/* Quality Inspection & Quantities Receiving Table */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-gradient-to-r from-blue-50/50 via-white to-white">
              <div>
                <h2 className="text-base font-black text-[#0B2550] flex items-center gap-2">
                  <CheckCircle className="text-emerald-500" size={18} />
                  Inspection & Quantity Acceptance
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Adjust accepted quantities. Stock on hand will automatically increment by the accepted count.
                </p>
              </div>

              {/* Add item from catalog quick selector */}
              <div className="flex items-center gap-2">
                <select
                  value={selectedCatalogSku}
                  onChange={(e) => setSelectedCatalogSku(e.target.value)}
                  className="border border-slate-200 rounded-xl px-3 py-1.5 text-xs font-semibold text-slate-700 bg-white max-w-[200px] outline-none"
                >
                  <option value="">+ Select SKU from Catalog</option>
                  {inventoryItems.map((item) => (
                    <option key={item.id} value={item.sku}>
                      {item.sku} - {item.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleAddItem}
                  disabled={!selectedCatalogSku}
                  className="px-3 py-1.5 bg-blue-600 text-white font-bold text-xs rounded-xl hover:bg-blue-700 disabled:opacity-40 transition-colors shrink-0 flex items-center gap-1"
                >
                  <Plus size={14} /> Add
                </button>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="bg-slate-50 text-slate-500 font-extrabold uppercase tracking-wider border-b border-slate-100">
                  <tr>
                    <th className="py-3 px-4">SKU / Item Details</th>
                    <th className="py-3 px-3 text-center">Shipped</th>
                    <th className="py-3 px-3 text-center">Total Received</th>
                    <th className="py-3 px-3 text-center bg-emerald-50/70 text-emerald-700">Accepted (Stock In)</th>
                    <th className="py-3 px-3 text-center bg-red-50/70 text-red-700">Rejected</th>
                    <th className="py-3 px-3 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {lineItems.map((item) => (
                    <tr key={item.id} className="hover:bg-slate-50/60 transition-colors">
                      <td className="py-3.5 px-4 font-bold text-slate-800">
                        <div className="font-mono text-xs text-blue-600">{item.sku}</div>
                        <div className="text-xs text-slate-700 font-bold">{item.name}</div>
                        <div className="text-[10px] text-slate-400">UoM: {item.unit}</div>
                      </td>

                      <td className="py-3.5 px-3 text-center">
                        <input
                          type="number"
                          value={item.shipped}
                          onChange={(e) => {
                            const val = parseInt(e.target.value) || 0;
                            setLineItems(prev => prev.map(i => i.id === item.id ? { ...i, shipped: val } : i));
                          }}
                          className="w-16 border border-slate-200 rounded-lg p-1 text-center font-bold text-slate-600 outline-none"
                        />
                      </td>

                      <td className="py-3.5 px-3 text-center">
                        <input
                          type="number"
                          value={item.received}
                          onChange={(e) => updateItemQuantities(item.id, 'received', parseInt(e.target.value) || 0)}
                          className="w-16 border border-slate-200 rounded-lg p-1 text-center font-bold text-slate-800 outline-none"
                        />
                      </td>

                      <td className="py-3.5 px-3 text-center bg-emerald-50/30">
                        <input
                          type="number"
                          value={item.accepted}
                          onChange={(e) => updateItemQuantities(item.id, 'accepted', parseInt(e.target.value) || 0)}
                          className="w-20 border border-emerald-300 rounded-lg p-1.5 text-center font-black text-emerald-700 bg-white outline-none focus:ring-2 focus:ring-emerald-400"
                        />
                      </td>

                      <td className="py-3.5 px-3 text-center bg-red-50/30">
                        <input
                          type="number"
                          value={item.rejected}
                          onChange={(e) => updateItemQuantities(item.id, 'rejected', parseInt(e.target.value) || 0)}
                          className="w-16 border border-red-200 rounded-lg p-1 text-center font-black text-red-600 bg-white outline-none"
                        />
                        {item.rejected > 0 && (
                          <span className="block text-[9px] text-red-600 font-bold mt-1 uppercase">Return to Supplier</span>
                        )}
                      </td>

                      <td className="py-3.5 px-3 text-center">
                        <button
                          type="button"
                          onClick={() => handleRemoveItem(item.id)}
                          className="text-slate-400 hover:text-red-500 p-1.5 rounded-lg hover:bg-red-50 transition-colors"
                          title="Remove item"
                        >
                          <Trash2 size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {lineItems.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-slate-400">
                        No line items added. Select an item from the catalog dropdown above to add.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right Column: Reference & Documentation Panel */}
        <div className="xl:col-span-1 space-y-6">
          <div className="bg-gradient-to-br from-blue-50 to-indigo-50/50 rounded-2xl border border-blue-100 p-5">
            <h3 className="font-black text-blue-950 text-sm mb-3 flex items-center gap-2">
              <Truck size={16} className="text-blue-600" /> Carrier & Logistics Summary
            </h3>
            <div className="space-y-2.5 text-xs text-blue-900/80">
              <div className="flex justify-between py-1 border-b border-blue-100/60">
                <span className="text-slate-500">Carrier Partner</span>
                <span className="font-bold text-slate-900">{carrier}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-blue-100/60">
                <span className="text-slate-500">Total Items in GRN</span>
                <span className="font-bold text-slate-900">{lineItems.length} SKUs</span>
              </div>
              <div className="flex justify-between py-1 border-b border-blue-100/60">
                <span className="text-slate-500">Total Accepted</span>
                <span className="font-black text-emerald-700">
                  {lineItems.reduce((acc, c) => acc + c.accepted, 0)} Units
                </span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-slate-500">Total Rejected</span>
                <span className="font-black text-red-600">
                  {lineItems.reduce((acc, c) => acc + c.rejected, 0)} Units
                </span>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 space-y-4">
            <h3 className="font-black text-[#0B2550] text-sm flex items-center gap-2">
              <FileText size={16} className="text-blue-600" /> Receiving Notes & Remarks
            </h3>
            <div>
              <label className="block text-xs font-bold text-slate-600 mb-1">Dock Inspection Notes</label>
              <textarea
                rows={4}
                value={receivingNotes}
                onChange={(e) => setReceivingNotes(e.target.value)}
                placeholder="Enter notes on physical inspection, pallet integrity, seal verification..."
                className="w-full border border-slate-200 rounded-xl p-3 text-xs text-slate-800 outline-none focus:border-blue-500 resize-none"
              ></textarea>
            </div>
          </div>
        </div>
      </div>

      {/* Floating Bottom Action Bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-white/95 backdrop-blur-md border-t border-slate-200 p-4 px-6 sm:px-12 flex justify-between items-center z-40 shadow-[0_-4px_16px_rgba(0,0,0,0.06)]">
        <Link
          href="/inventory"
          className="px-5 py-2.5 text-xs font-bold text-slate-600 bg-white border border-slate-300 rounded-xl hover:bg-slate-50 transition-colors"
        >
          Cancel
        </Link>
        <button
          onClick={handleSubmitGRN}
          disabled={isSubmitting || lineItems.length === 0}
          className={`px-8 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-black text-sm rounded-xl shadow-lg shadow-blue-500/25 flex items-center gap-2 transition-all ${
            isSubmitting ? 'opacity-70 cursor-not-allowed' : 'active:scale-95'
          }`}
        >
          {isSubmitting ? (
            <>
              <RefreshCw size={16} className="animate-spin" />
              Recording Inbound Receipt...
            </>
          ) : (
            <>
              <CheckCircle size={18} />
              Generate GRN & Update Inventory (+Stock)
            </>
          )}
        </button>
      </div>
    </div>
  );
}
