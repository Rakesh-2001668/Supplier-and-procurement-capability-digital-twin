'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Factory, Award, Settings, ShieldCheck, Upload, Plus, ChevronRight,
  CheckCircle2, X, Loader2, Wrench, Box, Layers, DollarSign, Clock,
  MapPin, Phone, Mail, Building2, Radio, Edit3, Trash2, ExternalLink,
  RefreshCw, Check, Sparkles, FileText, Globe, FileSignature
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

export default function SupplierDigitalTwinProfile() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'OVERVIEW' | 'MACHINERY' | 'CAPABILITIES' | 'PRODUCTS' | 'CERTS' | 'TERMS'>('OVERVIEW');
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Modals
  const [showEditProfileModal, setShowEditProfileModal] = useState(false);
  const [showMachineModal, setShowMachineModal] = useState(false);
  const [showProductModal, setShowProductModal] = useState(false);
  const [showCertModal, setShowCertModal] = useState(false);
  const [showIotModal, setShowIotModal] = useState(false);

  // Forms
  const [profileForm, setProfileForm] = useState<any>({});
  const [machineForm, setMachineForm] = useState({ name: '', type: '5-Axis CNC Milling', count: 1, tolerance: '±0.003 mm', envelope: '600 x 600 x 500 mm', status: 'Operational', capacity: '85%' });
  const [productForm, setProductForm] = useState({ partNumber: '', name: '', category: 'Precision CNC Machined Parts', material: 'Aluminum 7075-T6', unitPriceUsd: 250, moq: 25, leadTimeDays: 14, stockAvailable: 100, tolerances: '±0.005 mm', description: '' });
  const [certForm, setCertForm] = useState({ name: 'ISO 9001:2015', authority: 'TUV Rheinland', certificateNo: 'CERT-2026-99', expiry: '2028-12-31' });
  const [iotForm, setIotForm] = useState({ gatewayUrl: 'https://iot.abc-manufacturing.com/v1/telemetry', apiKey: 'sec_live_99a812' });

  // Fetch full Digital Twin from backend
  const { data: twinData, isLoading, refetch } = useQuery({
    queryKey: ['supplier-full-twin'],
    queryFn: async () => {
      const res = await apiClient.get('/api/v1/suppliers/twin/full-twin');
      return res.data;
    }
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const profile = twinData?.profile || {
    companyName: "ABC Manufacturing Ltd",
    legalEntity: "ABC Manufacturing & Industrial Technologies Ltd",
    industry: "Aerospace Machining & Precision High-Tolerance Components",
    tier: "Tier 1 Qualified Production Partner",
    digitalTwinId: "TWIN-ABC-MFG-001",
    facilityLocation: "Precision Industrial Corridor, Phase II, Aerospace SEZ",
    facilitySizeSqFt: "45,000 sq.ft High-Precision Manufacturing Plant",
    yearFounded: 2012,
    employees: 180,
    email: "procurement-twin@abc-manufacturing.com",
    phone: "+1 (555) 234-5678",
    description: "AS9100D and ISO 9001:2015 certified aerospace and industrial machining facility specializing in 5-axis complex geometric milling, tight tolerance turning, titanium/Inconel superalloys, and cleanroom aerospace assembly."
  };

  const metrics = twinData?.twinMetrics || {
    trustScore: 96,
    freshnessScore: 98,
    profileCompleteness: 94,
    lastSynced: "2026-10-14 09:30:00 UTC",
    auditStatus: "Fully Compliant (AS9100D & ITAR Active)"
  };

  const capabilities = twinData?.capabilities || {
    coreProcesses: ["5-Axis CNC Milling", "Multi-Tasking Mill-Turn Lathe", "Precision Wire EDM", "Coordinate Metrology (Zeiss CMM)", "Cleanroom Packaging"],
    materialsCertified: ["Titanium Ti-6Al-4V (Grade 5)", "Inconel 718", "Aluminum 7075-T6 & 6061-T651", "Stainless Steel 316L", "PEEK Polymer"],
    precisionTolerance: "±0.003 mm (High Precision)",
    surfaceFinishes: ["MIL-A-8625 Type III Hardcoat Anodizing", "Electropolishing Ra 0.4 µm", "Passivation (ASTM A967)"]
  };

  const machinery = twinData?.machinery || [];
  const products = twinData?.productsCatalog || [];
  const certs = twinData?.certifications || [];
  const terms = twinData?.purchasingTerms || {
    paymentTerms: "Net 30 Days (Electronic Bank Wire)",
    currency: "USD / EUR",
    incoterms: "DDP (Delivered Duty Paid) Buyer Warehouse",
    standardLeadTimeDays: 14,
    expeditedLeadTimeDays: 7,
    volumeRebates: "5% rebate on annual volume > $250k; 8% on > $500k",
    warrantyPeriod: "24 Months Full Replacement Warranty"
  };

  // Profile Save Mutation
  const profileMutation = useMutation({
    mutationFn: async (updated: any) => {
      const res = await apiClient.put('/api/v1/suppliers/twin/profile', updated);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supplier-full-twin'] });
      setShowEditProfileModal(false);
      showToast("Company Digital Twin profile saved successfully!");
    }
  });

  // Machine Add Mutation
  const addMachineMutation = useMutation({
    mutationFn: async (newMach: any) => {
      const res = await apiClient.post('/api/v1/suppliers/twin/machinery', newMach);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supplier-full-twin'] });
      setShowMachineModal(false);
      showToast("New manufacturing machine added to Digital Twin roster!");
    }
  });

  // Machine Delete Mutation
  const deleteMachineMutation = useMutation({
    mutationFn: async (machineId: string) => {
      const res = await apiClient.delete(`/api/v1/suppliers/twin/machinery/${machineId}`);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supplier-full-twin'] });
      showToast("Machine removed from equipment roster.");
    }
  });

  // Product Add Mutation
  const addProductMutation = useMutation({
    mutationFn: async (newProd: any) => {
      const res = await apiClient.post('/api/v1/suppliers/twin/products', newProd);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supplier-full-twin'] });
      setShowProductModal(false);
      showToast("Product offering published to Buyer Discovery catalog!");
    }
  });

  // Product Delete Mutation
  const deleteProductMutation = useMutation({
    mutationFn: async (prodId: string) => {
      const res = await apiClient.delete(`/api/v1/suppliers/twin/products/${prodId}`);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supplier-full-twin'] });
      showToast("Product removed from catalog.");
    }
  });

  // Cert Add Mutation
  const addCertMutation = useMutation({
    mutationFn: async (newCert: any) => {
      const res = await apiClient.post('/api/v1/suppliers/twin/certifications', newCert);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supplier-full-twin'] });
      setShowCertModal(false);
      showToast("Quality certification registered in compliance vault!");
    }
  });

  return (
    <div className="space-y-6 pb-16 max-w-[1600px] mx-auto">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-50 bg-[#0B2550] text-white px-5 py-3 rounded-xl shadow-2xl flex items-center gap-3 border border-blue-400/30 animate-in fade-in slide-in-from-top-4">
          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          <span className="text-sm font-bold">{toastMessage}</span>
        </div>
      )}

      {/* HEADER BREADCRUMB */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Supplier Portal</span>
            <span className="text-slate-300">/</span>
            <span className="text-purple-600 font-bold">My Digital Twin</span>
            <span className="text-slate-300">/</span>
            <span>Company Capability Profile & Master Catalog</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <Factory className="w-8 h-8 text-purple-600" />
            <span>Digital Twin: {profile.companyName}</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            The live digital representation of your firm. Updates made here directly feed into Buyer Discovery, Automated RFQ Matching, and Enterprise Vendor Approvals.
          </p>
        </div>

        {/* Global Action Buttons */}
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => {
              refetch();
              showToast("Digital Twin telemetry re-synchronized with shop-floor IoT.");
            }}
            className="px-3.5 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
          >
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span>Sync Twin</span>
          </button>

          <button
            onClick={() => {
              setProfileForm({ ...profile });
              setShowEditProfileModal(true);
            }}
            className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
          >
            <Edit3 className="w-4 h-4" />
            <span>Edit Company Profile</span>
          </button>
        </div>
      </div>

      {/* TWIN IDENTITY & HEALTH METRICS BANNER */}
      <div className="bg-gradient-to-r from-[#0B2550] via-[#12396e] to-[#0B2550] text-white rounded-2xl shadow-xl overflow-hidden border border-blue-900/50 p-6 md:p-8">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          <div className="space-y-2 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-2.5 py-1 rounded-md text-xs font-black bg-purple-500/30 text-purple-200 border border-purple-400/30">
                {profile.tier}
              </span>
              <span className="px-2.5 py-1 rounded-md text-xs font-bold bg-white/10 text-white flex items-center gap-1">
                <MapPin size={14} className="text-blue-300" />
                {profile.facilityLocation}
              </span>
              <span className="px-2.5 py-1 rounded-md text-xs font-bold bg-emerald-500/30 text-emerald-300 border border-emerald-400/30 flex items-center gap-1">
                <ShieldCheck size={14} /> AS9100D Verified
              </span>
            </div>

            <h2 className="text-3xl font-black tracking-tight text-white flex items-center gap-2">
              <span>{profile.companyName}</span>
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" title="IoT Connected" />
            </h2>
            <p className="text-blue-100/90 text-xs max-w-3xl leading-relaxed">
              {profile.description}
            </p>
          </div>

          {/* Twin Metrics Meter */}
          <div className="flex items-center gap-4 bg-white/10 backdrop-blur-md p-4 rounded-xl border border-white/15 shrink-0">
            <div className="text-center px-3 border-r border-white/15">
              <span className="text-[10px] font-black uppercase text-blue-200 block tracking-wider">
                Twin Trust Score
              </span>
              <span className="text-3xl font-black text-emerald-400 block mt-0.5">
                {metrics.trustScore}%
              </span>
              <span className="text-[10px] text-emerald-300 font-bold block mt-1">
                Verified
              </span>
            </div>

            <div className="text-center px-3 border-r border-white/15">
              <span className="text-[10px] font-black uppercase text-blue-200 block tracking-wider">
                Freshness
              </span>
              <span className="text-2xl font-black text-white block mt-0.5">
                {metrics.freshnessScore}%
              </span>
              <span className="text-[10px] text-blue-300 font-bold block mt-1">
                Live IoT Telemetry
              </span>
            </div>

            <div className="text-center px-3">
              <span className="text-[10px] font-black uppercase text-blue-200 block tracking-wider">
                Completeness
              </span>
              <span className="text-2xl font-black text-purple-300 block mt-0.5">
                {metrics.profileCompleteness}%
              </span>
              <span className="text-[10px] text-purple-200 font-bold block mt-1">
                All 6 Pillars Active
              </span>
            </div>
          </div>
        </div>

        {/* Quick Footer */}
        <div className="mt-6 pt-4 border-t border-white/10 flex flex-wrap items-center justify-between gap-4 text-xs text-blue-200/80">
          <div className="flex items-center gap-6">
            <span>Plant: <strong className="text-white">{profile.facilitySizeSqFt}</strong></span>
            <span>Workforce: <strong className="text-white">{profile.employees} Specialized Machinists</strong></span>
            <span>Founded: <strong className="text-white">{profile.yearFounded}</strong></span>
          </div>
          <span className="text-[11px] text-blue-300 font-mono">Last Synchronized: {metrics.lastSynced}</span>
        </div>
      </div>

      {/* NAVIGATION TABS */}
      <div className="flex border-b border-slate-200 gap-6 text-xs font-bold text-slate-500 overflow-x-auto pb-1">
        <button
          onClick={() => setActiveTab('OVERVIEW')}
          className={`pb-3 flex items-center gap-2 transition-all whitespace-nowrap ${
            activeTab === 'OVERVIEW'
              ? 'text-purple-600 border-b-2 border-purple-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <Building2 className="w-4 h-4" />
          <span>1. Company Overview & Facility</span>
        </button>

        <button
          onClick={() => setActiveTab('MACHINERY')}
          className={`pb-3 flex items-center gap-2 transition-all whitespace-nowrap ${
            activeTab === 'MACHINERY'
              ? 'text-purple-600 border-b-2 border-purple-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <Wrench className="w-4 h-4" />
          <span>2. Machinery & Equipment Roster ({machinery.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('CAPABILITIES')}
          className={`pb-3 flex items-center gap-2 transition-all whitespace-nowrap ${
            activeTab === 'CAPABILITIES'
              ? 'text-purple-600 border-b-2 border-purple-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <Layers className="w-4 h-4" />
          <span>3. Materials & Capabilities</span>
        </button>

        <button
          onClick={() => setActiveTab('PRODUCTS')}
          className={`pb-3 flex items-center gap-2 transition-all whitespace-nowrap ${
            activeTab === 'PRODUCTS'
              ? 'text-purple-600 border-b-2 border-purple-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <Box className="w-4 h-4" />
          <span>4. Manufactured Products Catalog ({products.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('CERTS')}
          className={`pb-3 flex items-center gap-2 transition-all whitespace-nowrap ${
            activeTab === 'CERTS'
              ? 'text-purple-600 border-b-2 border-purple-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <Award className="w-4 h-4" />
          <span>5. Certifications & Compliance ({certs.length})</span>
        </button>

        <button
          onClick={() => setActiveTab('TERMS')}
          className={`pb-3 flex items-center gap-2 transition-all whitespace-nowrap ${
            activeTab === 'TERMS'
              ? 'text-purple-600 border-b-2 border-purple-600 font-black'
              : 'hover:text-slate-800'
          }`}
        >
          <FileSignature className="w-4 h-4" />
          <span>6. Purchasing Terms & Conditions</span>
        </button>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: COMPANY OVERVIEW & FACILITY */}
      {/* ========================================================================= */}
      {activeTab === 'OVERVIEW' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
            <div className="border-b border-slate-100 pb-3 flex items-center justify-between">
              <div>
                <h3 className="text-base font-black text-[#0B2550]">
                  Corporate Entity & Facility Dossier
                </h3>
                <p className="text-xs text-slate-500 font-medium mt-0.5">
                  Verified credentials presented to enterprise buyers during RFQ matching.
                </p>
              </div>
              <button
                onClick={() => {
                  setProfileForm({ ...profile });
                  setShowEditProfileModal(true);
                }}
                className="text-xs font-bold text-purple-600 hover:underline flex items-center gap-1"
              >
                <Edit3 className="w-3.5 h-3.5" />
                <span>Edit Details</span>
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                <span className="text-slate-400 block font-bold">Company Display Name:</span>
                <span className="font-black text-[#0B2550] text-sm">{profile.companyName}</span>
              </div>
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                <span className="text-slate-400 block font-bold">Registered Legal Entity:</span>
                <span className="font-bold text-slate-800 text-sm">{profile.legalEntity}</span>
              </div>
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                <span className="text-slate-400 block font-bold">Industry Sector:</span>
                <span className="font-bold text-slate-800">{profile.industry}</span>
              </div>
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                <span className="text-slate-400 block font-bold">Digital Twin Node:</span>
                <span className="font-mono font-bold text-purple-700">{profile.digitalTwinId}</span>
              </div>
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                <span className="text-slate-400 block font-bold">Manufacturing Facility Size:</span>
                <span className="font-bold text-slate-800">{profile.facilitySizeSqFt}</span>
              </div>
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
                <span className="text-slate-400 block font-bold">Total Workforce / Shifts:</span>
                <span className="font-bold text-slate-800">{profile.employees} Specialized Personnel (3 Active Shifts)</span>
              </div>
            </div>

            <div className="pt-2">
              <span className="text-xs font-bold text-slate-400 block mb-1">Company Executive Overview:</span>
              <p className="text-xs text-slate-700 leading-relaxed bg-slate-50 p-4 rounded-xl border border-slate-100">
                {profile.description}
              </p>
            </div>
          </div>

          {/* Right Column: Contact & Connectivity */}
          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
            <h3 className="text-base font-black text-[#0B2550] border-b border-slate-100 pb-3">
              Official Contact & Telemetry Link
            </h3>

            <div className="space-y-3 text-xs">
              <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-xl border border-slate-100">
                <Mail className="w-4 h-4 text-purple-600 shrink-0" />
                <div>
                  <span className="text-slate-400 block text-[11px]">Procurement Desk:</span>
                  <span className="font-bold text-slate-800">{profile.email}</span>
                </div>
              </div>

              <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-xl border border-slate-100">
                <Phone className="w-4 h-4 text-emerald-600 shrink-0" />
                <div>
                  <span className="text-slate-400 block text-[11px]">Factory Telephone:</span>
                  <span className="font-bold text-slate-800">{profile.phone}</span>
                </div>
              </div>

              <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-xl border border-slate-100">
                <MapPin className="w-4 h-4 text-blue-600 shrink-0" />
                <div>
                  <span className="text-slate-400 block text-[11px]">Plant Address:</span>
                  <span className="font-bold text-slate-800 leading-snug">{profile.facilityLocation}</span>
                </div>
              </div>
            </div>

            <div className="p-4 bg-purple-50/50 rounded-xl border border-purple-100 space-y-2">
              <div className="flex items-center justify-between text-xs font-bold text-purple-900">
                <span className="flex items-center gap-1.5">
                  <Radio className="w-3.5 h-3.5 text-purple-600 animate-pulse" />
                  <span>Shop-Floor IoT Telemetry</span>
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-100 text-emerald-800 font-black">
                  ONLINE
                </span>
              </div>
              <p className="text-[11px] text-slate-600 leading-relaxed">
                Machine telemetry actively streaming feed rates, spindle vibration, and OEE to the buyer verification network.
              </p>
              <div className="flex items-center gap-3 pt-1">
                <Link
                  href="/supplier/telemetry"
                  className="text-xs font-bold text-purple-700 hover:underline flex items-center gap-1"
                >
                  <span>Open Live SCADA Telemetry Console →</span>
                </Link>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: MACHINERY & FACTORY EQUIPMENT ROSTER */}
      {/* ========================================================================= */}
      {activeTab === 'MACHINERY' && (
        <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-4">
            <div>
              <h3 className="text-lg font-black text-[#0B2550]">
                Manufacturing Machinery & Equipment Roster
              </h3>
              <p className="text-xs text-slate-500 font-medium mt-0.5">
                Audited CNC centers, multi-tasking mill-turn lathes, and quality metrology units.
              </p>
            </div>

            <button
              onClick={() => setShowMachineModal(true)}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
            >
              <Plus className="w-4 h-4" />
              <span>Add New Equipment</span>
            </button>
          </div>

          <div className="divide-y divide-slate-100">
            {machinery.map((mach: any) => (
              <div key={mach.id} className="py-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="space-y-1.5 flex-1">
                  <div className="flex items-center gap-2.5">
                    <Factory className="w-4 h-4 text-purple-600" />
                    <h4 className="font-bold text-slate-900 text-sm">{mach.name}</h4>
                    <span className="px-2 py-0.5 rounded text-[10px] font-black uppercase bg-purple-50 text-purple-700">
                      {mach.count || 1} Units Active
                    </span>
                    {mach.iotConnected && (
                      <span className="text-[10px] font-bold text-emerald-600 flex items-center gap-1">
                        <Radio className="w-3 h-3 text-emerald-500 animate-pulse" /> IoT Streaming
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-4 text-xs text-slate-500">
                    <span>Process: <strong className="text-slate-700">{mach.type}</strong></span>
                    <span>Tolerance: <strong className="text-slate-700">{mach.tolerance || '±0.003 mm'}</strong></span>
                    <span>Work Envelope: <strong className="text-slate-700">{mach.envelope || 'Standard'}</strong></span>
                  </div>
                </div>

                <div className="flex items-center gap-2.5 shrink-0">
                  <span className="px-3 py-1 bg-emerald-50 text-emerald-700 font-bold text-xs rounded-lg">
                    {mach.status} (OEE: {mach.capacity})
                  </span>

                  <Link
                    href="/supplier/telemetry"
                    className="px-3 py-1 bg-purple-50 hover:bg-purple-100 text-purple-700 font-bold text-xs rounded-lg flex items-center gap-1 border border-purple-200 transition-colors shadow-xs"
                  >
                    <Radio className="w-3 h-3 text-purple-600 animate-pulse" />
                    <span>Telemetry</span>
                  </Link>

                  <button
                    onClick={() => deleteMachineMutation.mutate(mach.id)}
                    className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                    title="Remove Machine"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: MATERIALS & CAPABILITIES */}
      {activeTab === 'CAPABILITIES' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Core Processes */}
            <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-3">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <h3 className="font-black text-[#0B2550] text-base flex items-center gap-2">
                  <Wrench className="w-4 h-4 text-purple-600" />
                  <span>Core Manufacturing Processes</span>
                </h3>
                <span className="text-xs text-slate-400 font-bold">{capabilities.coreProcesses.length} Verified</span>
              </div>

              <div className="space-y-2">
                {capabilities.coreProcesses.map((proc: string, idx: number) => (
                  <div key={idx} className="p-3 bg-slate-50 rounded-xl border border-slate-100 flex items-center justify-between text-xs font-bold text-slate-800">
                    <span>{proc}</span>
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  </div>
                ))}
              </div>
            </div>

            {/* Certified Materials */}
            <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-3">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <h3 className="font-black text-[#0B2550] text-base flex items-center gap-2">
                  <Layers className="w-4 h-4 text-blue-600" />
                  <span>Certified Materials & Superalloys</span>
                </h3>
                <span className="text-xs text-slate-400 font-bold">{capabilities.materialsCertified.length} Alloys</span>
              </div>

              <div className="space-y-2">
                {capabilities.materialsCertified.map((mat: string, idx: number) => (
                  <div key={idx} className="p-3 bg-slate-50 rounded-xl border border-slate-100 flex items-center justify-between text-xs font-bold text-slate-800">
                    <span>{mat}</span>
                    <span className="text-[10px] font-black uppercase text-blue-700 bg-blue-100 px-2 py-0.5 rounded">
                      Audited Batch Certified
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Precision Tolerances & Surface Finishes */}
          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
            <h3 className="text-base font-black text-[#0B2550] border-b border-slate-100 pb-3">
              Tolerances & Surface Finishing Capabilities
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="p-4 bg-emerald-50/50 rounded-xl border border-emerald-100 space-y-1">
                <span className="text-emerald-900 font-black text-sm block">Precision Tolerance Rating:</span>
                <span className="text-2xl font-black text-emerald-700 block mt-1">{capabilities.precisionTolerance}</span>
                <p className="text-[11px] text-slate-600 pt-1">
                  Inspected via Zeiss PRISMO CMM with 0.8 µm measuring uncertainty.
                </p>
              </div>

              <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-2">
                <span className="text-slate-500 font-black text-xs uppercase block">Surface Finishing Treatments:</span>
                <div className="flex flex-wrap gap-2">
                  {capabilities.surfaceFinishes.map((finish: string, idx: number) => (
                    <span key={idx} className="px-2.5 py-1 bg-white border border-slate-200 rounded-lg text-xs font-bold text-slate-800">
                      {finish}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 4: MANUFACTURED PRODUCTS CATALOG */}
      {/* ========================================================================= */}
      {activeTab === 'PRODUCTS' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-black text-[#0B2550]">
                Manufactured Products & Parts Catalog
              </h3>
              <p className="text-xs text-slate-500 font-medium mt-0.5">
                These are the products and parts enterprise buyers can view, evaluate, and purchase directly from your firm.
              </p>
            </div>

            <button
              onClick={() => setShowProductModal(true)}
              className="px-4 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5 active:scale-95"
            >
              <Plus className="w-4 h-4" />
              <span>Add Product Offering</span>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {products.map((prod: any) => (
              <div
                key={prod.id}
                className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between space-y-4"
              >
                <div className="space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="text-[10px] font-black uppercase text-purple-600 tracking-wider">
                        {prod.category}
                      </span>
                      <h4 className="text-base font-black text-[#0B2550] mt-0.5">
                        {prod.name}
                      </h4>
                      <span className="text-xs font-mono text-slate-400">
                        SKU: {prod.partNumber}
                      </span>
                    </div>

                    <div className="text-right">
                      <span className="text-xl font-black text-emerald-600 block">
                        ${prod.unitPriceUsd.toFixed(2)}
                      </span>
                      <span className="text-[10px] text-slate-400 font-bold">
                        per unit (MOQ: {prod.moq})
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-slate-600 leading-relaxed line-clamp-2">
                    {prod.description}
                  </p>

                  <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-slate-100">
                    <div>
                      <span className="text-slate-400 block text-[11px]">Material Spec:</span>
                      <span className="font-bold text-slate-800">{prod.material}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Precision Tolerance:</span>
                      <span className="font-bold text-slate-800">{prod.tolerances}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Production Lead Time:</span>
                      <span className="font-bold text-blue-600">{prod.leadTimeDays} Days</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[11px]">Physical Inventory:</span>
                      <span className="font-bold text-emerald-700">{prod.stockAvailable} Units On-Hand</span>
                    </div>
                  </div>

                  {/* Physical Inventory Depot Link Badge */}
                  <div className="mt-2 p-2.5 bg-blue-50/60 rounded-xl border border-blue-200/50 flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5 text-blue-900 font-bold">
                      <Box className="w-3.5 h-3.5 text-blue-600 shrink-0" />
                      <span>FGI Twin: <code className="font-mono text-blue-700 font-black">{prod.linkedInventorySku || prod.partNumber}</code></span>
                    </div>
                    <span className="text-[10px] font-black uppercase px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                      {prod.inventoryLocation || 'Depot Bay FG-01'}
                    </span>
                  </div>
                </div>

                <div className="pt-3 border-t border-slate-100 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-slate-400">{prod.id}</span>
                    <Link
                      href="/supplier/inventory"
                      className="text-[11px] font-bold text-blue-600 hover:text-blue-800 flex items-center gap-1 ml-2"
                    >
                      <span>View in Depot</span>
                      <ChevronRight className="w-3 h-3" />
                    </Link>
                  </div>
                  <button
                    onClick={() => deleteProductMutation.mutate(prod.id)}
                    className="p-1 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded"
                    title="Remove Product"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 5: CERTIFICATIONS & AUDITS */}
      {activeTab === 'CERTS' && (
        <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-4">
            <div>
              <h3 className="text-lg font-black text-[#0B2550]">
                Quality, Aerospace & Environmental Certifications
              </h3>
              <p className="text-xs text-slate-500 font-medium mt-0.5">
                Verified third-party credentials reviewed by enterprise compliance audits.
              </p>
            </div>

            <button
              onClick={() => setShowCertModal(true)}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5 active:scale-95"
            >
              <Upload className="w-4 h-4" />
              <span>Register New Certificate</span>
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {certs.map((c: any) => (
              <div key={c.id || c.name} className="p-4 rounded-xl border border-emerald-200 bg-emerald-50/30 flex items-start gap-3">
                <ShieldCheck className="w-7 h-7 text-emerald-600 shrink-0 mt-0.5" />
                <div className="space-y-1 flex-1">
                  <h4 className="font-black text-slate-800 text-sm">{c.name}</h4>
                  <p className="text-xs text-slate-600">
                    Authority: <strong className="text-slate-700">{c.authority || 'Accredited Body'}</strong> • Cert: <code className="text-slate-700">{c.certificateNo}</code>
                  </p>
                  <div className="flex items-center justify-between pt-2">
                    <span className="text-[11px] font-bold text-emerald-700">Valid Through: {c.expiry}</span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-black bg-emerald-200/60 text-emerald-900">
                      VERIFIED ACTIVE
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 6: PURCHASING TERMS & CONDITIONS */}
      {activeTab === 'TERMS' && (
        <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
          <div className="border-b border-slate-100 pb-3">
            <h3 className="text-lg font-black text-[#0B2550]">
              Commercial Purchasing Terms & Operating Conditions
            </h3>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Default procurement terms presented to buyers in the Supplier Network and Master Service Agreements.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
              <span className="text-slate-400 block font-bold">Standard Payment Terms:</span>
              <span className="font-black text-[#0B2550] text-sm">{terms.paymentTerms}</span>
            </div>

            <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
              <span className="text-slate-400 block font-bold">Standard Incoterms:</span>
              <span className="font-black text-[#0B2550] text-sm">{terms.incoterms}</span>
            </div>

            <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
              <span className="text-slate-400 block font-bold">Standard Manufacturing Lead Time:</span>
              <span className="font-bold text-blue-600 text-sm">{terms.standardLeadTimeDays} Calendar Days</span>
            </div>

            <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
              <span className="text-slate-400 block font-bold">Expedited Emergency Lead Time:</span>
              <span className="font-bold text-purple-600 text-sm">{terms.expeditedLeadTimeDays} Days (+{terms.expeditedPremiumPct || 15}% premium)</span>
            </div>

            <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
              <span className="text-slate-400 block font-bold">Volume Rebate Structure:</span>
              <span className="font-bold text-slate-800">{terms.volumeRebates}</span>
            </div>

            <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 space-y-1">
              <span className="text-slate-400 block font-bold">Warranty Period:</span>
              <span className="font-bold text-slate-800">{terms.warrantyPeriod}</span>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: EDIT COMPANY PROFILE */}
      {/* ========================================================================= */}
      {showEditProfileModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-xl w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550]">
                Edit Company Digital Twin Profile
              </h3>
              <button onClick={() => setShowEditProfileModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs max-h-[70vh] overflow-y-auto pr-1">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Company Display Name:</label>
                <input
                  type="text"
                  value={profileForm.companyName || ''}
                  onChange={(e) => setProfileForm({ ...profileForm, companyName: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Registered Legal Entity:</label>
                <input
                  type="text"
                  value={profileForm.legalEntity || ''}
                  onChange={(e) => setProfileForm({ ...profileForm, legalEntity: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Facility Address / Location:</label>
                <input
                  type="text"
                  value={profileForm.facilityLocation || ''}
                  onChange={(e) => setProfileForm({ ...profileForm, facilityLocation: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Official Email:</label>
                  <input
                    type="email"
                    value={profileForm.email || ''}
                    onChange={(e) => setProfileForm({ ...profileForm, email: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                  />
                </div>
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Telephone:</label>
                  <input
                    type="text"
                    value={profileForm.phone || ''}
                    onChange={(e) => setProfileForm({ ...profileForm, phone: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                  />
                </div>
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Company Description & Specialization:</label>
                <textarea
                  rows={4}
                  value={profileForm.description || ''}
                  onChange={(e) => setProfileForm({ ...profileForm, description: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowEditProfileModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={() => profileMutation.mutate(profileForm)}
                className="px-5 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Save Profile
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: ADD MACHINE */}
      {/* ========================================================================= */}
      {showMachineModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550]">
                Add Equipment to Machinery Roster
              </h3>
              <button onClick={() => setShowMachineModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Machine Model & Make:</label>
                <input
                  type="text"
                  placeholder="e.g. DMG Mori DMU 85 monoBLOCK 5-Axis"
                  value={machineForm.name}
                  onChange={(e) => setMachineForm({ ...machineForm, name: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Process Type:</label>
                  <select
                    value={machineForm.type}
                    onChange={(e) => setMachineForm({ ...machineForm, type: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  >
                    <option value="5-Axis CNC Milling">5-Axis CNC Milling</option>
                    <option value="Precision Turning/Milling">Precision Turning/Milling</option>
                    <option value="EDM Wire Cutting">EDM Wire Cutting</option>
                    <option value="Metrology & CMM">Metrology & CMM</option>
                  </select>
                </div>
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Active Machine Count:</label>
                  <input
                    type="number"
                    value={machineForm.count}
                    onChange={(e) => setMachineForm({ ...machineForm, count: Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Precision Tolerance:</label>
                  <input
                    type="text"
                    value={machineForm.tolerance}
                    onChange={(e) => setMachineForm({ ...machineForm, tolerance: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Max Work Envelope:</label>
                  <input
                    type="text"
                    value={machineForm.envelope}
                    onChange={(e) => setMachineForm({ ...machineForm, envelope: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowMachineModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={() => addMachineMutation.mutate(machineForm)}
                className="px-5 py-2 bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Add Machine
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: ADD PRODUCT OFFERING */}
      {/* ========================================================================= */}
      {showProductModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550]">
                Publish New Product to Catalog
              </h3>
              <button onClick={() => setShowProductModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs max-h-[70vh] overflow-y-auto pr-1">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Part Name / Product Title:</label>
                <input
                  type="text"
                  placeholder="e.g. Titanium High-Pressure Pinion Shaft"
                  value={productForm.name}
                  onChange={(e) => setProductForm({ ...productForm, name: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Part SKU / Number:</label>
                  <input
                    type="text"
                    placeholder="e.g. ABC-PIN-902"
                    value={productForm.partNumber}
                    onChange={(e) => setProductForm({ ...productForm, partNumber: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-mono font-bold text-slate-800"
                  />
                </div>
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Material Spec:</label>
                  <input
                    type="text"
                    placeholder="e.g. Titanium Ti-6Al-4V"
                    value={productForm.material}
                    onChange={(e) => setProductForm({ ...productForm, material: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Unit Price ($USD):</label>
                  <input
                    type="number"
                    value={productForm.unitPriceUsd}
                    onChange={(e) => setProductForm({ ...productForm, unitPriceUsd: Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-black text-emerald-600"
                  />
                </div>
                <div>
                  <label className="font-bold text-slate-700 block mb-1">MOQ (pcs):</label>
                  <input
                    type="number"
                    value={productForm.moq}
                    onChange={(e) => setProductForm({ ...productForm, moq: Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Lead Time (Days):</label>
                  <input
                    type="number"
                    value={productForm.leadTimeDays}
                    onChange={(e) => setProductForm({ ...productForm, leadTimeDays: Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
                <div>
                  <label className="font-bold text-slate-700 block mb-1">In-Stock Available Units:</label>
                  <input
                    type="number"
                    value={productForm.stockAvailable}
                    onChange={(e) => setProductForm({ ...productForm, stockAvailable: Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Product Description:</label>
                <textarea
                  rows={2}
                  placeholder="Engineered applications, tolerances, surface finishing..."
                  value={productForm.description}
                  onChange={(e) => setProductForm({ ...productForm, description: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                />
              </div>

              {/* Physical Inventory Provisioning Notice */}
              <div className="p-3 bg-blue-50/70 border border-blue-200/60 rounded-xl flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <Box className="w-4 h-4 text-blue-600 shrink-0" />
                  <div>
                    <span className="font-bold text-blue-900 block">Auto-Sync with Plant Inventory</span>
                    <span className="text-[11px] text-blue-700">Creates live Finished Goods item in Depot Bay FG-01 with initial stock.</span>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-black bg-blue-200 text-blue-900">
                  ENABLED
                </span>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowProductModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={() => addProductMutation.mutate(productForm)}
                className="px-5 py-2 bg-[#0B2550] hover:bg-blue-900 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Publish Product
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: REGISTER CERTIFICATE */}
      {/* ========================================================================= */}
      {showCertModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550]">
                Register Quality / Aerospace Certificate
              </h3>
              <button onClick={() => setShowCertModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Certificate Standard:</label>
                <input
                  type="text"
                  placeholder="e.g. Nadcap NDT (Non-Destructive Testing)"
                  value={certForm.name}
                  onChange={(e) => setCertForm({ ...certForm, name: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Accredited Authority:</label>
                <input
                  type="text"
                  placeholder="e.g. Performance Review Institute (PRI)"
                  value={certForm.authority}
                  onChange={(e) => setCertForm({ ...certForm, authority: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-medium text-slate-800"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Certificate Number:</label>
                  <input
                    type="text"
                    value={certForm.certificateNo}
                    onChange={(e) => setCertForm({ ...certForm, certificateNo: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-mono text-slate-800"
                  />
                </div>
                <div>
                  <label className="font-bold text-slate-700 block mb-1">Expiration Date:</label>
                  <input
                    type="date"
                    value={certForm.expiry}
                    onChange={(e) => setCertForm({ ...certForm, expiry: e.target.value })}
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl font-bold text-slate-800"
                  />
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowCertModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={() => addCertMutation.mutate(certForm)}
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Register Certificate
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: IOT GATEWAY CONFIG */}
      {/* ========================================================================= */}
      {showIotModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 border border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-lg font-black text-[#0B2550] flex items-center gap-2">
                <Radio className="w-5 h-5 text-purple-600" />
                <span>Shop-Floor IoT Telemetry Gateway</span>
              </h3>
              <button onClick={() => setShowIotModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-slate-700 block mb-1">MQTT / REST Telemetry Gateway URL:</label>
                <input
                  type="text"
                  value={iotForm.gatewayUrl}
                  onChange={(e) => setIotForm({ ...iotForm, gatewayUrl: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-mono text-slate-800"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Security Bearer API Key:</label>
                <input
                  type="password"
                  value={iotForm.apiKey}
                  onChange={(e) => setIotForm({ ...iotForm, apiKey: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl font-mono text-slate-800"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => setShowIotModal(false)}
                className="px-4 py-2 bg-white border border-slate-200 text-slate-700 font-bold text-xs rounded-xl hover:bg-slate-50"
              >
                Close
              </button>
              <button
                onClick={async () => {
                  await apiClient.post('/api/v1/suppliers/twin/iot-sync', iotForm);
                  setShowIotModal(false);
                  showToast("IoT gateway connection verified. Streaming machine metrics.");
                }}
                className="px-5 py-2 bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
              >
                Connect Gateway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
