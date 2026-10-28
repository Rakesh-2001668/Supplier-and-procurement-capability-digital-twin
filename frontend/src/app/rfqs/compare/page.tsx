"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { 
  ChevronRight, ArrowLeft, Trophy, CheckCircle, AlertTriangle, 
  TrendingDown, TrendingUp, Filter, ShieldCheck, Zap, Download,
  Clock, Package, MoreHorizontal, MessageSquare, Check, X,
  ExternalLink, Sparkles, RefreshCw
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, TEST_TENANT_ID } from '@/lib/apiClient';

export default function BidComparisonMatrix() {
  const queryClient = useQueryClient();
  const [selectedRfqId, setSelectedRfqId] = useState<string>('RFQ-2026-092');
  const [selectedSupplierId, setSelectedSupplierId] = useState<string | null>(null);
  const [showAwardModal, setShowAwardModal] = useState(false);
  const [awardedSuccess, setAwardedSuccess] = useState<any | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // 1. Fetch live RFQ List
  const { data: rfqList = [] } = useQuery({
    queryKey: ['buyer-rfqs-list'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/procurement/rfqs/list');
      return res.data;
    }
  });

  // 2. Fetch specific RFQ Detail
  const { data: rfqDetail } = useQuery({
    queryKey: ['buyer-rfq-detail', selectedRfqId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/procurement/rfqs/${selectedRfqId}`);
      return res.data;
    },
    enabled: !!selectedRfqId
  });

  // 3. Fetch live bids
  const { data: bidsData, isLoading: bidsLoading } = useQuery({
    queryKey: ['buyer-rfq-bids', selectedRfqId],
    queryFn: async () => {
      const res = await apiClient.get(`/api/v1/procurement/rfqs/${selectedRfqId}/bids`);
      return res.data;
    },
    enabled: !!selectedRfqId
  });

  // 4. Award Mutation
  const awardMutation = useMutation({
    mutationFn: async ({ quoteId, supplierId }: { quoteId: string; supplierId: string }) => {
      const res = await apiClient.post(`/api/v1/procurement/rfqs/${selectedRfqId}/award`, {
        quote_id: quoteId,
        supplier_id: supplierId,
        buyer_tenant_id: TEST_TENANT_ID
      });
      return res.data;
    },
    onSuccess: (data) => {
      setAwardedSuccess(data.award);
      setShowAwardModal(false);
      setToastMessage(`Contract awarded! Purchase Order ${data.award.po_number} generated.`);
      queryClient.invalidateQueries({ queryKey: ['buyer-rfq-detail', selectedRfqId] });
      queryClient.invalidateQueries({ queryKey: ['buyer-rfq-bids', selectedRfqId] });
      queryClient.invalidateQueries({ queryKey: ['buyer-rfqs-list'] });
      queryClient.invalidateQueries({ queryKey: ['rfq-awards-list'] });
    }
  });

  const bids: any[] = bidsData?.bids || [];
  const selectedBid = bids.find(b => b.supplier_id === selectedSupplierId) || bids[0];

  const isAwarded = rfqDetail?.status === 'AWARDED' || !!rfqDetail?.awarded_info;

  return (
    <div className="flex flex-col min-h-screen bg-[#070B14] text-slate-100 animate-in fade-in duration-300 pb-24">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] border border-cyan-500/40 text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 backdrop-blur-md animate-bounce">
          <CheckCircle className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-semibold">{toastMessage}</span>
          <button onClick={() => setToastMessage(null)} className="ml-2 text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* HEADER */}
      <div className="border-b border-slate-800 bg-[#0B0F19]/90 backdrop-blur-md px-8 py-6 shrink-0 sticky top-0 z-30">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 max-w-7xl mx-auto w-full">
          <div>
            <div className="text-[11px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-1.5">
              <Link href="/rfqs" className="hover:underline text-slate-400">Sourcing</Link>
              <span className="text-slate-600">›</span>
              <Link href="/rfqs/responses" className="hover:underline text-slate-400">Supplier Responses</Link>
              <span className="text-slate-600">›</span>
              <span className="text-cyan-400 font-extrabold">Side-by-Side Comparison Matrix</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight flex items-center gap-3">
              <span>Bid Comparison Matrix</span>
              <span className="text-sm text-cyan-400 font-mono font-bold bg-[#141B2D] px-2.5 py-1 rounded-lg border border-slate-700">
                {selectedRfqId}
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              Detailed commercial, technical, and operational risk cross-examination across all submitted supplier tenders.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <select
              value={selectedRfqId}
              onChange={(e) => {
                setSelectedRfqId(e.target.value);
                setSelectedSupplierId(null);
              }}
              className="bg-[#141B2D] border border-slate-700 rounded-xl px-3 py-2 text-xs font-bold text-cyan-300 outline-none cursor-pointer"
            >
              {rfqList.map((r: any) => (
                <option key={r.id} value={r.id} className="bg-[#141B2D] text-white">
                  {r.id} - {r.title.slice(0, 30)}...
                </option>
              ))}
            </select>

            <Link
              href="/rfqs/responses"
              className="px-4 py-2 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-xs font-bold transition-all flex items-center gap-2 shadow-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Back to Responses</span>
            </Link>
          </div>
        </div>
      </div>

      <div className="flex-1 px-8 py-6 space-y-6 max-w-7xl w-full mx-auto">
        {/* RFQ TARGET BANNER */}
        {rfqDetail && (
          <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-5 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-wider block mb-1">
                Engineering Sourcing Specification
              </span>
              <h2 className="text-lg font-black text-white">{rfqDetail.title}</h2>
              <div className="flex items-center gap-4 text-xs text-slate-400 mt-1 flex-wrap">
                <span>Part: <strong className="text-slate-200">{rfqDetail.part_number}</strong></span>
                <span>•</span>
                <span>Qty: <strong className="text-white">{rfqDetail.quantity} pcs</strong></span>
                <span>•</span>
                <span>Target Budget: <strong className="text-emerald-400">${rfqDetail.target_total_budget?.toLocaleString()}</strong> (${rfqDetail.target_unit_price}/pc)</span>
                <span>•</span>
                <span>Delivery Deadline: <strong className="text-white">{rfqDetail.target_delivery_date}</strong></span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 font-medium">Bids in Matrix:</span>
              <span className="px-3 py-1 rounded-full text-xs font-black bg-cyan-950 text-cyan-300 border border-cyan-800">
                {bids.length} Submissions
              </span>
            </div>
          </div>
        )}

        {/* COMPARISON MATRIX TABLE */}
        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl shadow-xl overflow-hidden overflow-x-auto">
          {bidsLoading ? (
            <div className="p-16 text-center text-slate-400">
              <RefreshCw className="w-8 h-8 animate-spin mx-auto text-cyan-400 mb-3" />
              <p className="text-sm font-semibold">Comparing supplier quotes...</p>
            </div>
          ) : bids.length === 0 ? (
            <div className="p-16 text-center text-slate-400">
              <AlertTriangle className="w-8 h-8 text-amber-400 mx-auto mb-3" />
              <p className="text-sm font-semibold">No quotation tenders received for this RFQ yet.</p>
            </div>
          ) : (
            <table className="w-full text-left text-xs border-collapse min-w-[900px]">
              <thead>
                <tr className="border-b border-slate-800 bg-[#141B2D]/80">
                  <th className="py-4 px-5 w-64 text-slate-400 font-bold uppercase tracking-wider">
                    Evaluation Parameters
                  </th>
                  {bids.map((b, i) => {
                    const isSelected = selectedSupplierId === b.supplier_id || (!selectedSupplierId && i === 0);
                    const isWinning = b.status === 'AWARDED' || rfqDetail?.awarded_info?.quote_id === b.quote_id;

                    return (
                      <th
                        key={b.quote_id}
                        onClick={() => setSelectedSupplierId(b.supplier_id)}
                        className={`py-4 px-5 text-left cursor-pointer transition-colors border-l border-slate-800 ${
                          isWinning
                            ? 'bg-purple-950/40 text-purple-200'
                            : isSelected
                            ? 'bg-cyan-950/40 text-cyan-200'
                            : 'hover:bg-slate-800/40'
                        }`}
                      >
                        <div className="flex justify-between items-start gap-2 mb-1">
                          <strong className="text-sm font-black text-white">{b.supplier_name}</strong>
                          {isWinning ? (
                            <span className="px-2 py-0.5 rounded text-[10px] font-black bg-purple-500 text-white">AWARDED</span>
                          ) : i === 0 ? (
                            <span className="px-2 py-0.5 rounded text-[10px] font-black bg-cyan-400 text-slate-950">MCDA #1</span>
                          ) : null}
                        </div>
                        <span className="text-[11px] text-slate-400 block font-normal">{b.supplier_tier}</span>
                        <span className="text-xl font-black text-emerald-400 block mt-2 font-mono">
                          ${b.total_amount?.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {/* Section: Commercial */}
                <tr className="bg-slate-900/60 font-bold text-slate-400 text-[10px] uppercase tracking-wider">
                  <td colSpan={bids.length + 1} className="py-2.5 px-5">Commercial Terms & Pricing</td>
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">Unit Price</td>
                  {bids.map(b => (
                    <td key={`up-${b.quote_id}`} className="py-3.5 px-5 font-mono font-bold text-white border-l border-slate-800">
                      ${b.unit_price} / pc
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">Tooling / NRE Costs</td>
                  {bids.map(b => (
                    <td key={`nre-${b.quote_id}`} className="py-3.5 px-5 font-mono border-l border-slate-800">
                      {b.tooling_nre_cost > 0 ? (
                        <span className="text-amber-400 font-bold">+${b.tooling_nre_cost.toLocaleString()}</span>
                      ) : (
                        <span className="text-emerald-400 font-bold">$0 (Standard Fixtures In-House)</span>
                      )}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">Payment Terms</td>
                  {bids.map(b => (
                    <td key={`pt-${b.quote_id}`} className="py-3.5 px-5 text-slate-200 border-l border-slate-800">
                      {b.payment_terms}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">Incoterms</td>
                  {bids.map(b => (
                    <td key={`in-${b.quote_id}`} className="py-3.5 px-5 text-slate-200 border-l border-slate-800">
                      {b.incoterms}
                    </td>
                  ))}
                </tr>

                {/* Section: Operational & Speed */}
                <tr className="bg-slate-900/60 font-bold text-slate-400 text-[10px] uppercase tracking-wider">
                  <td colSpan={bids.length + 1} className="py-2.5 px-5">Turnaround & Supply Chain Readiness</td>
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">Production Lead Time</td>
                  {bids.map(b => (
                    <td key={`lt-${b.quote_id}`} className="py-3.5 px-5 font-bold text-white border-l border-slate-800">
                      <span className="flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-cyan-400" />
                        {b.lead_time_days} Calendar Days ({b.committed_delivery_date})
                      </span>
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">Digital Twin ATP Fit</td>
                  {bids.map(b => (
                    <td key={`atp-${b.quote_id}`} className="py-3.5 px-5 border-l border-slate-800">
                      <span className="text-emerald-300 font-bold block">{b.atp_badge}</span>
                      <span className="text-[11px] text-slate-400 mt-0.5 block">{b.digital_twin_fit}</span>
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">Twin Match Ratio</td>
                  {bids.map(b => (
                    <td key={`tm-${b.quote_id}`} className="py-3.5 px-5 font-bold text-emerald-400 border-l border-slate-800 font-mono text-sm">
                      {b.twin_match_pct}% Verified
                    </td>
                  ))}
                </tr>

                {/* Section: Quality & Compliance */}
                <tr className="bg-slate-900/60 font-bold text-slate-400 text-[10px] uppercase tracking-wider">
                  <td colSpan={bids.length + 1} className="py-2.5 px-5">Quality, Metrology & ESG</td>
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">AS9100 Quality Rating</td>
                  {bids.map(b => (
                    <td key={`qs-${b.quote_id}`} className="py-3.5 px-5 text-slate-200 border-l border-slate-800 font-bold">
                      {b.quality_score}% ({b.quality_ppm} PPM Defect Rate)
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">ESG / Carbon Score</td>
                  {bids.map(b => (
                    <td key={`esg-${b.quote_id}`} className="py-3.5 px-5 font-mono text-slate-300 border-l border-slate-800">
                      {b.esg_score} / 100
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-bold text-slate-300">Composite MCDA Score</td>
                  {bids.map(b => (
                    <td key={`mcda-${b.quote_id}`} className="py-3.5 px-5 font-mono font-black text-cyan-300 text-base border-l border-slate-800">
                      {b.mcda_score} / 100
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* FIXED BOTTOM ACTION BAR */}
      <div className="fixed bottom-0 left-0 right-0 bg-[#0B0F19]/95 backdrop-blur-md border-t border-slate-800 p-4 px-8 z-40">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400">Selected Supplier Tender:</span>
            <strong className="text-white text-sm">
              {selectedBid?.supplier_name || 'None selected'}
            </strong>
            {selectedBid && (
              <span className="text-xs font-mono text-emerald-400 font-bold">
                (${selectedBid.total_amount?.toLocaleString()})
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <Link
              href={`/buyer/negotiation/${selectedBid?.quote_id || ''}`}
              className="px-4 py-2.5 bg-[#141B2D] hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5"
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Negotiate Terms</span>
            </Link>

            {isAwarded ? (
              <div className="px-6 py-2.5 bg-purple-950 border border-purple-500/50 text-purple-300 rounded-xl text-xs font-black">
                Contract Already Awarded
              </div>
            ) : (
              <button
                onClick={() => setShowAwardModal(true)}
                disabled={!selectedBid}
                className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-xl text-xs font-black shadow-lg shadow-emerald-600/30 flex items-center gap-2 transition-all active:scale-95"
              >
                <Trophy className="w-4 h-4" />
                <span>Award Contract to Selected Supplier</span>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* AWARD CONFIRMATION MODAL */}
      {showAwardModal && selectedBid && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in">
          <div className="bg-[#0E1526] border border-cyan-500/60 rounded-2xl max-w-lg w-full p-6 shadow-2xl text-slate-100 space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2.5">
                <div className="w-10 h-10 rounded-xl bg-emerald-950 text-emerald-400 flex items-center justify-center">
                  <Trophy className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-black text-white">Confirm Award Decision</h3>
                  <p className="text-xs text-slate-400">Lock contract and issue formal Purchase Order.</p>
                </div>
              </div>
              <button onClick={() => setShowAwardModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs bg-[#141E34] p-4 rounded-xl border border-slate-800">
              <div className="flex justify-between">
                <span className="text-slate-400">Winning Supplier:</span>
                <strong className="text-white text-sm">{selectedBid.supplier_name}</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Total Award Value:</span>
                <strong className="text-emerald-400 text-sm">
                  ${selectedBid.total_amount?.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Lead Time & Delivery:</span>
                <strong className="text-white">{selectedBid.lead_time_days} Days ({selectedBid.committed_delivery_date})</strong>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                onClick={() => setShowAwardModal(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs rounded-xl transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  awardMutation.mutate({
                    quoteId: selectedBid.quote_id,
                    supplierId: selectedBid.supplier_id
                  });
                }}
                disabled={awardMutation.isPending}
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-black text-xs rounded-xl shadow-lg shadow-emerald-600/30 flex items-center gap-1.5 transition-all"
              >
                {awardMutation.isPending ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Issuing PO...</span>
                  </>
                ) : (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    <span>Confirm Award</span>
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
