'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { 
  Workflow, GitPullRequest, Layers, ShieldCheck, 
  FileText, Clock, Sparkles, CheckCircle2, ArrowRight,
  Code2, Download, ExternalLink, Activity, Filter, Eye
} from 'lucide-react';
import BpmnSwimlanePlayer, { BpmnStep } from '@/components/bpmn/BpmnSwimlanePlayer';

interface SampleDocInstance {
  docId: string;
  flowCode: string;
  docType: string;
  title: string;
  currentStep: string;
  lane: string;
  status: string;
}

const SAMPLE_DOCUMENTS: SampleDocInstance[] = [
  {
    docId: 'PO-77410',
    flowCode: 'F5',
    docType: 'Purchase Order',
    title: 'PO #77410: Precision CNC Flange Casings',
    currentStep: 'Step 6: Advanced Shipping Notice (ASN) Dispatched',
    lane: 'External Supplier (Trichy Forge)',
    status: 'IN_TRANSIT'
  },
  {
    docId: 'REQ-2311',
    flowCode: 'F2',
    docType: 'Requisition',
    title: 'PR #2311: Replacement Tungsten Carbide Milling Inserts',
    currentStep: 'Step 8: Designated Multi-Tier Approver Review',
    lane: 'Designated Approvers (SOD-01)',
    status: 'PENDING_APPROVAL'
  },
  {
    docId: 'INV-TF-8812',
    flowCode: 'F7',
    docType: 'Invoice',
    title: 'INV #TF-8812: Machined Rotor Discs ₹14,25,000',
    currentStep: 'Step 5: 3-Way Match Verified & Payment Encumbered',
    lane: 'Platform AP Engine',
    status: 'SCHEDULED_FOR_PAYMENT'
  },
  {
    docId: 'MR-1043',
    flowCode: 'F1',
    docType: 'MRP Planned Order',
    title: 'MRP Run #1043: Direct Materials Net Requirements',
    currentStep: 'Step 3: Planner Converts to Standard Requisition',
    lane: 'MRP Controller',
    status: 'PLANNER_CONVERTED'
  },
  {
    docId: 'RFQ-701',
    flowCode: 'F3',
    docType: 'Strategic Sourcing',
    title: 'Sourcing Wave #701: Die-Casting Annual Tender',
    currentStep: 'Step 6: MIP Optimization Solver & TCO Scenario Evaluation',
    lane: 'Platform Sourcing Engine',
    status: 'SOLVER_OPTIMIZING'
  },
  {
    docId: 'CTR-991',
    flowCode: 'F4',
    docType: 'Contract Agreement',
    title: 'MSA #991: Master Supply Agreement with Trichy Forge',
    currentStep: 'Step 5: AI Clause Deviation & Legal Redline Studio',
    lane: 'Legal & Finance (SOD-04)',
    status: 'REDLINE_REVIEW'
  },
  {
    docId: 'GRN-4401',
    flowCode: 'F6',
    docType: 'Goods Receipt',
    title: 'GRN #4401: Batch #B-998 Titanium Bar Stock',
    currentStep: 'Step 5: Quality Inspection & QA Release',
    lane: 'Plant Quality Assurance',
    status: 'INSPECTION_PENDING'
  },
  {
    docId: 'SUP-ONB-108',
    flowCode: 'F8',
    docType: 'Supplier Qualification',
    title: 'Vendor #TF001: Category Qualification & Bank Validation',
    currentStep: 'Step 4: Dual-Approval Bank & Tax Verification (SOD-02)',
    lane: 'Finance & Compliance',
    status: 'DUAL_SIGN_OFF'
  },
  {
    docId: 'MAT-REQ-551',
    flowCode: 'F9',
    docType: 'Material Master',
    title: 'MDM Item #551: M12 Grade 8.8 Hex Bolts',
    currentStep: 'Step 2: Fuzzy Token Duplicate Shield (0.92 Cutoff)',
    lane: 'Platform MDM Engine',
    status: 'DUPLICATE_EVALUATED'
  }
];

export default function BpmnFlowsPage() {
  const [activeFlowCode, setActiveFlowCode] = useState<string>('F2');
  const [selectedDoc, setSelectedDoc] = useState<SampleDocInstance>(SAMPLE_DOCUMENTS[1]);
  const [xmlModalOpen, setXmlModalOpen] = useState<boolean>(false);
  const [activeStepInfo, setActiveStepInfo] = useState<BpmnStep | null>(null);

  const handleSelectDoc = (doc: SampleDocInstance) => {
    setSelectedDoc(doc);
    setActiveFlowCode(doc.flowCode);
  };

  const generateBpmnXml = (flowCode: string) => {
    return `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:camunda="http://camunda.org/schema/1.0/bpmn"
                  targetNamespace="http://alphahelion.procurement.cloud/bpmn">
  <bpmn:collaboration id="Collaboration_${flowCode}">
    <bpmn:participant id="Participant_${flowCode}" name="${flowCode} Governed Swimlane" processRef="pic.${flowCode.toLowerCase()}" />
  </bpmn:collaboration>
  <bpmn:process id="pic.${flowCode.toLowerCase()}" isExecutable="true">
    <bpmn:laneSet id="LaneSet_1">
      <bpmn:lane id="Lane_Human" name="Human User Tasks" />
      <bpmn:lane id="Lane_System" name="Automated Platform Engine" />
      <bpmn:lane id="Lane_Supplier" name="Supplier Portal External" />
    </bpmn:laneSet>
    <!-- Governed BPMN 2.0 Choreography Nodes -->
    <bpmn:startEvent id="StartEvent_1" name="Initiation Trigger" />
    <bpmn:userTask id="Task_1" name="Governed User Task" camunda:candidateGroups="BUYER_TEAM" />
    <bpmn:exclusiveGateway id="Gateway_1" name="DMN Routing Matrix" />
    <bpmn:serviceTask id="Service_1" name="Platform Automated Service Task" />
    <bpmn:endEvent id="EndEvent_1" name="Governed Complete Hand-off" />
  </bpmn:process>
</bpmn:definitions>`;
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 p-6 space-y-6">
      {/* Page Title & Standards Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono text-cyan-400 font-semibold tracking-wider uppercase bg-cyan-950/60 px-2.5 py-0.5 rounded border border-cyan-800/40">
              Process Choreography Engine
            </span>
            <span className="text-xs font-mono text-slate-400">
              Camunda 7/8 BPMN 2.0 & DMN-01
            </span>
          </div>
          <h1 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight flex items-center gap-3">
            <Workflow className="w-8 h-8 text-cyan-400" />
            Governed BPMN 2.0 Swimlane Workflows & Token Player
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-3xl">
            Complete visual representation of the 9 governed procurement processes defined in Product Blueprint Part C Section 21.
            Inspect human candidate groups, automated system tasks, DMN gateway logic, and track real-time token states across swimlanes.
          </p>
        </div>

        {/* XML Export & Doc Quick Action */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => setXmlModalOpen(true)}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-slate-900 border border-slate-700 hover:border-cyan-500/50 hover:bg-slate-800 text-xs font-semibold text-slate-200 transition-all shadow-md"
          >
            <Code2 className="w-4 h-4 text-cyan-400" />
            Export BPMN XML
          </button>

          <Link
            href="/command-centre"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs transition-all shadow-lg shadow-cyan-500/20"
          >
            <Activity className="w-4 h-4" />
            CPO Command Centre
          </Link>
        </div>
      </div>

      {/* KPI Stats Architecture Ribbon */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center gap-3 shadow-sm">
          <div className="p-3 bg-cyan-500/10 border border-cyan-500/30 rounded-lg text-cyan-400">
            <GitPullRequest className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xl font-bold text-white">9 Flows</div>
            <div className="text-xs text-slate-400">F1 (MRP) to F9 (MDM)</div>
          </div>
        </div>

        <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center gap-3 shadow-sm">
          <div className="p-3 bg-indigo-500/10 border border-indigo-500/30 rounded-lg text-indigo-400">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xl font-bold text-white">33 Swimlanes</div>
            <div className="text-xs text-slate-400">Human, System & External</div>
          </div>
        </div>

        <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center gap-3 shadow-sm">
          <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xl font-bold text-white">16 RBAC Roles</div>
            <div className="text-xs text-slate-400">SOD-01 to SOD-06 Segregated</div>
          </div>
        </div>

        <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl flex items-center gap-3 shadow-sm">
          <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400">
            <Clock className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xl font-bold text-white">DMN Routing</div>
            <div className="text-xs text-slate-400">SLA Timers & Escalations</div>
          </div>
        </div>
      </div>

      {/* Live Document Instance Tracking Selector */}
      <div className="p-4 bg-slate-900/80 border border-slate-800/80 rounded-xl space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Eye className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-bold text-white">
              Live Document Instances — Track Active Token Across BPMN Flows
            </h3>
          </div>
          <span className="text-xs font-mono text-slate-400">
            Select an enterprise document to project its live step onto the canvas
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
          {SAMPLE_DOCUMENTS.map(doc => {
            const isSelected = selectedDoc.docId === doc.docId;
            return (
              <button
                key={doc.docId}
                onClick={() => handleSelectDoc(doc)}
                className={`p-2.5 rounded-lg text-left transition-all border ${
                  isSelected
                    ? 'bg-cyan-950/50 border-cyan-500/70 shadow-md shadow-cyan-500/10 ring-1 ring-cyan-500/40'
                    : 'bg-slate-950/60 hover:bg-slate-800/60 border-slate-800'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-mono font-bold text-cyan-300">
                    {doc.docId}
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-slate-300">
                    {doc.flowCode}
                  </span>
                </div>
                <div className="text-xs font-medium text-slate-200 line-clamp-1">
                  {doc.docType}
                </div>
                <div className="text-[11px] text-slate-400 truncate mt-1">
                  {doc.currentStep}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Embedded BPMN 2.0 Swimlane Viewer & Token Player Component */}
      <BpmnSwimlanePlayer
        initialFlowCode={activeFlowCode}
        selectedDocId={selectedDoc.docId}
        onStepChange={(idx, step) => setActiveStepInfo(step)}
      />

      {/* BPMN Flows Directory Table (Blueprint Section 21 Mapping) */}
      <div className="p-6 bg-slate-900/60 border border-slate-800 rounded-xl space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <FileText className="w-4 h-4 text-cyan-400" />
              Blueprint Part C: Governed Process Catalog (Flows F1 - F9)
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Strict governance compliance: No direct material purchase allowed without purchase requisition (P01) or approved contract (P02).
            </p>
          </div>
          <span className="text-xs font-mono text-slate-500">
            Doc Ref: AHG/PRC/PIC/2026-10/01 Pages 37-54
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border border-slate-800">
            <thead className="bg-[#0A101D] text-slate-400 uppercase font-mono text-[11px] border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-3">Flow</th>
                <th className="py-2.5 px-3">Process Key</th>
                <th className="py-2.5 px-3">Process Title</th>
                <th className="py-2.5 px-3">Swimlanes</th>
                <th className="py-2.5 px-3">Key DMN / Governance</th>
                <th className="py-2.5 px-3">Hand-off Target</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {[
                { code: 'F1', key: 'pic.mrp-to-pr', title: 'MRP Run → Planned Order → Purchase Requisition', lanes: 'MRP Controller, Platform MRP Engine, Buyer', dmn: 'Lot Sizing & Reorder Point (DMN-03)', handoff: 'F5 (PO Lifecycle)' },
                { code: 'F2', key: 'pic.requisition', title: 'Guided Buying Requisition (Catalogue / Free Text / MDM)', lanes: 'Requester, Platform Policy, Approvers, MDM Steward', dmn: '4-Tier Approval Routing (DMN-01)', handoff: 'F3 or F5' },
                { code: 'F3', key: 'pic.sourcing-award', title: 'Strategic Sourcing → Award Optimization', lanes: 'Category Manager, Suppliers, Platform Sourcing, Award Board', dmn: 'MIP Optimization Solver (SOD-05)', handoff: 'F4 (Contract)' },
                { code: 'F4', key: 'pic.contract', title: 'Contract Lifecycle Management (CLM)', lanes: 'Contract Mgr, Platform CLM, Legal & Finance, Supplier', dmn: 'AI Clause Deviation & Auto-Renewal Alert', handoff: 'F5 (Call-off PO)' },
                { code: 'F5', key: 'pic.po', title: 'Purchase Order → Supplier Confirmation → Delivery', lanes: 'Buyer, Platform PO Engine, Approvers, Supplier', dmn: 'Acknowledgment SLA & Tolerances (DMN-02)', handoff: 'F6 (Receipt)' },
                { code: 'F6', key: 'pic.receipt', title: 'Goods Receipt / Service Entry → Quality Inspection', lanes: 'Receiver / Service Owner, Platform Receiving, QA, Supplier', dmn: 'Skip-lot Inspection & SES Acceptance', handoff: 'F7 (Invoice Match)' },
                { code: 'F7', key: 'pic.invoice', title: 'Invoice Matching → ERP Posting → Payment Run', lanes: 'Supplier, Platform AP Engine, AP Clerk, ERP / Bank', dmn: '3-Way Match & Auto-Posting (DMN-04)', handoff: 'Payment Settlement' },
                { code: 'F8', key: 'pic.supplier-onboarding', title: 'Supplier Onboarding & Qualification (SLM)', lanes: 'Supplier, Platform SLM, Finance & Compliance, Supplier Mgr', dmn: 'Dual Approval Bank Details (SOD-02)', handoff: 'F3 / Sourcing Ready' },
                { code: 'F9', key: 'pic.material-request', title: 'Material Master Governance (MDM Duplicate Shield)', lanes: 'Requester/Buyer, Platform MDM, Data Stewards, ERP', dmn: 'Duplicate Cutoff 0.92 Similarity Gate', handoff: 'F2 / Catalog Ready' },
              ].map(row => (
                <tr key={row.code} className="hover:bg-slate-850/50 transition-colors">
                  <td className="py-2.5 px-3 font-mono font-bold text-cyan-400">{row.code}</td>
                  <td className="py-2.5 px-3 font-mono text-slate-400">{row.key}</td>
                  <td className="py-2.5 px-3 font-semibold text-white">{row.title}</td>
                  <td className="py-2.5 px-3 text-slate-300">{row.lanes}</td>
                  <td className="py-2.5 px-3 font-mono text-amber-300">{row.dmn}</td>
                  <td className="py-2.5 px-3 font-mono text-emerald-400">{row.handoff}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* BPMN XML Preview Modal */}
      {xmlModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0B1322] border border-slate-700 rounded-xl w-full max-w-3xl overflow-hidden shadow-2xl flex flex-col max-h-[85vh]">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-900">
              <div className="flex items-center gap-2">
                <Code2 className="w-5 h-5 text-cyan-400" />
                <h3 className="font-bold text-white text-sm">
                  BPMN 2.0 XML Schema Definition — Flow {activeFlowCode}
                </h3>
              </div>
              <button
                onClick={() => setXmlModalOpen(false)}
                className="text-slate-400 hover:text-white text-xs font-semibold px-2 py-1 rounded bg-slate-800 hover:bg-slate-700"
              >
                Close
              </button>
            </div>

            <div className="p-4 overflow-y-auto flex-1 font-mono text-xs bg-[#060A12] text-cyan-300">
              <pre className="whitespace-pre-wrap">{generateBpmnXml(activeFlowCode)}</pre>
            </div>

            <div className="p-3 bg-slate-900 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
              <span>Standard Camunda 7/8 & OMG BPMN 2.0 Compliant</span>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(generateBpmnXml(activeFlowCode));
                  alert('BPMN 2.0 XML copied to clipboard!');
                }}
                className="px-3 py-1.5 rounded bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold"
              >
                Copy XML to Clipboard
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
