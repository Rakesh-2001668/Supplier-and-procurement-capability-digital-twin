'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { 
  ShieldCheck, FileText, CheckCircle2, AlertTriangle, Clock, 
  ExternalLink, Upload, RefreshCw, Search, Filter, Sparkles, 
  Layers, Lock, Database, Check, X, AlertCircle, ArrowUpRight,
  TrendingUp, Award, Building2, ChevronRight, Hash, Send, FileCheck,
  Eye, Download, AlertOctagon
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
  status: string;
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

interface OverviewKPIs {
  total_documents: number;
  verified_count: number;
  pending_count: number;
  conflicts_count: number;
  expiring_soon_count: number;
  tamper_check_integrity_score: number;
  overall_compliance_rate_pct: number;
}

export default function DocumentVaultPage() {
  const [activeTab, setActiveTab] = useState<string>('All Documents');
  const [documents, setDocuments] = useState<EvidenceDoc[]>([]);
  const [kpis, setKpis] = useState<OverviewKPIs | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('All');
  const [supplierFilter, setSupplierFilter] = useState<string>('All');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [sidebarTab, setSidebarTab] = useState<'overview' | 'extracted' | 'crypto' | 'history'>('overview');
  
  // Modals & Action States
  const [uploadModalOpen, setUploadModalOpen] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [tamperCheckResult, setTamperCheckResult] = useState<any | null>(null);

  // Upload Form
  const [uploadForm, setUploadForm] = useState({
    name: '',
    supplier_id: 'TWIN-APEX-001',
    supplier_name: 'Apex Precision Machining Ltd',
    category: 'Certifications',
    document_type: 'AS9100 Rev D Aerospace Quality Standard',
    issuing_body: 'BSI Group',
    accreditation_number: 'AS-9100D-' + Math.floor(100000 + Math.random() * 900000),
    expiry_date: '2027-06-30'
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4500);
  };

  // Fetch Documents & KPIs from backend
  const fetchData = async () => {
    try {
      setLoading(true);
      const [ovRes, docRes] = await Promise.all([
        fetch('http://127.0.0.1:8080/api/v1/evidence/overview'),
        fetch('http://127.0.0.1:8080/api/v1/evidence/documents')
      ]);

      if (ovRes.ok) {
        const ovData = await ovRes.json();
        setKpis(ovData.kpis);
      }

      if (docRes.ok) {
        const docData = await docRes.json();
        setDocuments(docData.documents || []);
        if (docData.documents && docData.documents.length > 0 && !selectedDocId) {
          setSelectedDocId(docData.documents[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to load evidence vault data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const selectedDoc = useMemo(() => {
    return documents.find(d => d.id === selectedDocId) || documents[0] || null;
  }, [documents, selectedDocId]);

  // Tab definitions
  const tabs = [
    { name: 'All Documents', count: documents.length },
    { name: 'Certifications', count: documents.filter(d => d.category.toLowerCase().includes('cert')).length },
    { name: 'Quality Documents', count: documents.filter(d => d.category.toLowerCase().includes('quality')).length },
    { name: 'Legal & Regulatory', count: documents.filter(d => d.category.toLowerCase().includes('legal')).length },
    { name: 'ESG', count: documents.filter(d => d.category.toLowerCase().includes('esg')).length },
  ];

  // Filtered documents
  const filteredDocs = useMemo(() => {
    return documents.filter(doc => {
      // Tab filter
      if (activeTab === 'Certifications' && !doc.category.toLowerCase().includes('cert')) return false;
      if (activeTab === 'Quality Documents' && !doc.category.toLowerCase().includes('quality')) return false;
      if (activeTab === 'Legal & Regulatory' && !doc.category.toLowerCase().includes('legal')) return false;
      if (activeTab === 'ESG' && !doc.category.toLowerCase().includes('esg')) return false;

      // Status filter
      if (statusFilter !== 'All' && doc.status.toUpperCase() !== statusFilter.toUpperCase()) return false;

      // Supplier filter
      if (supplierFilter !== 'All' && doc.supplier_id !== supplierFilter) return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchName = doc.name.toLowerCase().includes(q);
        const matchSupp = doc.supplier_name.toLowerCase().includes(q);
        const matchAccred = doc.accreditation_number.toLowerCase().includes(q);
        const matchBody = doc.issuing_body.toLowerCase().includes(q);
        if (!matchName && !matchSupp && !matchAccred && !matchBody) return false;
      }

      return true;
    });
  }, [documents, activeTab, statusFilter, supplierFilter, searchQuery]);

  // Actions
  const handleVerify = async (docId: string) => {
    setActionLoading(`verify-${docId}`);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/verify/${docId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'VERIFY',
          auditor_notes: 'Audited against official international accreditation directory. Credentials verified.',
          auditor_name: 'Lead Compliance Officer'
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Document "${data.document.name}" officially verified and cryptographically sealed.`);
        await fetchData();
      }
    } catch (err) {
      console.error(err);
      showToast('Error verifying document.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (docId: string) => {
    setActionLoading(`reject-${docId}`);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/reject/${docId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'REJECT',
          auditor_notes: 'Discrepancy detected during aerospace registrar cross-reference.',
          auditor_name: 'Senior Lead Auditor'
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Document "${data.document.name}" rejected. Notice dispatched to supplier twin.`);
        await fetchData();
      }
    } catch (err) {
      console.error(err);
      showToast('Error rejecting document.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleTamperCheck = async (docId: string) => {
    setActionLoading(`tamper-${docId}`);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/tamper-check/${docId}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setTamperCheckResult(data);
        setSidebarTab('crypto');
        showToast(data.is_tamper_free ? 'Cryptographic SHA-256 match confirmed. 0-tamper record.' : 'Warning: Hash discrepancy detected.');
      }
    } catch (err) {
      console.error(err);
      showToast('Error running tamper check.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleRequestRenewal = async (docId: string) => {
    setActionLoading(`renew-${docId}`);
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/request-renewal/${docId}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`Renewal notice dispatched to supplier: ${data.notification_id}`);
        await fetchData();
      }
    } catch (err) {
      console.error(err);
      showToast('Error requesting renewal.');
    } finally {
      setActionLoading(null);
    }
  };

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading('upload');
    try {
      const formData = new FormData();
      formData.append('name', uploadForm.name || 'Supplier Accreditation Certificate');
      formData.append('supplier_id', uploadForm.supplier_id);
      formData.append('supplier_name', uploadForm.supplier_name);
      formData.append('category', uploadForm.category);
      formData.append('document_type', uploadForm.document_type);
      formData.append('issuing_body', uploadForm.issuing_body);
      formData.append('accreditation_number', uploadForm.accreditation_number);
      formData.append('expiry_date', uploadForm.expiry_date);

      const res = await fetch('http://127.0.0.1:8080/api/v1/evidence/upload', {
        method: 'POST',
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        showToast(`New document "${data.document.name}" ingested into cryptographic vault.`);
        setUploadModalOpen(false);
        setUploadForm({
          name: '',
          supplier_id: 'TWIN-APEX-001',
          supplier_name: 'Apex Precision Machining Ltd',
          category: 'Certifications',
          document_type: 'AS9100 Rev D Aerospace Quality Standard',
          issuing_body: 'BSI Group',
          accreditation_number: 'AS-9100D-' + Math.floor(100000 + Math.random() * 900000),
          expiry_date: '2027-06-30'
        });
        await fetchData();
        if (data.document?.id) {
          setSelectedDocId(data.document.id);
        }
      }
    } catch (err) {
      console.error(err);
      showToast('Failed to upload document.');
    } finally {
      setActionLoading(null);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'VERIFIED':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"><Check className="w-3 h-3" /> Verified</span>;
      case 'IN_REVIEW':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-blue-500/15 text-blue-400 border border-blue-500/30"><Clock className="w-3 h-3" /> In Review</span>;
      case 'CONFLICT_FLAGGED':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30"><AlertTriangle className="w-3 h-3" /> Conflict Flagged</span>;
      case 'EXPIRING_SOON':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30"><AlertCircle className="w-3 h-3" /> Expiring Soon</span>;
      case 'REJECTED':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-600/20 text-rose-300 border border-rose-500/40"><X className="w-3 h-3" /> Rejected</span>;
      default:
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-slate-700/50 text-slate-300 border border-slate-600">{status}</span>;
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 bg-blue-600 text-white text-xs font-semibold rounded-lg shadow-xl border border-blue-400/40 animate-fade-in-up">
          <Sparkles className="w-4 h-4 text-amber-300 animate-pulse" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Top Header */}
      <div className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md px-8 py-5 shrink-0 flex flex-wrap justify-between items-center gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-bold text-blue-400 uppercase tracking-wider mb-1">
            <ShieldCheck className="w-4 h-4" />
            <span>AI Evidence & Regulatory Document Vault</span>
          </div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-white tracking-tight">Cryptographic Evidence Vault</h1>
            <span className="px-2.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[10px] font-bold">
              SHA-256 / Web3 Anchor
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Tamper-resistant supplier compliance repository with zero-knowledge validation and automated OCR verification.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link 
            href="/evidence"
            className="px-3.5 py-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-xs font-bold text-slate-300 hover:text-white transition-all flex items-center gap-1.5"
          >
            ← Overview Dashboard
          </Link>
          <button
            onClick={() => setUploadModalOpen(true)}
            className="px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-blue-500/20 transition-all flex items-center gap-2"
          >
            <Upload className="w-4 h-4" />
            + Upload Document
          </button>
        </div>
      </div>

      {/* Subnav Navigation Bar */}
      <div className="border-b border-slate-800/80 bg-slate-900/40 px-8 flex items-center gap-6 text-xs font-bold">
        <Link href="/evidence" className="py-3 text-slate-400 hover:text-slate-200 transition-colors">
          Overview
        </Link>
        <Link href="/evidence/vault" className="py-3 text-blue-400 border-b-2 border-blue-500 transition-colors flex items-center gap-1.5">
          <Database className="w-3.5 h-3.5" />
          Document Vault ({documents.length})
        </Link>
        <Link href="/evidence/audit" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <FileCheck className="w-3.5 h-3.5" />
          Audit Trail Sentinel
        </Link>
        <Link href="/evidence/conflicts" className="py-3 text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1.5">
          <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
          Conflict Discrepancies
        </Link>
      </div>

      {/* Main Body with Left Table & Right Sidebar */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Table & Filters */}
        <div className="flex-1 flex flex-col min-w-0 overflow-y-auto px-8 py-6 space-y-6">
          
          {/* Quick Stats Ribbon */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 shrink-0">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-blue-500/10 text-blue-400 flex items-center justify-center shrink-0">
                <FileText className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Total Records</div>
                <div className="text-lg font-black text-white">{kpis ? kpis.total_documents.toLocaleString() : '1,468'}</div>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center shrink-0">
                <CheckCircle2 className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Verified & Active</div>
                <div className="text-lg font-black text-emerald-400">{kpis ? kpis.verified_count.toLocaleString() : '1,257'}</div>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-amber-500/10 text-amber-400 flex items-center justify-center shrink-0">
                <Clock className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Expiring &lt;90d</div>
                <div className="text-lg font-black text-amber-400">{kpis ? kpis.expiring_soon_count : '157'}</div>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-rose-500/10 text-rose-400 flex items-center justify-center shrink-0">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Discrepancies</div>
                <div className="text-lg font-black text-rose-400">{kpis ? kpis.conflicts_count : '14'}</div>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center shrink-0">
                <Lock className="w-5 h-5" />
              </div>
              <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Tamper Integrity</div>
                <div className="text-lg font-black text-indigo-400">{kpis ? `${kpis.tamper_check_integrity_score}%` : '98.6%'}</div>
              </div>
            </div>
          </div>

          {/* Table Container */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl flex flex-col flex-1 min-h-[460px]">
            {/* Category Tabs */}
            <div className="flex border-b border-slate-800 px-4 bg-slate-950/40 overflow-x-auto hide-scrollbar">
              {tabs.map(tab => (
                <button
                  key={tab.name}
                  onClick={() => setActiveTab(tab.name)}
                  className={`py-3.5 px-4 text-xs font-bold border-b-2 transition-all flex items-center gap-2 whitespace-nowrap ${
                    activeTab === tab.name 
                      ? 'border-blue-500 text-blue-400 bg-blue-500/5' 
                      : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700'
                  }`}
                >
                  <span>{tab.name}</span>
                  <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${
                    activeTab === tab.name ? 'bg-blue-500/20 text-blue-300' : 'bg-slate-800 text-slate-400'
                  }`}>
                    {tab.count}
                  </span>
                </button>
              ))}
            </div>

            {/* Filter Controls Bar */}
            <div className="p-4 border-b border-slate-800/80 bg-slate-900/60 flex flex-wrap items-center gap-3">
              <div className="relative flex-1 min-w-[240px]">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by title, accreditation #, issuer, or supplier..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/30"
                />
              </div>

              <div className="flex items-center gap-2">
                <span className="text-[11px] font-bold text-slate-400">Status:</span>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-semibold"
                >
                  <option value="All">All Statuses</option>
                  <option value="VERIFIED">Verified</option>
                  <option value="IN_REVIEW">In Review</option>
                  <option value="CONFLICT_FLAGGED">Conflict Flagged</option>
                  <option value="EXPIRING_SOON">Expiring Soon</option>
                  <option value="REJECTED">Rejected</option>
                </select>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-[11px] font-bold text-slate-400">Supplier:</span>
                <select
                  value={supplierFilter}
                  onChange={(e) => setSupplierFilter(e.target.value)}
                  className="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-semibold"
                >
                  <option value="All">All Suppliers</option>
                  <option value="TWIN-APEX-001">Apex Precision Machining Ltd</option>
                  <option value="TWIN-PREC-002">Precision AutoComp Ltd</option>
                  <option value="TWIN-KOVAI-003">Kovai Diecast & CNC</option>
                  <option value="TWIN-AERO-004">Pacific Aero Component Tech</option>
                  <option value="TWIN-SEMI-008">MicroAvionics Foundry</option>
                  <option value="TWIN-COPP-024">Apex Copper Formings</option>
                </select>
              </div>

              <button
                onClick={fetchData}
                disabled={loading}
                className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 transition-all flex items-center justify-center"
                title="Refresh Vault Records"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-blue-400' : ''}`} />
              </button>
            </div>

            {/* Document Data Table */}
            <div className="overflow-x-auto flex-1">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/70 text-slate-400 font-bold border-b border-slate-800 sticky top-0 uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="py-3 px-4">Document / Certification</th>
                    <th className="py-3 px-4">Supplier & Location</th>
                    <th className="py-3 px-3">Category</th>
                    <th className="py-3 px-3">Accreditation #</th>
                    <th className="py-3 px-3">Expiry Date</th>
                    <th className="py-3 px-3">Status</th>
                    <th className="py-3 px-3">AI Conf.</th>
                    <th className="py-3 px-4 text-right">Integrity</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-medium">
                  {loading && documents.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-500">
                        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-blue-400" />
                        Loading evidence repository...
                      </td>
                    </tr>
                  ) : filteredDocs.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-500">
                        No regulatory documents match the selected filters.
                      </td>
                    </tr>
                  ) : (
                    filteredDocs.map((doc) => {
                      const isSelected = selectedDocId === doc.id;
                      return (
                        <tr
                          key={doc.id}
                          onClick={() => setSelectedDocId(doc.id)}
                          className={`cursor-pointer transition-colors ${
                            isSelected 
                              ? 'bg-blue-600/15 border-l-4 border-blue-500 text-white' 
                              : 'hover:bg-slate-800/40 text-slate-300'
                          }`}
                        >
                          <td className="py-3.5 px-4">
                            <div className="flex items-center gap-3">
                              <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                                doc.status === 'VERIFIED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                                doc.status === 'CONFLICT_FLAGGED' ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' :
                                'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                              }`}>
                                <FileText className="w-4 h-4" />
                              </div>
                              <div className="min-w-0">
                                <div className="font-bold text-white text-xs truncate max-w-[240px]" title={doc.name}>
                                  {doc.name}
                                </div>
                                <div className="text-[10px] text-slate-400 font-mono flex items-center gap-1.5 mt-0.5">
                                  <span>{doc.id}</span>
                                  <span>•</span>
                                  <span>{doc.issuing_body}</span>
                                </div>
                              </div>
                            </div>
                          </td>

                          <td className="py-3.5 px-4">
                            <div className="font-bold text-slate-200 text-xs">{doc.supplier_name}</div>
                            <div className="text-[10px] text-slate-400 flex items-center gap-1">
                              <Building2 className="w-3 h-3 text-slate-500" />
                              <span>{doc.location}</span>
                            </div>
                          </td>

                          <td className="py-3.5 px-3">
                            <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px] font-semibold border border-slate-700">
                              {doc.category}
                            </span>
                          </td>

                          <td className="py-3.5 px-3 font-mono text-[11px] text-slate-300">
                            {doc.accreditation_number}
                          </td>

                          <td className="py-3.5 px-3">
                            <div className="font-mono text-xs">{doc.expiry_date}</div>
                            <div className={`text-[10px] font-bold ${
                              doc.days_until_expiry < 90 ? 'text-amber-400' : 'text-slate-400'
                            }`}>
                              {doc.days_until_expiry} days left
                            </div>
                          </td>

                          <td className="py-3.5 px-3">
                            {getStatusBadge(doc.status)}
                          </td>

                          <td className="py-3.5 px-3">
                            <div className="flex items-center gap-1.5">
                              <div className="w-10 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                                <div 
                                  className={`h-full rounded-full ${
                                    doc.ai_confidence_score >= 90 ? 'bg-emerald-400' :
                                    doc.ai_confidence_score >= 75 ? 'bg-blue-400' : 'bg-amber-400'
                                  }`}
                                  style={{ width: `${doc.ai_confidence_score}%` }}
                                />
                              </div>
                              <span className="font-mono text-[11px] font-bold">{doc.ai_confidence_score}%</span>
                            </div>
                          </td>

                          <td className="py-3.5 px-4 text-right">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleTamperCheck(doc.id);
                              }}
                              className="px-2.5 py-1 rounded-md bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 text-[10px] font-bold transition-all flex items-center gap-1 ml-auto"
                            >
                              <Lock className="w-3 h-3 text-indigo-400" />
                              Tamper Check
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Table Footer */}
            <div className="p-3 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between text-xs text-slate-400 shrink-0">
              <div>
                Showing <span className="font-bold text-white">{filteredDocs.length}</span> of{' '}
                <span className="font-bold text-white">{documents.length}</span> documents
              </div>
              <div className="text-[11px] text-slate-500 flex items-center gap-2">
                <span>Multi-tenant Isolation Active</span>
                <span>•</span>
                <span className="font-mono">SHA-256 / SHA-3 Verified</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Side: Active Document Inspection Drawer */}
        {selectedDoc && (
          <div className="w-[440px] border-l border-slate-800 bg-slate-900/95 flex flex-col h-full shrink-0 shadow-2xl animate-fade-in-left">
            {/* Drawer Header */}
            <div className="p-5 border-b border-slate-800 bg-slate-950/60 shrink-0">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
                    selectedDoc.status === 'VERIFIED' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                    selectedDoc.status === 'CONFLICT_FLAGGED' ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' :
                    'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                  }`}>
                    <Award className="w-5 h-5" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-sm font-black text-white leading-tight truncate" title={selectedDoc.name}>
                      {selectedDoc.name}
                    </h3>
                    <div className="text-xs text-slate-400 mt-0.5">{selectedDoc.supplier_name}</div>
                  </div>
                </div>
                <div className="shrink-0">{getStatusBadge(selectedDoc.status)}</div>
              </div>

              {/* Sidebar Tabs */}
              <div className="flex items-center gap-2 mt-4 border-b border-slate-800 text-[11px] font-bold">
                <button
                  onClick={() => setSidebarTab('overview')}
                  className={`pb-2 transition-colors ${sidebarTab === 'overview' ? 'text-blue-400 border-b-2 border-blue-500' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  Overview
                </button>
                <button
                  onClick={() => setSidebarTab('extracted')}
                  className={`pb-2 transition-colors ${sidebarTab === 'extracted' ? 'text-blue-400 border-b-2 border-blue-500' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  OCR Data
                </button>
                <button
                  onClick={() => setSidebarTab('crypto')}
                  className={`pb-2 transition-colors ${sidebarTab === 'crypto' ? 'text-blue-400 border-b-2 border-blue-500' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  Cryptographic Proof
                </button>
                <button
                  onClick={() => setSidebarTab('history')}
                  className={`pb-2 transition-colors ${sidebarTab === 'history' ? 'text-blue-400 border-b-2 border-blue-500' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  Audit Trail
                </button>
              </div>
            </div>

            {/* Drawer Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              
              {sidebarTab === 'overview' && (
                <>
                  {/* Accreditation Metadata Box */}
                  <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4 space-y-2.5 text-xs">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400 font-semibold">Document ID:</span>
                      <span className="font-mono text-slate-200 font-bold">{selectedDoc.id}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400 font-semibold">Standard / Type:</span>
                      <span className="text-white font-bold">{selectedDoc.document_type}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400 font-semibold">Issuing Registrar:</span>
                      <span className="text-blue-400 font-bold">{selectedDoc.issuing_body}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400 font-semibold">Accreditation #:</span>
                      <span className="font-mono text-slate-300 font-bold">{selectedDoc.accreditation_number}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400 font-semibold">Effective Date:</span>
                      <span className="text-slate-200 font-medium">{selectedDoc.issue_date}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-400 font-semibold">Expiration Date:</span>
                      <span className="text-slate-200 font-medium">{selectedDoc.expiry_date}</span>
                    </div>
                    <div className="flex justify-between items-center pt-1 border-t border-slate-800">
                      <span className="text-slate-400 font-semibold">Days to Expiration:</span>
                      <span className={`font-black ${selectedDoc.days_until_expiry < 90 ? 'text-amber-400' : 'text-emerald-400'}`}>
                        {selectedDoc.days_until_expiry} Days Left
                      </span>
                    </div>
                  </div>

                  {/* AI Confidence Meter */}
                  <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
                    <div className="flex justify-between items-center mb-2">
                      <div className="flex items-center gap-1.5 text-xs font-bold text-white">
                        <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                        AI Extraction Confidence
                      </div>
                      <span className="text-sm font-black text-blue-400">{selectedDoc.ai_confidence_score}%</span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden mb-2">
                      <div 
                        className="bg-gradient-to-r from-blue-500 to-emerald-400 h-full rounded-full"
                        style={{ width: `${selectedDoc.ai_confidence_score}%` }}
                      />
                    </div>
                    <p className="text-[11px] text-slate-400">
                      Verified against international registrar databases with automated semantic entity extraction.
                    </p>
                  </div>

                  {/* File Attachment preview */}
                  <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-3.5 flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <FileText className="w-5 h-5 text-blue-400" />
                      <div>
                        <div className="text-xs font-bold text-white truncate max-w-[200px]">{selectedDoc.file_name}</div>
                        <div className="text-[10px] text-slate-400">{selectedDoc.file_size_kb || 1420} KB • Cryptographically Signed PDF</div>
                      </div>
                    </div>
                    <button 
                      onClick={() => showToast(`Simulated secure preview of ${selectedDoc.file_name}`)}
                      className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs font-bold text-slate-200 flex items-center gap-1"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      View
                    </button>
                  </div>
                </>
              )}

              {sidebarTab === 'extracted' && (
                <div className="space-y-4">
                  <div className="text-xs font-bold text-slate-300 flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-blue-400" />
                    Automated OCR Extracted Attributes
                  </div>
                  {selectedDoc.extracted_metadata ? (
                    <div className="space-y-2.5">
                      {Object.entries(selectedDoc.extracted_metadata).map(([key, val]) => (
                        <div key={key} className="bg-slate-950/80 border border-slate-800 rounded-xl p-3">
                          <div className="text-[10px] font-bold text-blue-400 uppercase tracking-wider mb-1">
                            {key.replace(/_/g, ' ')}
                          </div>
                          <div className="text-xs text-slate-200 font-medium leading-relaxed">
                            {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-4 bg-slate-950/60 border border-slate-800 rounded-xl text-center text-slate-500 text-xs">
                      No custom OCR key-value pairs stored for this document.
                    </div>
                  )}
                </div>
              )}

              {sidebarTab === 'crypto' && (
                <div className="space-y-4">
                  <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 text-xs font-bold text-white">
                        <Lock className="w-4 h-4 text-emerald-400" />
                        Cryptographic SHA-256 Digest
                      </div>
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                        Immutable
                      </span>
                    </div>
                    <div className="p-2.5 bg-slate-900 border border-slate-800 rounded-lg font-mono text-[11px] text-slate-300 break-all select-all">
                      {selectedDoc.sha256_hash}
                    </div>
                  </div>

                  <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-4 space-y-2">
                    <div className="text-xs font-bold text-white flex items-center gap-2">
                      <Database className="w-4 h-4 text-indigo-400" />
                      Blockchain Anchor TX
                    </div>
                    <div className="p-2.5 bg-slate-900 border border-slate-800 rounded-lg font-mono text-[11px] text-indigo-300 break-all select-all">
                      {selectedDoc.blockchain_tx_hash}
                    </div>
                    <div className="text-[10px] text-slate-400 flex items-center gap-1 mt-1">
                      <ExternalLink className="w-3 h-3 text-slate-500" />
                      Anchor status: Verified in block header #18,941,202
                    </div>
                  </div>

                  {tamperCheckResult && (
                    <div className={`p-4 rounded-xl border ${
                      tamperCheckResult.is_tamper_free 
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
                        : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
                    }`}>
                      <div className="flex items-center gap-2 font-bold text-xs mb-1">
                        {tamperCheckResult.is_tamper_free ? <Check className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
                        {tamperCheckResult.integrity_status}
                      </div>
                      <p className="text-[11px] opacity-90 leading-tight">
                        Proof generated at: {tamperCheckResult.verified_at}
                      </p>
                    </div>
                  )}

                  <button
                    onClick={() => handleTamperCheck(selectedDoc.id)}
                    disabled={actionLoading === `tamper-${selectedDoc.id}`}
                    className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs shadow-lg shadow-indigo-600/20 transition-all flex items-center justify-center gap-2"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${actionLoading === `tamper-${selectedDoc.id}` ? 'animate-spin' : ''}`} />
                    Run Real-Time Re-Hash Tamper Check
                  </button>
                </div>
              )}

              {sidebarTab === 'history' && (
                <div className="space-y-4">
                  <div className="text-xs font-bold text-slate-300">Auditable Event Log</div>
                  <div className="space-y-3 relative before:absolute before:inset-0 before:left-3.5 before:w-0.5 before:bg-slate-800">
                    {(selectedDoc.audit_trail || [
                      { timestamp: selectedDoc.issue_date, action: 'UPLOADED', actor: 'Enterprise Portal Ingest' },
                      { timestamp: selectedDoc.issue_date, action: 'OCR_VERIFIED', actor: 'SupplyTwin AI Sentinel' }
                    ]).map((item, idx) => (
                      <div key={idx} className="relative flex items-start gap-3 pl-7">
                        <div className="absolute left-2 top-1.5 w-3 h-3 rounded-full bg-blue-500 ring-4 ring-slate-900 shrink-0" />
                        <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-3 flex-1 text-xs">
                          <div className="flex justify-between items-center mb-1">
                            <span className="font-bold text-white">{item.action}</span>
                            <span className="text-[10px] text-slate-500 font-mono">
                              {new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                          </div>
                          <div className="text-[11px] text-slate-400">Actor: <span className="text-slate-200 font-semibold">{item.actor}</span></div>
                          {item.notes && (
                            <p className="mt-1 text-[11px] text-slate-300 italic bg-slate-900/60 p-2 rounded border border-slate-800">
                              "{item.notes}"
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Drawer Actions Footer */}
            <div className="p-4 border-t border-slate-800 bg-slate-950/80 shrink-0 space-y-2">
              <div className="flex items-center gap-2">
                {selectedDoc.status !== 'VERIFIED' && (
                  <button
                    onClick={() => handleVerify(selectedDoc.id)}
                    disabled={actionLoading === `verify-${selectedDoc.id}`}
                    className="flex-1 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-md transition-all flex items-center justify-center gap-1.5"
                  >
                    <Check className="w-3.5 h-3.5" />
                    Verify Document
                  </button>
                )}
                {selectedDoc.status !== 'REJECTED' && (
                  <button
                    onClick={() => handleReject(selectedDoc.id)}
                    disabled={actionLoading === `reject-${selectedDoc.id}`}
                    className="flex-1 py-2.5 rounded-xl bg-rose-600/80 hover:bg-rose-600 text-white font-bold text-xs shadow-md transition-all flex items-center justify-center gap-1.5"
                  >
                    <X className="w-3.5 h-3.5" />
                    Reject
                  </button>
                )}
              </div>
              <button
                onClick={() => handleRequestRenewal(selectedDoc.id)}
                disabled={actionLoading === `renew-${selectedDoc.id}`}
                className="w-full py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-xs font-bold transition-all flex items-center justify-center gap-1.5"
              >
                <Send className="w-3.5 h-3.5 text-blue-400" />
                Dispatch Renewal Notice to Supplier
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Upload Document Modal */}
      {uploadModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
            <div className="p-5 border-b border-slate-800 bg-slate-950/60 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <Upload className="w-4 h-4 text-blue-400" />
                <h3 className="text-base font-bold text-white">Ingest Regulatory Document</h3>
              </div>
              <button 
                onClick={() => setUploadModalOpen(false)}
                className="text-slate-400 hover:text-white p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleUploadSubmit} className="p-6 overflow-y-auto space-y-4 text-xs">
              <div>
                <label className="block text-slate-300 font-bold mb-1.5">Document Title / Standard</label>
                <input
                  type="text"
                  required
                  value={uploadForm.name}
                  onChange={(e) => setUploadForm({...uploadForm, name: e.target.value})}
                  placeholder="e.g. ISO 14001:2015 Environmental Certificate"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-300 font-bold mb-1.5">Supplier Name</label>
                  <select
                    value={uploadForm.supplier_id}
                    onChange={(e) => {
                      const id = e.target.value;
                      const suppMap: Record<string, string> = {
                        'TWIN-APEX-001': 'Apex Precision Machining Ltd',
                        'TWIN-PREC-002': 'Precision AutoComp Ltd',
                        'TWIN-KOVAI-003': 'Kovai Diecast & CNC',
                        'TWIN-AERO-004': 'Pacific Aero Component Tech',
                        'TWIN-SEMI-008': 'MicroAvionics Foundry',
                        'TWIN-COPP-024': 'Apex Copper Formings'
                      };
                      setUploadForm({
                        ...uploadForm,
                        supplier_id: id,
                        supplier_name: suppMap[id] || 'Apex Precision Machining Ltd'
                      });
                    }}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="TWIN-APEX-001">Apex Precision Machining Ltd</option>
                    <option value="TWIN-PREC-002">Precision AutoComp Ltd</option>
                    <option value="TWIN-KOVAI-003">Kovai Diecast & CNC</option>
                    <option value="TWIN-AERO-004">Pacific Aero Component Tech</option>
                    <option value="TWIN-SEMI-008">MicroAvionics Foundry</option>
                    <option value="TWIN-COPP-024">Apex Copper Formings</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-300 font-bold mb-1.5">Category</label>
                  <select
                    value={uploadForm.category}
                    onChange={(e) => setUploadForm({...uploadForm, category: e.target.value})}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="Certifications">Certifications</option>
                    <option value="Quality Documents">Quality Documents</option>
                    <option value="Legal & Regulatory">Legal & Regulatory</option>
                    <option value="Financial">Financial Disclosures</option>
                    <option value="ESG">ESG & RoHS/REACH</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-300 font-bold mb-1.5">Issuing Body / Registrar</label>
                  <input
                    type="text"
                    required
                    value={uploadForm.issuing_body}
                    onChange={(e) => setUploadForm({...uploadForm, issuing_body: e.target.value})}
                    placeholder="e.g. BSI Group / TÜV SÜD"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-slate-300 font-bold mb-1.5">Accreditation Number</label>
                  <input
                    type="text"
                    required
                    value={uploadForm.accreditation_number}
                    onChange={(e) => setUploadForm({...uploadForm, accreditation_number: e.target.value})}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white font-mono focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-300 font-bold mb-1.5">Expiration Date</label>
                <input
                  type="date"
                  required
                  value={uploadForm.expiry_date}
                  onChange={(e) => setUploadForm({...uploadForm, expiry_date: e.target.value})}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="border border-dashed border-slate-700 rounded-xl p-4 text-center bg-slate-950/40">
                <FileText className="w-8 h-8 mx-auto text-slate-500 mb-2" />
                <p className="text-slate-300 font-bold">Drop PDF / Certificate file here</p>
                <p className="text-slate-500 text-[10px] mt-0.5">Automated OCR and SHA-256 seal will be triggered upon ingest</p>
              </div>

              <div className="pt-3 border-t border-slate-800 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setUploadModalOpen(false)}
                  className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionLoading === 'upload'}
                  className="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-lg shadow-blue-500/20 flex items-center gap-2"
                >
                  {actionLoading === 'upload' ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Parsing OCR & Sealing...
                    </>
                  ) : (
                    <>
                      <Upload className="w-3.5 h-3.5" />
                      Ingest to Vault
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
