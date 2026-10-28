'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { 
  ArrowLeft, 
  Box, 
  CheckCircle2, 
  AlertTriangle, 
  RefreshCw, 
  Layers, 
  Building2, 
  DollarSign, 
  Warehouse,
  ShieldCheck,
  Plus
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

export default function AddInventoryItemPage() {
  const router = useRouter();
  const [activeStep, setActiveStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  // Item Form Fields
  const [formData, setFormData] = useState({
    sku: `SKU-${Math.floor(1000 + Math.random() * 9000)}`,
    name: '',
    category: 'Mechanical Components',
    unit: 'pcs',
    quantity_on_hand: 50,
    unit_price: 25.0,
    min_threshold: 20,
    max_capacity: 1000,
    location: 'Warehouse A - Bay 02',
    notes: ''
  });

  const categories = [
    'Mechanical Components',
    'Raw Materials',
    'Electrical & Semiconductors',
    'Hydraulics & Pneumatics',
    'Fasteners & Hardware',
    'Tooling & Consumables'
  ];

  const units = ['pcs', 'kg', 'meters', 'sets', 'liters', 'rolls'];

  const handleChange = (field: string, val: any) => {
    setFormData(prev => ({ ...prev, [field]: val }));
  };

  const handleNext = () => {
    if (activeStep === 1 && !formData.name.trim()) {
      setErrorMsg('Item name is required.');
      return;
    }
    setErrorMsg('');
    if (activeStep < 4) {
      setActiveStep(activeStep + 1);
    } else {
      handleSubmit();
    }
  };

  const handleBack = () => {
    setErrorMsg('');
    if (activeStep > 1) setActiveStep(activeStep - 1);
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    setErrorMsg('');
    try {
      await apiClient.post('/api/v1/inventory/items', {
        sku: formData.sku.trim().toUpperCase(),
        name: formData.name.trim(),
        category: formData.category,
        unit: formData.unit,
        quantity_on_hand: Number(formData.quantity_on_hand),
        unit_price: Number(formData.unit_price),
        min_threshold: Number(formData.min_threshold),
        max_capacity: Number(formData.max_capacity),
        location: formData.location
      });
      setIsSuccess(true);
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || err?.message || 'Failed to register item in catalog.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const steps = [
    { id: 1, title: 'Item Details', desc: 'SKU, name, category' },
    { id: 2, title: 'Pricing & Stock', desc: 'Quantity, unit price, thresholds' },
    { id: 3, title: 'Warehouse Location', desc: 'Storage bay and bin' },
    { id: 4, title: 'Review & Confirm', desc: 'Verify before saving' },
  ];

  if (isSuccess) {
    return (
      <div className="p-4 sm:p-8 max-w-2xl mx-auto min-h-screen flex items-center justify-center animate-fade-in-up">
        <div className="bg-white rounded-3xl shadow-xl border border-slate-200 p-8 text-center space-y-5 w-full">
          <div className="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-3xl flex items-center justify-center mx-auto shadow-inner">
            <CheckCircle2 size={36} />
          </div>
          <h2 className="text-2xl font-black text-[#0B2550]">Item Created & Cataloged!</h2>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            <span className="font-bold text-slate-800">{formData.name}</span> ({formData.sku}) has been successfully added to the active inventory catalog with an initial on-hand stock of <span className="font-bold text-emerald-600">{formData.quantity_on_hand} {formData.unit}</span>.
          </p>
          <div className="pt-4 flex flex-col sm:flex-row justify-center gap-3">
            <Link
              href="/inventory"
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center justify-center gap-1.5"
            >
              <Box size={14} /> View Master Inventory
            </Link>
            <Link
              href="/inventory/receipt"
              className="px-6 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold text-xs rounded-xl transition-all flex items-center justify-center gap-1.5"
            >
              <Plus size={14} /> Receive Additional Stock (GRN)
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-8 max-w-4xl mx-auto min-h-screen animate-fade-in-up">
      {/* Breadcrumb Header */}
      <div className="mb-6">
        <div className="text-[10px] font-black tracking-widest uppercase text-slate-500 mb-1 flex items-center gap-2">
          <Link href="/inventory" className="hover:text-blue-600 transition-colors flex items-center gap-1">
            <ArrowLeft size={12} /> INVENTORY
          </Link> 
          <span className="text-slate-300">›</span> 
          <span className="text-blue-600 font-bold">ADD NEW SKU</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-3">
          <Box className="text-blue-600" size={28} /> Add New Inventory Item
        </h1>
      </div>

      {/* Progress Steps */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-8">
        {steps.map((s) => (
          <div
            key={s.id}
            className={`p-3 rounded-2xl border transition-all ${
              activeStep === s.id
                ? 'bg-blue-50/80 border-blue-300 text-blue-900 shadow-sm'
                : activeStep > s.id
                ? 'bg-emerald-50/50 border-emerald-200 text-emerald-800'
                : 'bg-white border-slate-200 text-slate-400'
            }`}
          >
            <div className="flex items-center gap-2">
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-black ${
                activeStep === s.id
                  ? 'bg-blue-600 text-white'
                  : activeStep > s.id
                  ? 'bg-emerald-600 text-white'
                  : 'bg-slate-100 text-slate-500'
              }`}>
                {activeStep > s.id ? '✓' : s.id}
              </span>
              <span className="text-xs font-bold truncate">{s.title}</span>
            </div>
          </div>
        ))}
      </div>

      {errorMsg && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-center gap-2">
          <AlertTriangle size={16} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Step Contents */}
      <div className="bg-white rounded-3xl shadow-sm border border-slate-200 p-6 sm:p-8 mb-6">
        {activeStep === 1 && (
          <div className="space-y-4">
            <h2 className="text-base font-black text-[#0B2550] pb-2 border-b border-slate-100">Step 1: Item Identification</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">SKU Code *</label>
                <input
                  type="text"
                  value={formData.sku}
                  onChange={(e) => handleChange('sku', e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-mono font-bold text-slate-800 outline-none focus:border-blue-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Item Name *</label>
                <input
                  type="text"
                  placeholder="e.g. High-Pressure Hydraulic Pump"
                  value={formData.name}
                  onChange={(e) => handleChange('name', e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-bold text-slate-800 outline-none focus:border-blue-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Category *</label>
                <select
                  value={formData.category}
                  onChange={(e) => handleChange('category', e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-semibold text-slate-800 bg-white outline-none focus:border-blue-500"
                >
                  {categories.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Unit of Measure (UoM) *</label>
                <select
                  value={formData.unit}
                  onChange={(e) => handleChange('unit', e.target.value)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-semibold text-slate-800 bg-white outline-none focus:border-blue-500"
                >
                  {units.map((u) => (
                    <option key={u} value={u}>{u}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        )}

        {activeStep === 2 && (
          <div className="space-y-4">
            <h2 className="text-base font-black text-[#0B2550] pb-2 border-b border-slate-100">Step 2: Valuation & Stock Safety Rules</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Initial Quantity On-Hand</label>
                <input
                  type="number"
                  min="0"
                  value={formData.quantity_on_hand}
                  onChange={(e) => handleChange('quantity_on_hand', parseInt(e.target.value) || 0)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-bold text-slate-800 outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Unit Price ($ USD)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={formData.unit_price}
                  onChange={(e) => handleChange('unit_price', parseFloat(e.target.value) || 0)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-bold text-slate-800 outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Minimum Buffer Safety Threshold</label>
                <input
                  type="number"
                  min="0"
                  value={formData.min_threshold}
                  onChange={(e) => handleChange('min_threshold', parseInt(e.target.value) || 0)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-bold text-slate-800 outline-none focus:border-blue-500"
                />
                <span className="text-[10px] text-slate-400 mt-0.5 block">Triggers low stock warnings when stock drops below this.</span>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Maximum Warehouse Storage Capacity</label>
                <input
                  type="number"
                  min="1"
                  value={formData.max_capacity}
                  onChange={(e) => handleChange('max_capacity', parseInt(e.target.value) || 0)}
                  className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-bold text-slate-800 outline-none focus:border-blue-500"
                />
              </div>
            </div>
          </div>
        )}

        {activeStep === 3 && (
          <div className="space-y-4">
            <h2 className="text-base font-black text-[#0B2550] pb-2 border-b border-slate-100">Step 3: Storage Location</h2>
            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Storage Location / Rack / Bay</label>
              <input
                type="text"
                value={formData.location}
                onChange={(e) => handleChange('location', e.target.value)}
                className="w-full border border-slate-200 rounded-xl p-2.5 text-xs font-semibold text-slate-800 outline-none focus:border-blue-500"
              />
            </div>
          </div>
        )}

        {activeStep === 4 && (
          <div className="space-y-4">
            <h2 className="text-base font-black text-[#0B2550] pb-2 border-b border-slate-100">Step 4: Review SKU Catalog Registration</h2>
            <div className="bg-slate-50 p-5 rounded-2xl border border-slate-200 grid grid-cols-2 gap-4 text-xs">
              <div>
                <span className="text-slate-400 block font-bold text-[10px]">SKU Code</span>
                <span className="font-mono font-black text-blue-600 text-sm">{formData.sku}</span>
              </div>
              <div>
                <span className="text-slate-400 block font-bold text-[10px]">Item Name</span>
                <span className="font-bold text-slate-800 text-sm">{formData.name}</span>
              </div>
              <div>
                <span className="text-slate-400 block font-bold text-[10px]">Category</span>
                <span className="font-semibold text-slate-700">{formData.category}</span>
              </div>
              <div>
                <span className="text-slate-400 block font-bold text-[10px]">Unit</span>
                <span className="font-semibold text-slate-700">{formData.unit}</span>
              </div>
              <div>
                <span className="text-slate-400 block font-bold text-[10px]">Initial Quantity On Hand</span>
                <span className="font-mono font-bold text-emerald-600">{formData.quantity_on_hand} {formData.unit}</span>
              </div>
              <div>
                <span className="text-slate-400 block font-bold text-[10px]">Unit Price</span>
                <span className="font-mono font-bold text-slate-800">${formData.unit_price.toFixed(2)}</span>
              </div>
              <div>
                <span className="text-slate-400 block font-bold text-[10px]">Storage Bay</span>
                <span className="font-semibold text-slate-700">{formData.location}</span>
              </div>
              <div>
                <span className="text-slate-400 block font-bold text-[10px]">Reorder Buffer Threshold</span>
                <span className="font-mono font-bold text-amber-600">{formData.min_threshold} {formData.unit}</span>
              </div>
            </div>
          </div>
        )}

        {/* Buttons */}
        <div className="flex justify-between items-center pt-6 mt-6 border-t border-slate-100">
          <button
            type="button"
            onClick={handleBack}
            disabled={activeStep === 1 || isSubmitting}
            className="px-5 py-2 text-xs font-bold text-slate-600 bg-white border border-slate-300 rounded-xl hover:bg-slate-50 disabled:opacity-30 transition-all"
          >
            ← Back
          </button>

          <button
            type="button"
            onClick={handleNext}
            disabled={isSubmitting}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5"
          >
            {isSubmitting ? (
              <>
                <RefreshCw size={14} className="animate-spin" /> Saving...
              </>
            ) : activeStep === 4 ? (
              <>
                <CheckCircle2 size={15} /> Confirm & Create SKU
              </>
            ) : (
              'Continue →'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
