'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FileText, Send, CheckCircle2, Clock, AlertTriangle, XCircle,
  HelpCircle, DollarSign, Calendar, Truck, ShieldCheck, Download,
  Layers, Wrench, Search, Filter, ArrowUpRight, ArrowRight,
  Eye, RefreshCw, X, ChevronRight, FileCheck, Building2, MapPin,
  Zap, Sparkles, Box
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

interface CapabilityFit {
  match_pct: number;
  machine_fit: string;
  material_fit: string;
  tolerance_fit: string;
}

interface ATPAnalysis {
  status: 'IN_STOCK_FGI' | 'PARTIAL_FGI_WIP' | 'RAW_MATERIAL_READY' | 'MILL_PROCUREMENT_REQUIRED' | 'OUT_OF_SCOPE';
  badge_color: 'emerald' | 'blue' | 'amber' | 'slate' | 'red';
  badge_text: string;
  headline: string;
  available_fgi_qty: number;
  raw_stock_info: string;
  suggested_lead_time_days: number;
  suggested_unit_price: number;
  atp_action: string;
  notes: string;
}

interface QuotationResponse {
  decision: 'ACCEPTED' | 'DECLINED' | 'CLARIFICATION';
  quoted_unit_price: number | null;
  quoted_total_price: number | null;
  production_lead_time_days: number | null;
  committed_delivery_date: string | null;
  payment_terms: string | null;
  incoterms: string | null;
  validity_days: number | null;
  technical_notes: string | null;
  decline_reason: string | null;
  submitted_at: string;
}

interface IncomingRFQ {
  id: string;
  title: string;
  buyer_org: string;
  buyer_tier: string;
  buyer_location: string;
  part_number: string;
  cad_filename: string;
  cad_filesize: string;
  material_spec: string;
  precision_tolerance: string;
  surface_treatment: string;
  quantity_requested: number;
  buyer_target_unit_price: number;
  buyer_target_total: number;
  target_delivery_date: string;
  requested_payment_terms: string;
  requested_incoterms: string;
  deadline_date: string;
  deadline_countdown: string;
  status: 'PENDING_REVIEW' | 'QUOTED' | 'DECLINED' | 'CLARIFICATION_REQUESTED';
  created_at: string;
  capability_fit: CapabilityFit;
  atp_analysis?: ATPAnalysis;
  quotation_response: QuotationResponse | null;
}

export default function SupplierIncomingRFQsPage() {
  const queryClient = useQueryClient();
  const [selectedStatusFilter, setSelectedStatusFilter] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Active RFQ being analyzed or quoted
  const [activeRfqForAction, setActiveRfqForAction] = useState<IncomingRFQ | null>(null);
  const [viewDetailsRfq, setViewDetailsRfq] = useState<IncomingRFQ | null>(null);

  // Form State for Quotation Response
  const [responseForm, setResponseForm] = useState<{
    decision: 'ACCEPTED' | 'DECLINED' | 'CLARIFICATION';
    quoted_unit_price: number;
    production_lead_time_days: number;
    committed_delivery_date: string;
    payment_terms: string;
    incoterms: string;
    validity_days: number;
    technical_notes: string;
    decline_reason: string;
  }>({
    decision: 'ACCEPTED',
    quoted_unit_price: 290.0,
    production_lead_time_days: 14,
    committed_delivery_date: '2026-11-18',
    payment_terms: 'Net 30 Days (Electronic Bank Wire)',
    incoterms: 'DDP Buyer Warehouse',
    validity_days: 30,
    technical_notes: '100% CMM Metrology dimensional report, FAI inspection, and EN 10204 3.1 material test certificate included.',
    decline_reason: ''
  });

  // Fetch incoming RFQs from backend
  const { data: rfqs = [], isLoading, refetch } = useQuery({
    queryKey: ['supplier-incoming-rfqs'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/incoming-rfqs');
      return res.data as IncomingRFQ[];
    }
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  // Mutation to submit quotation response
  const submitResponseMutation = useMutation({
    mutationFn: async (payload: { rfqId: string; data: any }) => {
      const res = await apiClient.post(`/api/v1/procurement/incoming-rfqs/${payload.rfqId}/respond`, payload.data);
      return res.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['supplier-incoming-rfqs'] });
      setActiveRfqForAction(null);
      showToast(data.message || "Quotation reply submitted to buyer successfully!");
    },
    onError: () => {
      showToast("Error submitting quotation response. Please try again.");
    }
  });

  const handleOpenActionModal = (rfq: IncomingRFQ) => {
    setActiveRfqForAction(rfq);
    setResponseForm({
      decision: 'ACCEPTED',
      quoted_unit_price: rfq.buyer_target_unit_price ? Math.round(rfq.buyer_target_unit_price * 1.05) : 300,
      production_lead_time_days: 14,
      committed_delivery_date: rfq.target_delivery_date || '2026-11-20',
      payment_terms: rfq.requested_payment_terms || 'Net 30 Days',
      incoterms: rfq.requested_incoterms || 'DDP Buyer Warehouse',
      validity_days: 30,
      technical_notes: `Includes 100% CMM inspection scan for ${rfq.precision_tolerance}, raw material mill cert for ${rfq.material_spec}, and protective cleanroom packaging.`,
      decline_reason: ''
    });
  };

  // Filtered RFQs
  const filteredRfqs = rfqs.filter((r) => {
    const matchesStatus = selectedStatusFilter === 'ALL' || r.status === selectedStatusFilter;
    const matchesSearch =
      r.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.buyer_org.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.part_number.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  const pendingCount = rfqs.filter(r => r.status === 'PENDING_REVIEW').length;
  const quotedCount = rfqs.filter(r => r.status === 'QUOTED').length;
  const totalPipeline = rfqs.reduce((acc, r) => acc + (r.quotation_response?.quoted_total_price || r.buyer_target_total || 0), 0);

  return (
    <div className="space-y-6 pb-16 max-w-[1600px] mx-auto">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-in fade-in slide-in-from-top-4">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-bold">{toastMessage}</span>
        </div>
      )}

      {/* HEADER BREADCRUMB */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Supplier Operations</span>
            <span className="text-slate-300">/</span>
            <span className="text-purple-600 font-bold">Quotation Management</span>
            <span className="text-slate-300">/</span>
            <span>Incoming RFQ Module</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <FileText className="w-8 h-8 text-blue-600" />
            <span>Incoming RFQs & Quotation Response Desk</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Review quote requests from enterprise buyers, evaluate 3D CAD geometry & capability twin fit, and submit binding price, delivery, and payment quotations.
          </p>
        </div>

        {/* Global Refresh */}
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => {
              refetch();
              showToast("Incoming RFQ feed synchronized with buyer procurement network.");
            }}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span>Sync Buyer RFQs</span>
          </button>
        </div>
      </div>

      {/* TOP PIPELINE METRIC CARDS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Total Incoming RFQs</span>
            <FileText className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-black text-[#0B2550]">{rfqs.length} Requests</div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Matched to Twin</span>
            <span className="font-bold text-emerald-600">100% Verified</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Pending Review & Action</span>
            <Clock className="w-4 h-4 text-amber-500" />
          </div>
          <div className="text-2xl font-black text-amber-600">{pendingCount} Awaiting Response</div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Urgent Deadlines</span>
            <span className="font-bold text-amber-600">Action Required</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Quotations Submitted</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="text-2xl font-black text-emerald-600">{quotedCount} Active Quotes</div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Buyer Evaluation</span>
            <span className="font-bold text-slate-700">Under Review</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm space-y-2">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Total Quoted Pipeline</span>
            <DollarSign className="w-4 h-4 text-purple-600" />
          </div>
          <div className="text-2xl font-black text-[#0B2550]">
            ${totalPipeline.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </div>
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100 flex justify-between">
            <span>Potential Revenue</span>
            <span className="font-bold text-purple-600">Active Pipeline</span>
          </div>
        </div>
      </div>

      {/* FILTER & SEARCH TOOLBAR */}
      <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Status Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0 text-xs font-bold">
          {[
            { id: 'ALL', label: 'All Requests' },
            { id: 'PENDING_REVIEW', label: 'Pending Review' },
            { id: 'QUOTED', label: 'Quoted' },
            { id: 'DECLINED', label: 'Declined' }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setSelectedStatusFilter(tab.id)}
              className={`px-3.5 py-1.5 rounded-xl transition-all whitespace-nowrap ${
                selectedStatusFilter === tab.id
                  ? 'bg-[#0B2550] text-white shadow-sm font-black'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search Input */}
        <div className="relative w-full md:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search by Part, RFQ ID, or Buyer..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-xl text-xs font-medium text-slate-800 placeholder-slate-400 focus:outline-none focus:border-blue-600"
          />
        </div>
      </div>

      {/* INCOMING RFQS LIST */}
      <div className="space-y-4">
        {filteredRfqs.length === 0 ? (
          <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center text-slate-400 space-y-2">
            <FileText className="w-12 h-12 mx-auto text-slate-300 stroke-1" />
            <h4 className="font-bold text-slate-600 text-sm">No RFQs matching criteria</h4>
            <p className="text-xs text-slate-400">Incoming buyer requests will automatically appear here.</p>
          </div>
        ) : (
          filteredRfqs.map((rfq) => (
            <div
              key={rfq.id}
              className={`bg-white rounded-2xl border transition-all p-6 shadow-sm space-y-4 hover:shadow-md ${
                rfq.status === 'PENDING_REVIEW'
                  ? 'border-amber-200 bg-gradient-to-r from-white via-amber-50/10 to-white'
                  : rfq.status === 'QUOTED'
                  ? 'border-emerald-200'
                  : 'border-slate-200 opacity-90'
              }`}
            >
              {/* RFQ Header Row */}
              <div className="flex flex-col md:flex-row md:items-start justify-between gap-4 border-b border-slate-100 pb-4">
                <div className="space-y-1 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono font-black text-sm text-[#0B2550] bg-blue-50 px-2.5 py-0.5 rounded border border-blue-200/50">
                      {rfq.id}
                    </span>
                    <span className="text-xs font-bold text-slate-400">• Received: {rfq.created_at}</span>
                    <span className={`px-2.5 py-0.5 rounded text-[10px] font-black uppercase ${
                      rfq.status === 'PENDING_REVIEW'
                        ? 'bg-amber-100 text-amber-900 border border-amber-300/40'
                        : rfq.status === 'QUOTED'
                        ? 'bg-emerald-100 text-emerald-900 border border-emerald-300/40'
                        : 'bg-slate-100 text-slate-700'
                    }`}>
                      {rfq.status === 'PENDING_REVIEW' ? 'Pending Review' : rfq.status === 'QUOTED' ? 'Quote Submitted' : 'Declined'}
                    </span>

                    {/* Expiry Badge */}
                    <span className="text-[11px] font-bold text-red-600 bg-red-50 border border-red-200 px-2 py-0.5 rounded flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {rfq.deadline_countdown}
                    </span>
                  </div>

                  <h3 className="text-lg font-black text-[#0B2550] pt-1">
                    {rfq.title}
                  </h3>

                  <div className="flex items-center gap-4 text-xs text-slate-500 flex-wrap">
                    <span className="flex items-center gap-1 font-bold text-slate-700">
                      <Building2 className="w-3.5 h-3.5 text-blue-600" />
                      {rfq.buyer_org} ({rfq.buyer_tier})
                    </span>
                    <span className="flex items-center gap-1">
                      <MapPin className="w-3.5 h-3.5 text-slate-400" />
                      {rfq.buyer_location}
                    </span>
                  </div>
                </div>

                {/* Digital Twin & ATP Badges */}
                <div className="flex items-center gap-3 shrink-0 flex-wrap">
                  {rfq.atp_analysis && (
                    <div className="flex items-center gap-2 bg-gradient-to-r from-blue-50 to-indigo-50/50 p-2.5 px-3 rounded-xl border border-blue-200/70">
                      <Zap className="w-5 h-5 text-amber-500 fill-amber-400 shrink-0" />
                      <div className="text-right">
                        <span className="text-[9px] font-black uppercase text-blue-700 block tracking-wider">
                          Live ATP Status
                        </span>
                        <span className="text-xs font-black text-[#0B2550] block whitespace-nowrap">
                          {rfq.atp_analysis.badge_text}
                        </span>
                      </div>
                    </div>
                  )}

                  <div className="flex items-center gap-3 bg-slate-50 p-2.5 px-3 rounded-xl border border-slate-100">
                    <div className="text-right">
                      <span className="text-[9px] font-black uppercase text-slate-400 block tracking-wider">
                        Digital Twin Fit
                      </span>
                      <span className="text-sm font-black text-emerald-600 block">
                        {rfq.capability_fit.match_pct}% Match
                      </span>
                    </div>
                    <ShieldCheck className="w-6 h-6 text-emerald-600 shrink-0" />
                  </div>
                </div>
              </div>

              {/* Technical & Commercial Specifications Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
                <div className="p-3 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                  <span className="text-slate-400 block font-bold text-[11px]">Part Number & 3D CAD:</span>
                  <span className="font-mono font-bold text-slate-800 block">{rfq.part_number}</span>
                  <span className="text-blue-600 font-bold flex items-center gap-1 pt-0.5 text-[11px]">
                    <Download className="w-3 h-3" />
                    {rfq.cad_filename} ({rfq.cad_filesize})
                  </span>
                </div>

                <div className="p-3 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                  <span className="text-slate-400 block font-bold text-[11px]">Material & Tolerance:</span>
                  <span className="font-bold text-slate-800 block truncate" title={rfq.material_spec}>{rfq.material_spec}</span>
                  <span className="text-purple-700 font-black block text-[11px]">{rfq.precision_tolerance}</span>
                </div>

                <div className="p-3 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                  <span className="text-slate-400 block font-bold text-[11px]">Requested Quantity:</span>
                  <span className="font-black text-[#0B2550] text-sm block">{rfq.quantity_requested} Units</span>
                  <span className="text-slate-500 text-[11px] block">Target Delivery: <strong>{rfq.target_delivery_date}</strong></span>
                </div>

                <div className="p-3 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                  <span className="text-slate-400 block font-bold text-[11px]">Buyer Target Budget:</span>
                  <span className="font-black text-emerald-600 text-sm block">${rfq.buyer_target_unit_price.toFixed(2)} / unit</span>
                  <span className="text-slate-500 text-[11px] block">Total Target: <strong>${rfq.buyer_target_total.toLocaleString()}</strong></span>
                </div>
              </div>

              {/* Live Available-to-Promise (ATP) Fulfillment Trace */}
              {rfq.atp_analysis && (
                <div className="p-3.5 bg-gradient-to-r from-blue-50/70 via-indigo-50/40 to-slate-50 rounded-xl border border-blue-200/60 flex items-center justify-between text-xs gap-3 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className={`px-2.5 py-0.5 rounded text-[10px] font-black uppercase ${
                      rfq.atp_analysis.status === 'IN_STOCK_FGI'
                        ? 'bg-emerald-100 text-emerald-900 border border-emerald-300'
                        : rfq.atp_analysis.status === 'PARTIAL_FGI_WIP'
                        ? 'bg-blue-100 text-blue-900 border border-blue-300'
                        : rfq.atp_analysis.status === 'RAW_MATERIAL_READY'
                        ? 'bg-amber-100 text-amber-900 border border-amber-300'
                        : 'bg-red-100 text-red-900 border border-red-300'
                    }`}>
                      {rfq.atp_analysis.badge_text}
                    </span>
                    <span className="font-bold text-slate-800">{rfq.atp_analysis.headline}</span>
                  </div>

                  <div className="flex items-center gap-3 text-[11px] text-slate-600 flex-wrap">
                    <span>Suggested Lead Time: <strong className="text-blue-700">{rfq.atp_analysis.suggested_lead_time_days} Days</strong></span>
                    <span>•</span>
                    <span>Material Trace: <strong className="text-slate-800">{rfq.atp_analysis.raw_stock_info}</strong></span>
                  </div>
                </div>
              )}

              {/* Capability Analysis Details Note */}
              <div className="p-3 bg-blue-50/40 rounded-xl border border-blue-100/60 flex items-center justify-between text-xs text-slate-600 gap-4 flex-wrap">
                <div className="flex items-center gap-4 flex-wrap">
                  <span className="flex items-center gap-1 text-slate-700 font-bold">
                    <Wrench className="w-3.5 h-3.5 text-blue-600" />
                    {rfq.capability_fit.machine_fit}
                  </span>
                  <span className="flex items-center gap-1 text-slate-700 font-bold">
                    <Layers className="w-3.5 h-3.5 text-purple-600" />
                    {rfq.capability_fit.material_fit}
                  </span>
                </div>

                <span className="text-slate-500 font-medium text-[11px]">
                  Terms: {rfq.requested_payment_terms} • Incoterms: {rfq.requested_incoterms}
                </span>
              </div>

              {/* IF ALREADY QUOTED: SHOW SUBMITTED QUOTATION SUMMARY */}
              {rfq.status === 'QUOTED' && rfq.quotation_response && (
                <div className="p-4 bg-emerald-50/60 rounded-xl border border-emerald-200 space-y-2 text-xs">
                  <div className="flex items-center justify-between border-b border-emerald-200/60 pb-2">
                    <div className="flex items-center gap-2">
                      <FileCheck className="w-4 h-4 text-emerald-600" />
                      <span className="font-black text-emerald-900">Your Submitted Quotation Reply</span>
                    </div>
                    <span className="text-[11px] text-emerald-700 font-mono">
                      Submitted: {rfq.quotation_response.submitted_at}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
                    <div>
                      <span className="text-emerald-800 text-[11px] block font-bold">Quoted Unit Price:</span>
                      <span className="text-base font-black text-emerald-700">${rfq.quotation_response.quoted_unit_price?.toFixed(2)}</span>
                    </div>
                    <div>
                      <span className="text-emerald-800 text-[11px] block font-bold">Total Quoted Value:</span>
                      <span className="text-base font-black text-[#0B2550]">${rfq.quotation_response.quoted_total_price?.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
                    </div>
                    <div>
                      <span className="text-emerald-800 text-[11px] block font-bold">Committed Delivery Date:</span>
                      <span className="font-bold text-slate-800">{rfq.quotation_response.committed_delivery_date} ({rfq.quotation_response.production_lead_time_days} Days)</span>
                    </div>
                    <div>
                      <span className="text-emerald-800 text-[11px] block font-bold">Payment & Incoterms:</span>
                      <span className="font-bold text-slate-800">{rfq.quotation_response.payment_terms} • {rfq.quotation_response.incoterms}</span>
                    </div>
                  </div>

                  {rfq.quotation_response.technical_notes && (
                    <p className="text-[11px] text-slate-700 pt-1 border-t border-emerald-200/40">
                      <strong>Assurances:</strong> {rfq.quotation_response.technical_notes}
                    </p>
                  )}
                </div>
              )}

              {/* IF DECLINED: SHOW DECLINE REASON */}
              {rfq.status === 'DECLINED' && rfq.quotation_response && (
                <div className="p-4 bg-red-50/50 rounded-xl border border-red-200 space-y-1 text-xs">
                  <span className="font-bold text-red-900 flex items-center gap-1.5">
                    <XCircle className="w-4 h-4 text-red-600" />
                    Declined by Your Firm:
                  </span>
                  <p className="text-slate-700 text-[11px] leading-relaxed">
                    {rfq.quotation_response.decline_reason}
                  </p>
                </div>
              )}

              {/* Action Buttons Row */}
              <div className="flex items-center justify-between pt-2 border-t border-slate-100 flex-wrap gap-2">
                <span className="text-xs text-slate-400 font-bold">
                  Surface Finish: {rfq.surface_treatment}
                </span>

                <div className="flex items-center gap-2">
                  <Link
                    href={`/supplier/rfqs/bid?id=${rfq.id}`}
                    className="px-3.5 py-2 bg-white border border-blue-200 hover:bg-blue-50 text-blue-700 font-bold text-xs rounded-xl transition-all flex items-center gap-1.5 shadow-sm active:scale-95"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>3D Geometry & Bid Desk</span>
                  </Link>

                  {rfq.status === 'PENDING_REVIEW' ? (
                    <button
                      onClick={() => handleOpenActionModal(rfq)}
                      className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
                    >
                      <Send className="w-4 h-4" />
                      <span>Quick Quote</span>
                    </button>
                  ) : (
                    <button
                      onClick={() => handleOpenActionModal(rfq)}
                      className="px-3.5 py-1.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl transition-all flex items-center gap-1.5 active:scale-95"
                    >
                      <span>Update / Revise Quotation</span>
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* ========================================================================= */}
      {/* MODAL: ANALYZE RFQ & FORMULATE QUOTATION REPLY */}
      {/* ========================================================================= */}
      {activeRfqForAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full p-6 space-y-5 border border-slate-200 max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between border-b border-slate-100 pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono font-black text-xs text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                    {activeRfqForAction.id}
                  </span>
                  <span className="text-xs text-slate-400 font-bold">Buyer: {activeRfqForAction.buyer_org}</span>
                </div>
                <h3 className="text-lg font-black text-[#0B2550] mt-1">
                  Quotation Response: {activeRfqForAction.title}
                </h3>
              </div>
              <button
                onClick={() => setActiveRfqForAction(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* LIVE AVAILABLE-TO-PROMISE (ATP) AUTO-FILL BANNER */}
            {activeRfqForAction.atp_analysis && (
              <div className="p-4 rounded-xl border bg-gradient-to-r from-blue-50/90 via-indigo-50/60 to-white border-blue-200/80 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-sm">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded text-[10px] font-black uppercase bg-[#0B2550] text-white flex items-center gap-1 shadow-sm">
                      <Zap className="w-3 h-3 text-amber-400 fill-amber-400" />
                      {activeRfqForAction.atp_analysis.badge_text}
                    </span>
                    <span className="text-xs font-black text-slate-800">{activeRfqForAction.atp_analysis.headline}</span>
                  </div>
                  <p className="text-[11px] text-slate-600">
                    Suggested Lead Time: <strong className="text-blue-700">{activeRfqForAction.atp_analysis.suggested_lead_time_days} Days</strong> • Target Price: <strong className="text-emerald-700">${activeRfqForAction.atp_analysis.suggested_unit_price}</strong> • {activeRfqForAction.atp_analysis.raw_stock_info}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    const atp = activeRfqForAction.atp_analysis;
                    if (!atp) return;
                    const now = new Date();
                    now.setDate(now.getDate() + (atp.suggested_lead_time_days || 14));
                    const dateStr = now.toISOString().split('T')[0];
                    setResponseForm({
                      ...responseForm,
                      decision: atp.status === 'OUT_OF_SCOPE' ? 'DECLINED' : 'ACCEPTED',
                      quoted_unit_price: atp.suggested_unit_price || responseForm.quoted_unit_price,
                      production_lead_time_days: atp.suggested_lead_time_days || 14,
                      committed_delivery_date: dateStr,
                      technical_notes: atp.notes || responseForm.technical_notes,
                      decline_reason: atp.status === 'OUT_OF_SCOPE' ? atp.notes : ''
                    });
                    showToast("Auto-filled quote from live Available-to-Promise & Twin telemetry!");
                  }}
                  className="px-3.5 py-2 bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs rounded-xl shadow-md transition-all whitespace-nowrap active:scale-95 flex items-center gap-1.5 shrink-0"
                >
                  <Sparkles className="w-4 h-4 text-amber-300" />
                  <span>Auto-Fill from ATP</span>
                </button>
              </div>
            )}

            {/* STEP 1: DECISION (IS RFQ OK OR NOT?) */}
            <div className="space-y-2">
              <label className="text-xs font-black uppercase text-slate-500 tracking-wider block">
                1. Decision & Feasibility Assessment (Is the RFQ Feasible?)
              </label>

              <div className="grid grid-cols-3 gap-3">
                <button
                  type="button"
                  onClick={() => setResponseForm({ ...responseForm, decision: 'ACCEPTED' })}
                  className={`p-3 rounded-xl border text-xs font-bold transition-all text-center flex flex-col items-center gap-1.5 ${
                    responseForm.decision === 'ACCEPTED'
                      ? 'bg-emerald-50 border-emerald-500 text-emerald-900 ring-2 ring-emerald-500/30'
                      : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                  <span>Accept & Quote</span>
                  <span className="text-[10px] text-slate-400 font-normal">RFQ is OK to produce</span>
                </button>

                <button
                  type="button"
                  onClick={() => setResponseForm({ ...responseForm, decision: 'DECLINED' })}
                  className={`p-3 rounded-xl border text-xs font-bold transition-all text-center flex flex-col items-center gap-1.5 ${
                    responseForm.decision === 'DECLINED'
                      ? 'bg-red-50 border-red-500 text-red-900 ring-2 ring-red-500/30'
                      : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  <XCircle className="w-5 h-5 text-red-600" />
                  <span>Decline RFQ</span>
                  <span className="text-[10px] text-slate-400 font-normal">Capacity/Scope Mismatch</span>
                </button>

                <button
                  type="button"
                  onClick={() => setResponseForm({ ...responseForm, decision: 'CLARIFICATION' })}
                  className={`p-3 rounded-xl border text-xs font-bold transition-all text-center flex flex-col items-center gap-1.5 ${
                    responseForm.decision === 'CLARIFICATION'
                      ? 'bg-amber-50 border-amber-500 text-amber-900 ring-2 ring-amber-500/30'
                      : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  <HelpCircle className="w-5 h-5 text-amber-600" />
                  <span>Clarification</span>
                  <span className="text-[10px] text-slate-400 font-normal">Drawing / Tolerances query</span>
                </button>
              </div>
            </div>

            {/* STEP 2A: IF ACCEPTED -> FULL QUOTATION DETAILS */}
            {responseForm.decision === 'ACCEPTED' && (
              <div className="space-y-4 pt-2 border-t border-slate-100 text-xs">
                <label className="text-xs font-black uppercase text-slate-500 tracking-wider block">
                  2. Quotation Pricing, Delivery & Terms
                </label>

                {/* Price Calculation Row */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-4 bg-slate-50 rounded-xl border border-slate-200/80">
                  <div>
                    <label className="font-bold text-slate-700 block mb-1">Quoted Unit Price ($USD):</label>
                    <input
                      type="number"
                      step="0.5"
                      value={responseForm.quoted_unit_price}
                      onChange={(e) => setResponseForm({ ...responseForm, quoted_unit_price: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-slate-300 rounded-xl font-black text-emerald-600 text-sm outline-none focus:border-emerald-600"
                    />
                    <span className="text-[11px] text-slate-400 pt-1 block">
                      Buyer Target: ${activeRfqForAction.buyer_target_unit_price.toFixed(2)}
                    </span>
                  </div>

                  <div>
                    <span className="font-bold text-slate-700 block mb-1">Total Quoted Amount ($):</span>
                    <div className="px-3 py-2 bg-white border border-slate-200 rounded-xl font-black text-[#0B2550] text-base">
                      ${(responseForm.quoted_unit_price * activeRfqForAction.quantity_requested).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </div>
                    <span className="text-[11px] text-slate-400 pt-1 block">
                      Qty: {activeRfqForAction.quantity_requested} Units
                    </span>
                  </div>
                </div>

                {/* Lead Time & Delivery Date */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="font-bold text-slate-700 block mb-1">Manufacturing Lead Time (Calendar Days):</label>
                    <input
                      type="number"
                      value={responseForm.production_lead_time_days}
                      onChange={(e) => setResponseForm({ ...responseForm, production_lead_time_days: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                    />
                  </div>
                  <div>
                    <label className="font-bold text-slate-700 block mb-1">Committed Delivery / Ship Date:</label>
                    <input
                      type="date"
                      value={responseForm.committed_delivery_date}
                      onChange={(e) => setResponseForm({ ...responseForm, committed_delivery_date: e.target.value })}
                      className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                    />
                  </div>
                </div>

                {/* Commercial Terms & Incoterms */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="font-bold text-slate-700 block mb-1">Payment Terms:</label>
                    <select
                      value={responseForm.payment_terms}
                      onChange={(e) => setResponseForm({ ...responseForm, payment_terms: e.target.value })}
                      className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 bg-white"
                    >
                      <option value="Net 30 Days (Electronic Bank Wire)">Net 30 Days (Electronic Bank Wire)</option>
                      <option value="Net 45 Days">Net 45 Days</option>
                      <option value="50% Advance, 50% on Dispatch">50% Advance, 50% on Dispatch</option>
                      <option value="Net 60 Days">Net 60 Days</option>
                    </select>
                  </div>

                  <div>
                    <label className="font-bold text-slate-700 block mb-1">Shipping Incoterms:</label>
                    <select
                      value={responseForm.incoterms}
                      onChange={(e) => setResponseForm({ ...responseForm, incoterms: e.target.value })}
                      className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800 bg-white"
                    >
                      <option value="DDP Buyer Warehouse">DDP (Delivered Duty Paid) Buyer Warehouse</option>
                      <option value="FOB Port">FOB (Free on Board) Port</option>
                      <option value="EXW Factory Gate">EXW (Ex-Works) Factory Gate</option>
                      <option value="CIF Destination">CIF (Cost, Insurance & Freight)</option>
                    </select>
                  </div>
                </div>

                {/* Technical Remarks & Assurances */}
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Quality Assurances & Technical Scope Notes:</label>
                  <textarea
                    rows={3}
                    value={responseForm.technical_notes}
                    onChange={(e) => setResponseForm({ ...responseForm, technical_notes: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl text-xs font-medium text-slate-800 leading-relaxed"
                  />
                </div>
              </div>
            )}

            {/* STEP 2B: IF DECLINED -> REASON */}
            {responseForm.decision === 'DECLINED' && (
              <div className="space-y-3 pt-2 border-t border-slate-100 text-xs">
                <label className="text-xs font-black uppercase text-red-700 tracking-wider block">
                  Decline Reason & Scope Explanation for Buyer
                </label>
                <textarea
                  rows={4}
                  placeholder="Explain why this RFQ cannot be fulfilled (e.g., machine work envelope constraint, material not certified, production slots booked through Q4)..."
                  value={responseForm.decline_reason}
                  onChange={(e) => setResponseForm({ ...responseForm, decline_reason: e.target.value })}
                  className="w-full px-3 py-2 border border-red-200 rounded-xl text-xs font-medium text-slate-800 leading-relaxed bg-red-50/20"
                />
              </div>
            )}

            {/* STEP 2C: IF CLARIFICATION */}
            {responseForm.decision === 'CLARIFICATION' && (
              <div className="space-y-3 pt-2 border-t border-slate-100 text-xs">
                <label className="text-xs font-black uppercase text-amber-700 tracking-wider block">
                  Clarification Query for Buyer Engineering Team
                </label>
                <textarea
                  rows={4}
                  placeholder="Detail the technical drawing ambiguity or tolerance questions requiring buyer review..."
                  value={responseForm.technical_notes}
                  onChange={(e) => setResponseForm({ ...responseForm, technical_notes: e.target.value })}
                  className="w-full px-3 py-2 border border-amber-200 rounded-xl text-xs font-medium text-slate-800 leading-relaxed bg-amber-50/20"
                />
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setActiveRfqForAction(null)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={submitResponseMutation.isPending}
                onClick={() => {
                  submitResponseMutation.mutate({
                    rfqId: activeRfqForAction.id,
                    data: responseForm
                  });
                }}
                className={`px-5 py-2 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95 ${
                  responseForm.decision === 'ACCEPTED'
                    ? 'bg-emerald-600 hover:bg-emerald-700'
                    : responseForm.decision === 'DECLINED'
                    ? 'bg-red-600 hover:bg-red-700'
                    : 'bg-amber-600 hover:bg-amber-700'
                }`}
              >
                {submitResponseMutation.isPending ? (
                  <span>Submitting...</span>
                ) : (
                  <>
                    <Send className="w-3.5 h-3.5" />
                    <span>
                      {responseForm.decision === 'ACCEPTED'
                        ? 'Transmit Formal Quotation'
                        : responseForm.decision === 'DECLINED'
                        ? 'Transmit Decline Decision'
                        : 'Send Clarification Request'}
                    </span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
