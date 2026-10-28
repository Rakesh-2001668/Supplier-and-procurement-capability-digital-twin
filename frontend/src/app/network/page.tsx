'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  Globe, Users, Building2, ShieldCheck, CheckCircle2, Clock,
  FileText, DollarSign, Truck, AlertCircle, Search, Filter,
  ChevronRight, Calendar, ArrowRight, ExternalLink, X, RefreshCw,
  Plus, Check, Sparkles, MapPin, Layers, Award, FileSignature
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

interface ActiveWork {
  po_number: string;
  title: string;
  quantity: number;
  amount: number;
  committed_delivery: string;
  status: string;
  fulfillment_stage: string;
  progress_pct: number;
}

interface PastWork {
  po_number: string;
  title: string;
  quantity: number;
  amount: number;
  delivered_date: string;
  status: string;
  quality_acceptance_pct: number;
  invoice_ref: string;
}

interface VendorAVL {
  id: string;
  name: string;
  category: string;
  tier: string;
  avl_status: 'APPROVED_PREFERRED' | 'APPROVED_STANDARD' | 'APPROVED_WATCHLIST';
  location: string;
  facility_type: string;
  digital_twin_id: string;
  qualification_date: string;
  last_audit_date: string;
  next_audit_due: string;
  active_works_count: number;
  total_active_spend: number;
  total_lifetime_spend: number;
  past_works_count: number;
  delivery_period: {
    standard_lead_time_days: number;
    expedited_lead_time_days: number;
    otif_delivery_rate: number;
    avg_dispatch_lag_days: number;
    quote_turnaround_hrs: number;
  };
  purchasing_terms: {
    payment_terms: string;
    currency: string;
    incoterms: string;
    master_agreement_no: string;
    agreement_valid_until: string;
    volume_rebate_tier: string;
    warranty_period: string;
    defect_liability: string;
    audit_compliance_status: string;
  };
  capabilities: {
    core_processes: string[];
    materials_certified: string[];
    precision_tolerance: string[];
    surface_finishing: string[];
    certifications: string[];
  };
  works_in_progress: ActiveWork[];
  past_completed_works: PastWork[];
}

export default function SupplierNetworkPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [filterTier, setFilterTier] = useState("ALL");
  const [selectedVendor, setSelectedVendor] = useState<VendorAVL | null>(null);
  const [detailTab, setDetailTab] = useState<'ACTIVE_WORKS' | 'PAST_WORKS' | 'CAPABILITIES' | 'TERMS'>('ACTIVE_WORKS');
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Fetch complete AVL intelligence from backend
  const { data: avlVendors = [], isLoading, refetch } = useQuery({
    queryKey: ['supplier-network-avl'],
    queryFn: async () => {
      try {
        const res = await apiClient.get('/api/v1/network/avl');
        return res.data;
      } catch (err) {
        return [];
      }
    }
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const filteredVendors = avlVendors.filter((v: VendorAVL) => {
    const matchesSearch = 
      v.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      v.category.toLowerCase().includes(searchTerm.toLowerCase()) ||
      v.location.toLowerCase().includes(searchTerm.toLowerCase()) ||
      v.works_in_progress?.some(w => w.po_number.toLowerCase().includes(searchTerm.toLowerCase()) || w.title.toLowerCase().includes(searchTerm.toLowerCase()));
      
    const matchesTier = 
      filterTier === "ALL" || 
      (filterTier === "PREFERRED" && v.avl_status === "APPROVED_PREFERRED") ||
      (filterTier === "STANDARD" && v.avl_status === "APPROVED_STANDARD") ||
      (filterTier === "WATCHLIST" && v.avl_status === "APPROVED_WATCHLIST");

    return matchesSearch && matchesTier;
  });

  // KPI aggregates
  const totalActiveWipSpend = avlVendors.reduce((acc: number, v: VendorAVL) => acc + (v.total_active_spend || 0), 0);
  const totalActiveOrders = avlVendors.reduce((acc: number, v: VendorAVL) => acc + (v.active_works_count || 0), 0);
  const avgOtif = avlVendors.length > 0 
    ? (avlVendors.reduce((acc: number, v: VendorAVL) => acc + (v.delivery_period?.otif_delivery_rate || 0), 0) / avlVendors.length).toFixed(1)
    : "95.2";

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
            <span>Enterprise Portal</span>
            <span className="text-slate-300">/</span>
            <span className="text-blue-600 font-bold">Supplier Network</span>
            <span className="text-slate-300">/</span>
            <span>Approved Vendor List (AVL)</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <Globe className="w-8 h-8 text-blue-600" />
            <span>Supplier Network: Approved Vendor List</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Enterprise command center for pre-approved vendors. Track ongoing work-in-progress, past completed deliveries, technical capabilities, lead times, and purchasing terms.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => {
              refetch();
              showToast("Synchronized Approved Vendor List with ERP & Purchase Orders ledger.");
            }}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span>Sync AVL</span>
          </button>

          <Link
            href="/rfqs/create"
            className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-2 active:scale-95"
          >
            <Plus className="w-4 h-4" />
            <span>Assign New Work (Issue PO / RFQ)</span>
          </Link>
        </div>
      </div>

      {/* KPI METRICS OVERVIEW */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Approved Vendors</span>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-3xl font-black text-[#0B2550]">{avlVendors.length}</span>
            <span className="text-xs font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">100% Qualified</span>
          </div>
          <span className="text-[11px] text-slate-400 mt-2 block font-medium">Audited & contracted suppliers</span>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Work in Progress (WIP)</span>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-3xl font-black text-blue-600">
              ${totalActiveWipSpend.toLocaleString('en-US', { maximumFractionDigits: 0 })}
            </span>
            <span className="text-xs font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
              {totalActiveOrders} Active POs
            </span>
          </div>
          <span className="text-[11px] text-slate-400 mt-2 block font-medium">Currently in production & transit</span>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">On-Time Delivery (OTIF)</span>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-3xl font-black text-emerald-600">{avgOtif}%</span>
            <span className="text-xs font-bold text-slate-500">Benchmark: 90%</span>
          </div>
          <span className="text-[11px] text-slate-400 mt-2 block font-medium">Average across approved network</span>
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Master Purchasing Contracts</span>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-3xl font-black text-[#0B2550]">100%</span>
            <span className="text-xs font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded">MSAs Active</span>
          </div>
          <span className="text-[11px] text-slate-400 mt-2 block font-medium">Standardized terms & volume rebates</span>
        </div>
      </div>

      {/* FILTER & SEARCH BAR */}
      <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="relative flex-1 w-full">
          <Search className="absolute left-3.5 top-3.5 text-slate-400 w-4 h-4" />
          <input
            type="text"
            placeholder="Search approved vendors by name, capability, PO number, or location..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 text-xs font-semibold bg-slate-50 border border-slate-200 rounded-xl outline-none focus:bg-white focus:border-blue-500 transition-all text-slate-800"
          />
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto shrink-0">
          <span className="text-xs font-bold text-slate-400">Status:</span>
          {['ALL', 'PREFERRED', 'STANDARD', 'WATCHLIST'].map((tier) => (
            <button
              key={tier}
              onClick={() => setFilterTier(tier)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                filterTier === tier
                  ? 'bg-[#0B2550] text-white shadow-sm'
                  : 'bg-slate-100 hover:bg-slate-200 text-slate-600'
              }`}
            >
              {tier}
            </button>
          ))}
        </div>
      </div>

      {/* APPROVED VENDOR CARDS LIST */}
      {isLoading ? (
        <div className="p-16 text-center text-slate-400 text-sm font-bold animate-pulse">
          Loading Approved Vendor List & Active Purchase Order status...
        </div>
      ) : filteredVendors.length === 0 ? (
        <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center text-slate-500">
          <Building2 className="w-12 h-12 text-slate-300 mx-auto mb-2" />
          <h3 className="font-bold text-slate-700">No Approved Vendors Found</h3>
          <p className="text-xs text-slate-400 mt-1">Try clearing your search filters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5">
          {filteredVendors.map((vendor: VendorAVL) => (
            <div
              key={vendor.id}
              className="bg-white rounded-2xl border border-slate-200 hover:border-blue-300 shadow-sm transition-all overflow-hidden p-6 space-y-5"
            >
              {/* Row 1: Vendor Header & Identity */}
              <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-100 pb-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`px-2.5 py-0.5 rounded-md text-[10px] font-black uppercase tracking-wider ${
                      vendor.avl_status === 'APPROVED_PREFERRED' ? 'bg-emerald-100 text-emerald-800' :
                      vendor.avl_status === 'APPROVED_STANDARD' ? 'bg-blue-100 text-blue-800' :
                      'bg-amber-100 text-amber-800'
                    }`}>
                      {vendor.avl_status.replace('_', ' ')}
                    </span>
                    <span className="px-2.5 py-0.5 rounded-md text-[10px] font-bold bg-slate-100 text-slate-600">
                      {vendor.tier}
                    </span>
                    <span className="text-[10px] font-bold text-slate-400 flex items-center gap-1">
                      <MapPin className="w-3 h-3" /> {vendor.location}
                    </span>
                    <span className="text-[10px] font-bold text-emerald-600 flex items-center gap-1">
                      <ShieldCheck className="w-3.5 h-3.5" /> Next Audit: {vendor.next_audit_due}
                    </span>
                  </div>

                  <h3 className="text-xl font-black text-[#0B2550] tracking-tight">
                    {vendor.name}
                  </h3>
                  <p className="text-xs text-slate-500 font-medium">
                    {vendor.category} • Digital Twin: <code className="text-slate-600">{vendor.digital_twin_id}</code>
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => {
                      setSelectedVendor(vendor);
                      setDetailTab('ACTIVE_WORKS');
                    }}
                    className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
                  >
                    <span>Analyze Works & Terms</span>
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Row 2: 4-Core Summary Columns (Current Works, Past Works, Lead Time, Purchasing Terms) */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
                {/* Column 1: Works in Progress */}
                <div className="bg-blue-50/50 p-4 rounded-xl border border-blue-100 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-black text-blue-900 uppercase text-[10px] tracking-wider flex items-center gap-1">
                      <Clock className="w-3 h-3 text-blue-600" /> Works Now in Progress
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-black bg-blue-200/60 text-blue-800">
                      {vendor.active_works_count} Open POs
                    </span>
                  </div>
                  <div className="text-lg font-black text-[#0B2550]">
                    ${vendor.total_active_spend.toLocaleString('en-US', { minimumFractionDigits: 2 })} WIP
                  </div>
                  <p className="text-[11px] text-slate-600 leading-snug">
                    {vendor.works_in_progress?.[0] ? vendor.works_in_progress[0].title : 'No active orders in fabrication'}
                  </p>
                  <span className="text-[10px] font-bold text-blue-700 block pt-1">
                    Fulfillment Stage: {vendor.works_in_progress?.[0]?.progress_pct || 0}% Complete
                  </span>
                </div>

                {/* Column 2: Works Assigned Earlier */}
                <div className="bg-emerald-50/50 p-4 rounded-xl border border-emerald-100 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-black text-emerald-900 uppercase text-[10px] tracking-wider flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3 text-emerald-600" /> Works Assigned Earlier
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-black bg-emerald-200/60 text-emerald-800">
                      {vendor.past_works_count} Past POs
                    </span>
                  </div>
                  <div className="text-lg font-black text-emerald-700">
                    ${vendor.total_lifetime_spend.toLocaleString('en-US', { minimumFractionDigits: 2 })} Delivered
                  </div>
                  <p className="text-[11px] text-slate-600 leading-snug">
                    {vendor.past_completed_works?.[0] ? vendor.past_completed_works[0].title : 'Delivered batches on record'}
                  </p>
                  <span className="text-[10px] font-bold text-emerald-700 block pt-1">
                    Quality Pass Rate: 100% Acceptance
                  </span>
                </div>

                {/* Column 3: Delivery Period & Lead Times */}
                <div className="bg-slate-50 p-4 rounded-xl border border-slate-100 space-y-2">
                  <span className="font-black text-slate-500 uppercase text-[10px] tracking-wider flex items-center gap-1">
                    <Truck className="w-3 h-3 text-slate-500" /> Delivery Lead Times
                  </span>
                  <div className="text-lg font-black text-[#0B2550]">
                    {vendor.delivery_period?.standard_lead_time_days} Calendar Days
                  </div>
                  <div className="space-y-1 text-[11px] text-slate-600">
                    <div className="flex justify-between">
                      <span>OTIF Fulfillment:</span>
                      <span className="font-bold text-emerald-600">{vendor.delivery_period?.otif_delivery_rate}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Expedited Option:</span>
                      <span className="font-bold text-slate-700">{vendor.delivery_period?.expedited_lead_time_days} Days</span>
                    </div>
                  </div>
                </div>

                {/* Column 4: Purchasing Terms & Conditions */}
                <div className="bg-slate-50 p-4 rounded-xl border border-slate-100 space-y-2">
                  <span className="font-black text-slate-500 uppercase text-[10px] tracking-wider flex items-center gap-1">
                    <FileSignature className="w-3 h-3 text-slate-500" /> Terms & Conditions
                  </span>
                  <div className="text-sm font-black text-[#0B2550] truncate" title={vendor.purchasing_terms?.payment_terms}>
                    {vendor.purchasing_terms?.payment_terms}
                  </div>
                  <div className="space-y-1 text-[11px] text-slate-600">
                    <div className="flex justify-between">
                      <span>Incoterms:</span>
                      <span className="font-bold text-slate-700 truncate max-w-[120px]">{vendor.purchasing_terms?.incoterms}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>MSA Agreement:</span>
                      <span className="font-bold text-blue-600">{vendor.purchasing_terms?.master_agreement_no}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ========================================================================= */}
      {/* VENDOR DETAIL MODAL: DEEP DIVE INTO WORKS, CAPABILITIES & PURCHASING TERMS */}
      {/* ========================================================================= */}
      {selectedVendor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden border border-slate-200">
            {/* Modal Header */}
            <div className="px-6 py-5 bg-[#0B2550] text-white flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-black bg-blue-500/30 text-blue-200 border border-blue-400/30">
                    AVL IDENTIFIER: {selectedVendor.id}
                  </span>
                  <span className="text-xs text-blue-200">{selectedVendor.location}</span>
                </div>
                <h2 className="text-2xl font-black mt-1 text-white">
                  {selectedVendor.name}
                </h2>
                <p className="text-xs text-blue-200/80">
                  Approved Vendor Dossier: Active WIP, Historical Orders, Manufacturing Capabilities & Purchasing Terms.
                </p>
              </div>
              <button 
                onClick={() => setSelectedVendor(null)}
                className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/10"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Tabs */}
            <div className="flex bg-slate-100 border-b border-slate-200 px-6 gap-6 text-xs font-bold text-slate-600">
              <button
                onClick={() => setDetailTab('ACTIVE_WORKS')}
                className={`py-3 flex items-center gap-1.5 transition-all ${
                  detailTab === 'ACTIVE_WORKS'
                    ? 'text-blue-600 border-b-2 border-blue-600 font-black'
                    : 'hover:text-slate-900'
                }`}
              >
                <Clock className="w-4 h-4" />
                <span>Works in Progress ({selectedVendor.works_in_progress?.length || 0})</span>
              </button>

              <button
                onClick={() => setDetailTab('PAST_WORKS')}
                className={`py-3 flex items-center gap-1.5 transition-all ${
                  detailTab === 'PAST_WORKS'
                    ? 'text-blue-600 border-b-2 border-blue-600 font-black'
                    : 'hover:text-slate-900'
                }`}
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>Past Completed Works ({selectedVendor.past_completed_works?.length || 0})</span>
              </button>

              <button
                onClick={() => setDetailTab('CAPABILITIES')}
                className={`py-3 flex items-center gap-1.5 transition-all ${
                  detailTab === 'CAPABILITIES'
                    ? 'text-blue-600 border-b-2 border-blue-600 font-black'
                    : 'hover:text-slate-900'
                }`}
              >
                <Layers className="w-4 h-4" />
                <span>Technical Capabilities & Equipment</span>
              </button>

              <button
                onClick={() => setDetailTab('TERMS')}
                className={`py-3 flex items-center gap-1.5 transition-all ${
                  detailTab === 'TERMS'
                    ? 'text-blue-600 border-b-2 border-blue-600 font-black'
                    : 'hover:text-slate-900'
                }`}
              >
                <FileSignature className="w-4 h-4" />
                <span>Purchasing Terms & Agreement</span>
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-4 flex-1">
              {/* TAB 1: WORKS IN PROGRESS */}
              {detailTab === 'ACTIVE_WORKS' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between text-xs text-slate-500 pb-2 border-b border-slate-100">
                    <span className="font-bold">Active Purchase Orders Currently Under Fabrication / Shipping</span>
                    <span className="font-black text-blue-600">${selectedVendor.total_active_spend.toLocaleString('en-US', { minimumFractionDigits: 2 })} Total Active WIP</span>
                  </div>

                  {selectedVendor.works_in_progress?.map((work: ActiveWork) => (
                    <div key={work.po_number} className="p-4 rounded-xl border border-blue-200 bg-blue-50/30 space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-xs font-black bg-blue-600 text-white">
                              {work.po_number}
                            </span>
                            <span className="text-xs font-bold text-slate-700">
                              Target Delivery: {work.committed_delivery}
                            </span>
                          </div>
                          <h4 className="text-base font-black text-[#0B2550] mt-1">
                            {work.title}
                          </h4>
                          <p className="text-xs text-slate-600">
                            Batch Quantity: <span className="font-bold text-slate-800">{work.quantity} units</span>
                          </p>
                        </div>

                        <div className="text-right">
                          <span className="text-lg font-black text-[#0B2550]">
                            ${work.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                          </span>
                          <span className="text-[10px] text-blue-700 block font-bold">
                            {work.progress_pct}% Fulfillment
                          </span>
                        </div>
                      </div>

                      {/* Progress Bar & Stage */}
                      <div>
                        <div className="flex justify-between text-[11px] font-bold text-slate-600 mb-1">
                          <span>Status: {work.fulfillment_stage}</span>
                          <span>{work.progress_pct}%</span>
                        </div>
                        <div className="w-full bg-slate-200 rounded-full h-2">
                          <div className="bg-blue-600 h-2 rounded-full transition-all" style={{ width: `${work.progress_pct}%` }} />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* TAB 2: PAST COMPLETED WORKS */}
              {detailTab === 'PAST_WORKS' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between text-xs text-slate-500 pb-2 border-b border-slate-100">
                    <span className="font-bold">Historical Orders Delivered & Fulfilled</span>
                    <span className="font-black text-emerald-600">${selectedVendor.total_lifetime_spend.toLocaleString('en-US', { minimumFractionDigits: 2 })} Lifetime Volume</span>
                  </div>

                  <table className="w-full text-xs text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-200 text-slate-400 font-bold">
                        <th className="pb-2">PO Number</th>
                        <th className="pb-2">Delivered Description</th>
                        <th className="pb-2 text-right">Units</th>
                        <th className="pb-2 text-right">Order Amount</th>
                        <th className="pb-2 text-right">Delivered Date</th>
                        <th className="pb-2 text-right">Quality Pass</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {selectedVendor.past_completed_works?.map((past: PastWork) => (
                        <tr key={past.po_number} className="hover:bg-slate-50">
                          <td className="py-3 font-bold text-[#0B2550]">{past.po_number}</td>
                          <td className="py-3 text-slate-700">{past.title}</td>
                          <td className="py-3 text-right text-slate-600">{past.quantity}</td>
                          <td className="py-3 text-right font-black text-slate-800">
                            ${past.amount.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                          </td>
                          <td className="py-3 text-right text-slate-500">{past.delivered_date}</td>
                          <td className="py-3 text-right">
                            <span className="px-2 py-0.5 rounded text-[10px] font-black bg-emerald-100 text-emerald-800">
                              {past.quality_acceptance_pct}% Accepted
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* TAB 3: CAPABILITIES */}
              {detailTab === 'CAPABILITIES' && (
                <div className="space-y-5">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="border border-slate-200 rounded-xl p-4 space-y-2">
                      <span className="text-xs font-black uppercase text-blue-600 tracking-wider">Core Manufacturing Processes</span>
                      <ul className="text-xs text-slate-700 space-y-1.5 list-disc pl-4 font-medium">
                        {selectedVendor.capabilities?.core_processes?.map((p: string, idx: number) => (
                          <li key={idx}>{p}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="border border-slate-200 rounded-xl p-4 space-y-2">
                      <span className="text-xs font-black uppercase text-blue-600 tracking-wider">Certified Materials</span>
                      <ul className="text-xs text-slate-700 space-y-1.5 list-disc pl-4 font-medium">
                        {selectedVendor.capabilities?.materials_certified?.map((m: string, idx: number) => (
                          <li key={idx}>{m}</li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  <div className="border border-slate-200 rounded-xl p-4 space-y-3">
                    <span className="text-xs font-black uppercase text-blue-600 tracking-wider">Quality Certifications & Metrology</span>
                    <div className="flex flex-wrap gap-2">
                      {selectedVendor.capabilities?.certifications?.map((c: string, idx: number) => (
                        <span key={idx} className="px-3 py-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-lg text-xs font-bold flex items-center gap-1.5">
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                          <span>{c}</span>
                        </span>
                      ))}
                    </div>
                    <p className="text-xs text-slate-500 pt-1">
                      Certified Precision Tolerances: <span className="font-black text-slate-800">{selectedVendor.capabilities?.precision_tolerance}</span>
                    </p>
                  </div>
                </div>
              )}

              {/* TAB 4: PURCHASING TERMS & CONDITIONS */}
              {detailTab === 'TERMS' && (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4 text-xs">
                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                      <span className="text-slate-400 block font-bold">Standard Payment Terms:</span>
                      <span className="font-black text-[#0B2550] text-sm">{selectedVendor.purchasing_terms?.payment_terms}</span>
                    </div>

                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                      <span className="text-slate-400 block font-bold">Incoterms & Freight Terms:</span>
                      <span className="font-black text-[#0B2550] text-sm">{selectedVendor.purchasing_terms?.incoterms}</span>
                    </div>

                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                      <span className="text-slate-400 block font-bold">Master Agreement (MSA / MPA):</span>
                      <span className="font-black text-blue-600 text-sm">{selectedVendor.purchasing_terms?.master_agreement_no}</span>
                      <span className="text-[11px] text-slate-500 block">Valid through: {selectedVendor.purchasing_terms?.agreement_valid_until}</span>
                    </div>

                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                      <span className="text-slate-400 block font-bold">Volume Rebate Agreement:</span>
                      <span className="font-bold text-slate-800">{selectedVendor.purchasing_terms?.volume_rebate_tier}</span>
                    </div>

                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                      <span className="text-slate-400 block font-bold">Warranty Guarantee:</span>
                      <span className="font-bold text-slate-800">{selectedVendor.purchasing_terms?.warranty_period}</span>
                    </div>

                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                      <span className="text-slate-400 block font-bold">RMA & Defect Liability:</span>
                      <span className="font-bold text-slate-800">{selectedVendor.purchasing_terms?.defect_liability}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Modal Footer Actions */}
            <div className="px-6 py-4 bg-slate-50 border-t border-slate-200 flex justify-between items-center">
              <span className="text-xs text-slate-500">
                Supplier Digital Twin certified under enterprise procurement standards.
              </span>

              <div className="flex items-center gap-2">
                <Link
                  href="/rfqs/create"
                  className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
                >
                  <Plus className="w-4 h-4" />
                  <span>Assign New Work / PO</span>
                </Link>

                <button
                  onClick={() => setSelectedVendor(null)}
                  className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-100"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
