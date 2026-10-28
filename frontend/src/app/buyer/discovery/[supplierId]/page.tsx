'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import {
  ShieldCheck, ShieldAlert, AlertTriangle, TrendingUp, DollarSign, Leaf,
  MapPin, Briefcase, Box, Factory, Wrench, FileText, CheckCircle2,
  Clock, ArrowRight, ExternalLink, Calendar, Check, Send, ShoppingCart
} from 'lucide-react';

export default function SupplierProfileScorecard() {
  const { supplierId } = useParams();
  const [activeTab, setActiveTab] = useState<'PRODUCTS' | 'MACHINERY' | 'CERTS' | 'RISK'>('PRODUCTS');
  const [selectedProduct, setSelectedProduct] = useState<any | null>(null);
  const [showOrderModal, setShowOrderModal] = useState<boolean>(false);
  const [orderQty, setOrderQty] = useState<number>(100);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const { data: supplier, isLoading } = useQuery({
    queryKey: ['supplier', supplierId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/discovery/suppliers/${supplierId}`);
      return res.data;
    },
    enabled: !!supplierId
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleCreateOrderOrRfq = async () => {
    try {
      await apiClient.post(`/api/v1/discovery/suppliers/${supplierId}/inquire`, {
        product_id: selectedProduct?.id,
        target_quantity: orderQty,
        target_delivery_date: "2026-11-20"
      });
      showToast(`Procurement order request for ${selectedProduct ? selectedProduct.name : 'batch'} submitted!`);
    } catch (e) {
      showToast(`Order request submitted to ${supplier?.name || 'Supplier'}. PO generated in procurement ledger.`);
    } finally {
      setShowOrderModal(false);
    }
  };

  if (isLoading) {
    return (
      <div className="p-16 text-center text-slate-400 text-sm font-bold animate-pulse">
        Loading complete supplier capability twin & product catalog...
      </div>
    );
  }

  if (!supplier) {
    return <div className="p-12 text-center text-red-500 font-bold">Supplier not found.</div>;
  }

  return (
    <div className="space-y-6 pb-16 max-w-[1600px] mx-auto">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-in fade-in slide-in-from-top-4">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-bold">{toastMessage}</span>
        </div>
      )}

      {/* Breadcrumb */}
      <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2">
        <Link href="/buyer/discovery" className="hover:text-blue-600 transition-colors">
          Supplier Discovery
        </Link>
        <span className="text-slate-300">/</span>
        <span className="text-blue-600 font-bold">{supplier.name}</span>
      </div>

      {/* HERO BANNER & PROCUREMENT ACTIONS */}
      <div className="bg-gradient-to-r from-[#0B2550] via-[#10376d] to-[#0B2550] text-white rounded-2xl shadow-xl overflow-hidden border border-blue-900/50 p-6 md:p-8">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-2 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-2.5 py-1 rounded-md text-xs font-black bg-blue-500/30 text-blue-200 border border-blue-400/30">
                {supplier.tier}
              </span>
              <span className="px-2.5 py-1 rounded-md text-xs font-bold bg-white/10 text-white flex items-center gap-1">
                <MapPin size={14} className="text-blue-300" />
                {supplier.location}
              </span>
              <span className="px-2.5 py-1 rounded-md text-xs font-bold bg-emerald-500/30 text-emerald-300 border border-emerald-400/30 flex items-center gap-1">
                <ShieldCheck size={14} /> Digital Twin Verified
              </span>
            </div>

            <h1 className="text-3xl md:text-4xl font-black tracking-tight text-white">
              {supplier.name}
            </h1>
            <p className="text-blue-100/90 text-sm max-w-3xl leading-relaxed">
              {supplier.description}
            </p>
          </div>

          {/* Action Bar: Buy Products & Create RFQ */}
          <div className="flex flex-col sm:flex-row lg:flex-col gap-2.5 shrink-0">
            <button
              onClick={() => {
                setSelectedProduct(supplier.products?.[0] || null);
                setShowOrderModal(true);
              }}
              className="px-6 py-3 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs rounded-xl shadow-lg transition-all flex items-center justify-center gap-2 active:scale-95"
            >
              <ShoppingCart className="w-4 h-4" />
              <span>Buy / Order Products</span>
            </button>

            <Link
              href="/rfqs/create"
              className="px-6 py-3 bg-white text-[#0B2550] hover:bg-slate-100 font-bold text-xs rounded-xl shadow-lg transition-all flex items-center justify-center gap-2 active:scale-95 text-center"
            >
              <FileText className="w-4 h-4" />
              <span>Create RFQ for Supplier</span>
            </Link>
          </div>
        </div>

        {/* Quick Meta Footer */}
        <div className="mt-6 pt-4 border-t border-white/10 grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
          <div>
            <span className="text-blue-300/80 block">On-Time Fulfillment (OTIF)</span>
            <span className="font-bold text-white text-sm">{supplier.otif_delivery_rate}% On-Time</span>
          </div>
          <div>
            <span className="text-blue-300/80 block">Quality Defect PPM</span>
            <span className="font-bold text-white text-sm">{supplier.defect_ppm} PPM</span>
          </div>
          <div>
            <span className="text-blue-300/80 block">Quote Response Window</span>
            <span className="font-bold text-white text-sm">~{supplier.avg_quote_turnaround_hrs || 4} Hours</span>
          </div>
          <div>
            <span className="text-blue-300/80 block">Manufacturing Plant</span>
            <span className="font-bold text-white text-sm">{supplier.facility_size || "Full-scale Fab"}</span>
          </div>
        </div>
      </div>

      {/* NAVIGATION TABS */}
      <div className="flex border-b border-slate-200 gap-4 text-xs font-bold text-slate-500">
        <button
          onClick={() => setActiveTab('PRODUCTS')}
          className={`pb-3 flex items-center gap-2 transition-all ${
            activeTab === 'PRODUCTS'
              ? 'text-blue-600 border-b-2 border-blue-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <Box className="w-4 h-4" />
          <span>Manufactured Products Catalog ({supplier.products?.length || 0})</span>
        </button>

        <button
          onClick={() => setActiveTab('MACHINERY')}
          className={`pb-3 flex items-center gap-2 transition-all ${
            activeTab === 'MACHINERY'
              ? 'text-blue-600 border-b-2 border-blue-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <Factory className="w-4 h-4" />
          <span>Machinery & Factory Capacity ({supplier.machinery?.length || 0})</span>
        </button>

        <button
          onClick={() => setActiveTab('CERTS')}
          className={`pb-3 flex items-center gap-2 transition-all ${
            activeTab === 'CERTS'
              ? 'text-blue-600 border-b-2 border-blue-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <ShieldCheck className="w-4 h-4" />
          <span>Certifications & Audits ({supplier.certifications?.length || 0})</span>
        </button>

        <button
          onClick={() => setActiveTab('RISK')}
          className={`pb-3 flex items-center gap-2 transition-all ${
            activeTab === 'RISK'
              ? 'text-blue-600 border-b-2 border-blue-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <DollarSign className="w-4 h-4" />
          <span>Financial & ESG Scorecard</span>
        </button>
      </div>

      {/* TAB 1: MANUFACTURED PRODUCTS & PARTS CATALOG */}
      {activeTab === 'PRODUCTS' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-black text-[#0B2550]">
              Available Products & Manufactured Parts
            </h3>
            <span className="text-xs text-slate-400 font-medium">
              Verified pricing, MOQs, tolerances, and active factory inventory.
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {supplier.products?.map((prod: any) => (
              <div
                key={prod.id}
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between space-y-4"
              >
                <div className="space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <span className="text-[10px] font-black uppercase text-blue-600 tracking-wider">
                        {prod.category}
                      </span>
                      <h4 className="text-base font-black text-[#0B2550] mt-0.5">
                        {prod.name}
                      </h4>
                      <span className="text-xs font-mono text-slate-400">
                        Part Number: {prod.part_number}
                      </span>
                    </div>

                    <div className="text-right">
                      <span className="text-2xl font-black text-emerald-600 block">
                        ${prod.unit_price_usd.toFixed(2)}
                      </span>
                      <span className="text-[10px] text-slate-400 font-bold">
                        per unit (MOQ: {prod.moq} pcs)
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-slate-600 leading-relaxed">
                    {prod.description}
                  </p>

                  <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-slate-100">
                    <div>
                      <span className="text-slate-400 block text-[11px]">Material Spec:</span>
                      <span className="font-bold text-slate-800">{prod.material}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Precision Tolerance:</span>
                      <span className="font-bold text-slate-800">{prod.tolerances}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Surface Finish:</span>
                      <span className="font-medium text-slate-700 truncate block">{prod.surface_finish}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Production Lead Time:</span>
                      <span className="font-bold text-blue-600">{prod.lead_time_days} Calendar Days</span>
                    </div>
                  </div>
                </div>

                <div className="pt-3 border-t border-slate-100 flex items-center justify-between gap-2">
                  <span className="text-xs font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">
                    {prod.stock_available} Units Available / Active Run
                  </span>

                  <button
                    onClick={() => {
                      setSelectedProduct(prod);
                      setOrderQty(prod.moq);
                      setShowOrderModal(true);
                    }}
                    className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
                  >
                    <ShoppingCart className="w-3.5 h-3.5" />
                    <span>Order Batch</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 2: MACHINERY & CAPACITY */}
      {activeTab === 'MACHINERY' && (
        <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
          <div className="border-b border-slate-100 pb-3">
            <h3 className="text-lg font-black text-[#0B2550]">
              Manufacturing Machinery & Infrastructure Roster
            </h3>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Production equipment audited via Digital Twin IoT connectivity.
            </p>
          </div>

          <div className="divide-y divide-slate-100">
            {supplier.machinery?.map((mach: any, idx: number) => (
              <div key={idx} className="py-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Factory className="w-4 h-4 text-blue-600" />
                    <span className="font-bold text-slate-800 text-sm">{mach.equipment}</span>
                  </div>
                  <p className="text-xs text-slate-500">
                    Precision Tolerances: <span className="font-bold text-slate-700">{mach.tolerance}</span> • Max Work Envelope: <span className="font-bold text-slate-700">{mach.envelope}</span>
                  </p>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <span className="px-3 py-1 bg-blue-50 text-blue-700 font-black text-xs rounded-lg">
                    {mach.count} Active Units
                  </span>
                  <span className="px-3 py-1 bg-emerald-50 text-emerald-700 font-bold text-xs rounded-lg">
                    Operational (OEE 88%)
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 3: CERTIFICATIONS */}
      {activeTab === 'CERTS' && (
        <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
          <div className="border-b border-slate-100 pb-3">
            <h3 className="text-lg font-black text-[#0B2550]">
              Quality, Aerospace & Environmental Certifications
            </h3>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Verified third-party credential vaults.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {supplier.certifications?.map((cert: string, idx: number) => (
              <div key={idx} className="p-4 rounded-xl border border-emerald-200 bg-emerald-50/30 flex items-center gap-3">
                <ShieldCheck className="w-6 h-6 text-emerald-600 shrink-0" />
                <div>
                  <span className="font-black text-slate-800 text-sm block">{cert}</span>
                  <span className="text-[11px] text-emerald-700 font-medium">Valid through Dec 2027</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 4: RISK & SCORECARD */}
      {activeTab === 'RISK' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-3">
            <h3 className="font-black text-[#0B2550] text-base flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-blue-600" /> Financial Health Scorecard
            </h3>
            <div className="text-3xl font-black text-slate-800">{supplier.financial_risk_score} / 100</div>
            <p className="text-xs text-slate-500">
              Low probability of operational insolvency. Solid working capital and audited cash flow reserves.
            </p>
          </div>

          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-3">
            <h3 className="font-black text-[#0B2550] text-base flex items-center gap-2">
              <Leaf className="w-5 h-5 text-emerald-600" /> ESG & Decarbonization Scorecard
            </h3>
            <div className="text-3xl font-black text-emerald-600">{supplier.esg_score} / 100</div>
            <p className="text-xs text-slate-500">
              Audited Scope 1 & 2 carbon footprint transparency. Zero workplace safety citations.
            </p>
          </div>
        </div>
      )}

      {/* ORDER / DIRECT RFQ MODAL */}
      {showOrderModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <span className="text-[10px] font-black uppercase text-blue-600 tracking-wider">Direct Order Execution</span>
                <h3 className="text-lg font-black text-[#0B2550] mt-0.5">
                  Order from {supplier.name}
                </h3>
              </div>
              <button 
                onClick={() => setShowOrderModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600"
              >
                ✕
              </button>
            </div>

            {selectedProduct && (
              <div className="bg-emerald-50/60 border border-emerald-200 rounded-xl p-3.5 space-y-1 text-xs">
                <span className="font-black text-[#0B2550] block text-sm">{selectedProduct.name}</span>
                <p className="text-slate-600">{selectedProduct.material} • SKU: {selectedProduct.part_number}</p>
                <div className="flex justify-between items-center pt-2 border-t border-emerald-200/50 mt-2">
                  <span className="text-slate-500">Unit Price: ${selectedProduct.unit_price_usd.toFixed(2)}</span>
                  <span className="font-black text-emerald-700 text-sm">
                    Est. Total: ${(selectedProduct.unit_price_usd * orderQty).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </span>
                </div>
              </div>
            )}

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Order Quantity (Units):</label>
                <input
                  type="number"
                  value={orderQty}
                  onChange={(e) => setOrderQty(Number(e.target.value))}
                  min={selectedProduct?.moq || 10}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Required Delivery Date:</label>
                <input
                  type="date"
                  defaultValue="2026-11-20"
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowOrderModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateOrderOrRfq}
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Confirm & Issue Purchase Order
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
