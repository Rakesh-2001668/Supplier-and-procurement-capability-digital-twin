'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { 
  Play, Pause, SkipForward, SkipBack, RotateCcw, 
  Workflow, User, Cpu, Globe, CheckCircle2, AlertCircle, 
  ExternalLink, Clock, Shield, Sparkles, Layers, ArrowRight,
  GitBranch, Check, HelpCircle
} from 'lucide-react';
import axios from 'axios';

export interface BpmnStep {
  step_index: number;
  step_id: string;
  label: string;
  type: 'START_EVENT' | 'USER_TASK' | 'SYSTEM_TASK' | 'GATEWAY' | 'END_EVENT';
  lane: string;
  screen_ref?: string | null;
  candidate_group?: string | null;
  key_dmn_or_timer?: string | null;
  branch_notes?: string | null;
  description: string;
}

export interface BpmnLane {
  lane_id: string;
  name: string;
  role_type: 'HUMAN' | 'SYSTEM' | 'EXTERNAL_SUPPLIER';
  description: string;
}

export interface BpmnFlow {
  id: string;
  flow_code: string;
  process_key: string;
  title: string;
  start_trigger: string;
  lanes: BpmnLane[];
  steps: BpmnStep[];
  branches_and_nuances: string;
  total_steps?: number;
}

interface BpmnSwimlanePlayerProps {
  initialFlowCode?: string;
  selectedDocId?: string;
  onStepChange?: (stepIndex: number, step: BpmnStep) => void;
}

export default function BpmnSwimlanePlayer({
  initialFlowCode = 'F2',
  selectedDocId,
  onStepChange
}: BpmnSwimlanePlayerProps) {
  const [flows, setFlows] = useState<any[]>([]);
  const [selectedFlowCode, setSelectedFlowCode] = useState<string>(initialFlowCode);
  const [flowData, setFlowData] = useState<BpmnFlow | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playSpeed, setPlaySpeed] = useState<number>(2000); // ms per step
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [history, setHistory] = useState<number[]>([0]);
  const [branchChoice, setBranchChoice] = useState<'MAIN_PATH' | 'ALTERNATIVE_BRANCH'>('MAIN_PATH');
  const [actionLog, setActionLog] = useState<string[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Fetch all flows list
  useEffect(() => {
    async function loadFlowsList() {
      try {
        const res = await axios.get('http://127.0.0.1:8080/api/v1/bpmn/flows');
        if (Array.isArray(res.data)) {
          setFlows(res.data);
        }
      } catch (err) {
        console.error('Failed to fetch BPMN flows list:', err);
      }
    }
    loadFlowsList();
  }, []);

  // Fetch active flow detail
  useEffect(() => {
    async function loadFlowDetail() {
      setIsLoading(true);
      try {
        const res = await axios.get(`http://127.0.0.1:8080/api/v1/bpmn/flows/${selectedFlowCode}`);
        if (res.data && res.data.flow) {
          setFlowData(res.data.flow);
          const state = res.data.token_state;
          const idx = state?.current_step_index ?? 0;
          setCurrentStepIndex(idx);
          setHistory(state?.history ?? [0]);
          setActionLog([`Initialized flow ${res.data.flow.flow_code} (${res.data.flow.process_key}) at Step ${idx + 1}`]);
          if (onStepChange && res.data.flow.steps[idx]) {
            onStepChange(idx, res.data.flow.steps[idx]);
          }
        }
      } catch (err) {
        console.error('Failed to load flow details:', err);
      } finally {
        setIsLoading(false);
      }
    }
    loadFlowDetail();
  }, [selectedFlowCode]);

  // Handle Playback Interval
  useEffect(() => {
    if (isPlaying) {
      timerRef.current = setInterval(() => {
        handleStepForward();
      }, playSpeed);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isPlaying, currentStepIndex, flowData, playSpeed, branchChoice]);

  const handleStepForward = async () => {
    if (!flowData) return;
    const total = flowData.steps.length;
    if (currentStepIndex >= total - 1) {
      setIsPlaying(false);
      return;
    }

    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/bpmn/flows/${selectedFlowCode}/simulate`, {
        current_step_index: currentStepIndex,
        branch_choice: branchChoice,
        actor: 'Active Platform User'
      });
      const newIdx = res.data.new_step_index;
      setCurrentStepIndex(newIdx);
      setHistory(prev => (prev.includes(newIdx) ? prev : [...prev, newIdx]));
      setActionLog(prev => [res.data.message, ...prev.slice(0, 9)]);
      if (onStepChange && flowData.steps[newIdx]) {
        onStepChange(newIdx, flowData.steps[newIdx]);
      }
      if (newIdx >= total - 1) {
        setIsPlaying(false);
      }
    } catch (err) {
      console.error('Error advancing token:', err);
      setIsPlaying(false);
    }
  };

  const handleStepBack = () => {
    if (!flowData || currentStepIndex <= 0) return;
    const prevIdx = currentStepIndex - 1;
    setCurrentStepIndex(prevIdx);
    setActionLog(prev => [`Stepped back to Step ${prevIdx + 1}: ${flowData.steps[prevIdx].label}`, ...prev.slice(0, 9)]);
    if (onStepChange && flowData.steps[prevIdx]) {
      onStepChange(prevIdx, flowData.steps[prevIdx]);
    }
  };

  const handleReset = async () => {
    setIsPlaying(false);
    try {
      const res = await axios.post(`http://127.0.0.1:8080/api/v1/bpmn/flows/${selectedFlowCode}/reset`);
      setCurrentStepIndex(0);
      setHistory([0]);
      setActionLog([res.data.message || 'Token reset to start event.']);
      if (onStepChange && flowData?.steps[0]) {
        onStepChange(0, flowData.steps[0]);
      }
    } catch (err) {
      console.error('Error resetting flow:', err);
      setCurrentStepIndex(0);
      setHistory([0]);
    }
  };

  const activeStep: BpmnStep | undefined = flowData?.steps[currentStepIndex];

  // Screen mapping lookup for one-click navigation
  const getScreenUrl = (screenRef?: string | null) => {
    if (!screenRef) return null;
    const s = screenRef.toUpperCase();
    if (s.includes('REQ')) return '/p2p';
    if (s.includes('PO')) return '/p2p';
    if (s.includes('SRC')) return '/sourcing';
    if (s.includes('CLM')) return '/contracts/agreements';
    if (s.includes('RCV')) return '/p2p';
    if (s.includes('INV')) return '/p2p';
    if (s.includes('SLM')) return '/network';
    if (s.includes('MDM')) return '/mdm/requests';
    if (s.includes('MRP')) return '/mrp/planner-workbench';
    if (s.includes('SPD')) return '/spend/cube';
    return '/command-centre';
  };

  return (
    <div className="w-full bg-[#0A0F1D] border border-slate-800/80 rounded-xl overflow-hidden shadow-2xl">
      {/* Top Header & Flow Selector */}
      <div className="p-4 bg-slate-900/90 border-b border-slate-800 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-cyan-500/10 border border-cyan-500/30 rounded-lg text-cyan-400">
            <Workflow className="w-6 h-6 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-white tracking-wide">
                BPMN 2.0 Governed Swimlane Viewer & Token Player
              </h2>
              <span className="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                Live Engine
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Deterministic BPMN choreography with Camunda token-advancement, DMN gating, and role candidate routing.
            </p>
          </div>
        </div>

        {/* Playback Controls Toolbar */}
        <div className="flex items-center gap-2 bg-[#060A14] border border-slate-800 p-1.5 rounded-lg shadow-inner">
          <button
            onClick={handleStepBack}
            disabled={currentStepIndex <= 0}
            title="Step Back"
            className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <SkipBack className="w-4 h-4" />
          </button>

          <button
            onClick={() => setIsPlaying(!isPlaying)}
            title={isPlaying ? "Pause Token" : "Play Flow Automatically"}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded font-semibold text-xs shadow-md transition-all ${
              isPlaying
                ? 'bg-amber-500 hover:bg-amber-600 text-slate-950 font-bold'
                : 'bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold'
            }`}
          >
            {isPlaying ? (
              <>
                <Pause className="w-3.5 h-3.5 fill-current" /> Pause
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" /> Play Token
              </>
            )}
          </button>

          <button
            onClick={handleStepForward}
            disabled={flowData ? currentStepIndex >= flowData.steps.length - 1 : true}
            title="Step Forward"
            className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <SkipForward className="w-4 h-4" />
          </button>

          <button
            onClick={handleReset}
            title="Reset to Start Event"
            className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded transition-colors"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          <div className="h-4 w-px bg-slate-800 mx-1" />

          {/* Speed Toggle */}
          <div className="flex items-center text-xs font-mono text-slate-400">
            <span className="mr-1.5 text-[11px] text-slate-500">Speed:</span>
            {[
              { label: '0.5x', speed: 3000 },
              { label: '1x', speed: 2000 },
              { label: '2x', speed: 1000 }
            ].map(s => (
              <button
                key={s.label}
                onClick={() => setPlaySpeed(s.speed)}
                className={`px-1.5 py-0.5 rounded text-[11px] ${
                  playSpeed === s.speed
                    ? 'bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>

          <div className="h-4 w-px bg-slate-800 mx-1" />

          {/* Current Step Tracker Badge */}
          <div className="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700 text-xs font-mono text-cyan-300">
            Step {flowData ? currentStepIndex + 1 : 0}/{flowData?.steps.length ?? 0}
          </div>
        </div>
      </div>

      {/* 9 BPMN Flow Switcher Pills */}
      <div className="px-4 py-2.5 bg-[#070D1A] border-b border-slate-800 flex items-center gap-2 overflow-x-auto scrollbar-thin">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider shrink-0 flex items-center gap-1 mr-1">
          <Layers className="w-3.5 h-3.5 text-cyan-400" /> Flows:
        </span>
        {[
          { code: 'F1', name: 'MRP-to-PR' },
          { code: 'F2', name: 'Requisition' },
          { code: 'F3', name: 'Sourcing' },
          { code: 'F4', name: 'Contract' },
          { code: 'F5', name: 'PO Lifecycle' },
          { code: 'F6', name: 'Receipt & SES' },
          { code: 'F7', name: 'Invoice Match' },
          { code: 'F8', name: 'Supplier SLM' },
          { code: 'F9', name: 'Material MDM' }
        ].map(item => {
          const isSelected = selectedFlowCode === item.code;
          return (
            <button
              key={item.code}
              onClick={() => {
                setSelectedFlowCode(item.code);
                setIsPlaying(false);
              }}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all flex items-center gap-1.5 ${
                isSelected
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 shadow-sm shadow-cyan-500/20 font-semibold'
                  : 'bg-slate-900/60 text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-slate-800'
              }`}
            >
              <span className={`px-1 rounded text-[10px] font-bold ${
                isSelected ? 'bg-cyan-500 text-slate-950' : 'bg-slate-800 text-slate-400'
              }`}>
                {item.code}
              </span>
              <span>{item.name}</span>
            </button>
          );
        })}
      </div>

      {/* Active Flow Banner Metadata */}
      {flowData && (
        <div className="px-6 py-3 bg-gradient-to-r from-slate-900/90 via-[#0B1528] to-slate-900/90 border-b border-slate-800/70 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-3">
            <div>
              <span className="text-slate-500 font-mono mr-2">PROCESS:</span>
              <span className="font-bold text-slate-200 text-sm">{flowData.title}</span>
              <span className="ml-2 font-mono text-[11px] text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800/50">
                {flowData.process_key}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-4 text-slate-400">
            <div>
              <span className="text-slate-500">Trigger:</span>{' '}
              <span className="text-slate-300 italic">{flowData.start_trigger}</span>
            </div>
            {selectedDocId && (
              <div className="flex items-center gap-1 bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 rounded text-amber-300 font-mono">
                <span>Instance:</span>
                <span className="font-bold">{selectedDocId}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Main Swimlanes Visual Canvas */}
      <div className="relative p-6 overflow-x-auto min-h-[460px] bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900/30 via-[#070B14] to-[#04070E]">
        {isLoading ? (
          <div className="flex items-center justify-center h-64 text-slate-400">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-400 mr-3" />
            Loading BPMN Swimlane Model...
          </div>
        ) : flowData ? (
          <div className="min-w-[950px] space-y-4">
            {flowData.lanes.map((lane, laneIdx) => {
              // Get all steps in this lane
              const laneSteps = flowData.steps.filter(s => s.lane === lane.name);
              
              const isHuman = lane.role_type === 'HUMAN';
              const isSystem = lane.role_type === 'SYSTEM';
              const isSupplier = lane.role_type === 'EXTERNAL_SUPPLIER';

              return (
                <div 
                  key={lane.lane_id} 
                  className="flex border border-slate-800/80 rounded-xl bg-slate-950/40 backdrop-blur-sm overflow-hidden shadow-lg transition-all hover:border-slate-700/80"
                >
                  {/* Left Swimlane Header (Entity / Role) */}
                  <div className={`w-64 shrink-0 p-4 border-r border-slate-800/80 flex flex-col justify-between ${
                    isHuman 
                      ? 'bg-slate-900/70 border-l-4 border-l-indigo-500' 
                      : isSystem 
                      ? 'bg-slate-900/70 border-l-4 border-l-cyan-500' 
                      : 'bg-slate-900/70 border-l-4 border-l-amber-500'
                  }`}>
                    <div>
                      <div className="flex items-center gap-2 mb-1.5">
                        {isHuman && <User className="w-4 h-4 text-indigo-400" />}
                        {isSystem && <Cpu className="w-4 h-4 text-cyan-400" />}
                        {isSupplier && <Globe className="w-4 h-4 text-amber-400" />}
                        <span className="text-xs font-bold text-white tracking-wide">{lane.name}</span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed line-clamp-2">
                        {lane.description}
                      </p>
                    </div>

                    <div className="mt-2 pt-2 border-t border-slate-800/60 flex items-center justify-between">
                      <span className={`text-[10px] font-mono px-2 py-0.5 rounded font-semibold ${
                        isHuman 
                          ? 'bg-indigo-950/60 text-indigo-300 border border-indigo-800/40' 
                          : isSystem 
                          ? 'bg-cyan-950/60 text-cyan-300 border border-cyan-800/40' 
                          : 'bg-amber-950/60 text-amber-300 border border-amber-800/40'
                      }`}>
                        {lane.role_type}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">
                        {laneSteps.length} {laneSteps.length === 1 ? 'task' : 'tasks'}
                      </span>
                    </div>
                  </div>

                  {/* Right Lane Grid track: Render steps in sequential columns */}
                  <div className="flex-1 p-4 flex items-center gap-6 overflow-x-auto relative">
                    {/* Connecting rail backdrop */}
                    <div className="absolute left-4 right-4 h-0.5 bg-slate-800/60 top-1/2 -translate-y-1/2 pointer-events-none" />

                    {flowData.steps.map((step, sIdx) => {
                      const isInThisLane = step.lane === lane.name;
                      const isActive = sIdx === currentStepIndex;
                      const isPast = history.includes(sIdx);

                      if (!isInThisLane) {
                        // Render invisible placeholder spacer to align columns across swimlanes
                        return (
                          <div 
                            key={step.step_id} 
                            className="w-48 shrink-0 h-28 opacity-0 pointer-events-none" 
                          />
                        );
                      }

                      // Render BPMN Node based on type
                      if (step.type === 'START_EVENT') {
                        return (
                          <div
                            key={step.step_id}
                            onClick={() => {
                              setCurrentStepIndex(sIdx);
                              if (onStepChange) onStepChange(sIdx, step);
                            }}
                            className={`w-36 shrink-0 flex flex-col items-center justify-center p-3 rounded-xl cursor-pointer transition-all ${
                              isActive 
                                ? 'scale-105 ring-2 ring-emerald-400 bg-emerald-950/50 shadow-lg shadow-emerald-500/20' 
                                : 'bg-slate-900/60 hover:bg-slate-850 border border-slate-800'
                            }`}
                          >
                            <div className="relative">
                              <div className={`w-11 h-11 rounded-full flex items-center justify-center border-2 transition-all ${
                                isActive 
                                  ? 'border-emerald-400 bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/50 animate-pulse' 
                                  : isPast 
                                  ? 'border-emerald-500 bg-emerald-950/80 text-emerald-300' 
                                  : 'border-slate-700 bg-slate-800 text-slate-400'
                              }`}>
                                <Play className="w-5 h-5 fill-current ml-0.5" />
                              </div>
                              {isActive && (
                                <span className="absolute -top-1 -right-1 flex h-3 w-3">
                                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                                  <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500" />
                                </span>
                              )}
                            </div>
                            <span className="text-[11px] font-bold text-center text-slate-200 mt-2 line-clamp-1">
                              {step.label}
                            </span>
                            <span className="text-[9px] font-mono text-emerald-400 uppercase tracking-wider">
                              Start Event
                            </span>
                          </div>
                        );
                      }

                      if (step.type === 'END_EVENT') {
                        return (
                          <div
                            key={step.step_id}
                            onClick={() => {
                              setCurrentStepIndex(sIdx);
                              if (onStepChange) onStepChange(sIdx, step);
                            }}
                            className={`w-36 shrink-0 flex flex-col items-center justify-center p-3 rounded-xl cursor-pointer transition-all ${
                              isActive 
                                ? 'scale-105 ring-2 ring-rose-400 bg-rose-950/50 shadow-lg shadow-rose-500/20' 
                                : 'bg-slate-900/60 hover:bg-slate-850 border border-slate-800'
                            }`}
                          >
                            <div className="relative">
                              <div className={`w-11 h-11 rounded-full flex items-center justify-center border-4 transition-all ${
                                isActive 
                                  ? 'border-rose-400 bg-rose-500 text-white shadow-md shadow-rose-500/50 animate-pulse' 
                                  : isPast 
                                  ? 'border-rose-500 bg-rose-950/80 text-rose-300' 
                                  : 'border-slate-700 bg-slate-800 text-slate-400'
                              }`}>
                                <CheckCircle2 className="w-5 h-5 stroke-[2.5]" />
                              </div>
                              {isActive && (
                                <span className="absolute -top-1 -right-1 flex h-3 w-3">
                                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
                                  <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500" />
                                </span>
                              )}
                            </div>
                            <span className="text-[11px] font-bold text-center text-slate-200 mt-2 line-clamp-1">
                              {step.label}
                            </span>
                            <span className="text-[9px] font-mono text-rose-400 uppercase tracking-wider">
                              End Event
                            </span>
                          </div>
                        );
                      }

                      if (step.type === 'GATEWAY') {
                        return (
                          <div
                            key={step.step_id}
                            onClick={() => {
                              setCurrentStepIndex(sIdx);
                              if (onStepChange) onStepChange(sIdx, step);
                            }}
                            className={`w-44 shrink-0 p-3 rounded-xl cursor-pointer transition-all relative flex flex-col items-center text-center ${
                              isActive 
                                ? 'scale-105 ring-2 ring-amber-400 bg-amber-950/40 shadow-xl shadow-amber-500/20' 
                                : 'bg-slate-900/70 hover:bg-slate-850 border border-slate-800'
                            }`}
                          >
                            {/* BPMN Exclusive Gateway Diamond */}
                            <div className="relative my-1">
                              <div className={`w-10 h-10 rotate-45 rounded border-2 flex items-center justify-center transition-all ${
                                isActive 
                                  ? 'border-amber-400 bg-amber-500 text-slate-950 shadow-md shadow-amber-500/40' 
                                  : isPast 
                                  ? 'border-amber-500 bg-amber-950/70 text-amber-300' 
                                  : 'border-slate-700 bg-slate-800 text-slate-400'
                              }`}>
                                <GitBranch className="w-5 h-5 -rotate-45 stroke-[2.5]" />
                              </div>
                              {isActive && (
                                <span className="absolute -top-1 -right-1 flex h-3 w-3">
                                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                                  <span className="relative inline-flex rounded-full h-3 w-3 bg-amber-500" />
                                </span>
                              )}
                            </div>

                            <span className="text-xs font-bold text-slate-200 mt-2 line-clamp-2">
                              {step.label}
                            </span>
                            
                            {step.key_dmn_or_timer && (
                              <span className="mt-1 text-[10px] font-mono text-amber-300 bg-amber-950/60 px-1.5 py-0.5 rounded border border-amber-800/40 line-clamp-1">
                                {step.key_dmn_or_timer}
                              </span>
                            )}
                          </div>
                        );
                      }

                      // USER_TASK or SYSTEM_TASK
                      const isUserTask = step.type === 'USER_TASK';

                      return (
                        <div
                          key={step.step_id}
                          onClick={() => {
                            setCurrentStepIndex(sIdx);
                            if (onStepChange) onStepChange(sIdx, step);
                          }}
                          className={`w-48 shrink-0 p-3 rounded-xl cursor-pointer transition-all relative flex flex-col justify-between ${
                            isActive
                              ? isUserTask
                                ? 'scale-105 ring-2 ring-indigo-400 bg-gradient-to-b from-indigo-950/80 to-slate-900 shadow-xl shadow-indigo-500/20'
                                : 'scale-105 ring-2 ring-cyan-400 bg-gradient-to-b from-cyan-950/80 to-slate-900 shadow-xl shadow-cyan-500/20'
                              : isPast
                              ? 'bg-slate-900/80 hover:bg-slate-800/90 border border-slate-750'
                              : 'bg-slate-900/50 hover:bg-slate-850/60 border border-slate-800'
                          }`}
                        >
                          {/* Live Token Pulse Marker */}
                          {isActive && (
                            <div className="absolute -top-2.5 left-1/2 -translate-x-1/2 px-2 py-0.5 bg-cyan-400 text-slate-950 font-black text-[9px] rounded-full uppercase tracking-wider flex items-center gap-1 shadow-md">
                              <span className="w-1.5 h-1.5 rounded-full bg-slate-950 animate-ping" />
                              Active Token
                            </div>
                          )}

                          {/* Top Card Badges */}
                          <div>
                            <div className="flex items-center justify-between mb-1.5">
                              <span className={`text-[9px] font-mono uppercase font-bold px-1.5 py-0.5 rounded flex items-center gap-1 ${
                                isUserTask 
                                  ? 'bg-indigo-950 text-indigo-300 border border-indigo-800/40' 
                                  : 'bg-cyan-950 text-cyan-300 border border-cyan-800/40'
                              }`}>
                                {isUserTask ? <User className="w-2.5 h-2.5" /> : <Cpu className="w-2.5 h-2.5" />}
                                {isUserTask ? 'User Task' : 'System Task'}
                              </span>

                              {step.screen_ref && (
                                <span className="text-[9px] font-mono text-slate-400 bg-slate-800 px-1.5 py-0.5 rounded">
                                  [{step.screen_ref}]
                                </span>
                              )}
                            </div>

                            <h4 className="text-xs font-semibold text-white leading-tight line-clamp-2">
                              {step.label}
                            </h4>
                          </div>

                          {/* Bottom Card Attributes */}
                          <div className="mt-3 pt-2 border-t border-slate-800/70 space-y-1">
                            {step.candidate_group && (
                              <div className="flex items-center gap-1 text-[10px] text-slate-400 truncate">
                                <Shield className="w-3 h-3 text-indigo-400 shrink-0" />
                                <span className="truncate">{step.candidate_group}</span>
                              </div>
                            )}

                            {step.key_dmn_or_timer && (
                              <div className="flex items-center gap-1 text-[10px] font-mono text-cyan-300 truncate">
                                <Clock className="w-3 h-3 text-cyan-400 shrink-0" />
                                <span className="truncate">{step.key_dmn_or_timer}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>

      {/* Step Inspector & Dynamic Gateway Decider Panel */}
      {activeStep && (
        <div className="p-4 bg-slate-900/95 border-t border-slate-800 grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs">
          {/* Active Step Details */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-500 text-slate-950">
                STEP {currentStepIndex + 1}
              </span>
              <h3 className="text-sm font-bold text-white">{activeStep.label}</h3>
            </div>
            <p className="text-slate-300 text-xs leading-relaxed">{activeStep.description}</p>
            
            <div className="flex flex-wrap gap-2 pt-1">
              <span className="text-slate-400 font-mono">Lane: <strong className="text-slate-200">{activeStep.lane}</strong></span>
              {activeStep.candidate_group && (
                <span className="text-indigo-300 font-mono">Candidate: <strong>{activeStep.candidate_group}</strong></span>
              )}
            </div>
          </div>

          {/* SLA, Governance & Gateway Choice */}
          <div className="space-y-2 lg:border-x lg:border-slate-800 lg:px-4">
            <div className="font-semibold text-slate-300 flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-cyan-400" /> Governance & Routing
            </div>

            {activeStep.type === 'GATEWAY' ? (
              <div className="p-2.5 bg-amber-950/30 border border-amber-800/50 rounded-lg">
                <span className="text-amber-300 font-bold block mb-1">DMN Exclusive Branch Selector:</span>
                <div className="flex gap-2 mt-1.5">
                  <button
                    onClick={() => setBranchChoice('MAIN_PATH')}
                    className={`px-2.5 py-1 rounded text-xs font-semibold transition-all ${
                      branchChoice === 'MAIN_PATH'
                        ? 'bg-emerald-500 text-slate-950 font-bold shadow'
                        : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                    }`}
                  >
                    Standard Route
                  </button>
                  <button
                    onClick={() => setBranchChoice('ALTERNATIVE_BRANCH')}
                    className={`px-2.5 py-1 rounded text-xs font-semibold transition-all ${
                      branchChoice === 'ALTERNATIVE_BRANCH'
                        ? 'bg-amber-500 text-slate-950 font-bold shadow'
                        : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                    }`}
                  >
                    Exception / Alternative
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-slate-300">
                  <span className="text-slate-500">DMN / Timer:</span>
                  <span className="font-mono text-cyan-300 font-semibold">
                    {activeStep.key_dmn_or_timer || 'Automated / Synchronous'}
                  </span>
                </div>
                {activeStep.screen_ref && (
                  <div className="flex items-center gap-2 pt-1">
                    <span className="text-slate-500">Screen Ref:</span>
                    <span className="font-mono font-bold text-white bg-slate-800 px-1.5 py-0.5 rounded">
                      {activeStep.screen_ref}
                    </span>
                    {getScreenUrl(activeStep.screen_ref) && (
                      <Link
                        href={getScreenUrl(activeStep.screen_ref)!}
                        className="inline-flex items-center gap-1 text-[11px] text-cyan-400 hover:text-cyan-300 underline font-semibold ml-2"
                      >
                        Open Workspace <ExternalLink className="w-3 h-3" />
                      </Link>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Action Log / Blueprint Nuances */}
          <div className="space-y-1.5">
            <div className="font-semibold text-slate-300 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-400" /> Blueprint Business Rules
              </span>
              <span className="text-[10px] text-slate-500 font-mono">Sec. 21 Camunda Spec</span>
            </div>
            <div className="p-2 bg-slate-950/70 border border-slate-800 rounded-lg text-slate-400 text-[11px] max-h-24 overflow-y-auto leading-relaxed">
              {flowData?.branches_and_nuances}
            </div>

            {actionLog.length > 0 && (
              <div className="text-[10px] font-mono text-emerald-400 truncate">
                Last Event: {actionLog[0]}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
