'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { 
  ArrowRight, CheckCircle2, ShieldCheck, ShieldAlert, 
  AlertTriangle, Layers, Box, FileText, ShoppingCart, 
  Target, Scale, DollarSign, Database, Play, Sparkles, 
  ExternalLink, RefreshCw, ChevronRight, Clock, Award, 
  Building2, Zap, ArrowLeft, Truck, Receipt
} from 'lucide-react';

interface ScenarioMilestone {
  step: number;
  id: string;
  doc_id: string;
  title: string;
  module: string;
  module_code: string;
  plant: string;
  timestamp: string;
  status: 'COMPLETED' | 'IN_PROGRESS' | 'SIMULATED';
  summary: string;
  principle_enforced: string;
  sod_check?: string;
  key_metrics: { label: string; value: string; highlight?: boolean }[];
  deep_link: string;
  deep_link_label: string;
  details: {
    inputs: string;
    computation: string;
    outcome: string;
  };
}

const GOLDEN_SCENARIO_STEPS: ScenarioMilestone[] = [
  {
    step: 1,
    id: "STEP-MRP",
    doc_id: "MR-1043",
    title: "Net-Change Demand & MRP Netting",
    module: "Demand Planning & MRP",
    module_code: "M02",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 06:30",
    status: "COMPLETED",
    summary: "Exploded DC-330 motor assembly BOM. Netted 12,000 units gross demand against on-hand stock and safety levels.",
    principle_enforced: "P01 Traceable Demand Purpose",
    key_metrics: [
      { label: "Gross Demand", value: "12,000 EA" },
      { label: "Stock On-Hand", value: "2,500 EA" },
      { label: "Scheduled", value: "700 EA" },
      { label: "Net Planned", value: "9,000 EA", highlight: true }
    ],
    deep_link: "/mrp/planner-workbench",
    deep_link_label: "Open MRP Planner Workbench",
    details: {
      inputs: "Finished Good: ASM-DC330-MOTOR | Material: MAT-DC330-HSG | Lead Time: 14 Days",
      computation: "Net = max(0, Gross 12,000 - OnHand 2,500 - Sched 700 + Safety 200) = 9,000 EA",
      outcome: "Generated Planned Order PLO-55821 scheduled for start 2026-10-27 and finish 2026-11-10."
    }
  },
  {
    step: 2,
    id: "STEP-REQ",
    doc_id: "REQ-2311",
    title: "Governed Purchase Requisition",
    module: "Operational Requisitions",
    module_code: "M04",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 07:15",
    status: "COMPLETED",
    summary: "Converted PLO-55821 into Governed Requisition using 4-Tier Guided Buying search.",
    principle_enforced: "P03 Reuse Before Create & P10 Lineage",
    key_metrics: [
      { label: "Origin", value: "MRP Run MR-1043" },
      { label: "Lineage Link", value: "converted_from PLO-55821" },
      { label: "Value", value: "₹35,82,000" },
      { label: "DMN-01 Approvals", value: "4 Distinct Roles", highlight: true }
    ],
    deep_link: "/p2p",
    deep_link_label: "View Requisitions in P2P Cockpit",
    details: {
      inputs: "Requisitioner: u:planner.hosur | Purpose Code: PRD-DC330-LINE1 | Plant: P100 Hosur",
      computation: "DMN-01 Matrix evaluated: Value > ₹10L on Cost Center triggers Dept Head + Procurement + Finance.",
      outcome: "PR approved with P10 explicit link recorded between PLO-55821 and REQ-2311."
    }
  },
  {
    step: 3,
    id: "STEP-MDM",
    doc_id: "MDM-REQ-701",
    title: "Master Data Governance & Duplicate Shield",
    module: "Master Data Management",
    module_code: "M03",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 07:45",
    status: "COMPLETED",
    summary: "Prevented duplicate master catalog pollution via Fuzzy Duplicate Token Scorer (similarity 94% >= 92% cutoff).",
    principle_enforced: "P04 Clean Master & P05 Governed Material",
    sod_check: "SOD-06 Enforced (Requester cannot approve as Domain Steward)",
    key_metrics: [
      { label: "Similarity Score", value: "94.0%", highlight: true },
      { label: "Matched Record", value: "MAT-DC330-HSG" },
      { label: "Decision", value: "BLOCKED_DUPLICATE" },
      { label: "Directive", value: "Enforce Standard Item Reuse" }
    ],
    deep_link: "/mdm/requests",
    deep_link_label: "Inspect MDM Duplicate Shield",
    details: {
      inputs: "Proposed Item: 'Die-Cast Housing for DC-330 Motor with Anodized Finish'",
      computation: "SequenceMatcher + Jaccard token overlap = 0.94 similarity with standard MAT-DC330-HSG.",
      outcome: "Duplicate creation autonomously blocked; requesters redirected to active master item (Principle P03)."
    }
  },
  {
    step: 4,
    id: "STEP-SOURCING",
    doc_id: "RFQ-2231",
    title: "Should-Cost & MIP Award Optimization",
    module: "Strategic Sourcing",
    module_code: "M05",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 09:00",
    status: "COMPLETED",
    summary: "Conducted sealed-bid RFQ against should-cost baseline of ₹391. MIP solver yielded 60/40 dual-source award.",
    principle_enforced: "P06 Evidence-Based Sourcing & P08 Purchase Type Rules",
    sod_check: "SOD-05 Enforced (Awarder distinct from sole bid evaluator)",
    key_metrics: [
      { label: "Should-Cost", value: "₹391.00" },
      { label: "Last Paid Price", value: "₹410.00" },
      { label: "Split Strategy", value: "60/40 Dual-Source", highlight: true },
      { label: "Negotiated Savings", value: "₹0.99 Cr/yr", highlight: true }
    ],
    deep_link: "/sourcing",
    deep_link_label: "Open Sourcing Cockpit & MIP Solver",
    details: {
      inputs: "Monthly run-rate: 90,000 units. Trichy Forge cap: 60k/mo. Kovai Diecast cap: 45k/mo.",
      computation: "MIP solver constraints: Trichy Forge 60% @ ₹398 + Kovai Diecast 40% @ ₹405 = Weighted Avg ₹400.80.",
      outcome: "Eliminated single-source shutdown risk while securing 100% capacity coverage and ₹0.99 Cr annual savings."
    }
  },
  {
    step: 5,
    id: "STEP-CLM",
    doc_id: "SA-5520",
    title: "Scheduling Agreement & LME Indexation",
    module: "Contract Lifecycle Management",
    module_code: "M07",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 10:00",
    status: "COMPLETED",
    summary: "Contracted long-term agreement with Trichy Forge Works featuring quarterly LME Aluminium Cash indexation.",
    principle_enforced: "P14 Dynamic Formula Reset with Deadband",
    key_metrics: [
      { label: "Target Volume", value: "648,000 EA" },
      { label: "Target Commitment", value: "₹25.79 Cr" },
      { label: "LME Baseline", value: "$2,450 / MT" },
      { label: "Deadband Tolerance", value: "±3.0%", highlight: true }
    ],
    deep_link: "/contracts/agreements",
    deep_link_label: "View Contract & LME Reset Modal",
    details: {
      inputs: "Contract Type: SCHEDULING_AGREEMENT | Supplier: TF001 Trichy Forge | Terms: N60 FCA Trichy",
      computation: "Quarterly review evaluates LME index shift: movements within ±3.0% retain effective price ₹398.00.",
      outcome: "Governed contract framework active. Released 5,400 units (₹21.49L, 0.83% consumption)."
    }
  },
  {
    step: 6,
    id: "STEP-PO",
    doc_id: "PO-77410",
    title: "Touchless Purchase Order Auto-Release",
    module: "Operational Purchase Orders",
    module_code: "M08",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 10:30",
    status: "COMPLETED",
    summary: "Issued release order against SA-5520. Evaluated additive PO risk score (18/100) and released touchlessly.",
    principle_enforced: "P07 Contract Terms Inheritance & DMN-02 Auto-Release",
    key_metrics: [
      { label: "Quantity", value: "5,400 EA" },
      { label: "Order Value", value: "₹21,49,200" },
      { label: "Risk Score", value: "18 / 100 (LOW)", highlight: true },
      { label: "DMN-02 Decision", value: "TOUCHLESS_RELEASE" }
    ],
    deep_link: "/p2p",
    deep_link_label: "Inspect Touchless PO in P2P Cockpit",
    details: {
      inputs: "Inherits price ₹398, terms N60, delivery tolerances +2% / -5% directly from SA-5520.",
      computation: "Risk Engine formula: Supplier History (0) + Commodity Volatility (12) + Value Tier (6) = 18 <= 20 threshold.",
      outcome: "Order autonomously transitioned to RELEASED without manual purchasing department delay."
    }
  },
  {
    step: 7,
    id: "STEP-ASN",
    doc_id: "ASN-61208",
    title: "Advance Shipping Notice & IoT Telemetry",
    module: "Receiving & Logistics",
    module_code: "M09",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 11:00",
    status: "COMPLETED",
    summary: "Supplier dispatched 5,400 units in 54 returnable bins with electronic dispatch notification and transit tracking.",
    principle_enforced: "P08 Purchase Type Rules (Scheduling Agreement Delivery)",
    key_metrics: [
      { label: "Carrier", value: "Axion Dedicated Logistics" },
      { label: "Dispatch Qty", value: "5,400 Units" },
      { label: "GPS Corridor", value: "Trichy-Hosur NH44" },
      { label: "ETA Window", value: "On-Time (+0.2h)", highlight: true }
    ],
    deep_link: "/p2p",
    deep_link_label: "Track Shipment in P2P Cockpit",
    details: {
      inputs: "Consignment: 54 returnable ESD steel bins @ 100 units/bin with individual QR lot codes.",
      computation: "Transit Sentinel verified packaging barcodes and tamper seals en-route.",
      outcome: "Gate arrival logged at Hosur receiving dock for storekeeper physical intake."
    }
  },
  {
    step: 8,
    id: "STEP-GR",
    doc_id: "GR-90231",
    title: "Goods Receipt & Quality Quarantine QL-2210",
    module: "Receiving & Quality Inspection",
    module_code: "M09",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 11:30",
    status: "COMPLETED",
    summary: "Storekeeper posted physical receipt. Quality metrology identified 20 units with gas porosity defects.",
    principle_enforced: "P09 SoD Enforcement (SOD-03)",
    sod_check: "SOD-03 Enforced (PO Creator blocked from posting Goods Receipt)",
    key_metrics: [
      { label: "Total Received", value: "5,400 EA" },
      { label: "Accepted to Stock", value: "5,380 EA", highlight: true },
      { label: "Rejected Defect", value: "20 EA (Porosity)" },
      { label: "Quality Document", value: "QL-2210" }
    ],
    deep_link: "/p2p",
    deep_link_label: "View Goods Receipt in P2P Cockpit",
    details: {
      inputs: "Receiver: u:store.keeper.hosur | Inspector: u:quality.inspector.p100 | Quality Standard: Nadcap NDT",
      computation: "CMM bore check found 20 parts with internal gas porosity exceeding 0.05mm limit.",
      outcome: "Accepted 5,380 parts to unrestricted inventory; quarantined 20 defective parts under QL-2210."
    }
  },
  {
    step: 9,
    id: "STEP-INV",
    doc_id: "INV-TF-8812",
    title: "3-Way Match Exception & Credit Note Resolution",
    module: "Invoicing & Matching",
    module_code: "M10",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 12:00",
    status: "COMPLETED",
    summary: "Supplier billed 5,400 units vs 5,380 accepted (+20 discrepancy). Resolved with Credit Note CN-TF-221.",
    principle_enforced: "P09 SoD Enforcement (SOD-04)",
    sod_check: "SOD-04 Enforced (PO Creator blocked from approving invoice exception)",
    key_metrics: [
      { label: "Billed Qty", value: "5,400 EA" },
      { label: "Accepted GR Qty", value: "5,380 EA" },
      { label: "Quantity Variance", value: "+20 EA Exception" },
      { label: "Credit Note Ref", value: "CN-TF-221 (₹7,960)", highlight: true }
    ],
    deep_link: "/p2p",
    deep_link_label: "Inspect 3-Way Reconciliation",
    details: {
      inputs: "Invoice: INV-TF-8812 for ₹21,49,200 | Tax IRN: 9a38f72c10b83e47a988d01124f",
      computation: "3-way comparison triggered DMN-03 exception (+20 EA billed above accepted receipt).",
      outcome: "AP Clerk applied Credit Note CN-TF-221 for ₹7,960; invoice reconciled to MATCHED."
    }
  },
  {
    step: 10,
    id: "STEP-SETTLEMENT",
    doc_id: "5100004421",
    title: "Exactly-Once ERP Posting & P&L Savings",
    module: "ERP Integration & Savings Realisation",
    module_code: "M11/M13",
    plant: "P100 Hosur",
    timestamp: "2026-10-21 14:00",
    status: "COMPLETED",
    summary: "Posted invoice idempotently to SAP S/4HANA (Doc 5100004421). Realised ₹0.38 Cr P&L savings with finance sign-off.",
    principle_enforced: "P12 Three Kinds of Savings & P13 Exactly-Once Posting",
    sod_check: "SOD-07 Enforced (Finance Controller validated; Category Owner blocked)",
    key_metrics: [
      { label: "SAP S/4HANA Doc", value: "#5100004421", highlight: true },
      { label: "Idempotency Replay", value: "replayed: true (Verified)" },
      { label: "Realised P&L Savings", value: "₹0.38 Cr", highlight: true },
      { label: "Cost Avoidance", value: "₹0.32 Cr (Ringfenced)" }
    ],
    deep_link: "/savings",
    deep_link_label: "View Value Waterfall in Savings Cockpit",
    details: {
      inputs: "Transactional Outbox connector to SAP S/4HANA (BAPI_INCOMINGINVOICE_CREATE).",
      computation: "Principle P12 Accounting Rule: Realised savings recognized strictly from posted general ledger invoices.",
      outcome: "Ledger credited; Finance Controller u:finance.controller.p100 signed off under SOD-07."
    }
  }
];

export default function GoldenScenarioSimulator() {
  const [activeStepIndex, setActiveStepIndex] = useState<number>(0);
  const [simulating, setSimulating] = useState(false);

  const activeStep = GOLDEN_SCENARIO_STEPS[activeStepIndex];

  const handleNext = () => {
    if (activeStepIndex < GOLDEN_SCENARIO_STEPS.length - 1) {
      setActiveStepIndex(prev => prev + 1);
    }
  };

  const handlePrev = () => {
    if (activeStepIndex > 0) {
      setActiveStepIndex(prev => prev - 1);
    }
  };

  return (
    <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-6">
      {/* Simulator Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider bg-gradient-to-r from-cyan-500/20 to-blue-500/20 text-cyan-300 border border-cyan-500/30">
              Axion Mobility Systems Golden Scenario
            </span>
            <span className="text-xs text-slate-400 font-mono">DC-330 Aluminium Die-Cast Housing</span>
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Zap className="w-5 h-5 text-amber-400" />
            End-to-End Enterprise Purchasing Lifecycle Simulator (P01–P14)
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            10-milestone demand-to-settlement journey traversing all 13 modules, SoD command-time validations, and SAP S/4HANA ledger posting.
          </p>
        </div>

        {/* Stepper Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={handlePrev}
            disabled={activeStepIndex === 0}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-40 transition flex items-center gap-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Prev
          </button>
          <span className="font-mono text-xs text-cyan-400 px-2 font-bold">
            Step {activeStepIndex + 1} of {GOLDEN_SCENARIO_STEPS.length}
          </span>
          <button
            onClick={handleNext}
            disabled={activeStepIndex === GOLDEN_SCENARIO_STEPS.length - 1}
            className="px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-xs font-bold text-white shadow-md shadow-cyan-600/20 disabled:opacity-40 transition flex items-center gap-1"
          >
            Next <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Horizontal Milestone Progress Stepper */}
      <div className="overflow-x-auto pb-2">
        <div className="flex items-center gap-2 min-w-[950px]">
          {GOLDEN_SCENARIO_STEPS.map((m, idx) => {
            const isActive = idx === activeStepIndex;
            const isDone = idx < activeStepIndex;
            return (
              <div
                key={m.id}
                onClick={() => setActiveStepIndex(idx)}
                className={`flex-1 p-2.5 rounded-xl border cursor-pointer transition relative ${
                  isActive
                    ? 'bg-[#12223F] border-cyan-400/80 shadow-lg shadow-cyan-950/40 ring-1 ring-cyan-400/50'
                    : isDone
                    ? 'bg-[#0E1B33]/80 border-slate-800 hover:border-slate-700'
                    : 'bg-slate-950/50 border-slate-900 opacity-60 hover:opacity-100'
                }`}
              >
                <div className="flex items-center justify-between text-[10px] font-mono mb-1">
                  <span className={isActive ? 'text-cyan-300 font-bold' : 'text-slate-400'}>
                    #{m.step} {m.doc_id}
                  </span>
                  {isDone ? (
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  ) : isActive ? (
                    <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
                  ) : (
                    <span className="text-slate-600 font-bold">&bull;</span>
                  )}
                </div>
                <div className="text-[11px] font-bold text-slate-200 line-clamp-1 leading-tight">
                  {m.title}
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5 font-sans">
                  {m.module_code}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Active Milestone Deep Dive Theater */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 pt-2">
        {/* Left Column: Milestone Narrative & Execution Details (8 Cols) */}
        <div className="lg:col-span-8 space-y-4">
          <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold text-cyan-400 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-500/40">
                    Milestone {activeStep.step}: {activeStep.doc_id}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-semibold">
                    {activeStep.module} ({activeStep.module_code})
                  </span>
                </div>
                <h3 className="text-lg font-bold text-white mt-1.5">
                  {activeStep.title}
                </h3>
              </div>

              <div className="text-right">
                <span className="text-[11px] font-mono text-slate-400 block">{activeStep.plant}</span>
                <span className="text-[10px] text-slate-500 font-mono">{activeStep.timestamp} UTC</span>
              </div>
            </div>

            <p className="text-xs text-slate-200 leading-relaxed font-sans">
              {activeStep.summary}
            </p>

            {/* Principles & SoD Compliance Banner */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800 flex items-start gap-2.5">
                <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                <div>
                  <span className="text-[10px] font-semibold uppercase text-slate-400 block">Enforced Principle</span>
                  <span className="text-cyan-300 font-medium">{activeStep.principle_enforced}</span>
                </div>
              </div>

              {activeStep.sod_check ? (
                <div className="p-3 rounded-lg bg-amber-950/20 border border-amber-500/30 flex items-start gap-2.5">
                  <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-amber-400 block">SoD Command Guard</span>
                    <span className="text-amber-200 font-medium">{activeStep.sod_check}</span>
                  </div>
                </div>
              ) : (
                <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800 flex items-start gap-2.5">
                  <Layers className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-slate-400 block">System State</span>
                    <span className="text-emerald-400 font-medium">Auto-Recorded to Lineage Engine</span>
                  </div>
                </div>
              )}
            </div>

            {/* Execution Details Triple Box */}
            <div className="space-y-2 pt-2 border-t border-slate-800/80 text-xs font-mono">
              <div className="p-2.5 rounded-lg bg-slate-950/50 border border-slate-800/60 flex items-baseline gap-2">
                <span className="text-[10px] text-slate-500 uppercase font-bold shrink-0 w-24">Inputs:</span>
                <span className="text-slate-300 text-[11px] font-sans">{activeStep.details.inputs}</span>
              </div>
              <div className="p-2.5 rounded-lg bg-slate-950/50 border border-slate-800/60 flex items-baseline gap-2">
                <span className="text-[10px] text-cyan-400 uppercase font-bold shrink-0 w-24">Logic / Math:</span>
                <span className="text-cyan-200 text-[11px] font-sans">{activeStep.details.computation}</span>
              </div>
              <div className="p-2.5 rounded-lg bg-slate-950/50 border border-slate-800/60 flex items-baseline gap-2">
                <span className="text-[10px] text-emerald-400 uppercase font-bold shrink-0 w-24">Outcome:</span>
                <span className="text-emerald-300 text-[11px] font-sans">{activeStep.details.outcome}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Key Milestone Metrics & Direct Cockpit Jump (4 Cols) */}
        <div className="lg:col-span-4 space-y-4">
          <div className="p-5 rounded-xl bg-slate-900/70 border border-slate-800 space-y-4 flex flex-col justify-between h-full">
            <div>
              <span className="text-[10px] font-semibold uppercase text-slate-400 tracking-wider block mb-3">
                Milestone Telemetry & KPIs
              </span>

              <div className="grid grid-cols-2 gap-3">
                {activeStep.key_metrics.map((km, i) => (
                  <div
                    key={i}
                    className={`p-3 rounded-lg border ${
                      km.highlight 
                        ? 'bg-cyan-950/30 border-cyan-500/40' 
                        : 'bg-slate-950/60 border-slate-800/80'
                    }`}
                  >
                    <span className="text-[10px] text-slate-400 block font-sans">{km.label}</span>
                    <div className={`text-sm font-bold font-mono mt-0.5 ${
                      km.highlight ? 'text-cyan-300' : 'text-slate-100'
                    }`}>
                      {km.value}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Direct Deep Link Button */}
            <div className="pt-4 border-t border-slate-800/80 space-y-2">
              <Link
                href={activeStep.deep_link}
                className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-xs font-bold text-white shadow-lg shadow-cyan-600/20 transition flex items-center justify-center gap-2 group"
              >
                <span>{activeStep.deep_link_label}</span>
                <ExternalLink className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
              </Link>
              <div className="text-[10px] text-slate-500 text-center font-mono">
                Click to inspect live operational data in {activeStep.module}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
