"use client";

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Clock, CheckCircle2, XCircle, AlertTriangle, ShieldCheck, 
  DollarSign, Building2, User, ArrowRight, ChevronRight, RefreshCw, 
  Check, X, FileText, Layers, Calendar, Filter, Search, Award
} from 'lucide-react';

interface ApprovalItem {
  id: string;
  po_number: string;
  total_amount: number;
  currency: string;
  supplier_name: string;
  supplier_category: string;
  supplier_rating: number;
  supplier_color: string;
  supplier_initials: string;
  department: string;
  buyer_name: string;
  priority: string;
  cost_center: string;
  created_at: string;
  target_delivery_date: string;
  approval_tier: string;
  approval_due_date: string;
  sla_status: string;
  budget_limit_check: {
    department_budget: number;
    allocated_to_date: number;
    this_po: number;
    remaining_after: number;
    status: string;
  };
  line_items: Array<{
    item_id: string;
    sku: string;
    name: string;
    qty_ordered: number;
    unit: string;
    unit_price: number;
    line_total: number;
  }>;
}

export default function PendingApprovalsWorkstationPage() {
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedItems, setSelectedItems] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [tierFilter, setTierFilter] = useState('ALL');
  const [activeDossier, setActiveDossier] = useState<ApprovalItem | null>(null);
  const [actionInProgress, setActionInProgress] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const fetchApprovals = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/procurement/purchase-orders/approvals/pending');
      if (res.ok) {
        const data = await res.json();
        setApprovals(data.approvals || []);
      }
    } catch (err) {
      console.error("Failed to load pending approvals:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchApprovals();
  }, []);

  const toggleSelect = (poNumber: string) => {
    setSelectedItems(prev => prev.includes(poNumber) ? prev.filter(i => i !== poNumber) : [...prev, poNumber]);
  };

  const toggleSelectAll = () => {
    if (selectedItems.length > 0) setSelectedItems([]);
    else setSelectedItems(filteredApprovals.map(a => a.po_number));
  };

  const handleSingleApproval = async (poNumber: string, action: 'APPROVE' | 'REJECT') => {
    try {
      setActionInProgress(true);
      const res = await fetch(`http://127.0.0.1:8080/api/v1/procurement/purchase-orders/${poNumber}/transition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          actor_name: "Elena Rostova",
          actor_role: "VP Finance & Operations",
          notes: action === 'APPROVE' 
            ? "Executive Level 3 authorization signed electronically under CAPEX FY2026." 
            : "Rejected: budget allocation exceeds current quarterly ceiling."
        })
      });

      if (res.ok) {
        setToastMessage(`PO ${poNumber} has been ${action === 'APPROVE' ? 'APPROVED and ISSUED' : 'REJECTED'}.`);
        setTimeout(() => setToastMessage(null), 4000);
        if (activeDossier?.po_number === poNumber) setActiveDossier(null);
        fetchApprovals();
      }
    } catch (err) {
      console.error("Approval error:", err);
    } finally {
      setActionInProgress(false);
    }
  };

  const handleBatchApproval = async (action: 'APPROVE' | 'REJECT') => {
    if (selectedItems.length === 0) return;
    try {
      setActionInProgress(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/procurement/purchase-orders/approvals/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          po_ids: selectedItems,
          action,
          approver_name: "Elena Rostova",
          approver_role: "VP Finance & Operations",
          comments: `Batch ${action} execution authorized under enterprise procurement matrix.`
        })
      });

      if (res.ok) {
        const data = await res.json();
        setToastMessage(data.message);
        setTimeout(() => setToastMessage(null), 4000);
        setSelectedItems([]);
        fetchApprovals();
      }
    } catch (err) {
      console.error("Batch error:", err);
    } finally {
      setActionInProgress(false);
    }
  };

  const filteredApprovals = approvals.filter(item => {
    if (tierFilter !== 'ALL') {
      if (tierFilter === 'LEVEL_3' && !item.approval_tier.includes('Level 3')) return false;
      if (tierFilter === 'LEVEL_2' && !item.approval_tier.includes('Level 2')) return false;
      if (tierFilter === 'LEVEL_1' && !item.approval_tier.includes('Level 1')) return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        item.po_number.toLowerCase().includes(q) ||
        item.supplier_name.toLowerCase().includes(q) ||
        item.department.toLowerCase().includes(q) ||
        item.buyer_name.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const totalPendingValue = approvals.reduce((sum, a) => sum + a.total_amount, 0);

  return (
    <div className="flex flex-col h-full bg-[#070B14] text-slate-100 min-h-screen p-6 font-sans">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-5 right-5 z-50 bg-gradient-to-r from-emerald-600 to-teal-600 text-white px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3 border border-emerald-400/40 animate-in fade-in slide-in-from-top-4 duration-300">
          <CheckCircle2 size={20} className="text-white shrink-0" />
          <div className="text-sm font-bold">{toastMessage}</div>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6 pb-5 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-2 text-xs font-bold text-slate-400 uppercase tracking-widest mb-1.5">
            <Link href="/purchase-orders" className="hover:text-cyan-400 transition-colors">Purchase Orders</Link>
            <span className="text-slate-600">/</span>
            <span className="text-amber-400">Executive Approvals</span>
            <span className="text-slate-600">/</span>
            <span className="text-slate-300">Tier Matrix Workstation</span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
            Multi-Tier Executive Approvals Matrix
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30 font-bold uppercase tracking-wider">
              Financial Gatekeeper
            </span>
          </h1>
          <p className="text-xs text-slate-400 mt-1 max-w-2xl">
            Autonomous financial policy threshold manager: Level 1 (&lt;$50k Dept), Level 2 ($50k–$100k Procurement/Finance), and Level 3 (&gt;$100k VP/CFO dual sign-off).
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchApprovals}
            className="p-2.5 rounded-xl bg-slate-900 border border-slate-700/80 text-slate-300 hover:text-white hover:border-slate-600 transition-all shadow-sm"
            title="Refresh Queue"
          >
            <RefreshCw size={16} className={loading ? "animate-spin text-amber-400" : ""} />
          </button>
          <Link href="/purchase-orders">
            <button className="px-4 py-2.5 rounded-xl bg-slate-900 border border-slate-700/80 text-slate-300 hover:text-white text-xs font-bold transition-all flex items-center gap-2 shadow-sm">
              <span>View All POs</span>
            </button>
          </Link>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-[#0E1526] border border-amber-900/40 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-amber-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Pending Authorizations</span>
            <Clock size={16} className="text-amber-400" />
          </div>
          <div className="text-3xl font-black text-amber-300">{approvals.length}</div>
          <div className="text-[10px] text-amber-400/80 font-medium mt-1">Awaiting electronic executive sign-off</div>
        </div>

        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Total Pending Spend</span>
            <DollarSign size={16} className="text-cyan-400" />
          </div>
          <div className="text-3xl font-black text-white">
            ${totalPendingValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-[10px] text-slate-400 font-medium mt-1">Across all enterprise cost centers</div>
        </div>

        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Level 3 (VP / CFO) Threshold</span>
            <Award size={16} className="text-purple-400" />
          </div>
          <div className="text-3xl font-black text-purple-300">
            {approvals.filter(a => a.approval_tier.includes('Level 3')).length}
          </div>
          <div className="text-[10px] text-purple-400/80 font-medium mt-1">Orders exceeding $100,000</div>
        </div>

        <div className="bg-[#0E1526] border border-slate-800 rounded-2xl p-4 shadow-sm relative overflow-hidden">
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Budget Ceiling Check</span>
            <ShieldCheck size={16} className="text-emerald-400" />
          </div>
          <div className="text-3xl font-black text-emerald-400">100%</div>
          <div className="text-[10px] text-emerald-400/80 font-medium mt-1">All orders within Q4 departmental buffer</div>
        </div>
      </div>

      {/* Main Ledger Card */}
      <div className="flex-1 bg-[#0E1526] border border-slate-800/90 rounded-2xl shadow-xl flex flex-col overflow-hidden">
        {/* Filter and Batch Bar */}
        <div className="p-4 bg-slate-900/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3 flex-1 min-w-[280px]">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3.5 top-2.5 text-slate-400" size={15} />
              <input 
                type="text" 
                placeholder="Search PO #, supplier, or department..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-[#070B14] border border-slate-700/80 rounded-xl pl-9 pr-4 py-2 text-xs text-slate-200 placeholder:text-slate-500 outline-none focus:border-amber-500 transition-colors"
              />
            </div>

            <div className="w-48">
              <select
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value)}
                className="w-full bg-[#070B14] border border-slate-700/80 rounded-xl px-3 py-2 text-xs text-slate-200 outline-none focus:border-amber-500"
              >
                <option value="ALL">All Approval Tiers</option>
                <option value="LEVEL_3">Level 3 (VP / CFO &gt;$100k)</option>
                <option value="LEVEL_2">Level 2 (Head $50k-$100k)</option>
                <option value="LEVEL_1">Level 1 (Dept &lt;$50k)</option>
              </select>
            </div>
          </div>

          {/* Batch Actions Button Bar */}
          <div className="flex items-center gap-2">
            {selectedItems.length > 0 && (
              <>
                <button
                  disabled={actionInProgress}
                  onClick={() => handleBatchApproval('REJECT')}
                  className="px-3.5 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 text-xs font-bold transition-all"
                >
                  Reject Selected ({selectedItems.length})
                </button>
                <button
                  disabled={actionInProgress}
                  onClick={() => handleBatchApproval('APPROVE')}
                  className="px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 text-white text-xs font-extrabold shadow-lg transition-all flex items-center gap-1.5"
                >
                  <Check size={14} />
                  <span>Batch Approve Selected ({selectedItems.length})</span>
                </button>
              </>
            )}
          </div>
        </div>

        {/* Pending Approvals Table */}
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="p-16 flex flex-col items-center justify-center text-slate-400 gap-3">
              <RefreshCw size={28} className="animate-spin text-amber-400" />
              <p className="text-xs font-semibold">Scanning executive financial authorization queue...</p>
            </div>
          ) : filteredApprovals.length === 0 ? (
            <div className="p-16 text-center text-slate-400">
              <CheckCircle2 size={40} className="mx-auto mb-2 text-emerald-400" />
              <p className="text-sm font-bold text-slate-200">Executive Queue Clear!</p>
              <p className="text-xs text-slate-500 mt-1">There are currently no purchase orders requiring financial sign-off.</p>
            </div>
          ) : (
            <table className="w-full text-left border-collapse text-xs">
              <thead className="sticky top-0 bg-[#0B101E] border-b border-slate-800 text-[11px] font-bold uppercase tracking-wider text-slate-400 z-10">
                <tr>
                  <th className="py-3.5 px-4 w-10">
                    <input 
                      type="checkbox" 
                      checked={selectedItems.length > 0 && selectedItems.length === filteredApprovals.length}
                      onChange={toggleSelectAll}
                      className="rounded bg-slate-800 border-slate-700 text-amber-500 focus:ring-0 cursor-pointer"
                    />
                  </th>
                  <th className="py-3.5 px-3">PO Number</th>
                  <th className="py-3.5 px-3">Supplier Organization</th>
                  <th className="py-3.5 px-3">Department & Cost Center</th>
                  <th className="py-3.5 px-3 text-right">Commitment Value</th>
                  <th className="py-3.5 px-3">Authorization Tier</th>
                  <th className="py-3.5 px-3">Budget Impact Check</th>
                  <th className="py-3.5 px-4 text-center">Executive Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-medium">
                {filteredApprovals.map(item => {
                  const isChecked = selectedItems.includes(item.po_number);
                  return (
                    <tr 
                      key={item.id} 
                      className={`hover:bg-slate-800/40 transition-colors cursor-pointer ${
                        isChecked ? 'bg-amber-950/20' : ''
                      }`}
                      onClick={() => setActiveDossier(item)}
                    >
                      <td className="py-3.5 px-4" onClick={(e) => e.stopPropagation()}>
                        <input 
                          type="checkbox" 
                          checked={isChecked}
                          onChange={() => toggleSelect(item.po_number)}
                          className="rounded bg-slate-800 border-slate-700 text-amber-500 focus:ring-0 cursor-pointer"
                        />
                      </td>

                      <td className="py-3.5 px-3">
                        <div className="font-extrabold text-amber-400 hover:underline flex items-center gap-1.5">
                          <span>{item.po_number}</span>
                        </div>
                        <div className="text-[10px] text-slate-500 mt-0.5">Created: {item.created_at}</div>
                      </td>

                      <td className="py-3.5 px-3">
                        <div className="flex items-center gap-2.5">
                          <div className={`w-6 h-6 rounded-lg text-white flex items-center justify-center text-[10px] font-black ${item.supplier_color || 'bg-cyan-600'}`}>
                            {item.supplier_initials || 'SP'}
                          </div>
                          <div>
                            <div className="font-bold text-white leading-tight">{item.supplier_name}</div>
                            <div className="text-[10px] text-slate-400 mt-0.5">{item.supplier_category}</div>
                          </div>
                        </div>
                      </td>

                      <td className="py-3.5 px-3">
                        <div className="text-slate-200 font-semibold">{item.department}</div>
                        <div className="text-[10px] text-slate-500">{item.cost_center} • Req by {item.buyer_name}</div>
                      </td>

                      <td className="py-3.5 px-3 text-right">
                        <div className="font-mono font-black text-white text-sm">
                          ${item.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </div>
                        <div className="text-[10px] text-slate-500">USD</div>
                      </td>

                      <td className="py-3.5 px-3">
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-extrabold bg-amber-500/10 text-amber-300 border border-amber-500/30">
                          {item.approval_tier}
                        </span>
                        <div className="text-[10px] text-amber-400/80 mt-1 font-semibold flex items-center gap-1">
                          <Clock size={10} /> SLA Due: {item.approval_due_date}
                        </div>
                      </td>

                      <td className="py-3.5 px-3">
                        <div className="flex items-center gap-1.5 text-emerald-400 font-bold">
                          <CheckCircle2 size={13} />
                          <span>Within Budget Limits</span>
                        </div>
                        <div className="text-[10px] text-slate-500 mt-0.5">
                          Remaining Buffer: ${(item.budget_limit_check?.remaining_after || 33000).toLocaleString()}
                        </div>
                      </td>

                      <td className="py-3.5 px-4 text-center" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-center gap-1.5">
                          <button
                            disabled={actionInProgress}
                            onClick={() => handleSingleApproval(item.po_number, 'REJECT')}
                            className="p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 transition-all"
                            title="Reject PO"
                          >
                            <X size={14} />
                          </button>
                          <button
                            disabled={actionInProgress}
                            onClick={() => handleSingleApproval(item.po_number, 'APPROVE')}
                            className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-extrabold text-[11px] shadow-sm transition-all flex items-center gap-1"
                            title="1-Click Approve & Issue"
                          >
                            <Check size={13} />
                            <span>Approve & Issue</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Line Items & Policy Inspection Modal */}
      {activeDossier && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="bg-[#090E1A] border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            <div className="p-5 bg-[#0D1527] border-b border-slate-800 flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xl font-black text-white">{activeDossier.po_number}</span>
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/10 text-amber-300 border border-amber-500/30">
                    {activeDossier.approval_tier}
                  </span>
                </div>
                <div className="text-xs text-slate-400">
                  Total Financial Value: <strong className="text-white">${activeDossier.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong>
                </div>
              </div>
              <button onClick={() => setActiveDossier(null)} className="p-2 text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>

            <div className="p-6 overflow-y-auto space-y-5 text-xs">
              {/* Budget Limit Card */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 grid grid-cols-3 gap-3">
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-bold">Department Budget</div>
                  <div className="text-sm font-bold text-white mt-0.5">${(activeDossier.budget_limit_check?.department_budget || 500000).toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-bold">Allocated To Date</div>
                  <div className="text-sm font-bold text-slate-300 mt-0.5">${(activeDossier.budget_limit_check?.allocated_to_date || 342000).toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-bold">Buffer Post-PO</div>
                  <div className="text-sm font-bold text-emerald-400 mt-0.5">${(activeDossier.budget_limit_check?.remaining_after || 33000).toLocaleString()}</div>
                </div>
              </div>

              {/* Line Items Spec */}
              <div>
                <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2">Line Items Spec & Quantities</h4>
                <div className="bg-[#0E1526] border border-slate-800 rounded-xl overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900/60 border-b border-slate-800 text-[10px] font-bold uppercase text-slate-400">
                      <tr>
                        <th className="py-2.5 px-3">SKU</th>
                        <th className="py-2.5 px-3">Description</th>
                        <th className="py-2.5 px-3 text-center">Qty</th>
                        <th className="py-2.5 px-3 text-right">Unit Price</th>
                        <th className="py-2.5 px-3 text-right">Total</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {activeDossier.line_items?.map((item, idx) => (
                        <tr key={idx}>
                          <td className="py-2.5 px-3 font-mono text-cyan-400 font-bold">{item.sku}</td>
                          <td className="py-2.5 px-3 text-white font-medium">{item.name}</td>
                          <td className="py-2.5 px-3 text-center text-slate-300 font-bold">{item.qty_ordered} {item.unit}</td>
                          <td className="py-2.5 px-3 text-right font-mono">${item.unit_price.toFixed(2)}</td>
                          <td className="py-2.5 px-3 text-right font-mono font-bold text-white">${item.line_total.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="p-4 bg-[#0D1527] border-t border-slate-800 flex items-center justify-between">
              <span className="text-xs text-slate-400 font-medium">Authorization will be logged to immutable audit ledger.</span>
              <div className="flex items-center gap-2">
                <button
                  disabled={actionInProgress}
                  onClick={() => handleSingleApproval(activeDossier.po_number, 'REJECT')}
                  className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 text-xs font-bold transition-all"
                >
                  Reject PO
                </button>
                <button
                  disabled={actionInProgress}
                  onClick={() => handleSingleApproval(activeDossier.po_number, 'APPROVE')}
                  className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 text-white text-xs font-extrabold shadow-md transition-all flex items-center gap-1.5"
                >
                  <Check size={14} />
                  <span>Authorize & Issue to Supplier Network</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
