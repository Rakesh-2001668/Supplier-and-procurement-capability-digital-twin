'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { 
  ShieldCheck, FileText, CheckCircle2, AlertTriangle, Clock, 
  ExternalLink, Upload, RefreshCw, Search, Filter, Sparkles, 
  Layers, Lock, Database, Check, X, AlertCircle, ArrowUpRight,
  FileCheck, AlertOctagon, RotateCcw, FileX, Send, Eye,
  Building2, Hash, Calendar, Award, ChevronRight, Shield, History as HistoryIcon
} from 'lucide-react';

interface EvidenceDoc {
  id: string;
  name: string;
  supplier_id: string;
  supplier_name: string;
  location: string;
  category: string;
  document_type: string;
  issuing_body: string;
  accreditation_number: string;
  issue_date: string;
  expiry_date: string;
  days_until_expiry: number;
  status: string; // "VERIFIED" | "IN_REVIEW" | "PENDING" | "CONFLICT_FLAGGED" | "EXPIRING_SOON" | "REJECTED"
  ai_confidence_score: number;
  file_name: string;
  file_size_kb?: number;
  sha256_hash: string;
  blockchain_tx_hash: string;
  tamper_status: string;
  extracted_metadata?: Record<string, any>;
  audit_trail?: Array<{
    timestamp: string;
    action: string;
    actor: string;
    notes?: string;
  }>;
}

export default function VerificationQueuePage() {
  const [documents, setDocuments] = useState<EvidenceDoc[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [categoryFilter, setCategoryFilter] = useState<string>('All Categories');
  const [supplierFilter, setSupplierFilter] = useState<string>('All Suppliers');
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [tamperCheckResult, setTamperCheckResult] = useState<any | null>(null);
  const [rejectReason, setRejectReason] = useState<string>('');
  const [showRejectModal, setShowRejectModal] = useState<boolean>(false);
  const [drawerTab, setDrawerTab] = useState<'overview' | 'extracted' | 'timeline' | 'history'>('overview');

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const fetchQueueDocuments = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/evidence/documents');
      if (res.ok) {
        const data = await res.json();
        const docs: EvidenceDoc[] = data.documents || [];
        setDocuments(docs);
        if (docs.length > 0 && !selectedDocId) {
          // Default to first document or one in review
          const inReview = docs.find(d => d.status === 'IN_REVIEW' || d.status === 'PENDING');
          setSelectedDocId(inReview ? inReview.id : docs[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to load queue documents:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueueDocuments();
  }, []);

  const selectedDoc = useMemo(() => {
    return documents.find(d => d.id === selectedDocId) || null;
  }, [documents, selectedDocId]);

  // Tab counts
  const tabCounts = useMemo(() => {
    const total = documents.length;
    const inReview = documents.filter(d => d.status === 'IN_REVIEW' || d.status === 'PENDING').length;
    const verified = documents.filter(d => d.status === 'VERIFIED').length;
    const conflicts = documents.filter(d => d.status === 'CONFLICT_FLAGGED').length;
    const expiring = documents.filter(d => d.status === 'EXPIRING_SOON' || d.days_until_expiry < 90).length;
    const rejected = documents.filter(d => d.status === 'REJECTED').length;
    return { total, inReview, verified, conflicts, expiring, rejected };
  }, [documents]);

  const tabs = [
    { name: 'All', count: tabCounts.total },
    { name: 'In Review', count: tabCounts.inReview },
    { name: 'Verified', count: tabCounts.verified },
    { name: 'Conflicts', count: tabCounts.conflicts },
    { name: 'Expiring Soon', count: tabCounts.expiring },
    { name: 'Rejected', count: tabCounts.rejected },
  ];

  // Filtering
  const filteredDocuments = useMemo(() => {
    return documents.filter(doc => {
      // Tab filter
      if (activeTab === 'In Review' && doc.status !== 'IN_REVIEW' && doc.status !== 'PENDING') return false;
      if (activeTab === 'Verified' && doc.status !== 'VERIFIED') return false;
      if (activeTab === 'Conflicts' && doc.status !== 'CONFLICT_FLAGGED') return false;
      if (activeTab === 'Expiring Soon' && doc.status !== 'EXPIRING_SOON' && doc.days_until_expiry >= 90) return false;
      if (activeTab === 'Rejected' && doc.status !== 'REJECTED') return false;

      // Category filter
      if (categoryFilter !== 'All Categories' && doc.category !== categoryFilter) return false;

      // Supplier filter
      if (supplierFilter !== 'All Suppliers' && doc.supplier_name !== supplierFilter) return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchName = doc.name.toLowerCase().includes(q);
        const matchSupplier = doc.supplier_name.toLowerCase().includes(q);
        const matchAccreditation = doc.accreditation_number.toLowerCase().includes(q);
        const matchIssuer = doc.issuing_body.toLowerCase().includes(q);
        if (!matchName && !matchSupplier && !matchAccreditation && !matchIssuer) return false;
      }

      return true;
    });
  }, [documents, activeTab, categoryFilter, supplierFilter, searchQuery]);

  // Unique suppliers and categories
  const uniqueSuppliers = useMemo(() => {
    return Array.from(new Set(documents.map(d => d.supplier_name))).filter(Boolean);
  }, [documents]);

  const uniqueCategories = useMemo(() => {
    return Array.from(new Set(documents.map(d => d.category))).filter(Boolean);
  }, [documents]);

  // Actions
  const handleVerify = async (docId: string) => {
    try {
      setActionLoading('verify');
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/verify/${docId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'VERIFY',
          auditor_notes: 'Document satisfies aerospace standards and verified against registrar.',
          auditor_name: 'Lead Aerospace Quality Auditor'
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`✓ Document '${data.document.name}' verified and logged to blockchain.`);
        await fetchQueueDocuments();
      }
    } catch (err) {
      console.error(err);
      showToast('Verification failed.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (docId: string) => {
    try {
      setActionLoading('reject');
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/reject/${docId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'REJECT',
          auditor_notes: rejectReason.trim() || 'Document does not satisfy aerospace accreditation requirements.',
          auditor_name: 'Lead Compliance Auditor'
        })
      });
      if (res.ok) {
        showToast(`Document rejected. Resubmission notice dispatched to supplier.`);
        setShowRejectModal(false);
        setRejectReason('');
        await fetchQueueDocuments();
      }
    } catch (err) {
      console.error(err);
      showToast('Rejection failed.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleTamperCheck = async (docId: string) => {
    try {
      setActionLoading('tamper');
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/tamper-check/${docId}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setTamperCheckResult(data);
        showToast(`Cryptographic SHA-256 verification complete: ${data.integrity_status}`);
      }
    } catch (err) {
      console.error(err);
      showToast('Tamper check failed.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleRenewalNotice = async (docId: string) => {
    try {
      setActionLoading('renewal');
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/request-renewal/${docId}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`📨 Recertification renewal notice dispatched (${data.notification_id})`);
        await fetchQueueDocuments();
      }
    } catch (err) {
      console.error(err);
      showToast('Failed to dispatch renewal request.');
    } finally {
      setActionLoading(null);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'VERIFIED':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1 w-max"><CheckCircle2 className="w-3 h-3" /> Verified</span>;
      case 'IN_REVIEW':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/30 flex items-center gap-1 w-max"><Clock className="w-3 h-3" /> In Review</span>;
      case 'PENDING':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-1 w-max"><Clock className="w-3 h-3" /> Pending</span>;
      case 'CONFLICT_FLAGGED':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-1 w-max"><AlertOctagon className="w-3 h-3" /> Conflict</span>;
      case 'EXPIRING_SOON':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-1 w-max"><AlertTriangle className="w-3 h-3" /> Expiring</span>;
      case 'REJECTED':
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-red-500/10 text-red-400 border border-red-500/30 flex items-center gap-1 w-max"><FileX className="w-3 h-3" /> Rejected</span>;
      default:
        return <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-slate-800 text-slate-400">{status}</span>;
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#070B14] text-slate-100 min-h-screen">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0F172A] border border-blue-500/60 text-white px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3 backdrop-blur-md animate-slide-up">
          <Sparkles className="w-5 h-5 text-blue-400 animate-spin" />
          <span className="text-sm font-semibold">{toastMessage}</span>
          <button onClick={() => setToastMessage(null)} className="ml-2 text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Reject Modal */}
      {showRejectModal && selectedDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fade-in">
          <div className="bg-[#0B1528] border border-rose-500/40 rounded-2xl w-full max-w-lg p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-start">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-rose-500/20 text-rose-400 flex items-center justify-center">
                  <FileX className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">Reject Regulatory Evidence</h3>
                  <p className="text-xs text-slate-400">{selectedDoc.name}</p>
                </div>
              </div>
              <button onClick={() => setShowRejectModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-slate-300">Auditor Rejection Justification</label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="State the non-compliance reason (e.g. Expired standard clause, missing accreditation stamp, or unverified laboratory scope)..."
                rows={4}
                className="w-full bg-slate-950/80 border border-slate-700 rounded-xl p-3 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-rose-500 transition-colors"
              />
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setShowRejectModal(false)}
                className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-300"
              >
                Cancel
              </button>
              <button
                onClick={() => handleReject(selectedDoc.id)}
                disabled={actionLoading === 'reject'}
                className="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-xs font-bold text-white shadow-lg shadow-rose-600/30 flex items-center gap-2"
              >
                {actionLoading === 'reject' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <FileX className="w-3.5 h-3.5" />}
                Confirm Rejection & Notify
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header Area */}
      <div className="border-b border-slate-800/80 bg-[#0B1528] px-8 py-5 shrink-0">
        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
          <div>
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-600 text-white flex items-center justify-center shadow-lg shadow-blue-500/20">
                <FileCheck className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-extrabold text-blue-400 uppercase tracking-widest">
                  REGULATORY COMPLIANCE VAULT
                </div>
                <h1 className="text-2xl font-black text-white tracking-tight">Evidence Verification Queue</h1>
              </div>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Autonomous AI credential extraction, registrar validation, and deep manual auditor verification workbench.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => fetchQueueDocuments()}
              className="px-3.5 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-xs font-bold text-slate-300 hover:text-white transition-all flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-blue-400' : ''}`} />
              Refresh Queue
            </button>
            <Link
              href="/evidence/vault"
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-blue-500/20 transition-all flex items-center gap-2"
            >
              <Database className="w-4 h-4" />
              Browse Full Vault
            </Link>
          </div>
        </div>
      </div>

      {/* Subnav Navigation Bar */}
      <div className="border-b border-slate-800/80 bg-slate-900/40 px-8 flex items-center gap-6 text-xs font-bold shrink-0 overflow-x-auto">
        <Link href="/evidence" className="py-3 text-slate-400 hover:text-slate-200 transition-colors">
          Overview
        </Link>
        <Link href="/evidence/vault" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <Database className="w-3.5 h-3.5" />
          Document Vault
        </Link>
        <Link href="/evidence/verification-queue" className="py-3 text-blue-400 border-b-2 border-blue-500 transition-colors flex items-center gap-1.5">
          <FileCheck className="w-3.5 h-3.5 text-blue-400" />
          Verification Queue ({tabCounts.inReview + tabCounts.conflicts})
        </Link>
        <Link href="/evidence/conflicts" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
          Conflict Discrepancies
        </Link>
        <Link href="/evidence/integrity" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <Shield className="w-3.5 h-3.5 text-emerald-400" />
          Integrity & Cryptographic Check
        </Link>
        <Link href="/evidence/audit" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <HistoryIcon className="w-3.5 h-3.5 text-purple-400" />
          Audit Trail Sentinel
        </Link>
      </div>

      {/* Main Split Layout: Left Table + Right Detail Drawer */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Table Panel */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden border-r border-slate-800/80">
          
          {/* Status Tabs Bar */}
          <div className="flex gap-2 border-b border-slate-800 bg-[#0B1528]/50 px-6 pt-3 shrink-0 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                key={tab.name}
                onClick={() => setActiveTab(tab.name)}
                className={`px-4 py-2 text-xs font-bold rounded-t-lg transition-all flex items-center gap-2 border-b-2 ${
                  activeTab === tab.name
                    ? 'bg-slate-800 text-blue-400 border-blue-500'
                    : 'text-slate-400 hover:text-slate-200 border-transparent hover:bg-slate-800/40'
                }`}
              >
                <span>{tab.name}</span>
                <span className={`px-1.5 py-0.2 rounded text-[10px] ${activeTab === tab.name ? 'bg-blue-500/20 text-blue-300' : 'bg-slate-800 text-slate-400'}`}>
                  {tab.count}
                </span>
              </button>
            ))}
          </div>

          {/* Filter Toolbar */}
          <div className="p-4 border-b border-slate-800/80 bg-slate-900/30 flex flex-wrap items-center gap-3 shrink-0">
            <div className="relative flex-1 min-w-[240px]">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search documents, accreditation #, issuing authority, supplier..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
            </div>

            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500 font-medium"
            >
              <option>All Categories</option>
              {uniqueCategories.map(cat => <option key={cat}>{cat}</option>)}
            </select>

            <select
              value={supplierFilter}
              onChange={(e) => setSupplierFilter(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500 font-medium max-w-[200px] truncate"
            >
              <option>All Suppliers</option>
              {uniqueSuppliers.map(sup => <option key={sup}>{sup}</option>)}
            </select>

            {(searchQuery || categoryFilter !== 'All Categories' || supplierFilter !== 'All Suppliers') && (
              <button
                onClick={() => { setSearchQuery(''); setCategoryFilter('All Categories'); setSupplierFilter('All Suppliers'); }}
                className="text-xs text-rose-400 hover:text-rose-300 underline font-semibold"
              >
                Clear Filters
              </button>
            )}
          </div>

          {/* Documents Table */}
          <div className="flex-1 overflow-y-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="sticky top-0 bg-[#0B1528] text-slate-400 text-[10px] uppercase font-bold tracking-wider border-b border-slate-800 z-10">
                <tr>
                  <th className="py-3 px-4">Document / Accreditation</th>
                  <th className="py-3 px-4">Supplier</th>
                  <th className="py-3 px-4">Category</th>
                  <th className="py-3 px-4">Expiry Date</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4 text-center">AI Confidence</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-medium text-slate-300">
                {filteredDocuments.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-500">
                      No documents found matching the selected filter criteria.
                    </td>
                  </tr>
                ) : (
                  filteredDocuments.map((doc) => {
                    const isSelected = selectedDocId === doc.id;
                    return (
                      <tr
                        key={doc.id}
                        onClick={() => setSelectedDocId(doc.id)}
                        className={`cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-blue-600/15 border-l-2 border-l-blue-500'
                            : 'hover:bg-slate-800/40'
                        }`}
                      >
                        <td className="py-3 px-4">
                          <div className="flex items-start gap-2.5">
                            <div className="p-1.5 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20 shrink-0 mt-0.5">
                              <FileText className="w-3.5 h-3.5" />
                            </div>
                            <div>
                              <div className="font-bold text-white leading-tight">{doc.name}</div>
                              <div className="text-[10px] text-slate-400 flex items-center gap-1.5 mt-0.5">
                                <span>{doc.accreditation_number}</span>
                                <span>•</span>
                                <span className="text-slate-500">{doc.issuing_body}</span>
                              </div>
                            </div>
                          </div>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-semibold text-slate-200">{doc.supplier_name}</div>
                          <div className="text-[10px] text-slate-500">{doc.location}</div>
                        </td>

                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 rounded bg-slate-800/80 text-slate-300 text-[10px] font-semibold border border-slate-700/60">
                            {doc.category}
                          </span>
                        </td>

                        <td className="py-3 px-4">
                          <div className="text-slate-300 font-mono text-[11px]">{doc.expiry_date}</div>
                          <div className={`text-[10px] font-semibold ${doc.days_until_expiry < 90 ? 'text-amber-400' : 'text-slate-500'}`}>
                            {doc.days_until_expiry > 0 ? `${doc.days_until_expiry} days left` : 'Expired'}
                          </div>
                        </td>

                        <td className="py-3 px-4">
                          {getStatusBadge(doc.status)}
                        </td>

                        <td className="py-3 px-4 text-center">
                          <div className="inline-flex items-center gap-1 font-mono font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 text-[11px]">
                            {doc.ai_confidence_score.toFixed(1)}%
                          </div>
                        </td>

                        <td className="py-3 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1.5">
                            {doc.status !== 'VERIFIED' && (
                              <button
                                onClick={() => handleVerify(doc.id)}
                                disabled={actionLoading === 'verify'}
                                className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-[10px] font-bold shadow-sm transition-all flex items-center gap-1"
                                title="Approve & Verify Document"
                              >
                                <Check className="w-3 h-3" />
                                Verify
                              </button>
                            )}
                            <button
                              onClick={() => { setSelectedDocId(doc.id); setShowRejectModal(true); }}
                              className="p-1 rounded text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                              title="Reject Document"
                            >
                              <FileX className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Footer Bar */}
          <div className="px-6 py-2.5 border-t border-slate-800/80 bg-slate-900/60 flex justify-between items-center text-xs text-slate-400 shrink-0">
            <div>
              Showing <span className="text-white font-bold">{filteredDocuments.length}</span> of {documents.length} evidence records
            </div>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-400"></span> Live Blockchain Anchor
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-blue-400"></span> AI OCR Verified
              </span>
            </div>
          </div>
        </div>

        {/* Right Detail Drawer */}
        {selectedDoc ? (
          <div className="w-[450px] shrink-0 bg-[#0B1528] border-l border-slate-800 flex flex-col h-full overflow-hidden animate-fade-in">
            {/* Drawer Header */}
            <div className="p-5 border-b border-slate-800 bg-slate-900/50 shrink-0">
              <div className="flex justify-between items-start mb-2">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                    {selectedDoc.id}
                  </span>
                  {getStatusBadge(selectedDoc.status)}
                </div>
                <div className="flex items-center gap-1 text-slate-400">
                  <button
                    onClick={() => handleTamperCheck(selectedDoc.id)}
                    disabled={actionLoading === 'tamper'}
                    className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-blue-400 transition-colors"
                    title="Run Cryptographic SHA-256 Check"
                  >
                    <Lock className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <h2 className="text-base font-black text-white leading-snug">{selectedDoc.name}</h2>
              <p className="text-xs text-slate-400 mt-0.5">{selectedDoc.supplier_name}</p>

              {/* Drawer Inner Tabs */}
              <div className="flex gap-4 border-b border-slate-800 mt-4 text-xs font-bold">
                <button
                  onClick={() => setDrawerTab('overview')}
                  className={`pb-2 border-b-2 transition-colors ${drawerTab === 'overview' ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                >
                  Overview
                </button>
                <button
                  onClick={() => setDrawerTab('extracted')}
                  className={`pb-2 border-b-2 transition-colors ${drawerTab === 'extracted' ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                >
                  Extracted Data
                </button>
                <button
                  onClick={() => setDrawerTab('timeline')}
                  className={`pb-2 border-b-2 transition-colors ${drawerTab === 'timeline' ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                >
                  Timeline
                </button>
                <button
                  onClick={() => setDrawerTab('history')}
                  className={`pb-2 border-b-2 transition-colors ${drawerTab === 'history' ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-400 hover:text-slate-200'}`}
                >
                  Audit Trail
                </button>
              </div>
            </div>

            {/* Drawer Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {drawerTab === 'overview' && (
                <>
                  {/* Confidence & Cryptographic Integrity Card */}
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
                        <Sparkles className="w-3.5 h-3.5 text-blue-400" /> AI OCR Confidence
                      </span>
                      <span className="text-sm font-black text-emerald-400 font-mono">
                        {selectedDoc.ai_confidence_score.toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full h-1.5 bg-slate-950 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-blue-500 to-emerald-400 rounded-full"
                        style={{ width: `${selectedDoc.ai_confidence_score}%` }}
                      />
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      AI OCR extraction verified against official accreditation register. High text fidelity and digital seal conformance.
                    </p>
                  </div>

                  {/* Metadata Attributes */}
                  <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 space-y-2.5 text-xs">
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Document Type</span>
                      <span className="font-semibold text-white">{selectedDoc.document_type}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Accreditation #</span>
                      <span className="font-mono font-bold text-blue-400">{selectedDoc.accreditation_number}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Issuing Body</span>
                      <span className="font-semibold text-white">{selectedDoc.issuing_body}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Issue Date</span>
                      <span className="font-mono text-slate-300">{selectedDoc.issue_date}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-slate-800/60">
                      <span className="text-slate-400">Expiry Date</span>
                      <span className="font-mono text-slate-300">{selectedDoc.expiry_date}</span>
                    </div>
                    <div className="flex justify-between py-1">
                      <span className="text-slate-400">File Name</span>
                      <span className="font-mono text-slate-400 text-[11px] truncate max-w-[200px]">{selectedDoc.file_name}</span>
                    </div>
                  </div>

                  {/* Cryptographic SHA-256 Hashes */}
                  <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 space-y-2 font-mono text-[10px]">
                    <div className="text-slate-400 uppercase font-sans font-bold text-[10px] flex items-center gap-1.5">
                      <Lock className="w-3 h-3 text-emerald-400" /> Cryptographic Integrity Proof
                    </div>
                    <div>
                      <div className="text-slate-500">SHA-256 File Digest:</div>
                      <div className="text-slate-300 break-all select-all">{selectedDoc.sha256_hash}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Blockchain Tx Anchor:</div>
                      <div className="text-blue-400 break-all select-all">{selectedDoc.blockchain_tx_hash}</div>
                    </div>
                  </div>

                  {/* Tamper Result Callout if ran */}
                  {tamperCheckResult && (
                    <div className={`p-3.5 rounded-xl border text-xs space-y-1.5 ${tamperCheckResult.is_tamper_free ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-rose-500/10 border-rose-500/30 text-rose-300'}`}>
                      <div className="font-bold flex items-center gap-1.5">
                        <CheckCircle2 className="w-4 h-4" /> Cryptographic Tamper Verification Result
                      </div>
                      <div className="text-[11px] text-slate-300">
                        Status: <span className="font-bold text-white">{tamperCheckResult.integrity_status}</span>
                      </div>
                      <div className="text-[10px] font-mono text-slate-400">
                        Computed: {tamperCheckResult.computed_proof_hash}
                      </div>
                    </div>
                  )}
                </>
              )}

              {drawerTab === 'extracted' && (
                <div className="space-y-4">
                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 space-y-3">
                    <h3 className="text-xs font-bold text-blue-400 flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5" /> AI Extracted Scope & Metrology
                    </h3>
                    {selectedDoc.extracted_metadata ? (
                      <div className="space-y-2.5 text-xs">
                        {Object.entries(selectedDoc.extracted_metadata).map(([key, val]) => (
                          <div key={key} className="bg-slate-950 p-3 rounded-lg border border-slate-800/60">
                            <div className="text-[10px] font-bold uppercase text-slate-400 tracking-wider mb-1">
                              {key.replace(/_/g, ' ')}
                            </div>
                            <div className="text-white leading-relaxed font-sans">{String(val)}</div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">No automated OCR metadata available.</p>
                    )}
                  </div>
                </div>
              )}

              {drawerTab === 'timeline' && (
                <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 space-y-4">
                  <h3 className="text-xs font-bold text-white flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-blue-400" /> Verification Lifecycle Stages
                  </h3>
                  
                  <div className="relative pl-6 space-y-6 before:content-[''] before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
                    <div className="relative">
                      <div className="absolute -left-6 top-0.5 w-4 h-4 rounded-full bg-emerald-500 text-black flex items-center justify-center text-[9px] font-bold">✓</div>
                      <div className="text-xs font-bold text-white">Document Ingested</div>
                      <div className="text-[10px] text-slate-400">{selectedDoc.issue_date} • SHA-256 generated</div>
                    </div>
                    <div className="relative">
                      <div className="absolute -left-6 top-0.5 w-4 h-4 rounded-full bg-emerald-500 text-black flex items-center justify-center text-[9px] font-bold">✓</div>
                      <div className="text-xs font-bold text-white">AI OCR Extraction</div>
                      <div className="text-[10px] text-slate-400">Confidence: {selectedDoc.ai_confidence_score.toFixed(1)}%</div>
                    </div>
                    <div className="relative">
                      <div className="absolute -left-6 top-0.5 w-4 h-4 rounded-full bg-blue-500 text-black flex items-center justify-center text-[9px] font-bold">✓</div>
                      <div className="text-xs font-bold text-white">Registrar Cross-Check</div>
                      <div className="text-[10px] text-slate-400">{selectedDoc.issuing_body} database</div>
                    </div>
                    <div className="relative">
                      <div className={`absolute -left-6 top-0.5 w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold ${selectedDoc.status === 'VERIFIED' ? 'bg-emerald-500 text-black' : 'bg-slate-700 text-slate-300'}`}>
                        {selectedDoc.status === 'VERIFIED' ? '✓' : '•'}
                      </div>
                      <div className="text-xs font-bold text-white">Auditor Final Verification</div>
                      <div className="text-[10px] text-slate-400">Status: {selectedDoc.status}</div>
                    </div>
                  </div>
                </div>
              )}

              {drawerTab === 'history' && (
                <div className="space-y-3">
                  {selectedDoc.audit_trail && selectedDoc.audit_trail.length > 0 ? (
                    selectedDoc.audit_trail.map((item, idx) => (
                      <div key={idx} className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 text-xs space-y-1">
                        <div className="flex justify-between items-center">
                          <span className="font-bold text-blue-400">{item.action}</span>
                          <span className="text-[10px] text-slate-500 font-mono">{item.timestamp}</span>
                        </div>
                        <div className="text-slate-300 text-[11px]">Actor: {item.actor}</div>
                        {item.notes && <div className="text-slate-400 text-[10px] italic">"{item.notes}"</div>}
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-slate-500 text-center py-6">No historical audit entries found.</p>
                  )}
                </div>
              )}
            </div>

            {/* Drawer Actions Footer */}
            <div className="p-4 border-t border-slate-800 bg-slate-900/80 shrink-0 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => handleVerify(selectedDoc.id)}
                  disabled={actionLoading === 'verify' || selectedDoc.status === 'VERIFIED'}
                  className="py-2.5 px-3 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-1.5 transition-all"
                >
                  {actionLoading === 'verify' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  Verify & Approve
                </button>

                <button
                  onClick={() => setShowRejectModal(true)}
                  disabled={actionLoading === 'reject'}
                  className="py-2.5 px-3 rounded-xl bg-slate-800 hover:bg-rose-900/30 hover:border-rose-500/50 border border-slate-700 text-rose-400 font-bold text-xs flex items-center justify-center gap-1.5 transition-all"
                >
                  <FileX className="w-3.5 h-3.5" />
                  Reject Document
                </button>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => handleRenewalNotice(selectedDoc.id)}
                  disabled={actionLoading === 'renewal'}
                  className="flex-1 py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white font-semibold text-[11px] flex items-center justify-center gap-1.5 transition-all"
                >
                  <Send className="w-3 h-3 text-blue-400" />
                  Dispatch Renewal Ping
                </button>

                <button
                  onClick={() => handleTamperCheck(selectedDoc.id)}
                  disabled={actionLoading === 'tamper'}
                  className="py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white font-semibold text-[11px] flex items-center justify-center gap-1.5 transition-all"
                >
                  <Lock className="w-3 h-3 text-emerald-400" />
                  SHA-256 Check
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="w-[450px] shrink-0 bg-[#0B1528] border-l border-slate-800 flex items-center justify-center text-slate-500 text-xs p-6 text-center">
            Select a document from the queue to view its verification details and run audits.
          </div>
        )}
      </div>
    </div>
  );
}
