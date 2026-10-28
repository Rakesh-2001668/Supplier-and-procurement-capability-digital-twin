'use client';

import React, { useState, useEffect, useRef } from 'react';
import { 
  Building2, ChevronDown, Check, Sparkles, RefreshCw, 
  Layers, ExternalLink, ShieldCheck 
} from 'lucide-react';

interface IndustryTemplate {
  id: string;
  name: string;
  code: string;
  icon: string;
  tenant_name: string;
  tenant_id: string;
  nuance_description: string;
  is_active: boolean;
}

export default function IndustrySwitcher() {
  const [templates, setTemplates] = useState<IndustryTemplate[]>([]);
  const [activeTemplate, setActiveTemplate] = useState<IndustryTemplate | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const fetchTemplates = async () => {
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/industry-templates');
      if (res.ok) {
        const data = await res.json();
        setTemplates(data);
        const current = data.find((t: IndustryTemplate) => t.is_active) || data[0];
        setActiveTemplate(current);
      }
    } catch (e) {
      // Fallback defaults if backend is reloading
      const fallbackTemplates: IndustryTemplate[] = [
        {
          id: 'MANUFACTURING',
          name: 'Manufacturing & Industrial',
          code: 'IND-MFG-01',
          icon: '🏭',
          tenant_name: 'Axion Mobility Systems Pvt Ltd',
          tenant_id: 'tenant-axion-mfg-100',
          nuance_description: 'Net-Change MRP, PPAP, LME Indexation, 60/40 Split',
          is_active: true
        },
        {
          id: 'CONSTRUCTION',
          name: 'Construction & Projects',
          code: 'IND-CONST-02',
          icon: '🏗️',
          tenant_name: 'Apex Infra & Civil Engineering Ltd',
          tenant_id: 'tenant-apex-infra-200',
          nuance_description: 'BOQ, WBS hard stops, 5% retention, variation amendments',
          is_active: false
        },
        {
          id: 'IT_SERVICES',
          name: 'IT & Professional Services',
          code: 'IND-TECH-03',
          icon: '💻',
          tenant_name: 'Novus Global Tech & Consulting',
          tenant_id: 'tenant-novus-tech-300',
          nuance_description: 'Rate card RC-22, SOW, timesheet SES, auto-renewal alerts',
          is_active: false
        },
        {
          id: 'LOGISTICS',
          name: 'Logistics & Transportation',
          code: 'IND-LOG-04',
          icon: '🚚',
          tenant_name: 'TransBharat Freight & Cold Supply',
          tenant_id: 'tenant-transbharat-400',
          nuance_description: 'Lane rates CHE->PNQ, diesel fuel index, e-POD confirmation',
          is_active: false
        },
        {
          id: 'HEALTHCARE',
          name: 'Healthcare & Life Sciences',
          code: 'IND-HEALTH-05',
          icon: '🏥',
          tenant_name: 'Aethel Lifesciences & Hospitals Ltd',
          tenant_id: 'tenant-aethel-life-500',
          nuance_description: 'Consignment implant KN-77, cold-chain (2-8°C), recall trace',
          is_active: false
        },
        {
          id: 'GENERAL_ENTERPRISE',
          name: 'General Enterprise (Indirect)',
          code: 'IND-GEN-06',
          icon: '🏢',
          tenant_name: 'Horizon Enterprises Corp',
          tenant_id: 'tenant-horizon-corp-600',
          nuance_description: 'cXML punch-out, P-Card, 2-way match under threshold',
          is_active: false
        }
      ];
      setTemplates(fallbackTemplates);
      setActiveTemplate(fallbackTemplates[0]);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSwitch = async (templateId: string) => {
    setSwitching(true);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/industry-templates/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          template_id: templateId,
          actor: 'Chief Procurement Officer',
          notes: `Switched via Header Industry Switcher to ${templateId}`
        })
      });
      if (res.ok) {
        const data = await res.json();
        setToast(`Active Industry Template: ${data.tenant_name}`);
        setTimeout(() => setToast(null), 4000);
        await fetchTemplates();
      }
    } catch (e) {
      setToast(`Switched locally to ${templateId}`);
      setTimeout(() => setToast(null), 3000);
      setTemplates(prev => prev.map(t => ({
        ...t,
        is_active: t.id === templateId
      })));
      const sel = templates.find(t => t.id === templateId);
      if (sel) setActiveTemplate({ ...sel, is_active: true });
    } finally {
      setSwitching(false);
      setIsOpen(false);
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Toast Notification */}
      {toast && (
        <div className="fixed top-5 right-6 z-50 bg-cyan-950 border border-cyan-500/50 text-cyan-200 px-4 py-2.5 rounded-xl shadow-2xl flex items-center gap-2.5 text-xs font-semibold animate-fade-in">
          <Sparkles className="w-4 h-4 text-cyan-400 animate-spin" />
          <span>{toast}</span>
        </div>
      )}

      {/* Main Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl bg-slate-900/90 hover:bg-slate-800 border border-slate-700/80 hover:border-cyan-500/50 text-white transition-all shadow-md group"
        title="Switch Industry Template (Blueprint Section 23)"
      >
        <span className="text-base select-none">{activeTemplate?.icon || '🏭'}</span>
        <div className="text-left hidden lg:block">
          <div className="text-[10px] text-cyan-400 font-mono font-bold leading-none tracking-wider uppercase flex items-center gap-1">
            <span>Industry Pack</span>
            <span className="text-slate-500">•</span>
            <span className="text-slate-300">{activeTemplate?.code || 'IND-MFG-01'}</span>
          </div>
          <div className="text-xs font-bold text-slate-100 truncate max-w-[170px] mt-0.5">
            {activeTemplate?.name || 'Manufacturing'}
          </div>
        </div>
        <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${isOpen ? 'rotate-180 text-cyan-400' : 'group-hover:text-slate-200'}`} />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute right-0 mt-2 w-96 rounded-2xl bg-[#0B1528] border border-slate-700/90 shadow-2xl z-50 overflow-hidden backdrop-blur-xl animate-fade-in">
          {/* Header */}
          <div className="p-3.5 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-cyan-400" />
              <span className="text-xs font-bold text-white uppercase tracking-wider font-mono">
                Industry Configuration Packs
              </span>
            </div>
            <a
              href="/industry-templates"
              className="text-[11px] text-cyan-400 hover:text-cyan-300 font-bold flex items-center gap-1 hover:underline"
            >
              <span>Compare All</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          {/* Template List */}
          <div className="p-2 space-y-1.5 max-h-[380px] overflow-y-auto">
            {templates.map((tpl) => {
              const isSelected = activeTemplate?.id === tpl.id;
              return (
                <button
                  key={tpl.id}
                  onClick={() => handleSwitch(tpl.id)}
                  disabled={switching}
                  className={`w-full p-2.5 rounded-xl text-left transition-all flex items-start gap-3 border ${
                    isSelected
                      ? 'bg-gradient-to-r from-cyan-950/80 to-blue-950/80 border-cyan-500/60 shadow-lg shadow-cyan-950/40'
                      : 'bg-slate-900/50 hover:bg-slate-800/80 border-slate-800/80 hover:border-slate-700 text-slate-300'
                  }`}
                >
                  <span className="text-xl p-1 bg-slate-950/60 rounded-lg border border-slate-800">{tpl.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1">
                      <span className={`text-xs font-bold truncate ${isSelected ? 'text-white' : 'text-slate-200'}`}>
                        {tpl.name}
                      </span>
                      {isSelected ? (
                        <span className="flex items-center gap-1 text-[10px] font-mono text-cyan-400 font-bold bg-cyan-950/80 px-2 py-0.5 rounded-full border border-cyan-500/40">
                          <Check className="w-3 h-3" /> ACTIVE
                        </span>
                      ) : (
                        <span className="text-[10px] font-mono text-slate-400 bg-slate-950 px-1.5 py-0.5 rounded">
                          {tpl.code}
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] text-cyan-300/90 font-medium truncate mt-0.5">
                      {tpl.tenant_name}
                    </div>
                    <div className="text-[10px] text-slate-400 mt-1 line-clamp-1">
                      {tpl.nuance_description}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Footer */}
          <div className="p-2.5 bg-slate-950/80 border-t border-slate-800 text-[10px] text-slate-400 flex items-center justify-between font-mono">
            <span>Blueprint §23 • 6 Industry Packs</span>
            <span className="text-emerald-400 flex items-center gap-1">
              <ShieldCheck className="w-3 h-3" /> Zero Code Lock-In
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
