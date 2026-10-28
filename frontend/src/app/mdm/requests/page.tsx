'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  ShieldCheck, AlertTriangle, ArrowRight, Search, 
  RefreshCw, CheckCircle2, Building2, Layers, Sparkles, 
  CreditCard, Lock, Box, Sliders, CheckCheck, XCircle,
  Clock, ShieldAlert, Award, FileText, ArrowDownRight
} from 'lucide-react';
import axios from 'axios';

interface StandardMaterial {
  material_id: string;
  description: string;
  category: string;
  commodity_code: string;
  uom: string;
  standard_price_inr: number;
  drawing_number: string;
  plant_extensions: string[];
  status: string;
}

interface MaterialRequest {
  id: string;
  requester: string;
  proposed_description: string;
  category: string;
  commodity_code: string;
  uom: string;
  target_plant: string;
  status: string;
  duplicate_score: number;
  matched_material_id?: string;
  duplicate_reason?: string;
  created_at: string;
}

interface BankChangeRequest {
  id: string;
  supplier_id: string;
  supplier_name: string;
  old_bank_details: {
    bank_name: string;
    account_number: string;
    ifsc_code: string;
    branch: string;
  };
  new_bank_details: {
    bank_name: string;
    account_number: string;
    ifsc_code: string;
    branch: string;
  };
  initiated_by: string;
  first_approver?: string;
  first_approved_at?: string;
  second_approver?: string;
  second_approved_at?: string;
  status: string;
  cooling_off_until?: string;
  sod_rule_enforced: string;
}

export default function MDMGovernancePage() {
  const [activeTab, setActiveTab] = useState<'catalog' | 'requests' | 'bank_changes'>('requests');
  const [materials, setMaterials] = useState<StandardMaterial[]>([]);
  const [requests, setRequests] = useState<MaterialRequest[]>([]);
  const [bankChanges, setBankChanges] = useState<BankChangeRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // New Request Form State
  const [showNewReqModal, setShowNewReqModal] = useState(false);
  const [proposedDesc, setProposedDesc] = useState('');
  const [reqCategory, setReqCategory] = useState('Castings & Forgings');
  const [reqCommodity, setReqCommodity] = useState('CAST-ALU-HPDC');
  const [reqPlant, setReqPlant] = useState('P100 Hosur');
  const [submittingReq, setSubmittingReq] = useState(false);

  // Steward Approve Modal State
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [selectedReq, setSelectedReq] = useState<MaterialRequest | null>(null);
  const [stewardActor, setStewardActor] = useState('u:steward.metals');
  const [approving, setApproving] = useState(false);

  // Bank Change Approve Modal State
  const [showBankModal, setShowBankModal] = useState(false);
  const [selectedBCR, setSelectedBCR] = useState<BankChangeRequest | null>(null);
  const [bankApprover, setBankApprover] = useState('u:finance.director.global');
  const [approvingBank, setApprovingBank] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [matRes, reqRes, bcrRes] = await Promise.all([
        axios.get('http://localhost:8080/api/v1/mdm/material-catalog'),
        axios.get('http://localhost:8080/api/v1/mdm/material-requests'),
        axios.get('http://localhost:8080/api/v1/mdm/bank-change-requests')
      ]);

      if (matRes.data?.materials) setMaterials(matRes.data.materials);
      if (reqRes.data?.requests) setRequests(reqRes.data.requests);
      if (bcrRes.data?.requests) setBankChanges(bcrRes.data.requests);
    } catch (err) {
      console.error('Failed to load MDM data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreateRequest = async () => {
    setSubmittingReq(true);
    try {
      const res = await axios.post('http://localhost:8080/api/v1/mdm/material-requests', {
        proposed_description: proposedDesc,
        category: reqCategory,
        commodity_code: reqCommodity,
        uom: 'EA',
        target_plant: reqPlant,
        actor: 'u:planner.hosur'
      });

      if (res.data.status === 'BLOCKED_DUPLICATE') {
        setToastMessage(`BLOCKED (Principle P03): ${res.data.message}`);
      } else {
        setToastMessage(`Submitted to Domain Steward: ID ${res.data.request.id}`);
      }
      setShowNewReqModal(false);
      fetchData();
    } catch (err: any) {
      console.error('Request submission error:', err);
      setToastMessage(err.response?.data?.detail || 'Failed to submit request');
    } finally {
      setSubmittingReq(false);
    }
  };

  const handleStewardApprove = async () => {
    if (!selectedReq) return;
    setApproving(true);
    try {
      const res = await axios.post(
        `http://localhost:8080/api/v1/mdm/material-requests/${selectedReq.id}/approve`,
        {
          actor: stewardActor,
          comments: 'Approved aerospace grade specification.'
        }
      );

      if (res.data.status === 'success') {
        setToastMessage(`Material ${res.data.material_id} created and extended to plant. SOD-06 validated.`);
        setShowApproveModal(false);
        fetchData();
      }
    } catch (err: any) {
      console.error('Steward approval error:', err);
      setToastMessage(err.response?.data?.detail || 'SOD-06 block or approval failure');
    } finally {
      setApproving(false);
    }
  };

  const handleBankApprove = async () => {
    if (!selectedBCR) return;
    setApprovingBank(true);
    try {
      const res = await axios.post(
        `http://localhost:8080/api/v1/mdm/bank-change-requests/${selectedBCR.id}/approve`,
        {
          actor: bankApprover,
          approval_stage: selectedBCR.status === 'PENDING_FIRST' ? 'FIRST' : 'SECOND',
          comments: 'Corporate treasury cancelled cheque validation.'
        }
      );

      setToastMessage(res.data.message);
      setShowBankModal(false);
      fetchData();
    } catch (err: any) {
      console.error('Bank approve error:', err);
      setToastMessage(err.response?.data?.detail || 'SOD-02 dual approval conflict');
    } finally {
      setApprovingBank(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 space-y-6">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="p-4 rounded-xl bg-cyan-950/80 border border-cyan-500/50 text-cyan-200 flex items-center justify-between shadow-xl shadow-cyan-950/30 animate-in fade-in duration-200">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-cyan-400" />
            <span className="font-medium text-sm">{toastMessage}</span>
          </div>
          <button 
            onClick={() => setToastMessage(null)} 
            className="text-xs px-2.5 py-1 rounded-md bg-cyan-900/60 hover:bg-cyan-800 text-cyan-300"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="px-2.5 py-0.5 rounded text-[11px] font-semibold tracking-wider uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Module M03 • MDM-01..04
            </span>
            <span className="text-xs text-slate-400 font-mono">Master Data Governance</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Governed Master Data & Bank Change Cockpit
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Strict Principles P03 & P05: Fuzzy duplicate detection blocks duplicate records, SOD-06 steward checks, and SOD-02 bank dual approval.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={fetchData}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 text-xs font-medium text-slate-200 border border-slate-700/60 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button 
            onClick={() => setShowNewReqModal(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-xs font-semibold text-white shadow-lg shadow-cyan-600/20 transition"
          >
            <Sparkles className="w-3.5 h-3.5" />
            New Material Request
          </button>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800/80 pb-3">
        <button
          onClick={() => setActiveTab('requests')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'requests'
              ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <ShieldCheck className="w-4 h-4" />
          Material Requests ({requests.length})
        </button>

        <button
          onClick={() => setActiveTab('bank_changes')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'bank_changes'
              ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <CreditCard className="w-4 h-4" />
          Supplier Bank Changes & SOD-02 ({bankChanges.length})
        </button>

        <button
          onClick={() => setActiveTab('catalog')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition ${
            activeTab === 'catalog'
              ? 'bg-blue-500/10 text-blue-400 border border-blue-500/30'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
          }`}
        >
          <Box className="w-4 h-4" />
          Standard Material Catalog ({materials.length})
        </button>
      </div>

      {/* Tab 1: Material Requests with Principle P03 / P05 Checks */}
      {activeTab === 'requests' && (
        <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-cyan-400" />
                Material Master Requests & Duplicate Shield (MDM-02)
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Evaluates incoming requests against master catalog with fuzzy token matching (&ge;0.92 blocked under Principle P03).
              </p>
            </div>
            <span className="text-xs font-mono text-cyan-400 bg-cyan-950/60 px-2.5 py-1 rounded border border-cyan-500/30">
              SOD-06 Enforced
            </span>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-800/80">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/80 text-slate-400 font-medium border-b border-slate-800">
                <tr>
                  <th className="py-3 px-3.5">Request ID</th>
                  <th className="py-3 px-3.5">Proposed Description</th>
                  <th className="py-3 px-3.5">Requester & Plant</th>
                  <th className="py-3 px-3.5">Fuzzy Duplicate Score</th>
                  <th className="py-3 px-3.5">Status & Reason</th>
                  <th className="py-3 px-3.5 text-right">Steward Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {requests.map((req) => (
                  <tr key={req.id} className="hover:bg-slate-800/30">
                    <td className="py-3.5 px-3.5">
                      <span className="font-bold text-cyan-400">{req.id}</span>
                      <div className="text-[10px] text-slate-500 mt-0.5 font-sans">{req.category}</div>
                    </td>

                    <td className="py-3.5 px-3.5 font-sans">
                      <div className="font-bold text-slate-200">{req.proposed_description}</div>
                      <span className="text-[10px] text-slate-400 font-mono">{req.commodity_code}</span>
                    </td>

                    <td className="py-3.5 px-3.5 text-slate-300">
                      <div>{req.requester}</div>
                      <div className="text-[10px] text-slate-400">{req.target_plant}</div>
                    </td>

                    <td className="py-3.5 px-3.5">
                      <div className="flex items-center gap-2">
                        <div className="w-16 bg-slate-900 rounded-full h-1.5 overflow-hidden">
                          <div 
                            className={`h-1.5 rounded-full ${
                              req.duplicate_score >= 0.92 ? 'bg-rose-500' : 'bg-emerald-500'
                            }`}
                            style={{ width: `${req.duplicate_score * 100}%` }}
                          />
                        </div>
                        <span className={`font-bold ${
                          req.duplicate_score >= 0.92 ? 'text-rose-400' : 'text-emerald-400'
                        }`}>
                          {parseInt(String(req.duplicate_score * 100))}%
                        </span>
                      </div>
                      {req.matched_material_id && (
                        <div className="text-[10px] text-slate-400 mt-0.5">
                          Matched: <strong className="text-slate-200">{req.matched_material_id}</strong>
                        </div>
                      )}
                    </td>

                    <td className="py-3.5 px-3.5 font-sans">
                      {req.status === 'REJECTED_DUPLICATE' ? (
                        <div>
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
                            <XCircle className="w-3 h-3" />
                            BLOCKED DUPLICATE
                          </span>
                          <p className="text-[10px] text-rose-300/80 mt-1 line-clamp-1">
                            {req.duplicate_reason}
                          </p>
                        </div>
                      ) : req.status === 'APPROVED' ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                          <CheckCircle2 className="w-3 h-3" />
                          APPROVED
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                          <Clock className="w-3 h-3" />
                          PENDING STEWARD
                        </span>
                      )}
                    </td>

                    <td className="py-3.5 px-3.5 text-right font-sans">
                      {req.status === 'PENDING_STEWARD' ? (
                        <button
                          onClick={() => { setSelectedReq(req); setShowApproveModal(true); }}
                          className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-bold text-white shadow-md shadow-emerald-600/20 transition"
                        >
                          Steward Approve
                        </button>
                      ) : (
                        <span className="text-slate-500 text-xs">No Action</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 2: Supplier Bank Changes with Dual-Approval (SOD-02) */}
      {activeTab === 'bank_changes' && (
        <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <CreditCard className="w-5 h-5 text-amber-400" />
                Supplier Bank Detail Modifications & Cooling-Off (SOD-02)
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Mandatory dual-approval from distinct Finance Controllers with an automatic 14-day invoice posting lockout.
              </p>
            </div>
            <span className="text-xs font-mono text-amber-300 bg-amber-950/60 px-2.5 py-1 rounded border border-amber-500/30">
              Critical SoD Rule SOD-02
            </span>
          </div>

          <div className="space-y-4">
            {bankChanges.map((bcr) => (
              <div key={bcr.id} className="p-5 rounded-xl bg-slate-900/60 border border-slate-800 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800 pb-3">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm font-bold text-amber-400 bg-amber-950/60 px-2.5 py-1 rounded border border-amber-500/30">
                      {bcr.id}
                    </span>
                    <div>
                      <h4 className="text-sm font-bold text-white">{bcr.supplier_name} ({bcr.supplier_id})</h4>
                      <span className="text-[11px] text-slate-400 font-mono">Initiated: {bcr.initiated_by}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className={`px-2.5 py-1 rounded text-xs font-semibold ${
                      bcr.status === 'APPROVED' 
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30' 
                        : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                    }`}>
                      {bcr.status}
                    </span>

                    {bcr.status !== 'APPROVED' && (
                      <button
                        onClick={() => { setSelectedBCR(bcr); setShowBankModal(true); }}
                        className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-xs font-bold text-white shadow-md shadow-amber-600/20 transition"
                      >
                        Sign Dual Approval
                      </button>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  {/* Old Bank Details */}
                  <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-1">
                    <span className="text-[10px] font-semibold uppercase text-slate-400">Previous Verified Account</span>
                    <div className="text-sm font-bold text-slate-300">{bcr.old_bank_details.bank_name}</div>
                    <div className="font-mono text-slate-400">A/C: {bcr.old_bank_details.account_number}</div>
                    <div className="font-mono text-slate-400">IFSC: {bcr.old_bank_details.ifsc_code} ({bcr.old_bank_details.branch})</div>
                  </div>

                  {/* New Bank Details */}
                  <div className="p-3.5 rounded-xl bg-cyan-950/20 border border-cyan-500/30 space-y-1">
                    <span className="text-[10px] font-semibold uppercase text-cyan-400">Proposed New Account Details</span>
                    <div className="text-sm font-bold text-cyan-200">{bcr.new_bank_details.bank_name}</div>
                    <div className="font-mono text-cyan-300">A/C: {bcr.new_bank_details.account_number}</div>
                    <div className="font-mono text-cyan-300">IFSC: {bcr.new_bank_details.ifsc_code} ({bcr.new_bank_details.branch})</div>
                  </div>
                </div>

                {/* Approvals & Cooling-off Bar */}
                <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 text-xs space-y-2">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-4 text-[11px]">
                      <div>
                        <span className="text-slate-500 block">First Approver</span>
                        <span className="font-mono text-slate-200 font-bold">
                          {bcr.first_approver || 'Pending Sign-Off'}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500 block">Second Approver</span>
                        <span className="font-mono text-slate-200 font-bold">
                          {bcr.second_approver || 'Pending Sign-Off'}
                        </span>
                      </div>
                    </div>

                    {bcr.cooling_off_until && (
                      <div className="flex items-center gap-2 text-amber-300 font-mono text-[11px]">
                        <Clock className="w-3.5 h-3.5 text-amber-400" />
                        <span>Cooling-off Lockout: Active until {bcr.cooling_off_until.split('T')[0]}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 3: Standard Material Catalog */}
      {activeTab === 'catalog' && (
        <div className="p-6 rounded-2xl bg-[#0B1528] border border-slate-800 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Box className="w-5 h-5 text-blue-400" />
                Governed Standard Materials Catalog (MDM-01)
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Enterprise approved master records accessible across P100 Hosur and P200 Chennai plants.
              </p>
            </div>
            <span className="text-xs font-mono text-slate-400">
              {materials.length} Standard Master Records
            </span>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-800/80">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-900/80 text-slate-400 font-medium border-b border-slate-800">
                <tr>
                  <th className="py-3 px-3.5">Material ID</th>
                  <th className="py-3 px-3.5">Description</th>
                  <th className="py-3 px-3.5">Commodity Code</th>
                  <th className="py-3 px-3.5">Drawing / Spec</th>
                  <th className="py-3 px-3.5">Standard Price</th>
                  <th className="py-3 px-3.5">Plant Extensions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {materials.map((mat) => (
                  <tr key={mat.material_id} className="hover:bg-slate-800/30">
                    <td className="py-3.5 px-3.5 font-bold text-cyan-400">{mat.material_id}</td>
                    <td className="py-3.5 px-3.5 font-sans font-medium text-slate-200">{mat.description}</td>
                    <td className="py-3.5 px-3.5 text-slate-400">{mat.commodity_code}</td>
                    <td className="py-3.5 px-3.5 text-slate-300">{mat.drawing_number}</td>
                    <td className="py-3.5 px-3.5 text-emerald-400 font-bold">₹{mat.standard_price_inr.toFixed(2)} / {mat.uom}</td>
                    <td className="py-3.5 px-3.5 font-sans text-[11px] text-slate-400">
                      {mat.plant_extensions.join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* New Material Request Modal */}
      {showNewReqModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-lg bg-[#0B1528] border border-slate-700 rounded-2xl shadow-2xl p-6 space-y-5 text-slate-100">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3">
              <div>
                <span className="text-xs font-mono text-cyan-400 font-semibold">Principle P03 & P05 • Governance</span>
                <h3 className="text-lg font-bold text-white mt-0.5">Submit Standard Material Request</h3>
              </div>
              <button onClick={() => setShowNewReqModal(false)} className="text-slate-400 hover:text-white">✕</button>
            </div>

            <div className="space-y-4 text-xs">
              <div>
                <label className="block font-semibold text-slate-300 mb-1">
                  Proposed Material Description (Runs live duplicate match)
                </label>
                <input
                  type="text"
                  placeholder="e.g. DC-330 Aluminium Die-Cast Housing..."
                  value={proposedDesc}
                  onChange={(e) => setProposedDesc(e.target.value)}
                  className="w-full px-3.5 py-2.5 bg-slate-900 border border-slate-700 rounded-xl text-slate-200 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">Category</label>
                  <select
                    value={reqCategory}
                    onChange={(e) => setReqCategory(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-slate-200 focus:outline-none"
                  >
                    <option value="Castings & Forgings">Castings & Forgings</option>
                    <option value="Electrical & Motors">Electrical & Motors</option>
                    <option value="Raw Materials">Raw Materials</option>
                    <option value="Fasteners & Hardware">Fasteners & Hardware</option>
                  </select>
                </div>
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">Target Plant</label>
                  <select
                    value={reqPlant}
                    onChange={(e) => setReqPlant(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-slate-200 focus:outline-none"
                  >
                    <option value="P100 Hosur">P100 Hosur</option>
                    <option value="P200 Chennai">P200 Chennai</option>
                  </select>
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 text-[11px] text-slate-400 space-y-1">
                <div>&bull; If similarity is &ge;92% with an existing standard record, creation is strictly blocked.</div>
                <div>&bull; Requester cannot act as Domain Steward to approve (SOD-06).</div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button onClick={() => setShowNewReqModal(false)} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300">
                Cancel
              </button>
              <button
                onClick={handleCreateRequest}
                disabled={submittingReq || !proposedDesc.trim()}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-teal-600 hover:from-cyan-500 hover:to-teal-500 text-xs font-bold text-white shadow-lg shadow-cyan-600/20 disabled:opacity-50 transition"
              >
                {submittingReq ? 'Checking Duplicate Shield...' : 'Submit Request'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Steward Approve Modal */}
      {showApproveModal && selectedReq && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-md bg-[#0B1528] border border-slate-700 rounded-2xl shadow-2xl p-6 space-y-5 text-slate-100">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3">
              <div>
                <span className="text-xs font-mono text-emerald-400 font-semibold">SOD-06 Enforced • Domain Steward</span>
                <h3 className="text-lg font-bold text-white mt-0.5">Approve Material Request</h3>
              </div>
              <button onClick={() => setShowApproveModal(false)} className="text-slate-400 hover:text-white">✕</button>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 space-y-1 text-xs">
              <div>Proposed: <strong className="text-slate-100">{selectedReq.proposed_description}</strong></div>
              <div>Requester: <strong className="text-cyan-400 font-mono">{selectedReq.requester}</strong></div>
              <div>Duplicate Score: <span className="font-mono text-emerald-400 font-bold">{parseInt(String(selectedReq.duplicate_score * 100))}%</span></div>
            </div>

            <div className="space-y-3">
              <label className="block text-xs font-semibold text-slate-300">
                Domain Steward Actor (Must differ from requester)
              </label>
              <input
                type="text"
                value={stewardActor}
                onChange={(e) => setStewardActor(e.target.value)}
                className="w-full px-3.5 py-2 bg-slate-900 border border-slate-700 rounded-xl font-mono text-cyan-300 text-xs focus:outline-none"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button onClick={() => setShowApproveModal(false)} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300">
                Cancel
              </button>
              <button
                onClick={handleStewardApprove}
                disabled={approving}
                className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-xs font-bold text-white shadow-lg shadow-emerald-600/20 disabled:opacity-50 transition"
              >
                {approving ? 'Verifying SOD-06...' : 'Approve & Catalog'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bank Change Dual-Approve Modal */}
      {showBankModal && selectedBCR && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-md bg-[#0B1528] border border-slate-700 rounded-2xl shadow-2xl p-6 space-y-5 text-slate-100">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3">
              <div>
                <span className="text-xs font-mono text-amber-400 font-semibold">SOD-02 Enforced • Dual Approval</span>
                <h3 className="text-lg font-bold text-white mt-0.5">Finance Sign-Off on Bank Details</h3>
              </div>
              <button onClick={() => setShowBankModal(false)} className="text-slate-400 hover:text-white">✕</button>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 space-y-1 text-xs">
              <div>Supplier: <strong className="text-slate-100">{selectedBCR.supplier_name}</strong></div>
              <div>First Approver: <strong className="text-slate-300 font-mono">{selectedBCR.first_approver || 'Not yet recorded'}</strong></div>
              <div className="text-[11px] text-amber-400">Notice: Second approver must be distinct from first approver.</div>
            </div>

            <div className="space-y-3">
              <label className="block text-xs font-semibold text-slate-300">
                Finance Approver Actor ID
              </label>
              <input
                type="text"
                value={bankApprover}
                onChange={(e) => setBankApprover(e.target.value)}
                className="w-full px-3.5 py-2 bg-slate-900 border border-slate-700 rounded-xl font-mono text-amber-300 text-xs focus:outline-none"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button onClick={() => setShowBankModal(false)} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300">
                Cancel
              </button>
              <button
                onClick={handleBankApprove}
                disabled={approvingBank}
                className="px-5 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-xs font-bold text-white shadow-lg shadow-amber-600/20 disabled:opacity-50 transition"
              >
                {approvingBank ? 'Checking SOD-02...' : 'Authorize Bank Change'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
