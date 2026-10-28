'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  ShieldCheck, AlertTriangle, ArrowRight, Search, RefreshCw, CheckCircle2,
  Building2, Layers, Sparkles, CreditCard, Lock, Box, Sliders, CheckCheck,
  XCircle, Clock, ShieldAlert, Award, FileText, ArrowDownRight, Bot,
  ExternalLink, ChevronRight, Filter, AlertOctagon, Database, Check,
  UserCheck, ShieldOff, Cpu, Compass, Settings, Zap, ArrowUpRight
} from 'lucide-react';
import axios from 'axios';

const BACKEND_URL = 'http://127.0.0.1:8080/api/v1/mdm/studio';

interface DuplicateAnalysis {
  best_score: number;
  governance_band: string;
  governance_action: string;
  cutoff_threshold: number;
  is_blocked: boolean;
  message: string;
  matched_material?: {
    material_id: string;
    description: string;
    category: string;
    commodity_code: string;
    uom: string;
    standard_price_inr: number;
  };
  top_matches: Array<{
    material_id: string;
    description: string;
    category: string;
    similarity_score: number;
    token_overlap: string[];
    model_match: boolean;
  }>;
}

interface AgentContract {
  agent_id: string;
  agent_name: string;
  autonomy_level: string;
  confidence_score: number;
  recommendation: string;
}

interface GovernedRequest {
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
  views_completed?: string;
  is_ready_for_approval?: boolean;
  created_at: string;
}

interface StandardMaterial {
  material_id: string;
  description: string;
  category: string;
  commodity_code: string;
  uom: string;
  standard_price_inr: number;
  drawing_number?: string;
  material_group?: string;
  plant_extensions?: string[];
  status: string;
}

const PRESET_SCENARIOS = [
  {
    label: 'Near Duplicate: DC-330 Housing (Anodized Variant)',
    description: 'DC-330 Die-Cast Aluminium Housing (Anodized Finish)',
    category: 'Castings & Forgings',
    commodity: '25171500',
    uom: 'EA',
    plant: 'P100 Hosur',
    expected: 'HARD_BLOCK (>= 92%)'
  },
  {
    label: 'Standard Fastener: Hex Flange Bolt M8x30',
    description: 'Hex Flange Bolt M8x30 Grade 10.9 Geomet Coated Metric',
    category: 'Fasteners & Hardware',
    commodity: 'FAST-BOLT-M8',
    uom: 'EA',
    plant: 'P100 Hosur',
    expected: 'HARD_BLOCK (>= 92%)'
  },
  {
    label: 'Moderate Similarity: Rotor Stator Subassembly',
    description: 'DC-330 Copper Stator Segment with High Temp Insulation',
    category: 'Electrical & Motor Components',
    commodity: 'ELEC-ROT-330',
    uom: 'EA',
    plant: 'P100 Hosur',
    expected: 'JUSTIFICATION REQUIRED (70-91%)'
  },
  {
    label: 'Unique Novel Part: Ceramic Substrate 50x50',
    description: 'Silicon Nitride Ceramic Heat Sink Substrate 50x50mm',
    category: 'Thermal Systems',
    commodity: '25172200',
    uom: 'EA',
    plant: 'P100 Hosur',
    expected: 'CLEAR PASS (< 70%)'
  }
];

export default function MaterialMasterGovernanceStudio() {
  const [activeTab, setActiveTab] = useState<'SHIELD' | 'STEWARDS' | 'CATALOG'>('SHIELD');
  const [currentActor, setCurrentActor] = useState('u:planner.hosur');
  
  // Real-time analysis state
  const [proposedDesc, setProposedDesc] = useState('DC-330 Die-Cast Aluminium Housing (Anodized Finish)');
  const [selectedCategory, setSelectedCategory] = useState('Castings & Forgings');
  const [commodityCode, setCommodityCode] = useState('25171500');
  const [uom, setUom] = useState('EA');
  const [targetPlant, setTargetPlant] = useState('P100 Hosur');
  const [justification, setJustification] = useState('');
  
  const [analysis, setAnalysis] = useState<DuplicateAnalysis | null>(null);
  const [agentContract, setAgentContract] = useState<AgentContract | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  
  // Governed requests & catalog state
  const [requests, setRequests] = useState<GovernedRequest[]>([]);
  const [selectedRequest, setSelectedRequest] = useState<GovernedRequest | null>(null);
  const [requestViews, setRequestViews] = useState<any>(null);
  const [catalog, setCatalog] = useState<StandardMaterial[]>([]);
  const [metrics, setMetrics] = useState({
    total_requests: 0,
    blocked_duplicates: 0,
    pending_stewards: 0,
    active_catalog_size: 0,
    duplicate_cutoff_pct: 92.0
  });
  
  // Steward view enrichment form state
  const [activeStewardView, setActiveStewardView] = useState<'purchasing' | 'plant' | 'quality' | 'accounting'>('purchasing');
  const [enrichmentForm, setEnrichmentForm] = useState({
    // Purchasing
    purchasing_group: 'P01 Powertrain',
    order_unit: 'EA',
    planned_lead_time_days: 14,
    default_incoterms: 'FCA Trichy',
    // Plant
    plant: 'P100 Hosur',
    mrp_type: 'PD (MRP Netting)',
    lot_sizing_procedure: 'EX (Lot-for-lot)',
    safety_stock: 200,
    reorder_point: 500,
    storage_location: 'SL01 Raw Stores',
    // Quality
    inspection_setup: '01 Goods Receipt for PO',
    certificate_required: 'PPAP Level 3 & CoA',
    skip_lot_active: false,
    defect_ppm_threshold: 50,
    // Accounting
    valuation_class: '3000 Raw Materials',
    price_control: 'S (Standard Price)',
    standard_valuation_inr: 398.00
  });

  // Action status / Modal
  const [sodModalViolation, setSodModalViolation] = useState<any>(null);
  const [successBanner, setSuccessBanner] = useState<string | null>(null);
  const [erpSyncNotice, setErpSyncNotice] = useState<any>(null);

  // Initial load
  useEffect(() => {
    fetchRequests();
    fetchCatalog();
    runShieldAnalysis(proposedDesc, selectedCategory);
  }, []);

  const fetchRequests = async () => {
    try {
      const res = await axios.get(`${BACKEND_URL}/requests`);
      if (res.data.status === 'success') {
        setRequests(res.data.requests);
        setMetrics(res.data.metrics);
        if (res.data.requests.length > 0 && !selectedRequest) {
          selectRequestForAudit(res.data.requests[0]);
        }
      }
    } catch (err) {
      console.error('Failed fetching MDM requests', err);
    }
  };

  const fetchCatalog = async () => {
    try {
      const res = await axios.get(`${BACKEND_URL}/catalog`);
      if (res.data.status === 'success') {
        setCatalog(res.data.materials);
      }
    } catch (err) {
      console.error('Failed fetching standard catalog', err);
    }
  };

  const selectRequestForAudit = async (req: GovernedRequest) => {
    setSelectedRequest(req);
    try {
      const res = await axios.get(`${BACKEND_URL}/requests/${req.id}`);
      if (res.data.status === 'success') {
        setRequestViews(res.data.views);
      }
    } catch (err) {
      console.error('Failed loading request views', err);
    }
  };

  // Real-time fuzzy duplicate shield
  const runShieldAnalysis = async (desc: string, cat: string) => {
    if (!desc.trim()) return;
    setIsAnalyzing(true);
    try {
      const res = await axios.post(`${BACKEND_URL}/analyze-duplicate`, {
        proposed_description: desc,
        category: cat,
        commodity_code: commodityCode,
        uom: uom,
        target_plant: targetPlant
      });
      if (res.data.status === 'success') {
        setAnalysis(res.data.analysis);
        setAgentContract(res.data.agent_contract);
      }
    } catch (err) {
      console.error('Duplicate analysis failed', err);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handlePresetSelect = (preset: typeof PRESET_SCENARIOS[0]) => {
    setProposedDesc(preset.description);
    setSelectedCategory(preset.category);
    setCommodityCode(preset.commodity);
    setUom(preset.uom);
    setTargetPlant(preset.plant);
    runShieldAnalysis(preset.description, preset.category);
  };

  // Submit governed material creation request
  const handleSubmitMaterialRequest = async () => {
    try {
      const res = await axios.post(`${BACKEND_URL}/requests`, {
        proposed_description: proposedDesc,
        category: selectedCategory,
        commodity_code: commodityCode,
        uom: uom,
        target_plant: targetPlant,
        actor: currentActor,
        differentiation_justification: justification
      });
      
      if (res.data.status === 'BLOCKED_DUPLICATE') {
        setSuccessBanner(`Principle P03 Hard Block Enforced: ${res.data.message}. Material request rejected to protect master catalog integrity.`);
      } else {
        setSuccessBanner(`Governed Material Request ${res.data.request.id} initiated. Transferred to 4-View Domain Steward enrichment queue.`);
      }
      fetchRequests();
    } catch (err: any) {
      alert(`Request creation failed: ${err.response?.data?.detail || err.message}`);
    }
  };

  // Domain Steward View Enrichment
  const handleSaveStewardView = async () => {
    if (!selectedRequest) return;
    try {
      let attributes: any = {};
      if (activeStewardView === 'purchasing') {
        attributes = {
          purchasing_group: enrichmentForm.purchasing_group,
          order_unit: enrichmentForm.order_unit,
          planned_lead_time_days: enrichmentForm.planned_lead_time_days,
          default_incoterms: enrichmentForm.default_incoterms
        };
      } else if (activeStewardView === 'plant') {
        attributes = {
          plant: enrichmentForm.plant,
          mrp_type: enrichmentForm.mrp_type,
          lot_sizing_procedure: enrichmentForm.lot_sizing_procedure,
          safety_stock: enrichmentForm.safety_stock,
          reorder_point: enrichmentForm.reorder_point,
          storage_location: enrichmentForm.storage_location
        };
      } else if (activeStewardView === 'quality') {
        attributes = {
          inspection_setup: enrichmentForm.inspection_setup,
          certificate_required: enrichmentForm.certificate_required,
          skip_lot_active: enrichmentForm.skip_lot_active,
          defect_ppm_threshold: enrichmentForm.defect_ppm_threshold
        };
      } else if (activeStewardView === 'accounting') {
        attributes = {
          valuation_class: enrichmentForm.valuation_class,
          price_control: enrichmentForm.price_control,
          standard_valuation_inr: enrichmentForm.standard_valuation_inr
        };
      }

      const res = await axios.put(`${BACKEND_URL}/requests/${selectedRequest.id}/views/${activeStewardView}`, {
        view_name: activeStewardView,
        actor: currentActor,
        attributes: attributes
      });

      if (res.data.status === 'success') {
        setSuccessBanner(`Successfully saved ${activeStewardView.toUpperCase()} domain view for request ${selectedRequest.id}.`);
        selectRequestForAudit(selectedRequest);
        fetchRequests();
      }
    } catch (err: any) {
      alert(`Failed saving view: ${err.response?.data?.detail || err.message}`);
    }
  };

  // Final Domain Steward Approval & SAP S/4HANA Sync (SOD-06 Guarded)
  const handleFinalStewardApproval = async () => {
    if (!selectedRequest) return;
    setSodModalViolation(null);
    setErpSyncNotice(null);

    try {
      const res = await axios.post(`${BACKEND_URL}/requests/${selectedRequest.id}/steward-approve`, {
        actor: currentActor,
        steward_notes: `Approved standard aerospace material master by ${currentActor}`
      });

      if (res.data.status === 'success') {
        setSuccessBanner(`Approved Request ${selectedRequest.id}! Golden Master record ${res.data.golden_record.material_id} created.`);
        setErpSyncNotice(res.data.erp_sync);
        fetchRequests();
        fetchCatalog();
      }
    } catch (err: any) {
      if (err.response?.status === 403 && err.response?.data?.detail?.error === 'SEGREGATION_OF_DUTIES_VIOLATION') {
        setSodModalViolation(err.response.data.detail);
      } else {
        alert(`Approval error: ${err.response?.data?.detail || err.message}`);
      }
    }
  };

  return (
    <div className="min-h-screen bg-[#070B14] text-slate-100 flex flex-col">
      {/* Top Header Bar */}
      <div className="border-b border-slate-800 bg-[#090F1E]/90 backdrop-blur-md px-6 py-4 sticky top-0 z-30">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-tr from-cyan-600 via-indigo-600 to-emerald-500 p-0.5 shadow-lg shadow-cyan-900/40">
              <div className="w-full h-full bg-[#070B14] rounded-[10px] flex items-center justify-center">
                <ShieldCheck className="w-6 h-6 text-cyan-400" />
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                  Material Master Governance & Fuzzy Duplicate Shield Studio
                </h1>
                <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-cyan-950 border border-cyan-800/80 text-cyan-300">
                  MDM-01..04
                </span>
                <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-emerald-950 border border-emerald-800/80 text-emerald-300 flex items-center gap-1">
                  <Bot className="w-3 h-3" /> AGT-MDM-03 (L4)
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Principle P03 (Reuse Before Create) • 92% Hard Duplicate Block • 4-View Domain Steward Segregation • SOD-06 Enforced
              </p>
            </div>
          </div>

          {/* Actor Persona Switcher & Live Tabs */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 bg-slate-900/80 px-3 py-1.5 rounded-lg border border-slate-800 text-xs">
              <UserCheck className="w-4 h-4 text-cyan-400" />
              <span className="text-slate-400">Actor Persona:</span>
              <select
                value={currentActor}
                onChange={(e) => setCurrentActor(e.target.value)}
                className="bg-transparent text-cyan-300 font-medium focus:outline-none cursor-pointer"
              >
                <option value="u:planner.hosur" className="bg-slate-900 text-white">u:planner.hosur (Requester)</option>
                <option value="u:steward.purchasing" className="bg-slate-900 text-white">u:steward.purchasing (Purchasing Steward)</option>
                <option value="u:steward.plant" className="bg-slate-900 text-white">u:steward.plant (Plant / MRP Steward)</option>
                <option value="u:steward.quality" className="bg-slate-900 text-white">u:steward.quality (Quality Steward)</option>
                <option value="u:steward.finance" className="bg-slate-900 text-white">u:steward.finance (Accounting Steward)</option>
                <option value="u:steward.lead.materials" className="bg-slate-900 text-white">u:steward.lead.materials (Independent Lead Steward)</option>
              </select>
            </div>

            <div className="flex bg-slate-900/90 p-1 rounded-lg border border-slate-800">
              <button
                onClick={() => setActiveTab('SHIELD')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                  activeTab === 'SHIELD'
                    ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Compass className="w-3.5 h-3.5" />
                Duplicate Shield Workbench
              </button>
              <button
                onClick={() => setActiveTab('STEWARDS')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                  activeTab === 'STEWARDS'
                    ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Layers className="w-3.5 h-3.5" />
                4-View Steward Console
              </button>
              <button
                onClick={() => setActiveTab('CATALOG')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                  activeTab === 'CATALOG'
                    ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Database className="w-3.5 h-3.5" />
                Standard Golden Catalog
              </button>
            </div>
          </div>
        </div>

        {/* Global KPI Metrics Strip */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-4">
          <div className="bg-[#0B1324] border border-slate-800/80 rounded-lg p-3">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Total Governed Requests</div>
            <div className="text-xl font-bold text-white mt-1">{metrics.total_requests}</div>
            <div className="text-[10px] text-cyan-400 mt-0.5">Audited across plants</div>
          </div>
          <div className="bg-[#0B1324] border border-slate-800/80 rounded-lg p-3">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Duplicate Blocks (P03)</div>
            <div className="text-xl font-bold text-rose-400 mt-1">{metrics.blocked_duplicates}</div>
            <div className="text-[10px] text-rose-400/80 mt-0.5">Prevented catalog pollution</div>
          </div>
          <div className="bg-[#0B1324] border border-slate-800/80 rounded-lg p-3">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Pending Steward Review</div>
            <div className="text-xl font-bold text-amber-400 mt-1">{metrics.pending_stewards}</div>
            <div className="text-[10px] text-amber-400/80 mt-0.5">Under 4-view enrichment</div>
          </div>
          <div className="bg-[#0B1324] border border-slate-800/80 rounded-lg p-3">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Golden Master Catalog</div>
            <div className="text-xl font-bold text-emerald-400 mt-1">{catalog.length} Items</div>
            <div className="text-[10px] text-emerald-400/80 mt-0.5">Synced with SAP S/4HANA</div>
          </div>
          <div className="bg-[#0B1324] border border-slate-800/80 rounded-lg p-3">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Hard Block Threshold</div>
            <div className="text-xl font-bold text-cyan-400 mt-1">≥ 92.0%</div>
            <div className="text-[10px] text-slate-400 mt-0.5">Principle P03 Cutoff</div>
          </div>
        </div>
      </div>

      {/* Success Notification Banner */}
      {successBanner && (
        <div className="bg-emerald-950/80 border-b border-emerald-800 text-emerald-200 px-6 py-2.5 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>{successBanner}</span>
          </div>
          <button onClick={() => setSuccessBanner(null)} className="text-emerald-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Main Workspace Body */}
      <div className="flex-1 p-6 max-w-7xl mx-auto w-full">
        {activeTab === 'SHIELD' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left 7 Columns: Interactive Duplicate Shield & Part Submission */}
            <div className="lg:col-span-7 space-y-6">
              {/* Presets Strip */}
              <div className="bg-[#0B1324] border border-slate-800 rounded-xl p-4">
                <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-cyan-400" />
                  Try Enterprise Test Presets:
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {PRESET_SCENARIOS.map((p, idx) => (
                    <button
                      key={idx}
                      onClick={() => handlePresetSelect(p)}
                      className="text-left p-2.5 rounded-lg bg-slate-900/70 hover:bg-slate-800/80 border border-slate-800 hover:border-cyan-500/50 transition-all text-xs"
                    >
                      <div className="font-semibold text-cyan-300 flex items-center justify-between">
                        <span>{p.label}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          p.expected.includes('BLOCK') ? 'bg-rose-950 text-rose-300' :
                          p.expected.includes('JUSTIFICATION') ? 'bg-amber-950 text-amber-300' : 'bg-emerald-950 text-emerald-300'
                        }`}>
                          {p.expected}
                        </span>
                      </div>
                      <div className="text-slate-400 text-[11px] truncate mt-1">{p.description}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Real-time Material Spec Form */}
              <div className="bg-[#0B1324] border border-slate-800 rounded-xl p-5 shadow-xl">
                <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                  <FileText className="w-4 h-4 text-cyan-400" />
                  Candidate Material Master Specification
                </h3>

                <div className="space-y-4">
                  <div>
                    <label className="text-xs font-semibold text-slate-300 block mb-1">
                      Proposed Material Description (Evaluated in Real-Time):
                    </label>
                    <textarea
                      value={proposedDesc}
                      onChange={(e) => {
                        setProposedDesc(e.target.value);
                        runShieldAnalysis(e.target.value, selectedCategory);
                      }}
                      rows={2}
                      className="w-full bg-[#070B14] border border-slate-700 rounded-lg p-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                      placeholder="e.g. DC-330 Die-Cast Aluminium Housing (Anodized Finish)..."
                    />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs font-semibold text-slate-300 block mb-1">Category:</label>
                      <select
                        value={selectedCategory}
                        onChange={(e) => {
                          setSelectedCategory(e.target.value);
                          runShieldAnalysis(proposedDesc, e.target.value);
                        }}
                        className="w-full bg-[#070B14] border border-slate-700 rounded-lg p-2.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                      >
                        <option value="Castings & Forgings">Castings & Forgings</option>
                        <option value="Electrical & Motor Components">Electrical & Motor Components</option>
                        <option value="Fasteners & Hardware">Fasteners & Hardware</option>
                        <option value="Thermal Systems">Thermal Systems</option>
                        <option value="Raw Materials">Raw Materials</option>
                      </select>
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-slate-300 block mb-1">Commodity Code (UNSPSC):</label>
                      <input
                        type="text"
                        value={commodityCode}
                        onChange={(e) => setCommodityCode(e.target.value)}
                        className="w-full bg-[#070B14] border border-slate-700 rounded-lg p-2.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-slate-300 block mb-1">Base Unit of Measure (UoM):</label>
                      <input
                        type="text"
                        value={uom}
                        onChange={(e) => setUom(e.target.value)}
                        className="w-full bg-[#070B14] border border-slate-700 rounded-lg p-2.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-slate-300 block mb-1">Target Plant Extension:</label>
                      <input
                        type="text"
                        value={targetPlant}
                        onChange={(e) => setTargetPlant(e.target.value)}
                        className="w-full bg-[#070B14] border border-slate-700 rounded-lg p-2.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                      />
                    </div>
                  </div>

                  {analysis && analysis.best_score >= 0.70 && analysis.best_score < 0.92 && (
                    <div className="bg-amber-950/40 border border-amber-800/80 rounded-lg p-3">
                      <label className="text-xs font-semibold text-amber-300 block mb-1 flex items-center gap-1.5">
                        <AlertTriangle className="w-4 h-4 text-amber-400" />
                        Mandatory Engineering Differentiation Justification (Required for 70-91% similarity):
                      </label>
                      <textarea
                        value={justification}
                        onChange={(e) => setJustification(e.target.value)}
                        rows={2}
                        className="w-full bg-[#070B14] border border-amber-700 rounded-lg p-2 text-xs text-white placeholder-slate-500 focus:outline-none"
                        placeholder="State why existing standard item cannot be reused (e.g. Higher thermal duty cycle, AS9100 alloy spec)..."
                      />
                    </div>
                  )}

                  <div className="pt-2 flex items-center justify-between">
                    <button
                      onClick={() => runShieldAnalysis(proposedDesc, selectedCategory)}
                      disabled={isAnalyzing}
                      className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 flex items-center gap-1.5 transition-all"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isAnalyzing ? 'animate-spin' : ''}`} />
                      Re-Evaluate Shield
                    </button>

                    <button
                      onClick={handleSubmitMaterialRequest}
                      className={`px-5 py-2 rounded-lg text-xs font-bold transition-all shadow-md flex items-center gap-2 ${
                        analysis?.is_blocked
                          ? 'bg-rose-700/60 hover:bg-rose-600 text-rose-100 border border-rose-500 cursor-not-allowed'
                          : 'bg-gradient-to-r from-cyan-600 to-emerald-600 hover:from-cyan-500 hover:to-emerald-500 text-white'
                      }`}
                    >
                      {analysis?.is_blocked ? (
                        <>
                          <ShieldAlert className="w-4 h-4" />
                          Blocked by Principle P03 (Click to Enforce Hard Block)
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="w-4 h-4" />
                          Initiate Governed Material Creation
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Right 5 Columns: Shield Risk Gauge, Principle P03 Decision & Top Matches */}
            <div className="lg:col-span-5 space-y-6">
              {/* Dynamic Risk Gauge Card */}
              {analysis && (
                <div className={`border rounded-xl p-5 shadow-xl transition-all ${
                  analysis.is_blocked
                    ? 'bg-gradient-to-b from-rose-950/50 to-[#0B1324] border-rose-800/80 shadow-rose-950/30'
                    : analysis.best_score >= 0.70
                    ? 'bg-gradient-to-b from-amber-950/50 to-[#0B1324] border-amber-800/80 shadow-amber-950/30'
                    : 'bg-gradient-to-b from-emerald-950/50 to-[#0B1324] border-emerald-800/80 shadow-emerald-950/30'
                }`}>
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                      <ShieldCheck className="w-4 h-4 text-cyan-400" />
                      Fuzzy Duplicate Shield Gauge
                    </span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                      analysis.is_blocked
                        ? 'bg-rose-950 text-rose-300 border-rose-800'
                        : analysis.best_score >= 0.70
                        ? 'bg-amber-950 text-amber-300 border-amber-800'
                        : 'bg-emerald-950 text-emerald-300 border-emerald-800'
                    }`}>
                      {analysis.governance_band}
                    </span>
                  </div>

                  {/* Similarity Progress Bar */}
                  <div className="space-y-2 my-4">
                    <div className="flex items-baseline justify-between">
                      <span className="text-3xl font-extrabold text-white">
                        {Math.round(analysis.best_score * 100)}%
                      </span>
                      <span className="text-xs text-slate-400">
                        Cutoff Threshold: <strong className="text-cyan-400">{Math.round(analysis.cutoff_threshold * 100)}%</strong>
                      </span>
                    </div>

                    <div className="w-full bg-slate-900 rounded-full h-3 p-0.5 border border-slate-700">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          analysis.is_blocked
                            ? 'bg-gradient-to-r from-amber-500 to-rose-600'
                            : analysis.best_score >= 0.70
                            ? 'bg-gradient-to-r from-cyan-500 to-amber-500'
                            : 'bg-gradient-to-r from-cyan-500 to-emerald-500'
                        }`}
                        style={{ width: `${Math.min(100, Math.round(analysis.best_score * 100))}%` }}
                      />
                    </div>
                  </div>

                  <p className="text-xs text-slate-300 leading-relaxed bg-slate-900/60 p-3 rounded-lg border border-slate-800">
                    {analysis.message}
                  </p>

                  {/* Immediate Adoption Button if Blocked */}
                  {analysis.is_blocked && analysis.matched_material && (
                    <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between">
                      <div className="text-xs text-slate-400">
                        Mandated Standard Item: <strong className="text-cyan-400">{analysis.matched_material.material_id}</strong>
                      </div>
                      <button
                        onClick={() => {
                          setActiveTab('CATALOG');
                          setSuccessBanner(`Selected standard item ${analysis.matched_material?.material_id} for purchase requisition.`);
                        }}
                        className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-xs font-bold text-white shadow flex items-center gap-1.5"
                      >
                        <Check className="w-3.5 h-3.5" />
                        Adopt Existing Master Record
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Agent AGT-MDM-03 Copilot Card */}
              {agentContract && (
                <div className="bg-[#0B1324] border border-cyan-900/60 rounded-xl p-4 shadow-xl relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-32 h-32 bg-cyan-500/5 rounded-full blur-2xl pointer-events-none" />
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-lg bg-cyan-950 border border-cyan-800 flex items-center justify-center">
                        <Bot className="w-4 h-4 text-cyan-400" />
                      </div>
                      <div>
                        <div className="text-xs font-bold text-white">{agentContract.agent_name}</div>
                        <div className="text-[10px] text-cyan-400">{agentContract.agent_id} • {agentContract.autonomy_level}</div>
                      </div>
                    </div>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded bg-cyan-950 border border-cyan-800 text-cyan-300">
                      {Math.round(agentContract.confidence_score * 100)}% Confidence
                    </span>
                  </div>
                  <div className="text-xs text-slate-300 bg-slate-900/80 p-2.5 rounded-lg border border-slate-800 mt-2">
                    <span className="text-cyan-400 font-semibold">Autonomous Recommendation: </span>
                    {agentContract.recommendation}
                  </div>
                </div>
              )}

              {/* Top Matches Comparison */}
              {analysis && analysis.top_matches.length > 0 && (
                <div className="bg-[#0B1324] border border-slate-800 rounded-xl p-4">
                  <div className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-3 flex items-center justify-between">
                    <span>Closest Standard Catalog Matches</span>
                    <span className="text-[10px] text-slate-400">{analysis.top_matches.length} evaluated</span>
                  </div>

                  <div className="space-y-2.5">
                    {analysis.top_matches.map((m, idx) => (
                      <div key={idx} className="p-2.5 rounded-lg bg-slate-900/70 border border-slate-800">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-cyan-400">{m.material_id}</span>
                          <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                            m.similarity_score >= 0.92 ? 'bg-rose-950 text-rose-300' :
                            m.similarity_score >= 0.70 ? 'bg-amber-950 text-amber-300' : 'bg-slate-800 text-slate-300'
                          }`}>
                            {Math.round(m.similarity_score * 100)}% match
                          </span>
                        </div>
                        <div className="text-xs text-white font-medium mt-1">{m.description}</div>
                        <div className="flex flex-wrap items-center gap-1.5 mt-2">
                          {m.model_match && (
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-300">
                              Model Code Matched
                            </span>
                          )}
                          {m.token_overlap.map((tok, ti) => (
                            <span key={ti} className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                              {tok}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 2: 4-View Domain Steward Governance Console */}
        {activeTab === 'STEWARDS' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left 4 Columns: Request Queue */}
            <div className="lg:col-span-4 space-y-3">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Governed Request Queue ({requests.length})
                </h3>
                <button onClick={fetchRequests} className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
                  <RefreshCw className="w-3 h-3" /> Refresh
                </button>
              </div>

              <div className="space-y-2 max-h-[700px] overflow-y-auto pr-1">
                {requests.map((r) => (
                  <div
                    key={r.id}
                    onClick={() => selectRequestForAudit(r)}
                    className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                      selectedRequest?.id === r.id
                        ? 'bg-cyan-950/30 border-cyan-600 shadow-md shadow-cyan-950/40'
                        : 'bg-[#0B1324] border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-white">{r.id}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        r.status === 'APPROVED' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' :
                        r.status === 'REJECTED_DUPLICATE' ? 'bg-rose-950 text-rose-300 border border-rose-800' :
                        'bg-amber-950 text-amber-300 border border-amber-800'
                      }`}>
                        {r.status}
                      </span>
                    </div>

                    <div className="text-xs text-slate-300 font-medium mt-1.5 line-clamp-2">
                      {r.proposed_description}
                    </div>

                    <div className="mt-2.5 pt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
                      <span>Requester: <strong className="text-slate-300">{r.requester}</strong></span>
                      <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-cyan-300 font-mono">
                        {r.views_completed || '4/4'} Views
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right 8 Columns: 4-View Segregated Enrichment & SOD-06 Approval */}
            <div className="lg:col-span-8 space-y-5">
              {selectedRequest ? (
                <div className="bg-[#0B1324] border border-slate-800 rounded-xl p-5 shadow-xl">
                  {/* Request Detail Header */}
                  <div className="flex flex-col md:flex-row md:items-center justify-between pb-4 border-b border-slate-800 gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-base font-bold text-white">{selectedRequest.id}</span>
                        <span className="text-xs text-slate-400">({selectedRequest.target_plant})</span>
                        <span className="text-xs px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-cyan-300">
                          {selectedRequest.category}
                        </span>
                      </div>
                      <div className="text-xs text-slate-300 mt-1 font-medium">{selectedRequest.proposed_description}</div>
                    </div>

                    <div className="text-right">
                      <div className="text-[10px] text-slate-400">Logged Requester:</div>
                      <div className="text-xs font-mono font-bold text-amber-400">{selectedRequest.requester}</div>
                    </div>
                  </div>

                  {/* 4-View Tabs */}
                  <div className="mt-4">
                    <div className="flex border-b border-slate-800 gap-2">
                      {(['purchasing', 'plant', 'quality', 'accounting'] as const).map((v) => {
                        const isEnriched = requestViews && requestViews[`${v}_view`]?.enriched;
                        return (
                          <button
                            key={v}
                            onClick={() => setActiveStewardView(v)}
                            className={`px-4 py-2 text-xs font-semibold transition-all border-b-2 flex items-center gap-1.5 ${
                              activeStewardView === v
                                ? 'border-cyan-500 text-cyan-300'
                                : 'border-transparent text-slate-400 hover:text-slate-200'
                            }`}
                          >
                            <span className="capitalize">{v} View</span>
                            {isEnriched ? (
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                            ) : (
                              <span className="w-2 h-2 rounded-full bg-amber-500" />
                            )}
                          </button>
                        );
                      })}
                    </div>

                    {/* View Attribute Form */}
                    <div className="p-4 bg-slate-900/50 rounded-b-xl border-x border-b border-slate-800 space-y-4">
                      {activeStewardView === 'purchasing' && (
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Purchasing Group</label>
                            <input
                              type="text"
                              value={enrichmentForm.purchasing_group}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, purchasing_group: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Order Unit</label>
                            <input
                              type="text"
                              value={enrichmentForm.order_unit}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, order_unit: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Planned Lead Time (Days)</label>
                            <input
                              type="number"
                              value={enrichmentForm.planned_lead_time_days}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, planned_lead_time_days: parseInt(e.target.value) || 0 })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Default Incoterms</label>
                            <input
                              type="text"
                              value={enrichmentForm.default_incoterms}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, default_incoterms: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                        </div>
                      )}

                      {activeStewardView === 'plant' && (
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Target Plant</label>
                            <input
                              type="text"
                              value={enrichmentForm.plant}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, plant: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">MRP Type</label>
                            <input
                              type="text"
                              value={enrichmentForm.mrp_type}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, mrp_type: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Safety Stock</label>
                            <input
                              type="number"
                              value={enrichmentForm.safety_stock}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, safety_stock: parseInt(e.target.value) || 0 })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Storage Location</label>
                            <input
                              type="text"
                              value={enrichmentForm.storage_location}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, storage_location: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                        </div>
                      )}

                      {activeStewardView === 'quality' && (
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Inspection Setup</label>
                            <input
                              type="text"
                              value={enrichmentForm.inspection_setup}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, inspection_setup: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Required Certificate</label>
                            <input
                              type="text"
                              value={enrichmentForm.certificate_required}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, certificate_required: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Defect PPM Threshold</label>
                            <input
                              type="number"
                              value={enrichmentForm.defect_ppm_threshold}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, defect_ppm_threshold: parseInt(e.target.value) || 0 })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                        </div>
                      )}

                      {activeStewardView === 'accounting' && (
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Valuation Class</label>
                            <input
                              type="text"
                              value={enrichmentForm.valuation_class}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, valuation_class: e.target.value })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                          <div>
                            <label className="text-xs text-slate-400 block mb-1">Standard Valuation (INR)</label>
                            <input
                              type="number"
                              value={enrichmentForm.standard_valuation_inr}
                              onChange={(e) => setEnrichmentForm({ ...enrichmentForm, standard_valuation_inr: parseFloat(e.target.value) || 0 })}
                              className="w-full bg-[#070B14] border border-slate-700 rounded p-2 text-xs text-white"
                            />
                          </div>
                        </div>
                      )}

                      <div className="flex justify-end pt-2">
                        <button
                          onClick={handleSaveStewardView}
                          className="px-4 py-1.5 rounded-lg bg-cyan-700 hover:bg-cyan-600 text-xs font-semibold text-white shadow flex items-center gap-1.5"
                        >
                          <SaveViewIcon className="w-3.5 h-3.5" />
                          Save {activeStewardView.toUpperCase()} View Attributes
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* SOD-06 Sentinel Banner & Final Approval Action */}
                  <div className="mt-5 pt-4 border-t border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-3">
                    <div className="text-xs">
                      <span className="text-slate-400">SoD Rule: </span>
                      <span className="font-semibold text-cyan-300">SOD-06 (Request Material vs Steward Approve)</span>
                      <div className="text-[11px] text-slate-500 mt-0.5">
                        Requester (<span className="text-amber-400 font-mono">{selectedRequest.requester}</span>) cannot self-approve.
                      </div>
                    </div>

                    <button
                      onClick={handleFinalStewardApproval}
                      disabled={selectedRequest.status === 'APPROVED' || selectedRequest.status === 'REJECTED_DUPLICATE'}
                      className={`px-5 py-2.5 rounded-lg text-xs font-bold transition-all shadow-lg flex items-center gap-2 ${
                        selectedRequest.status === 'APPROVED'
                          ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                          : currentActor === selectedRequest.requester
                          ? 'bg-rose-900/60 hover:bg-rose-800 text-rose-200 border border-rose-700'
                          : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white'
                      }`}
                    >
                      {currentActor === selectedRequest.requester ? (
                        <>
                          <ShieldAlert className="w-4 h-4 text-rose-400" />
                          Test SOD-06 Block (Requester Self-Approval)
                        </>
                      ) : (
                        <>
                          <Award className="w-4 h-4" />
                          Domain Steward Approval & Golden Promotion
                        </>
                      )}
                    </button>
                  </div>

                  {/* ERP Outbox Sync Live Badge */}
                  {erpSyncNotice && (
                    <div className="mt-4 p-3 bg-indigo-950/40 border border-indigo-800 rounded-lg text-xs flex items-center justify-between">
                      <div className="flex items-center gap-2 text-indigo-300">
                        <CheckCheck className="w-4 h-4 text-indigo-400" />
                        <span>Posted to SAP S/4HANA via Transactional Outbox (Doc: <strong>{erpSyncNotice.erpDocument}</strong>)</span>
                      </div>
                      <span className="text-[10px] text-slate-400">Idempotent Delivery Guaranteed (P13)</span>
                    </div>
                  )}
                </div>
              ) : (
                <div className="bg-[#0B1324] border border-slate-800 rounded-xl p-12 text-center text-slate-500 text-xs">
                  Select a request from the left queue to view and enrich 4-domain views.
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 3: Standard Golden Catalog */}
        {activeTab === 'CATALOG' && (
          <div className="bg-[#0B1324] border border-slate-800 rounded-xl p-5 shadow-xl space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Database className="w-4 h-4 text-emerald-400" />
                  AlphaHelion Active Standard Materials Catalog (Golden Records)
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Principle P03 Standardized Components • Synchronized with SAP S/4HANA Master Catalog
                </p>
              </div>
              <button onClick={fetchCatalog} className="px-3 py-1.5 rounded-lg bg-slate-800 text-xs text-slate-300 flex items-center gap-1.5 self-start">
                <RefreshCw className="w-3.5 h-3.5" /> Refresh Catalog
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-900/90 text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="py-3 px-4">Material ID</th>
                    <th className="py-3 px-4">Description</th>
                    <th className="py-3 px-4">Category</th>
                    <th className="py-3 px-4">Drawing / Spec</th>
                    <th className="py-3 px-4">UoM</th>
                    <th className="py-3 px-4 text-right">Standard Cost (INR)</th>
                    <th className="py-3 px-4">Plant Extensions</th>
                    <th className="py-3 px-4 text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-medium">
                  {catalog.map((m) => (
                    <tr key={m.material_id} className="hover:bg-slate-900/40 transition-colors">
                      <td className="py-3 px-4 font-mono font-bold text-cyan-400">{m.material_id}</td>
                      <td className="py-3 px-4 text-white font-semibold">{m.description}</td>
                      <td className="py-3 px-4 text-slate-400">{m.category}</td>
                      <td className="py-3 px-4 font-mono text-[11px] text-slate-400">{m.drawing_number || 'SPEC-STD'}</td>
                      <td className="py-3 px-4">{m.uom}</td>
                      <td className="py-3 px-4 text-right font-mono text-emerald-400">
                        ₹{Number(m.standard_price_inr).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </td>
                      <td className="py-3 px-4">
                        <div className="flex flex-wrap gap-1">
                          {(m.plant_extensions || ['P100 Hosur']).map((p, idx) => (
                            <span key={idx} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-300">
                              {p}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-3 px-4 text-center">
                        <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-emerald-950 border border-emerald-800 text-emerald-300">
                          {m.status || 'ACTIVE'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Segregation of Duties (SOD-06) Violation Modal */}
      {sodModalViolation && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0B1324] border border-rose-600 rounded-xl max-w-md w-full p-6 shadow-2xl shadow-rose-950/60 animate-in fade-in zoom-in duration-200">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-rose-950 border border-rose-700 flex items-center justify-center">
                <ShieldAlert className="w-6 h-6 text-rose-400" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                  Command-Time SoD Violation Blocked
                </h3>
                <span className="text-xs font-mono font-bold text-rose-400">
                  Rule ID: {sodModalViolation.rule_id} ({sodModalViolation.risk} Risk)
                </span>
              </div>
            </div>

            <div className="bg-slate-900/90 rounded-lg p-3.5 border border-slate-800 text-xs text-slate-300 leading-relaxed mb-4">
              <p className="font-semibold text-rose-300 mb-1">Audit Policy Breach Detected:</p>
              {sodModalViolation.message}
            </div>

            <div className="space-y-2 text-xs mb-5 bg-slate-900/50 p-3 rounded-lg border border-slate-800">
              <div className="flex justify-between">
                <span className="text-slate-400">Attempted Action:</span>
                <span className="font-mono text-rose-400 font-bold">APPROVE_MATERIAL_STEWARD</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Conflicting Action:</span>
                <span className="font-mono text-amber-400 font-bold">{sodModalViolation.conflicting_action}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Blocked Actor:</span>
                <span className="font-mono text-white">{sodModalViolation.actor}</span>
              </div>
            </div>

            <p className="text-[11px] text-slate-400 mb-4 italic">
              Principle P09 Mandate: Material requester cannot approve their own material as Domain Steward. Switch actor persona to an independent steward (e.g. u:steward.lead.materials) to authorize creation.
            </p>

            <button
              onClick={() => setSodModalViolation(null)}
              className="w-full py-2.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-xs font-bold text-white shadow-lg shadow-rose-900/40 transition-all"
            >
              Acknowledge & Abort Action
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SaveViewIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" {...props}>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  );
}
