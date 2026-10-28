'use client';

import React, { useState, useEffect, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  Check, ChevronRight, Search, FileText, Calendar, MapPin, 
  Settings, Trash2, ArrowRight, DollarSign, UploadCloud, FileSignature, 
  Box, Plus, Info, Receipt, ShieldCheck, Truck, CheckCircle2, Building2,
  RefreshCw, Sparkles, AlertCircle
} from 'lucide-react';
import Link from 'next/link';
import { apiClient, TEST_SUPPLIER_TENANT_ID } from '@/lib/apiClient';

interface POLineItem {
  id: string | number;
  code: string;
  desc: string;
  ordered: number;
  invoiced: number;
  price: number;
  tax: number;
}

interface PODetail {
  id: string;
  buyer: string;
  buyer_id: string;
  date: string;
  currency: string;
  paymentTerms: string;
  freight: number;
  insurance: number;
  asnTracking?: string;
  carrier?: string;
  shipTo: string;
  items: POLineItem[];
}

const KNOWN_PO_DATA: Record<string, PODetail> = {
  'PO-2025-00123': {
    id: 'PO-2025-00123',
    buyer: 'SupplyTwin Enterprise Corp',
    buyer_id: 'TENANT_BUYER_001',
    date: 'Sep 20, 2025',
    currency: 'USD ($)',
    paymentTerms: 'Net 30 Days (FedNow / ACH Wire)',
    freight: 250.00,
    insurance: 150.00,
    asnTracking: 'FX-TEST-88912-US',
    carrier: 'FedEx Aerospace Priority Direct',
    shipTo: 'Boeing Delivery Center, Bay 4, Seattle, WA',
    items: [
      { id: 1, code: 'FG-ACT-SHF-01', desc: 'Precision CNC 5-Axis Avionics Enclosure (7075-T6)', ordered: 50, invoiced: 50, price: 350.00, tax: 18 },
      { id: 2, code: 'FG-FLG-ASMY-88', desc: 'Titanium Grade 5 Pinion Spline Shaft (Ti-6Al-4V)', ordered: 20, invoiced: 20, price: 400.00, tax: 18 },
      { id: 3, code: 'FLG-AN-03', desc: 'MIL-Spec Hardcoat Anodized Hydraulic Flange Ring', ordered: 40, invoiced: 40, price: 100.00, tax: 18 },
    ]
  },
  'PO-2025-00089': {
    id: 'PO-2025-00089',
    buyer: 'Global Aerospace Systems Corp',
    buyer_id: 'TENANT_BUYER_001',
    date: 'Sep 15, 2025',
    currency: 'USD ($)',
    paymentTerms: 'Net 30 Days',
    freight: 320.00,
    insurance: 180.00,
    asnTracking: 'FX-8841920-US',
    carrier: 'FedEx Freight Direct',
    shipTo: 'Avionics Assembly Plant, Dallas, TX',
    items: [
      { id: 1, code: 'ACT-MNF-718', desc: 'Inconel 718 Hydraulic Actuator Manifold', ordered: 85, invoiced: 85, price: 347.05, tax: 18 }
    ]
  },
  'PO-2025-00045': {
    id: 'PO-2025-00045',
    buyer: 'North American Defense Corp',
    buyer_id: 'TENANT_BUYER_001',
    date: 'Sep 02, 2025',
    currency: 'USD ($)',
    paymentTerms: 'Net 45 Days',
    freight: 450.00,
    insurance: 250.00,
    asnTracking: 'FX-9921041-US',
    carrier: 'FedEx Freight Direct',
    shipTo: 'Defense Logistics Depo, Fort Worth, TX',
    items: [
      { id: 1, code: 'PIN-SFT-TI64', desc: 'Titanium Grade 5 Pinion Drive Shaft', ordered: 65, invoiced: 65, price: 320.00, tax: 18 },
      { id: 2, code: 'ABC-FLG-718', desc: 'High-Pressure Hydraulic Flange Ring', ordered: 18, invoiced: 18, price: 483.33, tax: 18 }
    ]
  }
};

function CreateInvoiceContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const urlPoId = searchParams.get('po_id') || 'PO-2025-00123';
  const [selectedPoId, setSelectedPoId] = useState<string>(urlPoId);
  const [invoiceNumber, setInvoiceNumber] = useState<string>(`INV-${new Date().getFullYear()}-${Math.floor(1000 + Math.random() * 9000)}`);
  const [invoiceDate, setInvoiceDate] = useState<string>(new Date().toISOString().split('T')[0]);
  const [notes, setNotes] = useState<string>('Standard Commercial Invoice flipped from verified Advance Shipping Notice & Shop Floor Dispatch.');
  const [remittanceAccount, setRemittanceAccount] = useState<string>('JPMorgan Chase Commercial (Fedwire / ACH) - **** 9821');

  // Load server POs
  const { data: serverPOs = [] } = useQuery({
    queryKey: ['supplier-pos', TEST_SUPPLIER_TENANT_ID],
    queryFn: async () => {
      try {
        const response = await apiClient.get(`/api/v1/procurement/po?tenant_id=${TEST_SUPPLIER_TENANT_ID}`);
        return response.data;
      } catch (err) {
        return [];
      }
    }
  });

  // Active PO state
  const activePO: PODetail = KNOWN_PO_DATA[selectedPoId] || {
    id: selectedPoId,
    buyer: 'SupplyTwin Enterprise Corp',
    buyer_id: 'TENANT_BUYER_001',
    date: 'Oct 01, 2025',
    currency: 'USD ($)',
    paymentTerms: 'Net 30 Days',
    freight: 250.00,
    insurance: 150.00,
    asnTracking: 'FX-TEST-88912-US',
    carrier: 'FedEx Freight Direct',
    shipTo: 'Commercial Fulfillment Bay 1, Seattle, WA',
    items: [
      { id: 1, code: 'FG-ACT-SHF-01', desc: 'Precision CNC 5-Axis Aerospace Assembly', ordered: 50, invoiced: 50, price: 350.00, tax: 18 }
    ]
  };

  const [items, setItems] = useState<POLineItem[]>(activePO.items);

  // When PO changes, sync items
  useEffect(() => {
    if (KNOWN_PO_DATA[selectedPoId]) {
      setItems(KNOWN_PO_DATA[selectedPoId].items);
    }
  }, [selectedPoId]);

  // Dynamic calculations
  const subtotal = items.reduce((acc, item) => acc + (item.invoiced * item.price), 0);
  const taxAmount = items.reduce((acc, item) => acc + (item.invoiced * item.price * (item.tax / 100)), 0);
  const freight = activePO.freight;
  const insurance = activePO.insurance;
  const totalAmount = subtotal + taxAmount + freight + insurance;

  // Submit invoice mutation
  const invoiceMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        invoice_id: invoiceNumber,
        po_id: activePO.id,
        taxable_amount: subtotal,
        tax_percent: 18.0,
        total_amount: Math.round(totalAmount * 100) / 100,
        terms: activePO.paymentTerms,
        signature: 'Apex Tooling Inc. - Authorized Finance Officer',
        buyer_tenant_id: activePO.buyer_id || 'TENANT_BUYER_001',
        supplier_tenant_id: TEST_SUPPLIER_TENANT_ID,
        due_date: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
        description: `Commercial Invoice for ${activePO.id} - ${activePO.buyer}. Shipped under ASN ${activePO.asnTracking || 'FX-TEST-88912-US'}.`,
        match_status: 'MATCHED'
      };
      const res = await apiClient.post('/api/v1/finance/invoices', payload);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['supplier-invoices'] });
      queryClient.invalidateQueries({ queryKey: ['supplier-pos'] });
    }
  });

  if (invoiceMutation.isSuccess) {
    return (
      <div className="max-w-4xl mx-auto space-y-6 pt-10 pb-20 animate-in fade-in duration-500 text-center">
        <div className="w-24 h-24 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-6 shadow-inner">
          <Receipt size={48} className="text-emerald-600 animate-bounce"/>
        </div>
        
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-black bg-emerald-100 text-emerald-800 border border-emerald-300 mb-2">
          <ShieldCheck size={14} className="text-emerald-700"/>
          <span>AUTOMATICALLY 3-WAY MATCHED & AUDITED</span>
        </div>

        <h1 className="text-3xl font-black text-[#0B2550] tracking-tight mb-2">Commercial Invoice Created Successfully!</h1>
        <p className="text-slate-500 font-medium text-base max-w-lg mx-auto">
          Invoice <strong>{invoiceNumber}</strong> has been flipped from <strong>{activePO.id}</strong> and posted to the Buyer Enterprise Accounts Payable network.
        </p>
        
        <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-xl mt-8 mx-auto max-w-lg text-left space-y-3.5">
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-xs font-bold text-slate-500 uppercase">Invoice Number</span>
            <span className="font-mono font-black text-slate-900">{invoiceNumber}</span>
          </div>
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-xs font-bold text-slate-500 uppercase">Purchase Order</span>
            <span className="font-mono font-bold text-blue-600">{activePO.id}</span>
          </div>
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-xs font-bold text-slate-500 uppercase">Buyer Organization</span>
            <span className="font-bold text-slate-800">{activePO.buyer}</span>
          </div>
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-xs font-bold text-slate-500 uppercase">Advance Shipping Reference</span>
            <span className="font-mono font-bold text-emerald-700">{activePO.asnTracking || 'FX-TEST-88912-US'}</span>
          </div>
          <div className="flex justify-between border-b border-slate-100 pb-2.5">
            <span className="text-xs font-bold text-slate-500 uppercase">Due Date</span>
            <span className="font-bold text-slate-800">{new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toLocaleDateString()}</span>
          </div>
          <div className="flex justify-between pt-1 items-center">
            <span className="text-xs font-black text-slate-500 uppercase">Total Billed Amount</span>
            <span className="font-black text-[#0B2550] text-2xl">${totalAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          </div>
        </div>

        <div className="flex flex-wrap gap-4 justify-center mt-8">
          <Link 
            href="/supplier/invoices" 
            className="px-6 py-3 bg-slate-100 text-slate-700 font-bold rounded-xl hover:bg-slate-200 transition-colors shadow-sm"
          >
            View AR Invoices Ledger
          </Link>
          <Link 
            href="/supplier/smart-contracts" 
            className="px-6 py-3 bg-purple-600 text-white font-bold rounded-xl hover:bg-purple-700 transition-colors shadow-lg shadow-purple-600/20 flex items-center gap-2"
          >
            <Sparkles size={16}/>
            <span>Execute Smart Contract Auto-Settlement</span>
            <ArrowRight size={16}/>
          </Link>
          <Link 
            href="/supplier/orders" 
            className="px-6 py-3 bg-white border border-slate-200 text-slate-700 font-bold rounded-xl hover:bg-slate-50 transition-colors"
          >
            Fulfillment Desk
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-28 pt-4">
      {/* HEADER BREADCRUMB */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="text-[11px] font-black uppercase tracking-wider text-slate-400 flex items-center gap-2 mb-1">
            <span>Supplier Portal</span> 
            <ChevronRight size={12}/> 
            <span>Accounts Receivable</span> 
            <ChevronRight size={12}/> 
            <span className="text-blue-600 font-bold">Automated PO-to-Invoice Flip</span>
          </div>
          <h1 className="text-3xl font-black text-[#0B2550] tracking-tight flex items-center gap-2.5">
            <FileSignature className="w-8 h-8 text-blue-600" />
            <span>Generate Commercial Invoice (PO-Flip)</span>
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Zero-keying invoice generation pre-filled with confirmed purchase order contract parameters, manufactured line items, and ASN logistics tracking.
          </p>
        </div>

        {/* PO Quick Selector */}
        <div className="flex items-center gap-2 bg-slate-50 p-2 rounded-2xl border border-slate-200">
          <span className="text-xs font-bold text-slate-500 pl-2">Select Active PO:</span>
          <select 
            value={selectedPoId}
            onChange={(e) => setSelectedPoId(e.target.value)}
            className="bg-white border border-slate-300 text-slate-800 font-bold text-xs rounded-xl p-2 focus:ring-2 focus:ring-blue-500 outline-none cursor-pointer"
          >
            <option value="PO-2025-00123">PO-2025-00123 ($29,500.00 - Shipped w/ ASN)</option>
            <option value="PO-2025-00089">PO-2025-00089 ($29,500.00 - Shipped)</option>
            <option value="PO-2025-00045">PO-2025-00045 ($29,500.00 - Shipped)</option>
            {serverPOs
              .filter((spo: any) => !['PO-2025-00123', 'PO-2025-00089', 'PO-2025-00045'].includes(spo.id))
              .map((spo: any) => (
                <option key={spo.id} value={spo.id}>{spo.id} (${Number(spo.total_amount || 0).toLocaleString()})</option>
              ))
            }
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* LEFT COLUMN - INVOICE FORM */}
        <div className="xl:col-span-2 space-y-6">
          
          {/* Basic Info */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-5">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <h2 className="text-base font-black text-[#0B2550] flex items-center gap-2">
                <FileText className="text-blue-500" size={18}/> 
                <span>Commercial Invoice Parameters</span>
              </h2>
              <span className="px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-black border border-blue-200">
                Flipped from {activePO.id}
              </span>
            </div>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Invoice Number <span className="text-red-500">*</span>
                </label>
                <input 
                  type="text" 
                  value={invoiceNumber}
                  onChange={(e) => setInvoiceNumber(e.target.value)}
                  className="w-full border border-slate-300 rounded-xl p-2.5 focus:ring-2 focus:ring-blue-500 outline-none font-mono font-bold text-slate-800 text-sm" 
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Invoice Issue Date <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <input 
                    type="date" 
                    value={invoiceDate}
                    onChange={(e) => setInvoiceDate(e.target.value)}
                    className="w-full border border-slate-300 rounded-xl p-2.5 focus:ring-2 focus:ring-blue-500 outline-none font-bold text-slate-800 text-sm" 
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Supplier Tax ID / CAGE Code
                </label>
                <input 
                  type="text" 
                  value="CAGE: 1K892 • US-EIN: 91-4402911" 
                  className="w-full border border-slate-200 rounded-xl p-2.5 bg-slate-50 text-slate-600 font-mono text-xs font-bold" 
                  readOnly 
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                  Remittance Settlement Routing
                </label>
                <select 
                  value={remittanceAccount}
                  onChange={(e) => setRemittanceAccount(e.target.value)}
                  className="w-full border border-slate-300 rounded-xl p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-xs font-bold text-slate-800"
                >
                  <option>JPMorgan Chase Commercial (Fedwire / ACH) - **** 9821</option>
                  <option>Citibank Enterprise Treasury (Real-Time ACH) - **** 4410</option>
                  <option>Enterprise Smart Contract Escrow Release Wallet</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
                Invoice Memo / Commercial Contract Description
              </label>
              <textarea 
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                className="w-full border border-slate-300 rounded-xl p-2.5 focus:ring-2 focus:ring-blue-500 outline-none text-xs font-medium text-slate-700"
              />
            </div>
          </div>

          {/* Line Items (Flipped from PO) */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 flex flex-col overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-gradient-to-r from-blue-50/50 to-white">
              <div>
                <h2 className="text-base font-black text-[#0B2550] flex items-center gap-2">
                  <Box className="text-blue-500" size={18}/> 
                  <span>Manufactured Line Items (PO-Flip)</span>
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">Pre-populated from confirmed purchase order commitments.</p>
              </div>
              <div className="flex items-center gap-2 text-xs font-bold text-blue-700 bg-blue-100/70 px-3 py-1.5 rounded-xl border border-blue-200">
                <Info size={14}/> 
                <span>Contract pricing locked from PO</span>
              </div>
            </div>
            
            <div className="overflow-x-auto p-5">
              <table className="w-full text-xs text-left">
                <thead className="text-slate-400 font-bold border-b border-slate-200">
                  <tr>
                    <th className="pb-3 w-10">#</th>
                    <th className="pb-3 text-slate-700">SKU Code</th>
                    <th className="pb-3 text-slate-700">Description</th>
                    <th className="pb-3 text-center text-slate-500">PO Qty</th>
                    <th className="pb-3 text-center text-blue-900 bg-blue-50/60 rounded-t-xl">Invoiced Qty <span className="text-red-500">*</span></th>
                    <th className="pb-3 text-right text-slate-700">Unit Price ($)</th>
                    <th className="pb-3 text-right text-slate-900">Ext Total ($)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((item, index) => (
                    <tr key={item.id} className="hover:bg-slate-50/60 transition-colors">
                      <td className="py-3 text-slate-400 font-medium">{index + 1}</td>
                      <td className="py-3 font-mono font-bold text-slate-700">{item.code}</td>
                      <td className="py-3 text-slate-600 max-w-xs">{item.desc}</td>
                      <td className="py-3 text-center text-slate-500 font-medium">{item.ordered} pcs</td>
                      <td className="py-2 text-center bg-blue-50/30">
                        <input 
                          type="number" 
                          min={1}
                          max={item.ordered}
                          value={item.invoiced} 
                          onChange={(e) => {
                            const newItems = [...items];
                            newItems[index].invoiced = parseInt(e.target.value) || 0;
                            setItems(newItems);
                          }}
                          className="w-16 border border-blue-300 rounded-lg p-1.5 text-center font-bold text-blue-900 focus:ring-2 focus:ring-blue-500 outline-none text-xs" 
                        />
                      </td>
                      <td className="py-3 text-right text-slate-600 font-medium">${item.price.toFixed(2)}</td>
                      <td className="py-3 font-bold text-slate-900 text-right font-mono">${(item.invoiced * item.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* ASN & Quality Compliance Attachments */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-4">
            <h2 className="text-base font-black text-[#0B2550] flex items-center gap-2">
              <Truck className="text-emerald-500" size={18}/> 
              <span>Advance Shipping Notice (ASN) & Logistics Linkage</span>
            </h2>
            
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
              <div className="p-3.5 bg-emerald-50/60 rounded-xl border border-emerald-200 space-y-1">
                <span className="font-bold text-emerald-900 block">ASN Tracking Number</span>
                <span className="font-mono font-black text-emerald-800 text-sm">{activePO.asnTracking || 'FX-TEST-88912-US'}</span>
                <p className="text-[10px] text-emerald-700">Verified dispatched from Finish Goods Depot</p>
              </div>

              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-1">
                <span className="font-bold text-slate-700 block">Carrier & Service</span>
                <span className="font-bold text-slate-800 text-sm">{activePO.carrier || 'FedEx Aerospace Priority'}</span>
                <p className="text-[10px] text-slate-500">Bill of Lading: BOL-994120</p>
              </div>

              <div className="p-3.5 bg-blue-50/60 rounded-xl border border-blue-200 space-y-1">
                <span className="font-bold text-blue-900 block">Destination Depo</span>
                <span className="font-bold text-blue-800 text-sm truncate block">{activePO.shipTo}</span>
                <p className="text-[10px] text-blue-700">Dock receipt auto-matched on arrival</p>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN - SUMMARY & MATCHING RULES */}
        <div className="xl:col-span-1 space-y-6">
          
          {/* Purchase Order Context */}
          <div className="bg-gradient-to-br from-blue-900 to-[#0B2550] rounded-2xl p-6 text-white relative overflow-hidden shadow-xl">
            <div className="absolute top-0 right-0 p-4 opacity-10">
              <DollarSign size={100}/>
            </div>
            
            <div className="relative z-10 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="font-black text-sm uppercase tracking-wider text-blue-200">PO Contract Match</h3>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-blue-500/30 text-blue-200 border border-blue-400/30">
                  VERIFIED
                </span>
              </div>

              <div className="space-y-2.5 text-xs">
                <div className="flex justify-between border-b border-blue-800/60 pb-2">
                  <span className="text-blue-300">Buyer Enterprise</span>
                  <span className="font-bold text-white text-right">{activePO.buyer}</span>
                </div>
                <div className="flex justify-between border-b border-blue-800/60 pb-2">
                  <span className="text-blue-300">Contract PO Number</span>
                  <span className="font-mono font-bold text-white">{activePO.id}</span>
                </div>
                <div className="flex justify-between border-b border-blue-800/60 pb-2">
                  <span className="text-blue-300">Payment Terms</span>
                  <span className="font-bold text-white">{activePO.paymentTerms}</span>
                </div>
                <div className="flex justify-between pb-1">
                  <span className="text-blue-300">Contract Issue Date</span>
                  <span className="font-bold text-white">{activePO.date}</span>
                </div>
              </div>
              
              <div className="p-3 bg-white/10 rounded-xl border border-white/10 text-xs text-blue-100 font-medium flex items-start gap-2 backdrop-blur-sm">
                <ShieldCheck size={16} className="text-emerald-400 shrink-0 mt-0.5"/>
                <p className="text-[11px] leading-relaxed">
                  Flipping this PO automatically locks in <strong>3-Way Matching</strong> against the buyer's purchase order and your Advance Shipping Notice.
                </p>
              </div>
            </div>
          </div>

          {/* Financial Totals Breakdown */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-6 space-y-4">
            <h3 className="font-black text-[#0B2550] text-base border-b border-slate-100 pb-3">Invoice Financial Breakdown</h3>
            
            <div className="space-y-3 text-xs">
              <div className="flex justify-between text-slate-600">
                <span>Subtotal (Invoiced Items)</span>
                <span className="font-mono font-bold text-slate-800">${subtotal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between text-slate-600">
                <span>Freight & Handling (From PO)</span>
                <span className="font-mono font-bold text-slate-800">${freight.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              </div>
              <div className="flex justify-between text-slate-600">
                <span>Logistics Transit Insurance</span>
                <span className="font-mono font-bold text-slate-800">${insurance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              </div>
              <div className="border-t border-slate-100 pt-2 flex justify-between text-slate-600">
                <span>Aerospace Tax (18% Standard)</span>
                <span className="font-mono font-bold text-slate-800">${taxAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              </div>
              
              <div className="border-t-2 border-blue-100 mt-3 pt-3 flex justify-between items-center">
                <span className="font-black text-blue-900 text-sm">Net Commercial Total</span>
                <span className="font-mono font-black text-[#0B2550] text-2xl">${totalAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              </div>
            </div>

            <div className="p-3 bg-amber-50 rounded-xl border border-amber-200 text-amber-900 text-[11px] flex items-center gap-2">
              <AlertCircle size={15} className="text-amber-600 shrink-0"/>
              <span>Funds will settle into the remittance account via FedNow / Wire or Smart Contract upon approval.</span>
            </div>
          </div>
        </div>
      </div>

      {/* BOTTOM ACTION BAR */}
      <div className="fixed bottom-0 left-0 right-0 md:left-64 bg-white/95 backdrop-blur-md border-t border-slate-200 p-4 px-8 flex justify-between items-center z-40 shadow-[0_-4px_16px_rgba(0,0,0,0.06)]">
        <Link 
          href="/supplier/orders" 
          className="px-5 py-2.5 text-slate-600 bg-white border border-slate-300 font-bold text-xs rounded-xl hover:bg-slate-50 transition-colors"
        >
          Cancel & Return to Orders
        </Link>
        
        <div className="flex items-center gap-3">
          <button 
            type="button"
            onClick={() => invoiceMutation.mutate()} 
            disabled={invoiceMutation.isPending} 
            className={`px-8 py-2.5 bg-blue-600 text-white font-bold text-xs rounded-xl shadow-lg shadow-blue-600/30 flex items-center gap-2 active:scale-95 ${
              invoiceMutation.isPending ? 'opacity-70 cursor-wait' : 'hover:bg-blue-700 transition-colors'
            }`}
          >
            {invoiceMutation.isPending ? (
              <>
                <RefreshCw size={14} className="animate-spin"/>
                <span>Creating Commercial Invoice...</span>
              </>
            ) : (
              <>
                <Receipt size={16}/>
                <span>Submit Commercial Invoice (PO-Flip)</span>
                <ArrowRight size={14}/>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function CreateInvoicePOFlipPage() {
  return (
    <Suspense fallback={
      <div className="p-12 text-center text-slate-500 font-bold flex items-center justify-center gap-2">
        <RefreshCw size={18} className="animate-spin text-blue-600"/>
        <span>Loading PO-to-Invoice Workstation...</span>
      </div>
    }>
      <CreateInvoiceContent />
    </Suspense>
  );
}
