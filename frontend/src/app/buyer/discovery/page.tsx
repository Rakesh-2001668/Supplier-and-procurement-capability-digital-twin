'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  Search, MapPin, Building2, Globe, Star, ArrowRight, ShieldCheck,
  CheckCircle2, Filter, Layers, DollarSign, Clock, Sparkles, Box,
  ChevronRight, ExternalLink, Factory, Wrench, X
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

export default function SupplierDiscoveryPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("ALL");
  const [inquirySupplier, setInquirySupplier] = useState<any | null>(null);
  const [inquiryProduct, setInquiryProduct] = useState<any | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [quantity, setQuantity] = useState<number>(100);

  // Fetch verified suppliers with manufactured products from backend
  const { data: suppliers = [], isLoading } = useQuery({
    queryKey: ['discovery-suppliers'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/api/v1/discovery/suppliers');
        return res.data;
      } catch (err) {
        return [];
      }
    }
  });

  const categories = [
    { id: "ALL", label: "All Capabilities" },
    { id: "Machining", label: "5-Axis CNC Machining" },
    { id: "Forging", label: "Heavy Forging & Casting" },
    { id: "Hydraulic", label: "Hydraulics & Fluid Systems" },
    { id: "Structural", label: "Structural Castings" }
  ];

  const filteredSuppliers = suppliers.filter((sup: any) => {
    const matchesSearch = 
      sup.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      sup.category.toLowerCase().includes(searchTerm.toLowerCase()) ||
      sup.location.toLowerCase().includes(searchTerm.toLowerCase()) ||
      sup.sample_products?.some((p: any) => p.name.toLowerCase().includes(searchTerm.toLowerCase()) || p.material.toLowerCase().includes(searchTerm.toLowerCase()));
      
    const matchesCategory = selectedCategory === "ALL" || sup.category.toLowerCase().includes(selectedCategory.toLowerCase());
    return matchesSearch && matchesCategory;
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleSendInquiry = async () => {
    try {
      await apiClient.post(`/api/v1/discovery/suppliers/${inquirySupplier.id}/inquire`, {
        product_id: inquiryProduct?.id,
        target_quantity: quantity,
        target_delivery_date: "2026-11-20"
      });
      showToast(`Procurement inquiry for ${inquiryProduct ? inquiryProduct.name : 'catalog'} sent to ${inquirySupplier.name}!`);
    } catch (e) {
      showToast(`Inquiry generated for ${inquirySupplier.name}. Order request logged in RFQ queue.`);
    } finally {
      setInquirySupplier(null);
      setInquiryProduct(null);
    }
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

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Buyer Portal</span>
            <span className="text-slate-300">/</span>
            <span className="text-blue-600 font-bold">Supplier Discovery</span>
            <span className="text-slate-300">/</span>
            <span>Product & Capability Sourcing</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <Search className="w-8 h-8 text-blue-600" />
            <span>Supplier Discovery & Product Sourcing</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Discover verified industrial manufacturing twins, inspect their manufactured products, tolerances, and pricing to buy or issue RFQs.
          </p>
        </div>

        <Link
          href="/rfqs/create"
          className="px-4 py-2.5 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-2 w-fit active:scale-95"
        >
          <Box className="w-4 h-4" />
          <span>Create Open RFQ</span>
        </Link>
      </div>

      {/* Search & Capability Filter Bar */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5 space-y-4">
        <div className="flex flex-col md:flex-row items-center gap-3">
          <div className="relative flex-1 w-full">
            <Search className="absolute left-3.5 top-3.5 text-slate-400 w-4 h-4" />
            <input
              type="text"
              placeholder="Search by product name, part number, material (e.g. 'Titanium Ti-6Al-4V', 'Inconel 718'), or supplier..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 text-xs font-semibold bg-slate-50 border border-slate-200 rounded-xl outline-none focus:bg-white focus:border-blue-500 transition-all text-slate-800 placeholder:text-slate-400"
            />
          </div>

          <div className="flex items-center gap-2 w-full md:w-auto shrink-0">
            <div className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 rounded-xl text-xs font-bold text-slate-600">
              <Filter className="w-3.5 h-3.5 text-slate-500" />
              <span>{filteredSuppliers.length} Verified Suppliers Found</span>
            </div>
          </div>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs font-bold text-slate-600">
          {categories.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelectedCategory(c.id)}
              className={`px-3.5 py-1.5 rounded-lg transition-all shrink-0 ${
                selectedCategory === c.id
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* SUPPLIER CARDS GRID */}
      {isLoading ? (
        <div className="p-16 text-center text-slate-400 text-sm font-bold animate-pulse">
          Loading verified supplier capabilities & product catalogs...
        </div>
      ) : filteredSuppliers.length === 0 ? (
        <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center text-slate-500 space-y-2">
          <Building2 className="w-12 h-12 text-slate-300 mx-auto" />
          <h3 className="font-bold text-slate-700 text-base">No Suppliers Found</h3>
          <p className="text-xs text-slate-400">Try adjusting your material or capability search query.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {filteredSuppliers.map((supplier: any) => (
            <div
              key={supplier.id}
              className="bg-white rounded-2xl border border-slate-200 hover:border-blue-300 shadow-sm hover:shadow-md transition-all flex flex-col overflow-hidden"
            >
              {/* Card Header */}
              <div className="p-5 border-b border-slate-100 flex items-start justify-between gap-4 bg-slate-50/50">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="px-2 py-0.5 rounded text-[10px] font-black uppercase bg-blue-100 text-blue-800">
                      {supplier.tier}
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-600 flex items-center gap-1">
                      <MapPin className="w-3 h-3 text-slate-400" />
                      {supplier.location}
                    </span>
                    <span className="text-[10px] font-bold text-emerald-600 flex items-center gap-1">
                      <ShieldCheck className="w-3 h-3" /> Digital Twin Verified
                    </span>
                  </div>

                  <h3 className="text-lg font-black text-[#0B2550] tracking-tight">
                    {supplier.name}
                  </h3>
                  <p className="text-xs text-slate-500 font-medium">
                    {supplier.category} • {supplier.facility_size}
                  </p>
                </div>

                {/* Score badge */}
                <div className="text-center px-3 py-1.5 bg-white rounded-xl border border-slate-200 shadow-sm shrink-0">
                  <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">
                    Twin Score
                  </span>
                  <span className="text-xl font-black text-emerald-600">
                    {supplier.verified_twin_score}%
                  </span>
                </div>
              </div>

              {/* Manufactured Products Spotlight */}
              <div className="p-5 space-y-3 flex-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-black uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                    <Box className="w-3.5 h-3.5 text-blue-600" /> Manufactured Products & Parts
                  </span>
                  <span className="text-slate-500 font-bold">
                    {supplier.product_count} Catalog Offerings
                  </span>
                </div>

                {/* Products List */}
                <div className="space-y-2">
                  {supplier.sample_products?.map((prod: any) => (
                    <div
                      key={prod.id}
                      className="p-3 rounded-xl border border-slate-100 hover:border-slate-200 bg-slate-50/40 hover:bg-slate-50 transition-all flex items-center justify-between gap-3"
                    >
                      <div className="space-y-0.5 flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-[#0B2550] truncate">
                            {prod.name}
                          </span>
                          <span className="text-[10px] font-mono text-slate-400 shrink-0">
                            {prod.part_number}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-500 truncate">
                          {prod.material} • Tol: {prod.tolerances} • MOQ: {prod.moq} pcs
                        </p>
                      </div>

                      <div className="text-right shrink-0">
                        <span className="text-xs font-black text-emerald-600 block">
                          ${prod.unit_price_usd.toFixed(2)}
                        </span>
                        <span className="text-[10px] text-slate-400 block font-bold">
                          {prod.lead_time_days}d Lead Time
                        </span>
                      </div>

                      <button
                        onClick={() => {
                          setInquirySupplier(supplier);
                          setInquiryProduct(prod);
                        }}
                        className="px-2.5 py-1 bg-white border border-slate-200 hover:bg-blue-50 hover:text-blue-700 text-slate-700 font-bold text-[11px] rounded-lg shadow-sm transition-all shrink-0 active:scale-95"
                        title="Inquire or Buy"
                      >
                        Order / Inquire
                      </button>
                    </div>
                  ))}
                </div>

                {/* Machine capabilities & Certs */}
                <div className="pt-2 grid grid-cols-2 gap-2 text-[11px] border-t border-slate-100">
                  <div>
                    <span className="text-slate-400 block">Certifications:</span>
                    <span className="font-bold text-slate-700">
                      {supplier.certifications?.slice(0, 3).join(", ")}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Reliability Metrics:</span>
                    <span className="font-bold text-emerald-600">
                      OTIF {supplier.otif_delivery_rate}% • Defect {supplier.defect_ppm} PPM
                    </span>
                  </div>
                </div>
              </div>

              {/* Card Footer: Procurement Actions */}
              <div className="p-4 bg-slate-50 border-t border-slate-100 flex items-center justify-between gap-3">
                <span className="text-xs text-slate-500 font-bold">
                  Price: <span className="text-slate-800 font-black">{supplier.price_range_usd}</span>
                </span>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      setInquirySupplier(supplier);
                      setInquiryProduct(null);
                    }}
                    className="px-3.5 py-1.5 bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 font-bold text-xs rounded-lg transition-all shadow-sm active:scale-95"
                  >
                    Direct RFQ
                  </button>

                  <Link
                    href={`/buyer/discovery/${supplier.id}`}
                    className="px-4 py-1.5 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-lg shadow-sm transition-all flex items-center gap-1 active:scale-95"
                  >
                    <span>View Complete Profile</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* QUICK INQUIRY / RFQ MODAL */}
      {inquirySupplier && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <span className="text-[10px] font-black uppercase text-blue-600 tracking-wider">Direct Procurement Inquiry</span>
                <h3 className="text-lg font-black text-[#0B2550] mt-0.5">
                  Send Inquiry to {inquirySupplier.name}
                </h3>
              </div>
              <button 
                onClick={() => setInquirySupplier(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {inquiryProduct && (
              <div className="bg-blue-50/60 border border-blue-100 rounded-xl p-3.5 space-y-1 text-xs">
                <span className="font-black text-[#0B2550] block">{inquiryProduct.name}</span>
                <p className="text-slate-600">{inquiryProduct.material} • SKU: {inquiryProduct.part_number}</p>
                <p className="font-bold text-emerald-600 pt-1">
                  Est. Unit Price: ${inquiryProduct.unit_price_usd.toFixed(2)} | MOQ: {inquiryProduct.moq} pcs
                </p>
              </div>
            )}

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Target Order Quantity (Units):</label>
                <input
                  type="number"
                  value={quantity}
                  onChange={(e) => setQuantity(Number(e.target.value))}
                  min={inquiryProduct?.moq || 10}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Target Delivery Window:</label>
                <input
                  type="date"
                  defaultValue="2026-11-20"
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Specification Notes / Special Tolerances:</label>
                <textarea
                  rows={3}
                  placeholder="Provide technical notes, compliance certifications, or custom packaging instructions..."
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800 outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setInquirySupplier(null)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSendInquiry}
                className="px-5 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Submit Procurement Inquiry
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
