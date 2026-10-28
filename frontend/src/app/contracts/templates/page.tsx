"use client";
import React, { useState, useEffect } from "react";
import Link from 'next/link';

interface ContractTemplate {
  id: string;
  name: string;
  contract_type: string;
  department: string;
  version: string;
  status: string;
  recommended_sla: string;
  clauses_count: number;
  description: string;
}

export default function ContractTemplates() {
  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<ContractTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  };

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/contracts/templates/list');
      if (res.ok) {
        const data = await res.json();
        setTemplates(data.templates || []);
        if (data.templates && data.templates.length > 0) {
          setSelectedTemplate(data.templates[0]);
        }
      }
    } catch (e) {
      console.warn("Could not fetch templates from backend", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  const filteredTemplates = templates.filter(t => 
    searchQuery === '' ||
    t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    t.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
    t.contract_type.toLowerCase().includes(searchQuery.toLowerCase()) ||
    t.department.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex h-full bg-[#0B0F19] text-slate-100 flex-col overflow-y-auto">
      {toast && (
        <div className="fixed top-6 right-6 z-50 bg-emerald-950 border border-emerald-500/50 text-emerald-300 px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 text-sm font-semibold animate-fade-in">
          <span>✨</span> {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex justify-between items-start shrink-0 px-8 pt-8 pb-4 bg-[#111827] border-b border-slate-800">
        <div>
          <div className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest mb-1 flex items-center gap-1.5">
            <Link href="/contracts" className="hover:text-blue-400 transition-colors">Contracts Engine</Link>
            <span className="text-slate-600">›</span>
            <span className="text-blue-400">Legal Templates</span>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Enterprise Contract & SLA Templates</h1>
          <p className="text-sm text-slate-400 mt-1 font-medium">
            Pre-vetted aerospace, automotive, quality assurance, and non-disclosure templates with embedded digital twin SLA parameters.
          </p>
        </div>
        <div className="mt-2 flex gap-3">
          <Link
            href="/contracts/create"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm rounded-lg shadow-lg shadow-blue-900/30 flex items-center gap-2 transition-colors"
          >
            + New Agreement
          </Link>
        </div>
      </div>

      <div className="flex flex-col gap-6 flex-1 px-8 py-6">
        <div className="flex gap-6 items-start h-full">
          {/* Main Table Container */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl shadow-xl flex flex-col flex-1 min-w-0">
            {/* Filter Bar */}
            <div className="px-6 py-4 border-b border-slate-800 flex gap-4 shrink-0 flex-wrap items-center">
              <div className="relative flex-1 min-w-[240px] max-w-md">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-xs">🔍</span>
                <input 
                  type="text" 
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search templates by title, type, or department..." 
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-xs outline-none focus:border-blue-500 text-slate-200 placeholder-slate-500"
                />
              </div>

              <div className="text-xs text-slate-400 ml-auto font-mono">
                {filteredTemplates.length} standard templates
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs min-w-[700px]">
                <thead className="text-slate-400 font-bold border-b border-slate-800 bg-[#0B0F19]/50">
                  <tr>
                    <th className="py-3 px-6">ID</th>
                    <th className="py-3 px-4">Template Title</th>
                    <th className="py-3 px-4">Type</th>
                    <th className="py-3 px-4">Department</th>
                    <th className="py-3 px-4">Version</th>
                    <th className="py-3 px-4">Clauses</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-medium text-slate-300">
                  {loading ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-400">Loading templates...</td>
                    </tr>
                  ) : filteredTemplates.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-slate-400">No templates matched search.</td>
                    </tr>
                  ) : (
                    filteredTemplates.map((row) => (
                      <tr 
                        key={row.id} 
                        onClick={() => setSelectedTemplate(row)}
                        className={`cursor-pointer transition-colors ${
                          selectedTemplate?.id === row.id ? 'bg-blue-950/40 border-l-2 border-blue-500' : 'hover:bg-slate-800/40'
                        }`}
                      >
                        <td className="py-4 px-6 font-mono font-bold text-blue-400">{row.id}</td>
                        <td className="py-4 px-4 font-semibold text-white">
                          <div className="flex items-center gap-2">
                            <span>📄</span>
                            <span>{row.name}</span>
                          </div>
                        </td>
                        <td className="py-4 px-4 text-slate-300">{row.contract_type}</td>
                        <td className="py-4 px-4 text-slate-400">{row.department}</td>
                        <td className="py-4 px-4 font-mono text-purple-400">{row.version}</td>
                        <td className="py-4 px-4 font-mono">{row.clauses_count} clauses</td>
                        <td className="py-4 px-4">
                          <span className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 px-2.5 py-0.5 rounded-full text-xs font-bold">
                            {row.status}
                          </span>
                        </td>
                        <td className="py-4 px-4 text-center">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedTemplate(row);
                            }}
                            className="px-2.5 py-1 bg-slate-800 hover:bg-blue-600 text-slate-300 hover:text-white rounded text-xs transition-colors"
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="p-4 border-t border-slate-800 flex justify-between items-center text-xs text-slate-400 bg-slate-900/50 rounded-b-xl">
              <div>Vetted by Corporate Legal, AS9100D, and IATF 16949 Standards</div>
              <button 
                onClick={() => showToast("Custom legal template builder initialized.")}
                className="text-blue-400 hover:underline"
              >
                + Register Custom Template
              </button>
            </div>
          </div>

          {/* Right Sidebar Inspection */}
          {selectedTemplate && (
            <div className="w-[360px] flex flex-col gap-6 shrink-0">
              {/* Template Card */}
              <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-xl">
                <div className="flex items-start gap-3 mb-3">
                  <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 flex items-center justify-center text-xl shrink-0">
                    📜
                  </div>
                  <div>
                    <h3 className="font-bold text-white text-sm">{selectedTemplate.name}</h3>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs font-mono text-blue-400">{selectedTemplate.id}</span>
                      <span className="text-slate-600">•</span>
                      <span className="text-xs font-mono text-purple-400">{selectedTemplate.version}</span>
                    </div>
                  </div>
                </div>

                <p className="text-xs text-slate-300 leading-relaxed bg-slate-900/70 p-3 rounded-lg border border-slate-800 mb-4">
                  {selectedTemplate.description}
                </p>

                <div className="flex flex-col gap-2">
                  <Link
                    href={`/contracts/create?template=${selectedTemplate.id}`}
                    className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs py-2.5 rounded-lg shadow-lg shadow-blue-900/30 flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <span>⚡</span> Use Template in New Contract
                  </Link>
                  <button 
                    onClick={() => {
                      showToast(`Downloaded vetted clause pack for ${selectedTemplate.name}.`);
                    }}
                    className="w-full bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 font-semibold text-xs py-2 rounded-lg transition-colors flex items-center justify-center gap-1.5"
                  >
                    <span>📥</span> Download Sample Clause Pack
                  </button>
                </div>
              </div>

              {/* Template Parameters */}
              <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-xl">
                <h4 className="font-bold text-white text-sm mb-3 flex items-center gap-2">
                  <span className="text-blue-400">⚙️</span> Standard SLA Parameters
                </h4>
                <div className="space-y-3 text-xs">
                  <div>
                    <span className="text-slate-500 block mb-0.5">Recommended SLA Terms</span>
                    <span className="font-mono text-emerald-400 font-semibold">{selectedTemplate.recommended_sla}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-800">
                    <div>
                      <span className="text-slate-500 block mb-0.5">Department</span>
                      <span className="font-semibold text-slate-200">{selectedTemplate.department}</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block mb-0.5">Clauses</span>
                      <span className="font-semibold text-slate-200">{selectedTemplate.clauses_count} Pre-drafted</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Quick Actions */}
              <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 shadow-xl">
                <h4 className="font-bold text-white text-sm mb-3">Actions</h4>
                <div className="space-y-2">
                  <button 
                    onClick={() => {
                      showToast(`Cloned ${selectedTemplate.name} to custom draft sandbox.`);
                    }}
                    className="w-full text-left p-2.5 rounded-lg border border-slate-800 bg-slate-900/60 hover:bg-slate-800 text-xs font-semibold text-slate-300 transition-colors"
                  >
                    📋 Duplicate into Local Variant
                  </button>
                  <button 
                    onClick={() => {
                      showToast(`Template ${selectedTemplate.id} marked as default for ${selectedTemplate.contract_type}.`);
                    }}
                    className="w-full text-left p-2.5 rounded-lg border border-slate-800 bg-slate-900/60 hover:bg-slate-800 text-xs font-semibold text-slate-300 transition-colors"
                  >
                    ⭐ Set as Category Default
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
