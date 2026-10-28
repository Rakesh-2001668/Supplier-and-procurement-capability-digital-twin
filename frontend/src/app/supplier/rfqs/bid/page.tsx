'use client';

import React, { useState, useEffect, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  Check, ChevronRight, FileText, Calendar, UploadCloud, 
  Settings, ArrowRight, CheckCircle, Package, MessageSquare, 
  Briefcase, DollarSign, Info, ShieldCheck, Download, Wrench,
  Layers, Zap, Sparkles, Box, Clock, Building2, MapPin, Loader2,
  RefreshCw, CheckCircle2, AlertTriangle, ArrowLeft
} from 'lucide-react';
import Link from 'next/link';
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
  quotation_response: any;
}

function SupplierBiddingContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const rfqIdParam = searchParams.get('id') || 'RFQ-2026-092';

  const [activeTab, setActiveTab] = useState<'BID' | 'GEOMETRY' | 'TERMS'>('BID');
  const [isSuccess, setIsSuccess] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Form State for Commercial Proposal
  const [unitPrice, setUnitPrice] = useState<number>(285.0);
  const [leadTimeDays, setLeadTimeDays] = useState<number>(14);
  const [committedDate, setCommittedDate] = useState<string>('2026-11-20');
  const [paymentTerms, setPaymentTerms] = useState<string>('Net 30 Days (Electronic Bank Wire)');
  const [incoterms, setIncoterms] = useState<string>('DDP Buyer Warehouse');
  const [validityDays, setValidityDays] = useState<number>(30);
  const [technicalNotes, setTechnicalNotes] = useState<string>(
    '100% Zeiss CMM Metrology dimensional report, FAI inspection per AS9102, and EN 10204 3.1 material test certificate included.'
  );

  // Fetch RFQs from backend
  const { data: rfqs = [], isLoading } = useQuery({
    queryKey: ['supplier-incoming-rfqs'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/incoming-rfqs');
      return res.data as IncomingRFQ[];
    }
  });

  const activeRfq = rfqs.find((r) => r.id === rfqIdParam) || rfqs[0];

  // Auto-seed defaults when RFQ loads
  useEffect(() => {
    if (activeRfq) {
      if (activeRfq.quotation_response?.quoted_unit_price) {
        setUnitPrice(activeRfq.quotation_response.quoted_unit_price);
        setLeadTimeDays(activeRfq.quotation_response.production_lead_time_days || 14);
        setCommittedDate(activeRfq.quotation_response.committed_delivery_date || '2026-11-20');
        setPaymentTerms(activeRfq.quotation_response.payment_terms || 'Net 30 Days');
        setIncoterms(activeRfq.quotation_response.incoterms || 'DDP Buyer Warehouse');
        setTechnicalNotes(activeRfq.quotation_response.technical_notes || '');
      } else {
        const atp = activeRfq.atp_analysis;
        const initialPrice = atp?.suggested_unit_price || activeRfq.buyer_target_unit_price || 300.0;
        const initialLead = atp?.suggested_lead_time_days || 14;
        setUnitPrice(initialPrice);
        setLeadTimeDays(initialLead);
        
        const now = new Date();
        now.setDate(now.getDate() + initialLead);
        setCommittedDate(now.toISOString().split('T')[0]);
        if (atp?.notes) {
          setTechnicalNotes(atp.notes);
        }
      }
    }
  }, [activeRfq]);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  // Submission Mutation
  const submitBidMutation = useMutation({
    mutationFn: async () => {
      if (!activeRfq) return;
      const payload = {
        decision: 'ACCEPTED',
        quoted_unit_price: Number(unitPrice),
        production_lead_time_days: Number(leadTimeDays),
        committed_delivery_date: committedDate,
        payment_terms: paymentTerms,
        incoterms: incoterms,
        validity_days: Number(validityDays),
        technical_notes: technicalNotes,
        decline_reason: null
      };
      const res = await apiClient.post(`/api/v1/procurement/incoming-rfqs/${activeRfq.id}/respond`, payload);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supplier-incoming-rfqs'] });
      setIsSuccess(true);
    },
    onError: () => {
      showToast("Error submitting quotation. Please try again.");
    }
  });

  const handleApplyAtp = () => {
    if (!activeRfq?.atp_analysis) return;
    const atp = activeRfq.atp_analysis;
    setUnitPrice(atp.suggested_unit_price);
    setLeadTimeDays(atp.suggested_lead_time_days);
    const now = new Date();
    now.setDate(now.getDate() + (atp.suggested_lead_time_days || 14));
    setCommittedDate(now.toISOString().split('T')[0]);
    if (atp.notes) setTechnicalNotes(atp.notes);
    showToast("Commercial terms calibrated using live Available-to-Promise engine!");
  };

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto py-24 text-center space-y-4">
        <Loader2 className="w-10 h-10 text-blue-600 animate-spin mx-auto" />
        <h3 className="text-lg font-bold text-slate-700">Loading RFQ & Shop-Floor Available-to-Promise Data...</h3>
      </div>
    );
  }

  if (!activeRfq) {
    return (
      <div className="max-w-4xl mx-auto py-24 text-center space-y-4">
        <AlertTriangle className="w-12 h-12 text-amber-500 mx-auto" />
        <h3 className="text-xl font-bold text-slate-800">RFQ Not Found</h3>
        <p className="text-sm text-slate-500">The requested RFQ could not be located in your incoming queue.</p>
        <Link href="/supplier/rfqs" className="inline-block px-5 py-2.5 bg-[#0B2550] text-white rounded-xl font-bold text-xs">
          Return to RFQ Desk
        </Link>
      </div>
    );
  }

  const requestedQty = activeRfq.quantity_requested;
  const extendedTotal = Number(unitPrice || 0) * requestedQty;
  const buyerTargetExtended = activeRfq.buyer_target_total;
  const deltaPct = buyerTargetExtended > 0 ? (((extendedTotal - buyerTargetExtended) / buyerTargetExtended) * 100).toFixed(1) : '0';

  if (isSuccess) {
    return (
      <div className="max-w-3xl mx-auto space-y-6 pt-12 pb-24 text-center animate-in fade-in duration-300">
        <div className="w-20 h-20 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4 border border-emerald-300">
          <CheckCircle2 size={44} className="text-emerald-600" />
        </div>
        <h1 className="text-3xl font-black text-[#0B2550] tracking-tight">
          Quotation Submitted to Buyer!
        </h1>
        <p className="text-slate-500 font-medium text-sm max-w-lg mx-auto">
          Your formal binding proposal for <strong className="text-blue-700">{activeRfq.id}</strong> has been transmitted to <strong className="text-slate-800">{activeRfq.buyer_org}</strong> and logged in the enterprise commercial ledger.
        </p>

        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm max-w-md mx-auto text-left space-y-3 text-xs">
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-slate-400 font-bold">RFQ Reference</span>
            <span className="font-mono font-black text-blue-700">{activeRfq.id}</span>
          </div>
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-slate-400 font-bold">Buyer Organization</span>
            <span className="font-bold text-slate-800">{activeRfq.buyer_org}</span>
          </div>
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-slate-400 font-bold">Quoted Unit Price</span>
            <span className="font-black text-emerald-600 text-sm">${Number(unitPrice).toFixed(2)}</span>
          </div>
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-slate-400 font-bold">Total Contract Value</span>
            <span className="font-black text-[#0B2550] text-sm">${extendedTotal.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
          </div>
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-slate-400 font-bold">Production Lead Time</span>
            <span className="font-bold text-blue-600">{leadTimeDays} Calendar Days (Delivery: {committedDate})</span>
          </div>
          <div className="flex justify-between pt-1">
            <span className="text-slate-400 font-bold">Next Stage</span>
            <span className="font-black text-purple-700 uppercase tracking-wider">Buyer Award / Contract PO Issuance</span>
          </div>
        </div>

        <div className="flex gap-3 justify-center pt-4">
          <Link
            href="/supplier/rfqs"
            className="px-6 py-2.5 bg-slate-100 text-slate-700 font-bold rounded-xl text-xs hover:bg-slate-200 transition-colors"
          >
            Back to RFQ Desk
          </Link>
          <Link
            href="/supplier/inventory"
            className="px-6 py-2.5 bg-[#0B2550] text-white font-bold rounded-xl text-xs hover:bg-blue-900 transition-colors shadow-md"
          >
            Review Plant Inventory
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-6 pb-24 pt-4">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-in fade-in slide-in-from-top-4">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-bold">{toastMessage}</span>
        </div>
      )}

      {/* HEADER BREADCRUMB */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <Link href="/supplier/rfqs" className="hover:text-blue-600 flex items-center gap-1">
              <ArrowLeft className="w-3 h-3" />
              <span>Back to RFQ Desk</span>
            </Link>
            <span className="text-slate-300">/</span>
            <span>Commercial Proposal Desk</span>
            <span className="text-slate-300">/</span>
            <span className="text-purple-600 font-bold">{activeRfq.id}</span>
          </div>
          <h1 className="text-2xl md:text-3xl font-black text-[#0B2550] tracking-tight">
            Commercial Bidding: {activeRfq.title}
          </h1>
          <div className="flex items-center gap-4 text-xs text-slate-500 mt-1 flex-wrap">
            <span className="font-mono font-black text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
              {activeRfq.id}
            </span>
            <span className="flex items-center gap-1 font-bold text-slate-700">
              <Building2 className="w-3.5 h-3.5 text-blue-600" />
              {activeRfq.buyer_org} ({activeRfq.buyer_tier})
            </span>
            <span className="flex items-center gap-1 text-red-600 font-bold">
              <Clock className="w-3.5 h-3.5" />
              Deadline: {activeRfq.deadline_date} ({activeRfq.deadline_countdown})
            </span>
          </div>
        </div>

        {/* Digital Twin Fit Badge */}
        <div className="flex items-center gap-3 bg-white p-3 rounded-2xl border border-slate-200 shadow-sm shrink-0">
          <div className="text-right">
            <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">
              Twin Geometric Fit
            </span>
            <span className="text-xl font-black text-emerald-600 block">
              {activeRfq.capability_fit.match_pct}% Match
            </span>
          </div>
          <ShieldCheck className="w-8 h-8 text-emerald-600 shrink-0" />
        </div>
      </div>

      {/* LIVE AVAILABLE-TO-PROMISE (ATP) BANNER */}
      {activeRfq.atp_analysis && (
        <div className="bg-gradient-to-r from-blue-900 via-[#0B2550] to-indigo-950 text-white rounded-2xl p-5 shadow-lg border border-blue-800/60 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-1.5 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-3 py-1 rounded-full text-xs font-black uppercase bg-emerald-500 text-slate-950 flex items-center gap-1.5 shadow-sm">
                <Zap className="w-3.5 h-3.5 fill-current" />
                {activeRfq.atp_analysis.badge_text}
              </span>
              <span className="text-xs font-bold text-blue-200">
                {activeRfq.atp_analysis.headline}
              </span>
            </div>
            <p className="text-xs text-blue-100/90 leading-relaxed max-w-3xl">
              {activeRfq.atp_analysis.notes}
            </p>
            <div className="flex items-center gap-4 text-[11px] text-blue-200 pt-1 flex-wrap">
              <span>Depot FGI: <strong>{activeRfq.atp_analysis.available_fgi_qty} Units</strong></span>
              <span>•</span>
              <span>Raw Metal Supply: <strong>{activeRfq.atp_analysis.raw_stock_info}</strong></span>
              <span>•</span>
              <span>Fastest Turnaround: <strong className="text-emerald-400">{activeRfq.atp_analysis.suggested_lead_time_days} Days</strong></span>
            </div>
          </div>

          <button
            onClick={handleApplyAtp}
            className="px-5 py-3 bg-white text-[#0B2550] hover:bg-blue-50 font-black text-xs rounded-xl shadow-lg transition-all flex items-center gap-2 shrink-0 active:scale-95"
          >
            <Sparkles className="w-4 h-4 text-purple-600" />
            <span>Apply ATP Calibration</span>
          </button>
        </div>
      )}

      {/* NAVIGATION TABS */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="flex border-b border-slate-200 text-xs font-bold">
          <button
            onClick={() => setActiveTab('BID')}
            className={`flex-1 py-3.5 text-center transition-colors flex items-center justify-center gap-2 ${
              activeTab === 'BID'
                ? 'border-b-2 border-blue-600 text-blue-700 bg-blue-50/40 font-black'
                : 'text-slate-500 hover:bg-slate-50'
            }`}
          >
            <DollarSign className="w-4 h-4" />
            <span>Commercial Proposal & Pricing</span>
          </button>

          <button
            onClick={() => setActiveTab('GEOMETRY')}
            className={`flex-1 py-3.5 text-center transition-colors flex items-center justify-center gap-2 ${
              activeTab === 'GEOMETRY'
                ? 'border-b-2 border-blue-600 text-blue-700 bg-blue-50/40 font-black'
                : 'text-slate-500 hover:bg-slate-50'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>3D CAD Geometry & Tolerances</span>
          </button>

          <button
            onClick={() => setActiveTab('TERMS')}
            className={`flex-1 py-3.5 text-center transition-colors flex items-center justify-center gap-2 ${
              activeTab === 'TERMS'
                ? 'border-b-2 border-blue-600 text-blue-700 bg-blue-50/40 font-black'
                : 'text-slate-500 hover:bg-slate-50'
            }`}
          >
            <ShieldCheck className="w-4 h-4" />
            <span>Compliance, Metrology & Terms</span>
          </button>
        </div>

        <div className="p-6">
          {/* TAB 1: COMMERCIAL PROPOSAL */}
          {activeTab === 'BID' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Proposal Form (2 Cols) */}
              <div className="lg:col-span-2 space-y-6">
                <div className="border border-slate-200 rounded-xl overflow-hidden shadow-sm">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-slate-50 text-slate-500 border-b border-slate-200">
                      <tr>
                        <th className="p-3.5 font-bold">Part Description</th>
                        <th className="p-3.5 font-bold text-center">Requested Qty</th>
                        <th className="p-3.5 font-bold text-right">Buyer Target</th>
                        <th className="p-3.5 font-bold bg-blue-50/60 text-[#0B2550] text-right">Your Unit Price ($)</th>
                        <th className="p-3.5 font-bold text-right">Extended Total ($)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      <tr>
                        <td className="p-3.5">
                          <span className="font-black text-slate-800 block text-sm">{activeRfq.title}</span>
                          <span className="font-mono text-[11px] text-blue-600">{activeRfq.part_number}</span>
                          <span className="text-[11px] text-slate-400 block mt-0.5">{activeRfq.material_spec}</span>
                        </td>
                        <td className="p-3.5 text-center font-black text-slate-700 text-sm">
                          {requestedQty.toLocaleString()} pcs
                        </td>
                        <td className="p-3.5 text-right font-medium text-slate-500">
                          ${activeRfq.buyer_target_unit_price.toFixed(2)}
                        </td>
                        <td className="p-3 bg-blue-50/30 text-right">
                          <input
                            type="number"
                            step="0.01"
                            value={unitPrice}
                            onChange={(e) => setUnitPrice(Number(e.target.value))}
                            className="w-32 px-3 py-2 border border-blue-300 rounded-xl font-black text-right text-base text-[#0B2550] focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                          />
                        </td>
                        <td className="p-3.5 text-right font-black text-[#0B2550] text-base">
                          ${extendedTotal.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                {/* Delivery & Schedule Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-2 text-xs">
                    <label className="font-bold text-slate-700 block">Production Lead Time (Calendar Days):</label>
                    <input
                      type="number"
                      value={leadTimeDays}
                      onChange={(e) => {
                        const val = Number(e.target.value);
                        setLeadTimeDays(val);
                        const d = new Date();
                        d.setDate(d.getDate() + val);
                        setCommittedDate(d.toISOString().split('T')[0]);
                      }}
                      className="w-full px-3 py-2 border border-slate-300 rounded-xl font-black text-sm text-[#0B2550]"
                    />
                    <div className="flex gap-1.5 pt-1">
                      {[
                        { label: '⚡ 48h (FGI)', days: 2 },
                        { label: '⚙️ 8d (WIP)', days: 8 },
                        { label: '📅 14d (Norm)', days: 14 },
                        { label: '📦 28d (Mill)', days: 28 }
                      ].map((pill) => (
                        <button
                          key={pill.days}
                          type="button"
                          onClick={() => {
                            setLeadTimeDays(pill.days);
                            const d = new Date();
                            d.setDate(d.getDate() + pill.days);
                            setCommittedDate(d.toISOString().split('T')[0]);
                          }}
                          className={`px-2 py-1 rounded text-[10px] font-bold border transition-colors ${
                            leadTimeDays === pill.days
                              ? 'bg-blue-600 text-white border-blue-600'
                              : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-100'
                          }`}
                        >
                          {pill.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-2 text-xs">
                    <label className="font-bold text-slate-700 block">Committed Handover / Delivery Date:</label>
                    <input
                      type="date"
                      value={committedDate}
                      onChange={(e) => setCommittedDate(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-xl font-bold text-sm text-[#0B2550]"
                    />
                    <span className="text-[11px] text-slate-400 block pt-1">
                      Buyer requested delivery: <strong>{activeRfq.target_delivery_date}</strong>
                    </span>
                  </div>
                </div>

                {/* Commercial Terms Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-1 text-xs">
                    <label className="font-bold text-slate-700 block">Payment Terms:</label>
                    <input
                      type="text"
                      value={paymentTerms}
                      onChange={(e) => setPaymentTerms(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                    />
                  </div>

                  <div className="space-y-1 text-xs">
                    <label className="font-bold text-slate-700 block">Incoterms:</label>
                    <input
                      type="text"
                      value={incoterms}
                      onChange={(e) => setIncoterms(e.target.value)}
                      className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                    />
                  </div>
                </div>

                {/* Technical & Metrology Assurances */}
                <div className="space-y-1 text-xs">
                  <label className="font-bold text-slate-700 block">Technical Assurances, Metrology & Certification Notes:</label>
                  <textarea
                    rows={3}
                    value={technicalNotes}
                    onChange={(e) => setTechnicalNotes(e.target.value)}
                    className="w-full p-3 border border-slate-200 rounded-xl font-medium text-slate-800 focus:outline-none focus:border-blue-600"
                  />
                </div>
              </div>

              {/* Proposal Summary Card (1 Col) */}
              <div className="space-y-4">
                <div className="bg-slate-50 p-5 rounded-2xl border border-slate-200 space-y-4 text-xs">
                  <h4 className="font-black text-[#0B2550] text-sm uppercase tracking-wider border-b border-slate-200 pb-2">
                    Commercial Proposal Summary
                  </h4>

                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Order Quantity:</span>
                      <span className="font-bold text-slate-800">{requestedQty} units</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Quoted Unit Price:</span>
                      <span className="font-black text-emerald-700 text-sm">${Number(unitPrice).toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Buyer Target Unit:</span>
                      <span className="font-medium text-slate-500">${activeRfq.buyer_target_unit_price.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between pt-1 border-t border-slate-200">
                      <span className="text-slate-500">Budget Variance:</span>
                      <span className={`font-bold ${Number(deltaPct) <= 0 ? 'text-emerald-600' : 'text-amber-600'}`}>
                        {Number(deltaPct) > 0 ? `+${deltaPct}%` : `${deltaPct}%`} vs Target
                      </span>
                    </div>
                  </div>

                  <div className="p-3 bg-white rounded-xl border border-slate-200 space-y-1">
                    <span className="text-[10px] font-black uppercase text-slate-400 block tracking-wider">Total Contract Value</span>
                    <span className="text-2xl font-black text-[#0B2550] block">
                      ${extendedTotal.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </span>
                  </div>

                  <div className="space-y-2 pt-2 border-t border-slate-200">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Production Time:</span>
                      <span className="font-bold text-blue-700">{leadTimeDays} Days</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Committed Handover:</span>
                      <span className="font-bold text-slate-800">{committedDate}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Quote Validity:</span>
                      <span className="font-bold text-slate-800">{validityDays} Days</span>
                    </div>
                  </div>

                  <button
                    onClick={() => submitBidMutation.mutate()}
                    disabled={submitBidMutation.isPending}
                    className="w-full py-3.5 bg-emerald-600 hover:bg-emerald-700 text-white font-black text-sm rounded-xl shadow-lg transition-all flex items-center justify-center gap-2 active:scale-95 disabled:opacity-50"
                  >
                    {submitBidMutation.isPending ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Transmitting Quote...</span>
                      </>
                    ) : (
                      <>
                        <Check className="w-5 h-5" />
                        <span>Submit Binding Quotation</span>
                      </>
                    )}
                  </button>

                  <p className="text-[10px] text-slate-400 text-center leading-normal">
                    By submitting, your firm agrees to hold this quotation valid for {validityDays} days under AS9100D manufacturing terms.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: 3D CAD GEOMETRY & TOLERANCES */}
          {activeTab === 'GEOMETRY' && (
            <div className="space-y-6 text-xs">
              <div className="p-4 bg-slate-50 rounded-2xl border border-slate-200 flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center text-blue-700 shrink-0">
                    <FileText className="w-6 h-6" />
                  </div>
                  <div>
                    <h4 className="text-sm font-black text-slate-800">{activeRfq.cad_filename}</h4>
                    <p className="text-slate-400 font-mono text-[11px]">STEP 3D CAD Solid Model • {activeRfq.cad_filesize}</p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => showToast(`Downloaded ${activeRfq.cad_filename} for CAM toolpath verification.`)}
                  className="px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold rounded-xl flex items-center gap-1.5 shadow-sm"
                >
                  <Download className="w-3.5 h-3.5 text-blue-600" />
                  <span>Download CAD Solid Model</span>
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-1">
                  <span className="text-slate-400 font-bold block">Material Specification:</span>
                  <span className="font-black text-slate-800 text-sm block">{activeRfq.material_spec}</span>
                  <span className="text-[11px] text-slate-500 block pt-1">Chemical & tensile compliance certified per ASTM / AMS standards.</span>
                </div>

                <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-1">
                  <span className="text-slate-400 font-bold block">Precision Tolerance:</span>
                  <span className="font-black text-purple-700 text-sm block">{activeRfq.precision_tolerance}</span>
                  <span className="text-[11px] text-slate-500 block pt-1">Full 3D Zeiss CMM Coordinate Metrology report required on 100% of batch.</span>
                </div>

                <div className="p-4 bg-white rounded-xl border border-slate-200 space-y-1">
                  <span className="text-slate-400 font-bold block">Surface Finishing:</span>
                  <span className="font-black text-slate-800 text-sm block">{activeRfq.surface_treatment}</span>
                  <span className="text-[11px] text-slate-500 block pt-1">Mil-spec anodizing / passivation with salt-spray corrosion resistance.</span>
                </div>
              </div>

              <div className="p-4 bg-blue-50/50 rounded-xl border border-blue-200/60 space-y-2">
                <h5 className="font-bold text-blue-900 flex items-center gap-2">
                  <Wrench className="w-4 h-4 text-blue-600" />
                  <span>Digital Twin Equipment Fit Assessment</span>
                </h5>
                <p className="text-slate-700 leading-relaxed">
                  Machine cell designated for this job: <strong>{activeRfq.capability_fit.machine_fit}</strong>. Material certified in supplier envelope: <strong>{activeRfq.capability_fit.material_fit}</strong>. Metrology fit: <strong>{activeRfq.capability_fit.tolerance_fit}</strong>.
                </p>
              </div>
            </div>
          )}

          {/* TAB 3: COMPLIANCE & TERMS */}
          {activeTab === 'TERMS' && (
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-2">
                  <h5 className="font-black text-[#0B2550] text-sm">Quality Certifications Required:</h5>
                  <ul className="space-y-1.5 text-slate-700">
                    <li className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      <span>AS9100D Aerospace Quality Management System</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      <span>ISO 9001:2015 General Precision Manufacturing</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      <span>EN 10204 Type 3.1 Material Test Report (Heat # Trace)</span>
                    </li>
                  </ul>
                </div>

                <div className="p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-2">
                  <h5 className="font-black text-[#0B2550] text-sm">Packaging & Delivery Standards:</h5>
                  <ul className="space-y-1.5 text-slate-700">
                    <li className="flex items-center gap-2">
                      <Box className="w-4 h-4 text-blue-600" />
                      <span>VCI Anti-Corrosion Vacuum Sealed Packaging</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <Box className="w-4 h-4 text-blue-600" />
                      <span>Laser Engraved Serial & Part Number Identification</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <Box className="w-4 h-4 text-blue-600" />
                      <span>Advance Ship Notice (ASN) with GPS Carrier Tracking</span>
                    </li>
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function SupplierBiddingFlowPage() {
  return (
    <Suspense fallback={
      <div className="max-w-4xl mx-auto py-24 text-center">
        <Loader2 className="w-10 h-10 text-blue-600 animate-spin mx-auto" />
      </div>
    }>
      <SupplierBiddingContent />
    </Suspense>
  );
}
