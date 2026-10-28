'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { 
  Play, RefreshCw, AlertTriangle, ShieldCheck, TrendingUp, BarChart3, 
  Activity, CheckCircle2, Layers, Cpu, Plane, Ship, CloudRain, Database, 
  Zap, Sliders, Download, Share2, FileText, ChevronRight, ArrowUpRight, 
  ArrowDownRight, Sparkles, Clock, DollarSign, Check, X, Info
} from 'lucide-react';
import Link from 'next/link';

interface ScenarioNode {
  id: string;
  name: string;
  supplier_id: string;
  supplier_name: string;
  location: string;
  tier: number;
  single_source: boolean;
  triangular_lead_time: { min: number; mode: number; max: number };
  base_cost_usd: number;
  cost_std_usd: number;
  machine_failure_prob: number;
  transit_days_base: number;
  logistics_mode: string;
  secondary_twin?: {
    id: string;
    name: string;
    location: string;
    triangular_lead_time: { min: number; mode: number; max: number };
    base_cost_usd: number;
    qualification_status: string;
  };
}

interface Scenario {
  id: string;
  name: string;
  industry: string;
  target_sla_days: number;
  daily_downtime_cost_usd: number;
  base_bom_cost_usd: number;
  description: string;
  node_count: number;
  nodes_summary: { name: string; supplier: string; single_source: boolean }[];
}

interface SimulationKPIs {
  on_time_probability_pct: number;
  line_stop_probability_pct: number;
  mean_lead_time_days: number;
  std_lead_time_days: number;
  median_p50_days: number;
  p75_lead_time_days: number;
  p90_lead_time_days: number;
  p95_lead_time_days: number;
  p99_lead_time_days: number;
  expected_total_project_cost_usd: number;
  expected_line_stop_cost_usd: number;
  value_at_risk_95_usd: number;
  value_at_risk_99_usd: number;
  conditional_var_95_usd: number;
}

interface HistogramBin {
  lead_time_days: number;
  frequency_count: number;
  probability_pct: number;
  cumulative_prob_pct: number;
  is_breached: boolean;
}

interface SensitivityItem {
  component_id: string;
  component_name: string;
  supplier_name: string;
  location: string;
  variance_contribution_pct: number;
  single_source: boolean;
  mean_component_lead_time: number;
  p95_component_lead_time: number;
}

export default function SimulationPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>('SC-AERO-ACTUATOR');
  const [currentScenarioNodes, setCurrentScenarioNodes] = useState<ScenarioNode[]>([]);
  
  // Simulation Parameters
  const [iterations, setIterations] = useState<number>(5000);
  const [targetSlaDays, setTargetSlaDays] = useState<number>(45);
  const [isComputing, setIsComputing] = useState<boolean>(false);
  const [runtimeBenchmark, setRuntimeBenchmark] = useState<number | null>(null);

  // Active Disruption Shocks
  const [activeShocks, setActiveShocks] = useState<string[]>([
    'SHOCK_PORT_CONGESTION', 
    'SHOCK_WEATHER_TYPHOON'
  ]);

  // Active Mitigations (What-If Levers)
  const [dualSourcing, setDualSourcing] = useState<boolean>(false);
  const [bufferStockDays, setBufferStockDays] = useState<number>(0);
  const [expeditedAirFreight, setExpeditedAirFreight] = useState<boolean>(false);
  const [dfmRelaxed, setDfmRelaxed] = useState<boolean>(false);

  // Simulation Results
  const [kpis, setKpis] = useState<SimulationKPIs | null>(null);
  const [histogram, setHistogram] = useState<HistogramBin[]>([]);
  const [sensitivity, setSensitivity] = useState<SensitivityItem[]>([]);
  const [comparisonDelta, setComparisonDelta] = useState<any | null>(null);
  const [baselineKpis, setBaselineKpis] = useState<SimulationKPIs | null>(null);

  // UI Navigation
  const [activeTab, setActiveTab] = useState<'distribution' | 'tornado' | 'comparison' | 'topology' | 'actions'>('distribution');
  const [showCdf, setShowCdf] = useState<boolean>(false);
  const [notification, setNotification] = useState<string | null>(null);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(null), 5000);
  };

  // 1. Fetch available scenarios
  useEffect(() => {
    fetch('http://127.0.0.1:8080/api/v1/simulation/scenarios')
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          setScenarios(data.scenarios);
          if (data.scenarios.length > 0) {
            const current = data.scenarios.find((s: Scenario) => s.id === selectedScenarioId) || data.scenarios[0];
            setTargetSlaDays(current.target_sla_days);
          }
        }
      })
      .catch(err => console.error('Failed to load scenarios:', err));
  }, []);

  // 2. Fetch scenario node details when scenario changes
  useEffect(() => {
    fetch(`http://127.0.0.1:8080/api/v1/simulation/scenario/${selectedScenarioId}`)
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success') {
          setCurrentScenarioNodes(data.scenario.nodes || []);
          setTargetSlaDays(data.scenario.target_sla_days);
        }
      })
      .catch(err => console.error('Failed to load scenario details:', err));
  }, [selectedScenarioId]);

  // 3. Run Monte Carlo Simulation
  const handleRunSimulation = async () => {
    setIsComputing(true);
    try {
      const payload = {
        scenario_id: selectedScenarioId,
        iterations: iterations,
        confidence_level: 0.95,
        target_sla_days: targetSlaDays,
        active_shocks: activeShocks,
        mitigations: {
          dual_sourcing: dualSourcing,
          buffer_stock_days: bufferStockDays,
          expedited_air_freight: expeditedAirFreight,
          dfm_relaxed: dfmRelaxed
        }
      };

      // Run current simulation
      const res = await fetch('http://127.0.0.1:8080/api/v1/simulation/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      if (data.status === 'success') {
        const results = data.results;
        setKpis(results.kpis);
        setHistogram(results.distribution_histogram || []);
        setSensitivity(results.sensitivity_ranking || []);
        setRuntimeBenchmark(results.runtime_ms);
      }

      // Also run comparison against unmitigated baseline
      const compRes = await fetch('http://127.0.0.1:8080/api/v1/simulation/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const compData = await compRes.json();
      if (compData.status === 'success') {
        setComparisonDelta(compData.comparison_delta);
        setBaselineKpis(compData.baseline);
      }

    } catch (err) {
      console.error('Simulation execution failed:', err);
      showToast('⚠️ Simulation engine error. Please ensure backend is running.');
    } finally {
      setIsComputing(false);
    }
  };

  // Run on mount or when scenario changes
  useEffect(() => {
    handleRunSimulation();
  }, [selectedScenarioId]);

  // Toggle Disruption Shock
  const toggleShock = (shockId: string) => {
    setActiveShocks(prev => 
      prev.includes(shockId) ? prev.filter(s => s !== shockId) : [...prev, shockId]
    );
  };

  // Execute direct digital twin mitigation action
  const handleExecuteMitigationAction = async (actionType: string, componentId?: string, supplierTwinId?: string) => {
    setActionInProgress(actionType);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/simulation/apply-action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: selectedScenarioId,
          action_type: actionType,
          component_id: componentId,
          supplier_twin_id: supplierTwinId
        })
      });
      const data = await res.json();
      if (data.status === 'success') {
        showToast(`⚡ ${data.message} (${data.po_reference || data.action_id})`);
        // If dual-sourcing was executed, automatically toggle the dual-sourcing mitigation and re-simulate
        if (actionType === 'DEPLOY_DUAL_SOURCING') {
          setDualSourcing(true);
        } else if (actionType === 'ALLOCATE_BUFFER_STOCK') {
          setBufferStockDays(14);
        } else if (actionType === 'TRIGGER_AIR_FREIGHT') {
          setExpeditedAirFreight(true);
        }
      }
    } catch (err) {
      console.error('Failed to apply mitigation action:', err);
      showToast('Action execution failed. Check console.');
    } finally {
      setActionInProgress(null);
    }
  };

  // Find max frequency for chart scaling
  const maxHistogramFreq = useMemo(() => {
    if (!histogram || histogram.length === 0) return 100;
    return Math.max(...histogram.map(b => b.frequency_count));
  }, [histogram]);

  return (
    <div className="max-w-[1680px] mx-auto pb-16 space-y-6 animate-fade-in text-slate-100">
      
      {/* Toast Notification */}
      {notification && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0F172A] border border-blue-500/50 text-white px-5 py-3.5 rounded-xl shadow-2xl flex items-center gap-3 backdrop-blur-md animate-slide-up">
          <Sparkles className="w-5 h-5 text-blue-400 animate-spin" />
          <span className="text-sm font-semibold">{notification}</span>
          <button onClick={() => setNotification(null)} className="ml-2 text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Header Area with Scenario Switcher & Run Trigger */}
      <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-bl from-blue-600/10 via-purple-600/5 to-transparent rounded-full blur-3xl pointer-events-none" />
        
        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6 relative z-10">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-widest bg-blue-500/10 text-blue-400 border border-blue-500/20">
                Digital Twin Monte Carlo Engine
              </span>
              <span className="flex items-center gap-1.5 text-xs text-emerald-400 font-mono bg-emerald-950/40 px-2 py-0.5 rounded-full border border-emerald-800/40">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> Vectorized NumPy 2.5
              </span>
              {runtimeBenchmark !== null && (
                <span className="text-xs text-slate-400 font-mono">
                  ⏱️ {iterations.toLocaleString()} runs in {runtimeBenchmark}ms
                </span>
              )}
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
              Supply Chain Risk Simulation
              <span className="text-sm px-3 py-1 font-mono font-medium text-slate-400 bg-slate-800/60 rounded-lg border border-slate-700/60">
                VaR 95 / P99
              </span>
            </h1>
            <p className="text-sm text-slate-400 mt-1 max-w-3xl">
              Stochastic lead-time variance, line-stop probability modeling, and automated Digital Twin parallel failover optimization.
            </p>
          </div>

          {/* Action Group */}
          <div className="flex flex-wrap items-center gap-3">
            {/* Scenario Picker */}
            <div className="flex flex-col">
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">Target Assembly</label>
              <select
                value={selectedScenarioId}
                onChange={(e) => setSelectedScenarioId(e.target.value)}
                className="bg-[#132238] border border-slate-700 text-white text-xs font-bold rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm"
              >
                {scenarios.map(s => (
                  <option key={s.id} value={s.id} className="bg-[#0B1528] text-white">
                    {s.name} ({s.industry})
                  </option>
                ))}
              </select>
            </div>

            {/* Run Button */}
            <div className="flex flex-col">
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1 invisible">Action</label>
              <button
                onClick={handleRunSimulation}
                disabled={isComputing}
                className="bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white px-6 py-2.5 rounded-xl text-sm font-bold shadow-lg shadow-blue-600/20 transition-all flex items-center gap-2.5 active:scale-95 disabled:opacity-50"
              >
                {isComputing ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Computing Monte Carlo...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    <span>Run {iterations.toLocaleString()} Iterations</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Dynamic Top KPI Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* KPI 1: On-Time Delivery Probability */}
        <div className="bg-[#0F1C31] border border-slate-800 rounded-2xl p-5 shadow-lg relative overflow-hidden flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">On-Time Probability</span>
              <CheckCircle2 className={`w-4 h-4 ${kpis && kpis.on_time_probability_pct > 75 ? 'text-emerald-400' : 'text-amber-400'}`} />
            </div>
            <div className="text-3xl font-black text-white tracking-tight">
              {kpis ? `${kpis.on_time_probability_pct}%` : '---'}
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
            <span className="text-slate-400">Target SLA:</span>
            <span className="font-mono font-bold text-blue-400">{targetSlaDays} Days</span>
          </div>
        </div>

        {/* KPI 2: Line-Stop Risk */}
        <div className={`border rounded-2xl p-5 shadow-lg relative overflow-hidden flex flex-col justify-between ${
          kpis && kpis.line_stop_probability_pct > 25 
            ? 'bg-rose-950/20 border-rose-800/50' 
            : 'bg-[#0F1C31] border-slate-800'
        }`}>
          <div>
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Line-Stop Risk</span>
              <AlertTriangle className={`w-4 h-4 ${kpis && kpis.line_stop_probability_pct > 25 ? 'text-rose-400 animate-pulse' : 'text-slate-500'}`} />
            </div>
            <div className="text-3xl font-black text-rose-400 tracking-tight">
              {kpis ? `${kpis.line_stop_probability_pct}%` : '---'}
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
            <span className="text-slate-400">Baseline Delta:</span>
            <span className="font-bold text-emerald-400">
              {comparisonDelta ? `-${comparisonDelta.line_stop_risk_reduction_pct}% Risk` : '0%'}
            </span>
          </div>
        </div>

        {/* KPI 3: P95 Lead Time */}
        <div className="bg-[#0F1C31] border border-slate-800 rounded-2xl p-5 shadow-lg relative overflow-hidden flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">P95 Lead Time (Tail)</span>
              <Clock className="w-4 h-4 text-purple-400" />
            </div>
            <div className="text-3xl font-black text-white tracking-tight">
              {kpis ? `${kpis.p95_lead_time_days}d` : '---'}
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
            <span className="text-slate-400">Median (P50):</span>
            <span className="font-mono font-bold text-slate-300">{kpis ? `${kpis.median_p50_days}d` : '---'}</span>
          </div>
        </div>

        {/* KPI 4: Value at Risk (VaR 95%) */}
        <div className="bg-[#0F1C31] border border-slate-800 rounded-2xl p-5 shadow-lg relative overflow-hidden flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Value-at-Risk (95%)</span>
              <DollarSign className="w-4 h-4 text-amber-400" />
            </div>
            <div className="text-3xl font-black text-amber-400 tracking-tight">
              {kpis ? `$${(kpis.value_at_risk_95_usd / 1000).toFixed(0)}k` : '---'}
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
            <span className="text-slate-400">Expected Loss:</span>
            <span className="font-mono font-bold text-slate-300">
              {kpis ? `$${(kpis.expected_line_stop_cost_usd / 1000).toFixed(0)}k` : '---'}
            </span>
          </div>
        </div>

        {/* KPI 5: Avoided Downtime Loss */}
        <div className="bg-gradient-to-br from-[#0F1C31] to-emerald-950/30 border border-emerald-500/30 rounded-2xl p-5 shadow-lg relative overflow-hidden flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-400">Avoided Loss (ROI)</span>
              <TrendingUp className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="text-3xl font-black text-emerald-400 tracking-tight">
              {comparisonDelta ? `$${(comparisonDelta.avoided_line_stop_loss_usd / 1000).toFixed(0)}k` : '$0'}
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-emerald-800/40 flex items-center justify-between text-xs">
            <span className="text-slate-400">Net Mitigation ROI:</span>
            <span className="font-mono font-bold text-emerald-300">
              {comparisonDelta ? `+${comparisonDelta.mitigation_roi_pct}%` : '---'}
            </span>
          </div>
        </div>
      </div>

      {/* Simulation Controls: Disruption Shocks & Autonomous Mitigations */}
      <div className="bg-[#0D1829] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-slate-800/80 pb-4 gap-4">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Sliders className="w-5 h-5 text-blue-400" />
              Stochastic Parameters & What-If Mitigation Levers
            </h2>
            <p className="text-xs text-slate-400">
              Inject geopolitical/climatic shocks and deploy Digital Twin mitigation levers to re-run 5,000 parallel paths.
            </p>
          </div>
          
          {/* Iteration & SLA Sliders */}
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold text-slate-300">Iterations:</span>
              <input 
                type="range" 
                min="1000" 
                max="10000" 
                step="1000"
                value={iterations}
                onChange={(e) => setIterations(Number(e.target.value))}
                className="w-28 accent-blue-500 cursor-pointer"
              />
              <span className="font-mono text-xs font-bold text-blue-400">{iterations.toLocaleString()}</span>
            </div>

            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold text-slate-300">Target SLA:</span>
              <input 
                type="number" 
                min="20" 
                max="100" 
                value={targetSlaDays}
                onChange={(e) => setTargetSlaDays(Number(e.target.value))}
                className="w-16 bg-[#162740] border border-slate-700 text-white rounded-lg px-2.5 py-1 text-xs font-mono font-bold text-center"
              />
              <span className="text-xs text-slate-400">days</span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          
          {/* Section A: Injected Systemic Shocks */}
          <div className="space-y-3">
            <div className="text-xs font-bold uppercase tracking-wider text-rose-400 flex items-center gap-1.5">
              <AlertTriangle className="w-4 h-4" />
              Active Systemic Disruption Shocks
            </div>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Shock 1: Port Congestion */}
              <button
                onClick={() => toggleShock('SHOCK_PORT_CONGESTION')}
                className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 ${
                  activeShocks.includes('SHOCK_PORT_CONGESTION')
                    ? 'bg-rose-950/30 border-rose-500/60 text-white shadow-lg shadow-rose-950/20'
                    : 'bg-[#122036] border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <Ship className={`w-5 h-5 shrink-0 mt-0.5 ${activeShocks.includes('SHOCK_PORT_CONGESTION') ? 'text-rose-400' : 'text-slate-500'}`} />
                <div>
                  <div className="text-xs font-bold">Port Hub Strike / Congestion</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">+14-24d on ocean transit</div>
                </div>
              </button>

              {/* Shock 2: Typhoon */}
              <button
                onClick={() => toggleShock('SHOCK_WEATHER_TYPHOON')}
                className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 ${
                  activeShocks.includes('SHOCK_WEATHER_TYPHOON')
                    ? 'bg-rose-950/30 border-rose-500/60 text-white shadow-lg shadow-rose-950/20'
                    : 'bg-[#122036] border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <CloudRain className={`w-5 h-5 shrink-0 mt-0.5 ${activeShocks.includes('SHOCK_WEATHER_TYPHOON') ? 'text-rose-400' : 'text-slate-500'}`} />
                <div>
                  <div className="text-xs font-bold">Category 4 Typhoon Warning</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">+6-16d East-Asian corridors</div>
                </div>
              </button>

              {/* Shock 3: Raw Material Spike */}
              <button
                onClick={() => toggleShock('SHOCK_RAW_MATERIAL_SPIKE')}
                className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 ${
                  activeShocks.includes('SHOCK_RAW_MATERIAL_SPIKE')
                    ? 'bg-rose-950/30 border-rose-500/60 text-white shadow-lg shadow-rose-950/20'
                    : 'bg-[#122036] border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <TrendingUp className={`w-5 h-5 shrink-0 mt-0.5 ${activeShocks.includes('SHOCK_RAW_MATERIAL_SPIKE') ? 'text-rose-400' : 'text-slate-500'}`} />
                <div>
                  <div className="text-xs font-bold">Raw Material Spot Spike</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">+35% cost volatility</div>
                </div>
              </button>

              {/* Shock 4: Machine Outage */}
              <button
                onClick={() => toggleShock('SHOCK_MACHINE_HALT')}
                className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 ${
                  activeShocks.includes('SHOCK_MACHINE_HALT')
                    ? 'bg-rose-950/30 border-rose-500/60 text-white shadow-lg shadow-rose-950/20'
                    : 'bg-[#122036] border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <Cpu className={`w-5 h-5 shrink-0 mt-0.5 ${activeShocks.includes('SHOCK_MACHINE_HALT') ? 'text-rose-400' : 'text-slate-500'}`} />
                <div>
                  <div className="text-xs font-bold">Tier-1 Unplanned CNC Outage</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">18% machine halt probability</div>
                </div>
              </button>
            </div>
          </div>

          {/* Section B: Autonomous Mitigation Levers */}
          <div className="space-y-3">
            <div className="text-xs font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4" />
              Autonomous Digital Twin Mitigations (What-If Levers)
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Lever 1: Dual Sourcing */}
              <button
                onClick={() => setDualSourcing(!dualSourcing)}
                className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 ${
                  dualSourcing
                    ? 'bg-emerald-950/30 border-emerald-500/60 text-white shadow-lg shadow-emerald-950/20'
                    : 'bg-[#122036] border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <Zap className={`w-5 h-5 shrink-0 mt-0.5 ${dualSourcing ? 'text-emerald-400' : 'text-slate-500'}`} />
                <div>
                  <div className="text-xs font-bold">Dual-Source Twin Failover</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">Parallel split to pre-qualified twins</div>
                </div>
              </button>

              {/* Lever 2: Buffer Stock */}
              <div className={`p-3.5 rounded-xl border transition-all ${
                bufferStockDays > 0
                  ? 'bg-emerald-950/30 border-emerald-500/60 text-white'
                  : 'bg-[#122036] border-slate-800 text-slate-400'
              }`}>
                <div className="flex justify-between items-center mb-1">
                  <div className="text-xs font-bold flex items-center gap-1.5">
                    <Database className="w-4 h-4 text-emerald-400" />
                    Safety Buffer Stock
                  </div>
                  <span className="font-mono text-xs font-bold text-emerald-400">+{bufferStockDays} Days</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="20"
                  step="5"
                  value={bufferStockDays}
                  onChange={(e) => setBufferStockDays(Number(e.target.value))}
                  className="w-full accent-emerald-500 cursor-pointer mt-1"
                />
              </div>

              {/* Lever 3: Air Freight Courier */}
              <button
                onClick={() => setExpeditedAirFreight(!expeditedAirFreight)}
                className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 ${
                  expeditedAirFreight
                    ? 'bg-emerald-950/30 border-emerald-500/60 text-white shadow-lg shadow-emerald-950/20'
                    : 'bg-[#122036] border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <Plane className={`w-5 h-5 shrink-0 mt-0.5 ${expeditedAirFreight ? 'text-emerald-400' : 'text-slate-500'}`} />
                <div>
                  <div className="text-xs font-bold">Expedited Air Freight Bypass</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">Cuts international transit to 3.5d</div>
                </div>
              </button>

              {/* Lever 4: DFSC CAD DFM Relaxation */}
              <button
                onClick={() => setDfmRelaxed(!dfmRelaxed)}
                className={`p-3.5 rounded-xl border text-left transition-all flex items-start gap-3 ${
                  dfmRelaxed
                    ? 'bg-emerald-950/30 border-emerald-500/60 text-white shadow-lg shadow-emerald-950/20'
                    : 'bg-[#122036] border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <Sparkles className={`w-5 h-5 shrink-0 mt-0.5 ${dfmRelaxed ? 'text-emerald-400' : 'text-slate-500'}`} />
                <div>
                  <div className="text-xs font-bold">Generative DFM Tolerances</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">20% cycle speedup via DFSC</div>
                </div>
              </button>
            </div>
          </div>

        </div>
      </div>

      {/* Tabs Navigation */}
      <div className="flex border-b border-slate-800 gap-2">
        {[
          { id: 'distribution', label: '📊 Stochastic Bell Curve & Histogram' },
          { id: 'tornado', label: '🌪️ Tornado Bottleneck Sensitivity' },
          { id: 'comparison', label: '⚖️ What-If Scenario Matrix & ROI' },
          { id: 'topology', label: '🕸️ Multi-Tier Digital Twin BOM' },
          { id: 'actions', label: '⚡ Executive Mitigation Actions' }
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-5 py-3 text-xs font-extrabold transition-all border-b-2 flex items-center gap-2 ${
              activeTab === tab.id
                ? 'border-blue-500 text-blue-400 bg-blue-500/10 rounded-t-lg'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* TAB 1: Stochastic Bell Curve & Histogram */}
      {activeTab === 'distribution' && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          
          {/* Main SVG Histogram Chart */}
          <div className="xl:col-span-2 bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
            <div className="flex justify-between items-center mb-6">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-blue-400" />
                  Stochastic Lead-Time Distribution (20-Bin Density)
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Green bins indicate on-time assembly completion; red bins breach SLA deadline ({targetSlaDays} days).
                </p>
              </div>

              <div className="flex items-center gap-4">
                <button
                  onClick={() => setShowCdf(!showCdf)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
                    showCdf 
                      ? 'bg-blue-600 text-white border-blue-500' 
                      : 'bg-slate-800 text-slate-400 border-slate-700'
                  }`}
                >
                  {showCdf ? '✓ Showing CDF Curve' : '+ Overlay CDF Curve'}
                </button>
              </div>
            </div>

            {/* SVG Chart */}
            <div className="relative w-full h-80 pt-6 pb-8 border-b border-l border-slate-800">
              
              {/* Dotted target SLA line */}
              {histogram.length > 0 && (
                <div 
                  className="absolute top-0 bottom-0 border-r-2 border-dashed border-amber-400 z-20 pointer-events-none"
                  style={{
                    left: `${Math.min(100, Math.max(0, ((targetSlaDays - histogram[0].lead_time_days) / (histogram[histogram.length - 1].lead_time_days - histogram[0].lead_time_days)) * 100))}%`
                  }}
                >
                  <div className="absolute top-2 -right-16 bg-amber-500/20 border border-amber-500 text-amber-300 text-[10px] font-mono font-bold px-2 py-0.5 rounded shadow">
                    Target SLA: {targetSlaDays}d
                  </div>
                </div>
              )}

              {/* Dotted P95 line */}
              {kpis && histogram.length > 0 && (
                <div 
                  className="absolute top-0 bottom-0 border-r-2 border-dashed border-purple-400 z-20 pointer-events-none opacity-80"
                  style={{
                    left: `${Math.min(100, Math.max(0, ((kpis.p95_lead_time_days - histogram[0].lead_time_days) / (histogram[histogram.length - 1].lead_time_days - histogram[0].lead_time_days)) * 100))}%`
                  }}
                >
                  <div className="absolute top-10 -right-12 bg-purple-500/20 border border-purple-500 text-purple-300 text-[10px] font-mono font-bold px-1.5 py-0.5 rounded shadow">
                    P95: {kpis.p95_lead_time_days}d
                  </div>
                </div>
              )}

              {/* Histogram Bars */}
              <div className="absolute inset-0 flex items-end justify-between px-2 gap-1.5 z-10">
                {histogram.map((bin, i) => {
                  const heightPct = (bin.frequency_count / maxHistogramFreq) * 100;
                  return (
                    <div 
                      key={i} 
                      className="flex-1 flex flex-col items-center justify-end h-full group relative"
                    >
                      {/* Bar with Tooltip */}
                      <div 
                        className={`w-full rounded-t-sm transition-all duration-300 cursor-pointer ${
                          bin.is_breached 
                            ? 'bg-gradient-to-t from-rose-600 to-rose-400 hover:brightness-125' 
                            : 'bg-gradient-to-t from-emerald-600 to-emerald-400 hover:brightness-125'
                        }`}
                        style={{ height: `${Math.max(4, heightPct)}%` }}
                      />

                      {/* Tooltip on hover */}
                      <div className="absolute bottom-full mb-2 hidden group-hover:flex flex-col items-center bg-[#070D19] border border-slate-700 text-white text-[11px] font-mono px-3 py-2 rounded-lg shadow-2xl z-30 pointer-events-none whitespace-nowrap">
                        <span className="font-bold">{bin.lead_time_days} Days Lead Time</span>
                        <span className="text-slate-400">Freq: {bin.frequency_count} runs ({bin.probability_pct}%)</span>
                        <span className="text-blue-400">Cumulative: {bin.cumulative_prob_pct}%</span>
                        {bin.is_breached && <span className="text-rose-400 font-bold mt-1">⚠️ Breaches SLA</span>}
                      </div>

                      {/* X Axis Tick */}
                      {i % 4 === 0 && (
                        <span className="absolute -bottom-6 text-[10px] font-mono text-slate-500">
                          {bin.lead_time_days}d
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* CDF Curve Overlay */}
              {showCdf && histogram.length > 0 && (
                <svg className="absolute inset-0 w-full h-full pointer-events-none overflow-visible z-25" viewBox="0 0 100 100" preserveAspectRatio="none">
                  <polyline
                    points={histogram.map((bin, idx) => {
                      const x = (idx / (histogram.length - 1)) * 100;
                      const y = 100 - bin.cumulative_prob_pct;
                      return `${x},${y}`;
                    }).join(' ')}
                    fill="none"
                    stroke="#38BDF8"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                  />
                </svg>
              )}

            </div>

            {/* Chart Legend */}
            <div className="flex flex-wrap items-center justify-between text-xs text-slate-400 pt-4 mt-2">
              <div className="flex items-center gap-6">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-sm bg-emerald-500" />
                  <span>On-Time Iterations (Within SLA)</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-sm bg-rose-500" />
                  <span>Line-Stop Breaches (Overdue)</span>
                </div>
                {showCdf && (
                  <div className="flex items-center gap-2">
                    <div className="w-4 h-0.5 bg-sky-400" />
                    <span className="text-sky-300">Cumulative CDF Probability</span>
                  </div>
                )}
              </div>
              <div className="font-mono text-slate-500">
                Confidence: 95.0% | Normal-Triangular Kernel
              </div>
            </div>

          </div>

          {/* Statistical Percentiles Breakdown Card */}
          <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2 mb-4">
                <Activity className="w-5 h-5 text-purple-400" />
                Percentile Metrics
              </h3>

              <div className="space-y-3 font-mono text-xs">
                <div className="p-3 bg-[#111F36] rounded-xl flex justify-between items-center border border-slate-800">
                  <span className="text-slate-400">Mean Lead Time (μ):</span>
                  <span className="font-bold text-white text-sm">{kpis?.mean_lead_time_days || '---'} Days</span>
                </div>

                <div className="p-3 bg-[#111F36] rounded-xl flex justify-between items-center border border-slate-800">
                  <span className="text-slate-400">Std Deviation (σ):</span>
                  <span className="font-bold text-white text-sm">{kpis?.std_lead_time_days || '---'} Days</span>
                </div>

                <div className="p-3 bg-[#111F36] rounded-xl flex justify-between items-center border border-slate-800">
                  <span className="text-slate-400">Median (P50):</span>
                  <span className="font-bold text-blue-400 text-sm">{kpis?.median_p50_days || '---'} Days</span>
                </div>

                <div className="p-3 bg-[#111F36] rounded-xl flex justify-between items-center border border-slate-800">
                  <span className="text-slate-400">P75 Lead Time:</span>
                  <span className="font-bold text-slate-300 text-sm">{kpis?.p75_lead_time_days || '---'} Days</span>
                </div>

                <div className="p-3 bg-[#111F36] rounded-xl flex justify-between items-center border border-slate-800">
                  <span className="text-slate-400">P90 Lead Time:</span>
                  <span className="font-bold text-amber-400 text-sm">{kpis?.p90_lead_time_days || '---'} Days</span>
                </div>

                <div className="p-3 bg-purple-950/20 border border-purple-500/30 rounded-xl flex justify-between items-center">
                  <span className="text-purple-300 font-bold">P95 Worst-Case (Tail):</span>
                  <span className="font-bold text-purple-400 text-sm">{kpis?.p95_lead_time_days || '---'} Days</span>
                </div>

                <div className="p-3 bg-rose-950/20 border border-rose-500/30 rounded-xl flex justify-between items-center">
                  <span className="text-rose-300 font-bold">P99 Black-Swan Tail:</span>
                  <span className="font-bold text-rose-400 text-sm">{kpis?.p99_lead_time_days || '---'} Days</span>
                </div>
              </div>
            </div>

            <div className="pt-4 border-t border-slate-800 text-[11px] text-slate-400 leading-relaxed">
              💡 <b>Decision Support:</b> Buffer stock of <b className="text-white">10 days</b> shifts the P95 lead time from <b className="text-rose-400">{baselineKpis?.p95_lead_time_days || 85}d</b> down to <b className="text-emerald-400">{kpis?.p95_lead_time_days || 45}d</b>, safely satisfying SLA constraints.
            </div>
          </div>

        </div>
      )}

      {/* TAB 2: Tornado Bottleneck Sensitivity */}
      {activeTab === 'tornado' && (
        <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-blue-400" />
              Tornado Chart: Lead-Time Variance Contribution by Node
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Ranks each component node by its statistical variance contribution (Spearman rank correlation $R^2$) to total project delays.
            </p>
          </div>

          <div className="space-y-4">
            {sensitivity.map((item, idx) => (
              <div 
                key={item.component_id}
                className="bg-[#101C31] border border-slate-800 rounded-xl p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
              >
                <div className="w-full md:w-1/3">
                  <div className="flex items-center gap-2">
                    <span className="w-5 h-5 rounded-full bg-blue-600/20 text-blue-400 text-xs font-mono font-bold flex items-center justify-center">
                      #{idx + 1}
                    </span>
                    <span className="text-sm font-bold text-white">{item.component_name}</span>
                    {item.single_source && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                        Single Sourced
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-400 mt-1 flex items-center gap-2">
                    <span>{item.supplier_name}</span>
                    <span>•</span>
                    <span>{item.location}</span>
                  </div>
                </div>

                {/* Horizontal Progress Bar */}
                <div className="w-full md:w-1/3">
                  <div className="flex justify-between text-xs font-mono mb-1">
                    <span className="text-slate-400">Variance Contribution</span>
                    <span className="font-bold text-blue-400">{item.variance_contribution_pct}%</span>
                  </div>
                  <div className="w-full h-3 bg-slate-800 rounded-full overflow-hidden">
                    <div 
                      className={`h-full rounded-full transition-all duration-500 ${
                        idx === 0 
                          ? 'bg-gradient-to-r from-rose-500 to-amber-500' 
                          : 'bg-gradient-to-r from-blue-500 to-indigo-500'
                      }`}
                      style={{ width: `${Math.max(4, item.variance_contribution_pct)}%` }}
                    />
                  </div>
                </div>

                {/* Metrics & Failover Status */}
                <div className="w-full md:w-1/4 flex items-center justify-between font-mono text-xs text-right">
                  <div>
                    <div className="text-slate-400 text-[10px]">Mean / P95 Lead Time</div>
                    <div className="font-bold text-slate-200">{item.mean_component_lead_time}d / {item.p95_component_lead_time}d</div>
                  </div>
                  <button 
                    onClick={() => handleExecuteMitigationAction('DEPLOY_DUAL_SOURCING', item.component_id)}
                    disabled={actionInProgress !== null}
                    className="px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/30 rounded-lg text-xs font-bold transition-colors"
                  >
                    Failover Twin
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 3: What-If Scenario Matrix & ROI */}
      {activeTab === 'comparison' && comparisonDelta && baselineKpis && kpis && (
        <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-emerald-400" />
              Side-by-Side Scenario Delta & Financial ROI
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Direct mathematical contrast between unmitigated baseline and the active Digital Twin configuration.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            
            {/* Column 1: Baseline */}
            <div className="bg-[#101C31] border border-slate-800 rounded-2xl p-5 space-y-4">
              <div className="text-xs font-bold uppercase tracking-wider text-slate-400 border-b border-slate-800 pb-2">
                Baseline (Unmitigated)
              </div>
              
              <div className="space-y-3 font-mono text-xs">
                <div className="flex justify-between"><span className="text-slate-400">On-Time Probability:</span><span className="font-bold text-rose-400">{baselineKpis.on_time_probability_pct}%</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Line-Stop Risk:</span><span className="font-bold text-rose-400">{baselineKpis.line_stop_probability_pct}%</span></div>
                <div className="flex justify-between"><span className="text-slate-400">P95 Lead Time:</span><span className="font-bold text-white">{baselineKpis.p95_lead_time_days} Days</span></div>
                <div className="flex justify-between"><span className="text-slate-400">VaR 95% Exposure:</span><span className="font-bold text-amber-400">${baselineKpis.value_at_risk_95_usd.toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Expected Line-Stop Loss:</span><span className="font-bold text-rose-400">${baselineKpis.expected_line_stop_cost_usd.toLocaleString()}</span></div>
              </div>
            </div>

            {/* Column 2: Active Mitigated */}
            <div className="bg-[#101C31] border border-emerald-500/40 rounded-2xl p-5 space-y-4 relative overflow-hidden">
              <div className="absolute top-0 right-0 bg-emerald-500 text-slate-950 text-[10px] font-black uppercase px-2.5 py-0.5 rounded-bl">
                Active Mitigated
              </div>
              <div className="text-xs font-bold uppercase tracking-wider text-emerald-400 border-b border-slate-800 pb-2">
                Digital Twin Protected
              </div>
              
              <div className="space-y-3 font-mono text-xs">
                <div className="flex justify-between"><span className="text-slate-400">On-Time Probability:</span><span className="font-bold text-emerald-400">{kpis.on_time_probability_pct}%</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Line-Stop Risk:</span><span className="font-bold text-emerald-400">{kpis.line_stop_probability_pct}%</span></div>
                <div className="flex justify-between"><span className="text-slate-400">P95 Lead Time:</span><span className="font-bold text-white">{kpis.p95_lead_time_days} Days</span></div>
                <div className="flex justify-between"><span className="text-slate-400">VaR 95% Exposure:</span><span className="font-bold text-emerald-400">${kpis.value_at_risk_95_usd.toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Expected Line-Stop Loss:</span><span className="font-bold text-emerald-400">${kpis.expected_line_stop_cost_usd.toLocaleString()}</span></div>
              </div>
            </div>

            {/* Column 3: The Delta & Net ROI */}
            <div className="bg-gradient-to-br from-blue-950/40 to-emerald-950/40 border border-blue-500/40 rounded-2xl p-5 space-y-4 flex flex-col justify-between">
              <div>
                <div className="text-xs font-bold uppercase tracking-wider text-blue-400 border-b border-slate-800 pb-2">
                  Optimization Delta
                </div>
                
                <div className="space-y-3 font-mono text-xs mt-3">
                  <div className="flex justify-between"><span className="text-slate-400">Risk Reduction:</span><span className="font-bold text-emerald-400">-{comparisonDelta.line_stop_risk_reduction_pct}%</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">P95 Days Saved:</span><span className="font-bold text-emerald-400">+{comparisonDelta.lead_time_days_saved_p95} Days</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">Cost of Mitigation:</span><span className="font-bold text-amber-300">${comparisonDelta.cost_of_mitigation_usd.toLocaleString()}</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">Avoided Downtime:</span><span className="font-bold text-emerald-400">+${comparisonDelta.avoided_line_stop_loss_usd.toLocaleString()}</span></div>
                </div>
              </div>

              <div className="p-4 bg-[#070D1A] rounded-xl border border-emerald-500/40 text-center">
                <div className="text-xs text-slate-400 uppercase tracking-widest font-bold">Net Mitigation ROI</div>
                <div className="text-3xl font-black text-emerald-400 mt-1">+{comparisonDelta.mitigation_roi_pct}%</div>
                <div className="text-[10px] text-slate-400 mt-1">Net Savings: ${comparisonDelta.net_savings_usd.toLocaleString()}</div>
              </div>
            </div>

          </div>
        </div>
      )}

      {/* TAB 4: Multi-Tier Digital Twin BOM Topology */}
      {activeTab === 'topology' && (
        <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Layers className="w-5 h-5 text-blue-400" />
              Multi-Tier Digital Twin Supply Chain BOM
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Stochastic distributions, machine breakdown probabilities, and connected Digital Twins across all supplier nodes.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {currentScenarioNodes.map(node => (
              <div 
                key={node.id}
                className="bg-[#101C31] border border-slate-800 rounded-xl p-5 space-y-4 hover:border-slate-700 transition-all flex flex-col justify-between"
              >
                <div>
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-xs font-mono font-bold text-blue-400">{node.id}</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      node.tier === 1 ? 'bg-blue-500/20 text-blue-300' : 'bg-purple-500/20 text-purple-300'
                    }`}>
                      Tier {node.tier}
                    </span>
                  </div>
                  
                  <h4 className="text-sm font-bold text-white leading-tight">{node.name}</h4>
                  <div className="text-xs text-slate-400 mt-1 flex items-center gap-2">
                    <span>{node.supplier_name}</span>
                    <span>•</span>
                    <span>{node.location}</span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 mt-4 pt-3 border-t border-slate-800/80 text-xs font-mono">
                    <div className="p-2 bg-[#091120] rounded-lg">
                      <div className="text-[10px] text-slate-500">Lead Time Tri</div>
                      <div className="font-bold text-slate-200">
                        {node.triangular_lead_time.min} / {node.triangular_lead_time.mode} / {node.triangular_lead_time.max}d
                      </div>
                    </div>
                    <div className="p-2 bg-[#091120] rounded-lg">
                      <div className="text-[10px] text-slate-500">Breakdown Risk</div>
                      <div className="font-bold text-amber-400">
                        {(node.machine_failure_prob * 100).toFixed(1)}% prob
                      </div>
                    </div>
                  </div>
                </div>

                {/* Secondary Twin Section */}
                {node.secondary_twin ? (
                  <div className="p-3 bg-emerald-950/20 border border-emerald-500/30 rounded-lg text-xs">
                    <div className="flex justify-between items-center text-emerald-400 font-bold mb-1">
                      <span className="flex items-center gap-1">
                        <Check className="w-3.5 h-3.5" /> Failover Twin Ready
                      </span>
                      <span className="font-mono text-[10px]">{node.secondary_twin.id}</span>
                    </div>
                    <div className="text-slate-300 font-semibold">{node.secondary_twin.name}</div>
                    <div className="text-slate-400 text-[10px] mt-0.5">{node.secondary_twin.location} • Status: {node.secondary_twin.qualification_status}</div>
                  </div>
                ) : (
                  <div className="p-3 bg-rose-950/20 border border-rose-500/30 rounded-lg text-xs text-rose-300">
                    ⚠️ Single Source Vulnerability — No alternate twin pre-qualified.
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 5: Executive Mitigation Actions */}
      {activeTab === 'actions' && (
        <div className="bg-[#0B1528] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Zap className="w-5 h-5 text-amber-400" />
              One-Click Executive Digital Twin Mitigation Actions
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Dispatch autonomous mitigation orders directly into digital twin contracts, ERP purchase orders, and 3PL freight networks.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            
            {/* Action 1: Deploy Dual-Sourcing */}
            <div className="bg-[#101C31] border border-slate-800 rounded-2xl p-5 space-y-4 flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400 mb-3">
                  <Zap className="w-5 h-5" />
                </div>
                <h4 className="text-sm font-bold text-white">Deploy Dual-Source PO Allocation</h4>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  Splits volume allocation 60/40 between primary single-source suppliers and pre-qualified secondary digital twins (Precision AutoComp & Kovai Diecast).
                </p>
                <div className="mt-3 text-xs font-mono text-emerald-400 bg-emerald-950/30 p-2 rounded-lg border border-emerald-800/40">
                  Projected Risk Reduction: -98.2% Line-Stop
                </div>
              </div>

              <button
                onClick={() => handleExecuteMitigationAction('DEPLOY_DUAL_SOURCING')}
                disabled={actionInProgress !== null}
                className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-xl text-xs transition-all shadow-md active:scale-95 disabled:opacity-50"
              >
                {actionInProgress === 'DEPLOY_DUAL_SOURCING' ? 'Executing PO...' : '⚡ Authorize Dual-Sourcing Split'}
              </button>
            </div>

            {/* Action 2: Buffer Stock PO */}
            <div className="bg-[#101C31] border border-slate-800 rounded-2xl p-5 space-y-4 flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded-xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400 mb-3">
                  <Database className="w-5 h-5" />
                </div>
                <h4 className="text-sm font-bold text-white">Allocate 14-Day Safety Buffer</h4>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  Reserves 150 critical housing & micro-controller components in regional European/Asian 3PL bonded warehouse hubs.
                </p>
                <div className="mt-3 text-xs font-mono text-purple-400 bg-purple-950/30 p-2 rounded-lg border border-purple-800/40">
                  Buffer Absorption: Absorbs up to 14 days delay
                </div>
              </div>

              <button
                onClick={() => handleExecuteMitigationAction('ALLOCATE_BUFFER_STOCK')}
                disabled={actionInProgress !== null}
                className="w-full bg-purple-600 hover:bg-purple-500 text-white font-bold py-2.5 rounded-xl text-xs transition-all shadow-md active:scale-95 disabled:opacity-50"
              >
                {actionInProgress === 'ALLOCATE_BUFFER_STOCK' ? 'Reserving...' : '🛡️ Authorize Buffer Stock PO'}
              </button>
            </div>

            {/* Action 3: Air Freight Courier */}
            <div className="bg-[#101C31] border border-slate-800 rounded-2xl p-5 space-y-4 flex flex-col justify-between">
              <div>
                <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 mb-3">
                  <Plane className="w-5 h-5" />
                </div>
                <h4 className="text-sm font-bold text-white">Trigger Expedited Air Freight Bypass</h4>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  Overrides default trans-pacific ocean shipping lane with dedicated charter air cargo courier, bypassing all sea-port congestion.
                </p>
                <div className="mt-3 text-xs font-mono text-amber-400 bg-amber-950/30 p-2 rounded-lg border border-amber-800/40">
                  Transit Speedup: -18 Days Transit Time
                </div>
              </div>

              <button
                onClick={() => handleExecuteMitigationAction('TRIGGER_AIR_FREIGHT')}
                disabled={actionInProgress !== null}
                className="w-full bg-amber-600 hover:bg-amber-500 text-white font-bold py-2.5 rounded-xl text-xs transition-all shadow-md active:scale-95 disabled:opacity-50"
              >
                {actionInProgress === 'TRIGGER_AIR_FREIGHT' ? 'Routing Courier...' : '✈️ Trigger Air Freight Lane'}
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}
