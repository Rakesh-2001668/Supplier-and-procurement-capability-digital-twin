"use client";
import React, { useState, useEffect } from "react";
import Link from 'next/link';
import { useRouter } from 'next/navigation';

export default function CreateContract() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGeneratingClauses, setIsGeneratingClauses] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [createdContractId, setCreatedContractId] = useState<string | null>(null);

  // Form State
  const [formData, setFormData] = useState({
    name: "Aerospace Precision Actuator Long-Term Agreement",
    contract_type: "SUPPLY",
    category: "Precision Machining & Diecasting",
    supplier_id: "TWIN-KOVAI-003",
    supplier_name: "Kovai Diecast Industries",
    supplier_location: "Coimbatore, India",
    total_value_usd: 950000,
    start_date: "2026-11-01",
    end_date: "2028-11-01",
    payment_terms: "Net 45 (Smart Escrow)",
    target_otif_pct: 98.5,
    max_defect_ppm: 40,
    penalty_per_day_pct: 2.5,
    scope_description: "Comprehensive manufacturing and CMM inspection agreement with continuous edge IIoT digital twin verification."
  });

  const [generatedClauses, setGeneratedClauses] = useState<Array<{title: string; text: string; rationale: string}>>([
    {
      title: "Dynamic OTIF Delivery Guarantee (98.5%)",
      text: "Supplier shall maintain >= 98.5% On-Time In-Full delivery rate across all purchase orders. Delays beyond 48 hours incur 2.5% liquidated damages per calendar day.",
      rationale: "Grounded in digital twin variance analysis."
    },
    {
      title: "AS9100 Rev D Material Lot Traceability",
      text: "Supplier shall maintain 100% digital heat-lot traceability with certified test reports for all raw billets.",
      rationale: "Aerospace structural compliance standard."
    }
  ]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  };

  const handleGenerateAIClauses = async () => {
    setIsGeneratingClauses(true);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/contracts/dynamic-clauses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          supplier_id: formData.supplier_id,
          supplier_name: formData.supplier_name,
          component_category: formData.category,
          program_risk_level: "MEDIUM",
          free_capacity_pct: 18.0
        })
      });
      if (res.ok) {
        const data = await res.json();
        const formatted = (data.generated_clauses || []).map((c: any) => ({
          title: c.title,
          text: c.clause_text,
          rationale: c.rationale
        }));
        setGeneratedClauses(prev => [...prev, ...formatted]);
        showToast("Generated 2 AI-grounded SLA clauses from supplier telemetry!");
      }
    } catch {
      showToast("Unable to reach AI clause engine, using local baseline clauses.");
    } finally {
      setIsGeneratingClauses(false);
    }
  };

  const handleSubmitContract = async () => {
    setIsSubmitting(true);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/contracts/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });
      if (res.ok) {
        const data = await res.json();
        setCreatedContractId(data.contract.id);
        showToast(`Contract ${data.contract.id} successfully created and sent for counter-signature!`);
      } else {
        showToast("Error creating contract. Please verify input fields.");
      }
    } catch {
      showToast("Network error while submitting contract.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderStepper = () => {
    const steps = ['Basic Details', 'Commercials & Items', 'SLA & AI Clauses', 'Escrow & Governance', 'Review & Deploy'];
    return (
      <div className="flex items-center justify-between mb-8 px-4 bg-[#111827] border border-slate-800 p-4 rounded-xl shadow-lg">
        {steps.map((step, index) => {
          const stepNumber = index + 1;
          const isActive = currentStep === stepNumber;
          const isCompleted = currentStep > stepNumber;
          
          return (
            <React.Fragment key={step}>
              <div 
                className={`flex items-center gap-3 cursor-pointer transition-all ${
                  !isActive && !isCompleted ? 'opacity-40 hover:opacity-75' : ''
                }`} 
                onClick={() => setCurrentStep(stepNumber)}
              >
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-mono font-bold text-xs shadow-md ${
                  isActive ? 'bg-blue-600 text-white ring-2 ring-blue-400' : isCompleted ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400'
                }`}>
                  {isCompleted ? '✓' : stepNumber}
                </div>
                <span className={`text-xs font-bold ${isActive ? 'text-blue-400' : isCompleted ? 'text-slate-200' : 'text-slate-400'}`}>
                  {step}
                </span>
              </div>
              {index < steps.length - 1 && (
                <div className={`flex-1 h-px mx-4 ${isCompleted ? 'bg-emerald-500' : 'bg-slate-800'}`}></div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    );
  };

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
            <span className="text-blue-400">Create New Agreement</span>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Draft Smart Contract & SLA Agreement</h1>
          <p className="text-sm text-slate-400 mt-1 font-medium">
            Configure commercial terms, dynamic performance milestones, and automated blockchain liquidated damages.
          </p>
        </div>
        <div className="mt-2 flex gap-3">
          <Link
            href="/contracts/templates"
            className="px-4 py-2 border border-slate-700 bg-slate-900 text-slate-300 hover:text-white font-bold text-xs rounded-lg transition-colors flex items-center gap-1.5"
          >
            📄 Browse Templates
          </Link>
          <Link
            href="/contracts/view"
            className="px-4 py-2 text-slate-400 hover:text-slate-200 text-xs font-semibold rounded-lg hover:bg-slate-800 transition-colors"
          >
            Cancel
          </Link>
        </div>
      </div>

      <div className="flex flex-col flex-1 px-8 py-6 max-w-6xl mx-auto w-full">
        {renderStepper()}

        {/* Success Modal / Banner */}
        {createdContractId && (
          <div className="mb-8 p-6 bg-emerald-950/40 border border-emerald-500/40 rounded-xl shadow-2xl flex flex-col items-center text-center">
            <div className="w-14 h-14 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-3xl mb-3">
              🎉
            </div>
            <h2 className="text-xl font-bold text-white mb-1">Contract Created Successfully!</h2>
            <p className="text-sm text-slate-300 mb-4">
              Contract reference <span className="font-mono text-emerald-400 font-bold">{createdContractId}</span> has been signed with the buyer token and dispatched for supplier counter-signature.
            </p>
            <div className="flex gap-4">
              <Link
                href="/contracts/view"
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded-lg transition-colors"
              >
                Inspect in Repository →
              </Link>
              <button
                onClick={() => {
                  setCreatedContractId(null);
                  setCurrentStep(1);
                }}
                className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs rounded-lg transition-colors"
              >
                Draft Another Contract
              </button>
            </div>
          </div>
        )}

        {/* Step 1: Basic Details */}
        {currentStep === 1 && !createdContractId && (
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-8 shadow-xl flex flex-col gap-6">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-4">
              <span className="text-2xl">📄</span>
              <div>
                <h2 className="text-base font-bold text-white">Step 1: Agreement Identity & Supplier Metadata</h2>
                <p className="text-xs text-slate-400">Specify contract title, counterparty, and operational category.</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-6 text-xs">
              <div className="col-span-2">
                <label className="block text-slate-400 font-bold mb-1.5">Contract Agreement Title *</label>
                <input 
                  type="text" 
                  value={formData.name}
                  onChange={(e) => setFormData({...formData, name: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-white font-medium outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Supplier Name *</label>
                <input 
                  type="text" 
                  value={formData.supplier_name}
                  onChange={(e) => setFormData({...formData, supplier_name: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-white font-medium outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Supplier Digital Twin ID *</label>
                <input 
                  type="text" 
                  value={formData.supplier_id}
                  onChange={(e) => setFormData({...formData, supplier_id: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 font-mono text-blue-400 font-medium outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Supplier Location *</label>
                <input 
                  type="text" 
                  value={formData.supplier_location}
                  onChange={(e) => setFormData({...formData, supplier_location: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-white font-medium outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Category *</label>
                <select 
                  value={formData.category}
                  onChange={(e) => setFormData({...formData, category: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-white font-medium outline-none focus:border-blue-500"
                >
                  <option value="Precision Machining & Diecasting">Precision Machining & Diecasting</option>
                  <option value="Aerospace Actuation Systems">Aerospace Actuation Systems</option>
                  <option value="Automotive Powertrain">Automotive Powertrain</option>
                  <option value="EV Battery Packs">EV Battery Packs</option>
                  <option value="Defense Electronics">Defense Electronics</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Start Date *</label>
                <input 
                  type="date" 
                  value={formData.start_date}
                  onChange={(e) => setFormData({...formData, start_date: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-white font-medium outline-none focus:border-blue-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">End Date *</label>
                <input 
                  type="date" 
                  value={formData.end_date}
                  onChange={(e) => setFormData({...formData, end_date: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-white font-medium outline-none focus:border-blue-500 font-mono"
                />
              </div>

              <div className="col-span-2">
                <label className="block text-slate-400 font-bold mb-1.5">Scope of Work & Deliverables</label>
                <textarea
                  rows={3}
                  value={formData.scope_description}
                  onChange={(e) => setFormData({...formData, scope_description: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg p-3 text-white font-medium outline-none focus:border-blue-500 resize-none"
                />
              </div>
            </div>

            <div className="flex justify-end pt-4 border-t border-slate-800">
              <button 
                onClick={() => setCurrentStep(2)}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded-lg transition-colors flex items-center gap-1.5 shadow-lg shadow-blue-900/30"
              >
                Next: Commercials & Pricing →
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Commercials */}
        {currentStep === 2 && !createdContractId && (
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-8 shadow-xl flex flex-col gap-6">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-4">
              <span className="text-2xl">🪙</span>
              <div>
                <h2 className="text-base font-bold text-white">Step 2: Commercial Values & Payment Framework</h2>
                <p className="text-xs text-slate-400">Establish total value, payment terms, and smart escrow disbursement gates.</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-6 text-xs">
              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Total Contract Value (USD) *</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 font-mono">$</span>
                  <input 
                    type="number" 
                    value={formData.total_value_usd}
                    onChange={(e) => setFormData({...formData, total_value_usd: parseFloat(e.target.value) || 0})}
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg pl-8 pr-4 py-2.5 text-white font-mono font-bold text-sm outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Payment Terms *</label>
                <select 
                  value={formData.payment_terms}
                  onChange={(e) => setFormData({...formData, payment_terms: e.target.value})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-white font-medium outline-none focus:border-blue-500"
                >
                  <option value="Net 45 (Smart Escrow)">Net 45 (Smart Escrow Milestone Release)</option>
                  <option value="Net 30 (ASN Verification)">Net 30 (ASN Verification)</option>
                  <option value="Net 60 (Defense Milestone)">Net 60 (Defense Milestone)</option>
                  <option value="Pre-Funded Escrow (100%)">Pre-Funded Escrow (100%)</option>
                </select>
              </div>
            </div>

            <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800 text-xs">
              <h4 className="font-bold text-white mb-2">Automated Escrow Milestone Distribution</h4>
              <div className="grid grid-cols-3 gap-4 font-mono text-[11px]">
                <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg">
                  <div className="text-slate-400">ASN Dispatch Milestone</div>
                  <div className="text-emerald-400 font-bold mt-1">40% ($380,000 USD)</div>
                </div>
                <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg">
                  <div className="text-slate-400">Zeiss CMM Inspection Pass</div>
                  <div className="text-emerald-400 font-bold mt-1">40% ($380,000 USD)</div>
                </div>
                <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg">
                  <div className="text-slate-400">Line-Side Ingestion Clearance</div>
                  <div className="text-emerald-400 font-bold mt-1">20% ($190,000 USD)</div>
                </div>
              </div>
            </div>

            <div className="flex justify-between pt-4 border-t border-slate-800">
              <button 
                onClick={() => setCurrentStep(1)}
                className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs rounded-lg transition-colors"
              >
                ← Back
              </button>
              <button 
                onClick={() => setCurrentStep(3)}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded-lg transition-colors flex items-center gap-1.5 shadow-lg shadow-blue-900/30"
              >
                Next: SLA & AI Clauses →
              </button>
            </div>
          </div>
        )}

        {/* Step 3: SLA & AI Clauses */}
        {currentStep === 3 && !createdContractId && (
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-8 shadow-xl flex flex-col gap-6">
            <div className="flex justify-between items-center border-b border-slate-800 pb-4">
              <div className="flex items-center gap-3">
                <span className="text-2xl">🎯</span>
                <div>
                  <h2 className="text-base font-bold text-white">Step 3: Service Level Agreement (SLA) & Dynamic AI Clauses</h2>
                  <p className="text-xs text-slate-400">Target delivery performance, liquidated damages rates, and telemetry clauses.</p>
                </div>
              </div>
              <button
                disabled={isGeneratingClauses}
                onClick={handleGenerateAIClauses}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs rounded-lg shadow-lg shadow-purple-900/30 flex items-center gap-2 transition-colors disabled:opacity-50"
              >
                {isGeneratingClauses ? 'Synthesizing...' : '🤖 AI Generate Clauses from Telemetry'}
              </button>
            </div>

            <div className="grid grid-cols-3 gap-6 text-xs">
              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Target OTIF Delivery (%) *</label>
                <input 
                  type="number" 
                  step="0.1"
                  value={formData.target_otif_pct}
                  onChange={(e) => setFormData({...formData, target_otif_pct: parseFloat(e.target.value) || 0})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-emerald-400 font-mono font-bold outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Maximum Defect Threshold (PPM) *</label>
                <input 
                  type="number" 
                  value={formData.max_defect_ppm}
                  onChange={(e) => setFormData({...formData, max_defect_ppm: parseInt(e.target.value) || 0})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-white font-mono font-bold outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-bold mb-1.5">Delay Penalty (% / Day Delay) *</label>
                <input 
                  type="number" 
                  step="0.1"
                  value={formData.penalty_per_day_pct}
                  onChange={(e) => setFormData({...formData, penalty_per_day_pct: parseFloat(e.target.value) || 0})}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-amber-400 font-mono font-bold outline-none focus:border-blue-500"
                />
              </div>
            </div>

            {/* Clauses List */}
            <div className="flex flex-col gap-3">
              <h4 className="font-bold text-white text-xs">Attached Contract Clauses ({generatedClauses.length})</h4>
              {generatedClauses.map((c, i) => (
                <div key={i} className="p-4 bg-slate-900/60 rounded-xl border border-slate-800 text-xs">
                  <div className="font-bold text-white mb-1">{c.title}</div>
                  <p className="text-slate-300 text-[11px] leading-relaxed mb-2 font-sans">{c.text}</p>
                  <div className="text-[10px] text-cyan-300 font-mono bg-cyan-950/30 p-2 rounded border border-cyan-800/40">
                    💡 Telemetry Rationale: {c.rationale}
                  </div>
                </div>
              ))}
            </div>

            <div className="flex justify-between pt-4 border-t border-slate-800">
              <button 
                onClick={() => setCurrentStep(2)}
                className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs rounded-lg transition-colors"
              >
                ← Back
              </button>
              <button 
                onClick={() => setCurrentStep(4)}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded-lg transition-colors flex items-center gap-1.5 shadow-lg shadow-blue-900/30"
              >
                Next: Escrow & Governance →
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Governance */}
        {currentStep === 4 && !createdContractId && (
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-8 shadow-xl flex flex-col gap-6">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-4">
              <span className="text-2xl">🛡️</span>
              <div>
                <h2 className="text-base font-bold text-white">Step 4: Smart Escrow Binding & Ledger Governance</h2>
                <p className="text-xs text-slate-400">Configure cryptographic signing authorities and immutable chain deployment triggers.</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-6 text-xs">
              <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                <h4 className="font-bold text-white mb-2 flex items-center gap-2">
                  <span className="text-blue-400">🔐</span> Multi-Sig Signatory Authority
                </h4>
                <div className="space-y-2 text-slate-300">
                  <div>Buyer Signatory: <span className="font-bold text-white">Alex Sharma (VP Global Sourcing)</span></div>
                  <div>Supplier Signatory: <span className="font-bold text-white">{formData.supplier_name} Managing Director</span></div>
                  <div>Signing Protocol: <span className="font-mono text-purple-400">ECDSA secp256k1</span></div>
                </div>
              </div>

              <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                <h4 className="font-bold text-white mb-2 flex items-center gap-2">
                  <span className="text-purple-400">⛓️</span> Autonomous Blockchain Seal
                </h4>
                <div className="space-y-2 text-slate-300">
                  <div>Ledger Deployment: <span className="text-emerald-400 font-bold">Enabled</span></div>
                  <div>Oracle Link: <span className="font-mono text-cyan-400">Edge IIoT CMM Telemetry</span></div>
                  <div>Penalty Execution: <span className="text-white font-semibold">Automated Escrow Debit</span></div>
                </div>
              </div>
            </div>

            <div className="flex justify-between pt-4 border-t border-slate-800">
              <button 
                onClick={() => setCurrentStep(3)}
                className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs rounded-lg transition-colors"
              >
                ← Back
              </button>
              <button 
                onClick={() => setCurrentStep(5)}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded-lg transition-colors flex items-center gap-1.5 shadow-lg shadow-blue-900/30"
              >
                Next: Review & Deploy →
              </button>
            </div>
          </div>
        )}

        {/* Step 5: Review & Deploy */}
        {currentStep === 5 && !createdContractId && (
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-8 shadow-xl flex flex-col gap-6">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-4">
              <span className="text-2xl">🚀</span>
              <div>
                <h2 className="text-base font-bold text-white">Step 5: Final Review & Cryptographic Contract Execution</h2>
                <p className="text-xs text-slate-400">Review all contract parameters before generating the on-chain agreement.</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs">
              <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                <span className="text-slate-500 block">Contract Title</span>
                <span className="font-bold text-white text-sm">{formData.name}</span>
              </div>
              <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                <span className="text-slate-500 block">Total Agreement Value</span>
                <span className="font-mono font-bold text-emerald-400 text-sm">${formData.total_value_usd.toLocaleString()} USD</span>
              </div>
              <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                <span className="text-slate-500 block">Supplier</span>
                <span className="font-bold text-white">{formData.supplier_name} ({formData.supplier_id})</span>
              </div>
              <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                <span className="text-slate-500 block">Operational Window</span>
                <span className="font-mono font-bold text-white">{formData.start_date} to {formData.end_date}</span>
              </div>
              <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                <span className="text-slate-500 block">SLA Target OTIF</span>
                <span className="font-mono font-bold text-emerald-400">{formData.target_otif_pct}%</span>
              </div>
              <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800">
                <span className="text-slate-500 block">Liquidated Damages Delay Penalty</span>
                <span className="font-mono font-bold text-amber-400">{formData.penalty_per_day_pct}% per calendar day</span>
              </div>
            </div>

            <div className="flex justify-between pt-4 border-t border-slate-800">
              <button 
                onClick={() => setCurrentStep(4)}
                className="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs rounded-lg transition-colors"
              >
                ← Back
              </button>
              <button 
                disabled={isSubmitting}
                onClick={handleSubmitContract}
                className="px-8 py-3 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-sm rounded-lg transition-colors flex items-center gap-2 shadow-xl shadow-emerald-900/40 disabled:opacity-50"
              >
                {isSubmitting ? 'Executing Contract...' : '🚀 Submit & Dispatch Contract'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
