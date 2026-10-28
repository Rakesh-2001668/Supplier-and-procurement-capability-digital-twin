'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  ShieldCheck, FileText, CheckCircle2, AlertTriangle, Clock, 
  ExternalLink, Upload, RefreshCw, Search, Filter, Sparkles, 
  Layers, Lock, Database, Check, X, AlertCircle, ArrowUpRight,
  TrendingUp, Award, Building2
} from 'lucide-react';

interface OverviewKPIs {
  total_documents: number;
  verified_count: number;
  pending_count: number;
  conflicts_count: number;
  expiring_soon_count: number;
  tamper_check_integrity_score: number;
  overall_compliance_rate_pct: number;
}

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
  sha256_hash: string;
  blockchain_tx_hash: string;
  tamper_status: string;
  extracted_metadata?: Record<string, any>;
}

interface SupplierCompleteness {
  id: string;
  name: string;
  completeness_pct: number;
  verified_docs: number;
  missing_docs: number;
  status: string;
  tier: string;
}

export default function EvidenceDashboard() {
  const [kpis, setKpis] = useState<OverviewKPIs | null>(null);
  const [categories, setCategories] = useState<{ label: string; count: number; color: string }[]>([]);
  const [topSuppliers, setTopSuppliers] = useState<SupplierCompleteness[]>([]);
  const [recentDocs, setRecentDocs] = useState<EvidenceDoc[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [uploadModalOpen, setUploadModalOpen] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<EvidenceDoc | null>(null);
  const [tamperResult, setTamperResult] = useState<any | null>(null);
  const [verifyingDocId, setVerifyingDocId] = useState<string | null>(null);

  // New Upload Form State
  const [uploadForm, setUploadForm] = useState({
    name: '',
    supplier_id: 'TWIN-APEX-001',
    supplier_name: 'Apex Precision Machining Ltd',
    category: 'Certifications',
    document_type: 'Quality Management (AS9100 / ISO)',
    issuing_body: 'BSI Group',
    accreditation_number: '',
    expiry_date: '2027-12-31'
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const fetchOverview = async () => {
    try {
      setLoading(true);
      const res = await fetch('http://127.0.0.1:8080/api/v1/evidence/overview');
      if (res.ok) {
        const data = await res.json();
        setKpis(data.kpis);
        setCategories(data.categories || []);
        setTopSuppliers(data.top_suppliers_completeness || []);
        setRecentDocs(data.recent_documents || []);
        if (data.recent_documents && data.recent_documents.length > 0 && !selectedDoc) {
          setSelectedDoc(data.recent_documents[0]);
        }
      }
    } catch (err) {
      console.error('Failed to load evidence overview:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
  }, []);

  // Run Tamper Check
  const handleTamperCheck = async (docId: string) => {
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/tamper-check/${docId}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setTamperResult(data);
        showToast(`🔒 Tamper Check: ${data.integrity_status} (Anchor: ${data.blockchain_tx_anchor.slice(0, 14)}...)`);
      }
    } catch (err) {
      console.error('Tamper check error:', err);
      showToast('⚠️ Tamper verification failed.');
    }
  };

  // Verify Document
  const handleVerifyDocument = async (docId: string) => {
    try {
      setVerifyingDocId(docId);
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/verify/${docId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'VERIFY',
          auditor_notes: 'Accreditation verified against official register.',
          auditor_name: 'Lead Compliance Auditor'
        })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`✓ Document '${data.document.name}' successfully verified.`);
        fetchOverview();
        if (selectedDoc?.id === docId) {
          setSelectedDoc(data.document);
        }
      }
    } catch (err) {
      console.error('Failed to verify document:', err);
    } finally {
      setVerifyingDocId(null);
    }
  };

  // Request Renewal
  const handleRequestRenewal = async (docId: string) => {
    try {
      const res = await fetch(`http://127.0.0.1:8080/api/v1/evidence/request-renewal/${docId}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`📨 Re-certification notice dispatched to supplier (${data.notification_id})`);
        fetchOverview();
      }
    } catch (err) {
      console.error('Renewal request failed:', err);
    }
  };

  // Handle Upload
  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const formData = new FormData();
      formData.append('name', uploadForm.name);
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
        showToast(`✨ Document '${uploadForm.name}' ingested and AI OCR verified!`);
        setUploadModalOpen(false);
        fetchOverview();
      }
    } catch (err) {
      console.error('Failed to upload document:', err);
      showToast('Upload failed.');
    }
  };

  return (
    <div className="max-w-[1680px] mx-auto pb-16 space-y-6 animate-fade-in text-slate-100">
      
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

      {/* Header Area */}
      <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-bl from-blue-600/10 via-emerald-600/5 to-transparent rounded-full blur-3xl pointer-events-none" />
        
        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6 relative z-10">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-widest bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5" /> Trust & Compliance Vault
              </span>
              <span className="flex items-center gap-1.5 text-xs text-blue-400 font-mono bg-blue-950/40 px-2 py-0.5 rounded-full border border-blue-800/40">
                <Lock className="w-3 h-3 text-blue-400" /> SHA-256 Tamper Anchored
              </span>
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
              AI Supplier Evidence & Regulatory Vault
              <span className="text-sm px-3 py-1 font-mono font-medium text-slate-400 bg-slate-800/60 rounded-lg border border-slate-700/60">
                AS9100 / IATF / ITAR / RoHS
              </span>
            </h1>
            <p className="text-sm text-slate-400 mt-1 max-w-3xl">
              Automated OCR credential extraction, cryptographic tamper detection, expiry sentinels, and immutable audit logs.
            </p>
          </div>

          {/* Action Group */}
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/evidence/vault"
              className="bg-[#132238] hover:bg-[#1a2d4a] border border-slate-700 text-slate-200 px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2"
            >
              <FileText className="w-4 h-4 text-blue-400" />
              Document Vault ({kpis?.total_documents.toLocaleString() || '1,468'})
            </Link>

            <Link
              href="/evidence/verification-queue"
              className="bg-[#132238] hover:bg-[#1a2d4a] border border-slate-700 text-slate-200 px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2"
            >
              <Clock className="w-4 h-4 text-purple-400" />
              Verification Queue ({kpis?.pending_count || '184'})
            </Link>

            <Link
              href="/evidence/integrity"
              className="bg-[#132238] hover:bg-[#1a2d4a] border border-slate-700 text-slate-200 px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2"
            >
              <Lock className="w-4 h-4 text-emerald-400" />
              Integrity Sentinel
            </Link>

            <button
              onClick={() => setUploadModalOpen(true)}
              className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white px-5 py-2.5 rounded-xl text-xs font-bold shadow-lg shadow-blue-600/20 transition-all flex items-center gap-2 active:scale-95"
            >
              <Upload className="w-4 h-4" />
              Upload Certificate
            </button>
          </div>
        </div>
      </div>

      {/* 6-Card KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {/* Total Documents */}
        <div className="bg-[#0F1C31] border border-slate-800 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
            <span>Total Vault</span>
            <FileText className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-black text-white">
            {kpis ? kpis.total_documents.toLocaleString() : '1,468'}
          </div>
          <div className="text-[10px] text-emerald-400 font-semibold mt-2">↑ 12% vs last quarter</div>
        </div>

        {/* Verified */}
        <div className="bg-[#0F1C31] border border-slate-800 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
            <span>Verified</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-black text-emerald-400">
            {kpis ? kpis.verified_count.toLocaleString() : '1,256'}
          </div>
          <div className="text-[10px] text-slate-400 font-semibold mt-2">85.6% Vault Attested</div>
        </div>

        {/* Pending Verification */}
        <div className="bg-[#0F1C31] border border-slate-800 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
            <span>In Review</span>
            <Clock className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-2xl font-black text-purple-400">
            {kpis ? kpis.pending_count : '184'}
          </div>
          <div className="text-[10px] text-purple-400 font-semibold mt-2">AI Sentinel active</div>
        </div>

        {/* Conflicts Flagged */}
        <div className="bg-[#0F1C31] border border-slate-800 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
            <span>Conflicts</span>
            <AlertTriangle className="w-4 h-4 text-rose-400" />
          </div>
          <div className="text-2xl font-black text-rose-400">
            {kpis ? kpis.conflicts_count : '14'}
          </div>
          <div className="text-[10px] text-rose-400 font-semibold mt-2">Smelter / date audits</div>
        </div>

        {/* Expiring Soon */}
        <div className="bg-[#0F1C31] border border-slate-800 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 font-bold uppercase tracking-wider mb-2">
            <span>Expiring (&lt;90d)</span>
            <Clock className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-black text-amber-400">
            {kpis ? kpis.expiring_soon_count : '156'}
          </div>
          <div className="text-[10px] text-amber-400 font-semibold mt-2">Auto-renewal alerts active</div>
        </div>

        {/* Tamper-Free Integrity Score */}
        <div className="bg-gradient-to-br from-[#0F1C31] to-emerald-950/20 border border-emerald-500/30 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-emerald-400 font-bold uppercase tracking-wider mb-2">
            <span>Integrity Score</span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-black text-emerald-400">
            {kpis ? `${kpis.tamper_check_integrity_score}%` : '98.6%'}
          </div>
          <div className="text-[10px] text-emerald-300 font-semibold mt-2">Zero-Knowledge Validated</div>
        </div>
      </div>

      {/* Middle Row: Verification Distribution & Category Breakdowns */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Verification Status Donut Card */}
        <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider mb-4 flex items-center justify-between">
            <span>Verification Status Ratio</span>
            <span className="text-[10px] font-mono text-emerald-400">86% Attested</span>
          </h3>

          <div className="flex items-center justify-center gap-6 py-4">
            <div className="relative w-36 h-36">
              <svg className="w-full h-full transform -rotate-90">
                <circle cx="72" cy="72" r="56" fill="none" stroke="#1E293B" strokeWidth="16" />
                <circle cx="72" cy="72" r="56" fill="none" stroke="#10B981" strokeWidth="16" strokeDasharray="351.8" strokeDashoffset={351.8 - (351.8 * 86) / 100} strokeLinecap="round" />
                <circle cx="72" cy="72" r="56" fill="none" stroke="#6366F1" strokeWidth="16" strokeDasharray="351.8" strokeDashoffset={351.8 - (351.8 * 12) / 100} strokeLinecap="round" className="origin-center rotate-[310deg]" />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <div className="text-2xl font-black text-white">{kpis ? kpis.total_documents.toLocaleString() : '1,468'}</div>
                <div className="text-[10px] font-bold text-slate-400">Total Docs</div>
              </div>
            </div>

            <div className="flex flex-col gap-2.5 text-xs font-semibold">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span> Verified</div>
                <span className="font-mono text-slate-300">1,256 (86%)</span>
              </div>
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-indigo-500"></span> In Review</div>
                <span className="font-mono text-slate-300">184 (12%)</span>
              </div>
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span> Conflicts</div>
                <span className="font-mono text-slate-300">14 (1%)</span>
              </div>
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-rose-500"></span> Rejected</div>
                <span className="font-mono text-slate-300">14 (1%)</span>
              </div>
            </div>
          </div>

          <div className="pt-4 border-t border-slate-800 text-[11px] text-slate-400">
            Automated OCR confidence threshold set to <b className="text-white">90.0%</b> for automated verification approval.
          </div>
        </div>

        {/* Document Categories Bar Chart */}
        <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider mb-4 flex items-center justify-between">
            <span>Vault Categories</span>
            <Link href="/evidence/vault" className="text-xs text-blue-400 font-bold hover:underline flex items-center gap-1">
              View All <ArrowUpRight className="w-3 h-3" />
            </Link>
          </h3>

          <div className="space-y-2.5">
            {categories.map((cat, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <div className="w-40 text-slate-300 truncate font-semibold">{cat.label}</div>
                <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div className={`h-full ${cat.color} rounded-full`} style={{ width: `${(cat.count / 550) * 100}%` }} />
                </div>
                <div className="w-10 text-right font-mono font-bold text-slate-300">{cat.count}</div>
              </div>
            ))}
          </div>

          <div className="pt-4 border-t border-slate-800 text-[11px] text-slate-400">
            Top regulated standards: <span className="text-blue-400 font-mono">AS9100D</span>, <span className="text-purple-400 font-mono">IATF 16949</span>, <span className="text-emerald-400 font-mono">ITAR Part 122</span>.
          </div>
        </div>

        {/* Expiry Sentinel Card */}
        <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
              <Clock className="w-4 h-4 text-amber-400" />
              Expiry Sentinel Pipeline
            </h3>
            <button 
              onClick={() => handleRequestRenewal('DOC-EVID-003')}
              className="text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-1 rounded hover:bg-amber-500/30 transition-colors"
            >
              Dispatch Batch Alerts
            </button>
          </div>

          <div className="grid grid-cols-4 gap-2 text-center py-4">
            <div className="bg-[#101C31] p-3 rounded-xl border border-rose-500/30">
              <div className="text-xl font-black text-rose-400">12</div>
              <div className="text-[10px] font-bold text-slate-400 mt-1">Expired</div>
            </div>
            <div className="bg-[#101C31] p-3 rounded-xl border border-amber-500/30">
              <div className="text-xl font-black text-amber-400">28</div>
              <div className="text-[10px] font-bold text-slate-400 mt-1">&lt; 30 Days</div>
            </div>
            <div className="bg-[#101C31] p-3 rounded-xl border border-blue-500/30">
              <div className="text-xl font-black text-blue-400">116</div>
              <div className="text-[10px] font-bold text-slate-400 mt-1">31–90 Days</div>
            </div>
            <div className="bg-[#101C31] p-3 rounded-xl border border-emerald-500/30">
              <div className="text-xl font-black text-emerald-400">1,312</div>
              <div className="text-[10px] font-bold text-slate-400 mt-1">&gt; 90 Days</div>
            </div>
          </div>

          <div className="p-3 bg-amber-950/20 border border-amber-500/30 rounded-xl text-xs text-amber-300 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <div>
              <span className="font-bold">Automated Re-Certification Trigger:</span> Precision AutoComp's IATF 16949 audit renewal notice is queued for dispatch.
            </div>
          </div>
        </div>

      </div>

      {/* Bottom Row: Supplier Evidence Completeness & Live Document Inspector */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        
        {/* Table 1: Supplier Evidence Completeness */}
        <div className="xl:col-span-1 bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
              <Building2 className="w-4 h-4 text-blue-400" />
              Supplier Audit Completeness
            </h3>
            <span className="text-xs font-mono text-slate-400">Top Strategic Twins</span>
          </div>

          <div className="divide-y divide-slate-800/80">
            {topSuppliers.map(sup => (
              <div key={sup.id} className="py-3 flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-bold text-white">{sup.name}</span>
                  <span className="font-mono text-emerald-400 font-bold">{sup.completeness_pct}%</span>
                </div>
                <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div 
                    className={`h-full rounded-full ${sup.completeness_pct > 90 ? 'bg-emerald-500' : sup.completeness_pct > 80 ? 'bg-blue-500' : 'bg-amber-500'}`}
                    style={{ width: `${sup.completeness_pct}%` }}
                  />
                </div>
                <div className="flex justify-between text-[10px] text-slate-400">
                  <span>{sup.verified_docs} Verified • {sup.missing_docs} Missing</span>
                  <span className="text-slate-300 font-mono">{sup.status}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="pt-4 border-t border-slate-800 text-[11px] text-slate-400">
            Suppliers with &lt;80% completeness are temporarily blocked from submitting aerospace RFQ bids.
          </div>
        </div>

        {/* Table 2: Live Ingested Regulatory Documents Stream & Verification Action */}
        <div className="xl:col-span-2 bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
          <div className="flex justify-between items-center mb-4">
            <div>
              <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                Live Regulatory Document Stream & Integrity Proofs
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">Click any document to inspect cryptographic SHA-256 hash and audit decisions.</p>
            </div>
            
            <Link
              href="/evidence/vault"
              className="text-xs text-blue-400 font-bold hover:underline flex items-center gap-1"
            >
              Open Full Vault <ArrowUpRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-semibold">
              <thead className="text-slate-400 text-[10px] uppercase tracking-wider border-b border-slate-800 pb-2">
                <tr>
                  <th className="py-2.5 px-3">Document Name</th>
                  <th className="py-2.5 px-3">Supplier</th>
                  <th className="py-2.5 px-3">Issuing Authority</th>
                  <th className="py-2.5 px-3">Expiry Date</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                {recentDocs.slice(0, 6).map(doc => (
                  <tr 
                    key={doc.id}
                    onClick={() => setSelectedDoc(doc)}
                    className={`cursor-pointer transition-colors ${selectedDoc?.id === doc.id ? 'bg-blue-950/30' : 'hover:bg-slate-800/40'}`}
                  >
                    <td className="py-3 px-3 text-white font-sans font-bold flex items-center gap-2">
                      <FileText className="w-4 h-4 text-blue-400 shrink-0" />
                      <span className="truncate max-w-[200px]">{doc.name}</span>
                    </td>
                    <td className="py-3 px-3 text-slate-300 font-sans">{doc.supplier_name}</td>
                    <td className="py-3 px-3 text-slate-400 font-sans">{doc.issuing_body}</td>
                    <td className="py-3 px-3 text-slate-300">{doc.expiry_date}</td>
                    <td className="py-3 px-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        doc.status === 'VERIFIED' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                        doc.status === 'IN_REVIEW' ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' :
                        doc.status === 'EXPIRING_SOON' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                        'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                      }`}>
                        {doc.status}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right font-sans">
                      <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => handleTamperCheck(doc.id)}
                          className="px-2 py-1 bg-[#162740] hover:bg-[#1f375a] text-blue-300 rounded text-[10px] font-bold border border-slate-700 transition-colors"
                          title="Run cryptographic hash check"
                        >
                          Lock Check
                        </button>
                        {doc.status !== 'VERIFIED' && (
                          <button
                            onClick={() => handleVerifyDocument(doc.id)}
                            disabled={verifyingDocId === doc.id}
                            className="px-2 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[10px] font-bold transition-colors shadow"
                          >
                            Verify
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Inspection Panel for Selected Document */}
          {selectedDoc && (
            <div className="mt-4 p-4 bg-[#070E1A] rounded-xl border border-slate-800 text-xs font-mono space-y-2">
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-2 border-b border-slate-800 pb-2">
                <div>
                  <span className="text-slate-400">Inspecting:</span> <b className="text-white font-sans">{selectedDoc.name}</b>
                  <span className="ml-2 text-blue-400 font-bold">({selectedDoc.accreditation_number})</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-emerald-400 font-bold">AI OCR Confidence: {selectedDoc.ai_confidence_score}%</span>
                  <button
                    onClick={() => handleTamperCheck(selectedDoc.id)}
                    className="px-2.5 py-1 bg-blue-600/20 border border-blue-500/40 text-blue-400 rounded text-[10px] font-bold hover:bg-blue-600/30"
                  >
                    Verify Cryptographic Proof
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[11px] pt-1">
                <div>
                  <div className="text-slate-400">SHA-256 Digest:</div>
                  <div className="text-slate-300 truncate font-bold">{selectedDoc.sha256_hash}</div>
                </div>
                <div>
                  <div className="text-slate-400">Blockchain Anchor TX:</div>
                  <div className="text-purple-400 truncate font-bold">{selectedDoc.blockchain_tx_hash}</div>
                </div>
              </div>

              {selectedDoc.extracted_metadata?.scope && (
                <div className="pt-2 text-slate-400 text-[11px] font-sans">
                  <b>Accreditation Scope:</b> {selectedDoc.extracted_metadata.scope}
                </div>
              )}
            </div>
          )}

        </div>

      </div>

      {/* Upload Certificate Modal */}
      {uploadModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0D1829] border border-slate-700 rounded-2xl w-full max-w-xl p-6 shadow-2xl relative animate-scale-up">
            <div className="flex justify-between items-center border-b border-slate-800 pb-3 mb-4">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Upload className="w-5 h-5 text-blue-400" />
                Upload Regulatory Document or Certificate
              </h3>
              <button onClick={() => setUploadModalOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleUploadSubmit} className="space-y-4 text-xs font-semibold">
              <div>
                <label className="text-slate-300 block mb-1">Document / Certificate Title</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Nadcap Chemical Processing Accreditation"
                  value={uploadForm.name}
                  onChange={(e) => setUploadForm({ ...uploadForm, name: e.target.value })}
                  className="w-full bg-[#14233A] border border-slate-700 text-white rounded-xl px-3.5 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-slate-300 block mb-1">Supplier</label>
                  <select
                    value={uploadForm.supplier_id}
                    onChange={(e) => {
                      const id = e.target.value;
                      const name = id === 'TWIN-APEX-001' ? 'Apex Precision Machining Ltd' :
                                   id === 'TWIN-PREC-002' ? 'Precision AutoComp Ltd' :
                                   id === 'TWIN-AERO-004' ? 'Pacific Aero Component Tech' : 'Kovai Diecast & CNC';
                      setUploadForm({ ...uploadForm, supplier_id: id, supplier_name: name });
                    }}
                    className="w-full bg-[#14233A] border border-slate-700 text-white rounded-xl px-3 py-2 text-xs outline-none"
                  >
                    <option value="TWIN-APEX-001">Apex Precision Machining Ltd</option>
                    <option value="TWIN-PREC-002">Precision AutoComp Ltd</option>
                    <option value="TWIN-AERO-004">Pacific Aero Component Tech</option>
                    <option value="TWIN-KOVAI-003">Kovai Diecast & CNC</option>
                  </select>
                </div>

                <div>
                  <label className="text-slate-300 block mb-1">Category</label>
                  <select
                    value={uploadForm.category}
                    onChange={(e) => setUploadForm({ ...uploadForm, category: e.target.value })}
                    className="w-full bg-[#14233A] border border-slate-700 text-white rounded-xl px-3 py-2 text-xs outline-none"
                  >
                    <option value="Certifications">Certifications (ISO/AS9100)</option>
                    <option value="Quality Documents">Quality & Calibration Documents</option>
                    <option value="Legal & Regulatory">Legal & Regulatory (ITAR/EAR)</option>
                    <option value="ESG">ESG & RoHS/REACH Declarations</option>
                    <option value="Financial">Financial Disclosures</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-slate-300 block mb-1">Issuing Authority / Audit Lab</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. TÜV SÜD or PRI Nadcap"
                    value={uploadForm.issuing_body}
                    onChange={(e) => setUploadForm({ ...uploadForm, issuing_body: e.target.value })}
                    className="w-full bg-[#14233A] border border-slate-700 text-white rounded-xl px-3.5 py-2 text-xs outline-none"
                  />
                </div>

                <div>
                  <label className="text-slate-300 block mb-1">Accreditation / Certificate #</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. AS9100D-PRI-88392"
                    value={uploadForm.accreditation_number}
                    onChange={(e) => setUploadForm({ ...uploadForm, accreditation_number: e.target.value })}
                    className="w-full bg-[#14233A] border border-slate-700 text-white rounded-xl px-3.5 py-2 text-xs outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="text-slate-300 block mb-1">Expiration Date</label>
                <input
                  type="date"
                  required
                  value={uploadForm.expiry_date}
                  onChange={(e) => setUploadForm({ ...uploadForm, expiry_date: e.target.value })}
                  className="w-full bg-[#14233A] border border-slate-700 text-white rounded-xl px-3.5 py-2 text-xs outline-none"
                />
              </div>

              <div className="p-3 bg-blue-950/30 border border-blue-500/30 rounded-xl text-[11px] text-blue-300 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-blue-400 shrink-0" />
                <span>Upon upload, the AI Sentinel will automatically parse text via OCR, generate cryptographic SHA-256 hashes, and anchor the record.</span>
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setUploadModalOpen(false)}
                  className="px-4 py-2 border border-slate-700 text-slate-300 rounded-xl hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-xl shadow-lg transition-all"
                >
                  Upload & Verify
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
