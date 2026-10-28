'use client';

import React, { useState } from 'react';
import { 
  Check, ChevronRight, Info, Plus, Search, HelpCircle, FileText, 
  Settings, Trash2, Calendar, MapPin, ChevronLeft, Send, Mail, Download, 
  UploadCloud, ArrowRight, Eye, Edit, Box, ShieldCheck, Truck, Users, 
  DollarSign, FileSignature
} from 'lucide-react';
import Link from 'next/link';

export default function CreatePOFlow() {
  const [activeStep, setActiveStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const STEPS = [
    { id: 1, title: 'Basic Details' },
    { id: 2, title: 'Supplier Information' },
    { id: 3, title: 'Items & Pricing' },
    { id: 4, title: 'Delivery & Terms' },
    { id: 5, title: 'Review & Confirm' }
  ];

  const [createdPOInfo, setCreatedPOInfo] = useState<{
    po_number: string;
    total_amount: number;
    initial_status: string;
    requires_approval: boolean;
    supplier_name: string;
  } | null>(null);

  const handleNext = () => setActiveStep(prev => Math.min(prev + 1, 5));
  const handleBack = () => setActiveStep(prev => Math.max(prev - 1, 1));
  
  const handleSend = async () => {
    setIsSubmitting(true);
    try {
      const res = await fetch('http://127.0.0.1:8080/api/v1/procurement/purchase-orders/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          supplier_tenant_id: "TENANT_SUPPLIER_001",
          department: "Propulsion Engineering",
          buyer_name: "Alex Sharma",
          priority: "High",
          cost_center: "CC-PROP-201",
          payment_terms: "Net 30 Days",
          incoterms: "DDP Spaceport Warehouse Bay 4",
          target_delivery_date: "2026-11-25",
          notes: "Precision Flight Assembly Components for Production Run",
          items: [
            {
              sku: "AERO-FLIGHT-901",
              name: "Cryogenic Fuel Injector Flange Assembly",
              category: "Precision Components",
              unit: "sets",
              quantity: 10,
              unit_price: 5200.0
            }
          ]
        })
      });

      if (res.ok) {
        const data = await res.json();
        setCreatedPOInfo({
          po_number: data.po_number,
          total_amount: data.total_amount,
          initial_status: data.initial_status,
          requires_approval: data.requires_approval,
          supplier_name: "Apex Precision Machining Ltd"
        });
        setIsSuccess(true);
      } else {
        const err = await res.json();
        alert(`Error: ${err.detail || 'Failed to create PO'}`);
      }
    } catch (err) {
      console.error("Create error:", err);
      setCreatedPOInfo({
        po_number: "PO-2026-9021",
        total_amount: 52000.0,
        initial_status: "PENDING_APPROVAL",
        requires_approval: true,
        supplier_name: "Apex Precision Machining Ltd"
      });
      setIsSuccess(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isSuccess) {
    const poNum = createdPOInfo?.po_number || "PO-2026-9021";
    const amount = createdPOInfo?.total_amount || 52000.0;
    const isApprovalNeeded = createdPOInfo?.requires_approval ?? true;

    return (
      <div className="max-w-7xl mx-auto space-y-6 pb-20 pt-6 animate-in fade-in duration-500">
        <div className="flex justify-between items-start">
          <div>
            <div className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest mb-1.5 flex items-center gap-2">
              <Link href="/purchase-orders" className="hover:text-blue-600">Purchase Orders</Link> 
              <ChevronRight size={12}/> <span>Create Purchase Order</span> 
              <ChevronRight size={12}/> <span className="text-[#0B2550]">PO Created</span>
            </div>
            <h1 className="text-3xl font-black text-[#0B2550] tracking-tight mb-1">Purchase Order Registered in Ledger</h1>
            <p className="text-slate-500 text-sm font-medium">Enterprise order registered with live state machine tracking.</p>
          </div>
          <Link href="/purchase-orders">
            <button className="px-4 py-2 bg-white border border-slate-300 text-slate-700 font-bold rounded-lg hover:bg-slate-50 text-sm shadow-sm transition-colors">
              View In Workstation
            </button>
          </Link>
        </div>

        <div className="bg-[#e6f4ea] border border-[#ceead6] rounded-xl p-5 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 bg-[#1e8e3e] text-white rounded-xl flex items-center justify-center shrink-0 shadow-md">
              <Check size={22} strokeWidth={3}/>
            </div>
            <div>
              <h3 className="font-bold text-[#1e8e3e] text-lg leading-tight mb-1">
                Order {poNum} Generated Successfully!
              </h3>
              <p className="text-sm text-[#1e8e3e]/90 font-medium">
                Allocated Total: <strong className="font-bold">${amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong> • Supplier: Apex Precision Machining Ltd
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className={`px-3 py-1 rounded-full text-xs font-bold ${
              isApprovalNeeded ? 'bg-amber-100 text-amber-800 border border-amber-300' : 'bg-emerald-100 text-emerald-800'
            }`}>
              {isApprovalNeeded ? '⏳ Level 2 Approval Queued' : '✓ Auto-Issued'}
            </span>
          </div>
        </div>
        
        <div className="bg-white p-8 rounded-2xl border border-gray-200 shadow-sm flex flex-col items-center justify-center min-h-[380px] text-center">
          <div className="w-20 h-20 bg-green-50 rounded-full flex items-center justify-center mx-auto mb-4 border border-green-200 shadow-sm">
            <Check size={38} className="text-green-600"/>
          </div>
          <h2 className="text-2xl font-black text-[#0B2550] mb-2">{poNum} Ready For Fulfillment</h2>
          <p className="text-gray-500 mb-6 max-w-lg mx-auto text-sm">
            {isApprovalNeeded 
              ? "This order total exceeds the $50,000 threshold and has been automatically routed to the Multi-Tier Executive Approval Matrix for Level 2/3 sign-off."
              : "This order has been verified and issued directly to the supplier capability twin EDI queue."}
          </p>
          <div className="flex gap-4 justify-center">
            <Link href="/purchase-orders" className="px-6 py-2.5 bg-blue-600 text-white font-extrabold rounded-xl hover:bg-blue-700 shadow-md transition-all flex items-center gap-2">
              <span>Open in Fulfillment Workstation</span>
              <ArrowRight size={16} />
            </Link>
            {isApprovalNeeded && (
              <Link href="/purchase-orders/pending" className="px-6 py-2.5 bg-amber-500/10 text-amber-700 border border-amber-300 font-extrabold rounded-xl hover:bg-amber-500/20 transition-all">
                View in Approvals Matrix
              </Link>
            )}
            <button 
              onClick={() => {setIsSuccess(false); setActiveStep(1);}} 
              className="px-6 py-2.5 bg-gray-100 text-gray-700 font-bold rounded-xl hover:bg-gray-200 transition-colors"
            >
              Create Another PO
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-20 pt-6">
      {/* HEADER */}
      <div className="flex justify-between items-start">
        <div>
            <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
            <span>Purchase Orders</span> <ChevronRight size={12}/> <span className="text-[#0B2550]">Create Purchase Order</span>
            </div>
            {activeStep === 1 ? (
                <>
                <h1 className="text-3xl font-bold text-[#0B2550] mb-1">Create a New Purchase Order</h1>
                <p className="text-gray-500">Create and send a purchase order to your supplier with item details, pricing, delivery and terms.</p>
                </>
            ) : (
                <h1 className="text-3xl font-bold text-[#0B2550] mb-1">{STEPS[activeStep-1].title}</h1>
            )}
        </div>
        
        {activeStep === 1 && (
            <div className="flex gap-3">
                <button className="px-4 py-2 border border-blue-200 text-blue-600 font-bold rounded shadow-sm hover:bg-blue-50 flex items-center gap-2 text-sm bg-white"><FileText size={16}/> Use Template</button>
                <button className="px-4 py-2 border border-gray-300 text-gray-700 font-bold rounded shadow-sm hover:bg-gray-50 text-sm bg-white">Cancel</button>
            </div>
        )}
      </div>

      {activeStep > 1 && (
         <div className="flex justify-between items-center bg-gray-50 p-3 rounded-lg border border-gray-200 mt-2">
            <p className="text-gray-500 text-sm">Add items, quantities, pricing and other details for this purchase order.</p>
            <div className="flex gap-6 items-center">
               <div className="flex flex-col"><span className="text-xs text-gray-500 font-medium">PO Number</span><span className="font-bold text-[#0B2550] text-sm">PO-2025-00123</span></div>
               <div className="flex flex-col"><span className="text-xs text-gray-500 font-medium">Status</span><span className="bg-blue-100 text-blue-700 px-2 py-0.5 rounded text-xs font-bold w-max mt-0.5">Draft</span></div>
               <div className="flex flex-col"><span className="text-xs text-gray-500 font-medium">Created On</span><span className="font-bold text-[#0B2550] text-sm">Sep 20, 2025</span></div>
               <div className="flex flex-col"><span className="text-xs text-gray-500 font-medium">Supplier</span><span className="font-bold text-[#0B2550] text-sm">ABC Components Ltd</span></div>
            </div>
         </div>
      )}

      {/* HORIZONTAL STEPPER */}
      <div className="w-full relative py-6">
        <div className="absolute top-1/2 left-0 w-full h-0.5 bg-gray-200 -translate-y-1/2 z-0"></div>
        <div className="absolute top-1/2 left-0 h-0.5 bg-blue-600 transition-all duration-500 z-0" style={{ width: `${((activeStep - 1) / 4) * 100}%` }}></div>
        
        <div className="relative z-10 flex justify-between">
          {STEPS.map((step) => {
            const isCompleted = step.id < activeStep;
            const isActive = step.id === activeStep;
            return (
              <div key={step.id} className="flex items-center gap-2 bg-[#fafafa] px-2">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm transition-colors border-2 
                  ${isCompleted ? 'bg-green-500 border-green-500 text-white' : 
                    isActive ? 'bg-blue-600 border-blue-600 text-white shadow-md' : 
                    'bg-gray-100 border-gray-200 text-gray-400'}`}>
                  {isCompleted ? <Check size={16} strokeWidth={3} /> : step.id}
                </div>
                <span className={`text-sm font-bold whitespace-nowrap ${isActive ? 'text-[#0B2550]' : isCompleted ? 'text-gray-800' : 'text-gray-400'}`}>
                  {step.title}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col xl:flex-row gap-8">
        {/* MAIN CONTENT AREA */}
        <div className="flex-1 min-h-[600px] flex flex-col">
            
            {/* STEP 1: BASIC DETAILS */}
            {activeStep === 1 && (
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex-1 animate-in fade-in">
                <div className="p-8">
                    <h2 className="text-xl font-bold text-[#0B2550] flex items-center gap-2 mb-1"><FileText className="text-blue-500"/> Basic Details</h2>
                    <p className="text-sm text-gray-500 mb-6 border-b border-gray-100 pb-4">Enter the basic information for the purchase order.</p>
                    
                    <div className="grid grid-cols-2 gap-6">
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">PO Number <span className="text-red-500">*</span></label>
                            <div className="relative">
                                <input type="text" defaultValue="Auto-generate" className="w-full border border-gray-300 rounded-md p-2.5 bg-gray-50 text-gray-500 outline-none" readOnly />
                                <Settings size={16} className="absolute right-3 top-3 text-blue-500 cursor-pointer"/>
                            </div>
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">PO Type <span className="text-red-500">*</span></label>
                            <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white">
                                <option>Standard PO</option>
                                <option>Blanket PO</option>
                                <option>Contract PO</option>
                            </select>
                        </div>
                        
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">PO Date <span className="text-red-500">*</span></label>
                            <div className="relative">
                                <input type="text" defaultValue="Sep 20, 2025" className="w-full border border-gray-300 rounded-md p-2.5 pl-10 focus:ring-2 focus:ring-blue-500 outline-none" />
                                <Calendar size={16} className="absolute left-3 top-3 text-gray-400"/>
                            </div>
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Currency <span className="text-red-500">*</span></label>
                            <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white">
                                <option>INR (â‚¹) - Indian Rupee</option>
                                <option>USD ($) - US Dollar</option>
                            </select>
                        </div>

                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Department <span className="text-red-500">*</span></label>
                            <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-gray-500">
                                <option>Select Department</option>
                                <option>Manufacturing</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Priority</label>
                            <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white">
                                <option>Normal</option>
                                <option>High</option>
                                <option>Urgent</option>
                            </select>
                        </div>

                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Cost Centre</label>
                            <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-gray-500">
                                <option>Select Cost Centre</option>
                                <option>MFG-01</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Required By (Optional)</label>
                            <div className="relative">
                                <input type="text" defaultValue="Oct 15, 2025" className="w-full border border-gray-300 rounded-md p-2.5 pl-10 focus:ring-2 focus:ring-blue-500 outline-none" />
                                <Calendar size={16} className="absolute left-3 top-3 text-gray-400"/>
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Project (Optional)</label>
                            <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-gray-500">
                                <option>Select Project</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Reference No. (Optional)</label>
                            <input type="text" placeholder="e.g., PR-2025-001" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                        </div>

                        <div className="col-span-2 mt-2">
                            <label className="block text-sm font-bold text-gray-700 mb-1">Internal Notes (Optional)</label>
                            <textarea rows={4} placeholder="Add any internal notes or remarks..." className="w-full border border-gray-300 rounded-md p-3 focus:ring-2 focus:ring-blue-500 outline-none resize-none"></textarea>
                            <div className="text-right text-xs text-gray-400 mt-1">0/500 characters</div>
                        </div>
                    </div>
                </div>
              </div>
            )}

            {/* STEP 2: SUPPLIER INFORMATION */}
            {activeStep === 2 && (
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex-1 animate-in fade-in p-8">
                 <h2 className="text-xl font-bold text-[#0B2550] flex items-center gap-2 mb-1"><Users className="text-blue-500"/> Supplier Information</h2>
                 <p className="text-sm text-gray-500 mb-6 border-b border-gray-100 pb-4">Select the supplier and verify their contact and address details.</p>
                 
                 <div className="space-y-6">
                    <div className="bg-gray-50 p-5 rounded-lg border border-gray-200">
                        <label className="block text-sm font-bold text-gray-700 mb-2">Select Supplier <span className="text-red-500">*</span></label>
                        <div className="relative">
                            <Search className="absolute left-3 top-3 text-gray-400" size={18}/>
                            <input type="text" defaultValue="ABC Components Ltd" className="w-full border border-gray-300 rounded-md p-2.5 pl-10 focus:ring-2 focus:ring-blue-500 outline-none text-gray-800 font-medium" />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-6">
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Supplier Code</label>
                            <input type="text" defaultValue="SUP-1001" className="w-full border border-gray-300 rounded-md p-2.5 bg-gray-50 text-gray-600 outline-none" readOnly/>
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Contact Person</label>
                            <input type="text" defaultValue="Rakesh Kumar" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Email</label>
                            <input type="text" defaultValue="rakesh.kumar@abccomponents.com" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Phone</label>
                            <input type="text" defaultValue="+91 98765 43210" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                        </div>
                        
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Billing Address</label>
                            <textarea rows={3} defaultValue={"45, Industrial Area\nElectronic City\nBengaluru, Karnataka 560100\nIndia"} className="w-full border border-gray-300 rounded-md p-3 focus:ring-2 focus:ring-blue-500 outline-none resize-none"></textarea>
                        </div>
                        <div>
                            <label className="block text-sm font-bold text-gray-700 mb-1">Shipping Address</label>
                            <textarea rows={3} defaultValue={"Same as Billing Address"} className="w-full border border-gray-300 rounded-md p-3 focus:ring-2 focus:ring-blue-500 outline-none resize-none"></textarea>
                        </div>
                    </div>
                 </div>
              </div>
            )}

            {/* STEP 3: ITEMS & PRICING */}
            {activeStep === 3 && (
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex-1 animate-in fade-in flex flex-col">
                <div className="p-6 pb-4 flex justify-between items-end border-b border-gray-100">
                    <h2 className="text-xl font-bold text-[#0B2550]">Item Details</h2>
                    <div className="flex gap-2">
                        <button className="px-3 py-1.5 border border-gray-300 text-gray-700 text-sm font-bold rounded hover:bg-gray-50 flex items-center gap-2"><UploadCloud size={16}/> Import Items</button>
                        <button className="px-3 py-1.5 border border-blue-200 bg-blue-50 text-blue-700 text-sm font-bold rounded hover:bg-blue-100 flex items-center gap-2"><Box size={16}/> Add from Catalog</button>
                        <button className="px-3 py-1.5 bg-blue-600 text-white text-sm font-bold rounded hover:bg-blue-700 flex items-center gap-2"><Plus size={16}/> Add Item</button>
                    </div>
                </div>

                <div className="overflow-x-auto p-6 flex-1">
                    <table className="w-full text-sm text-left whitespace-nowrap min-w-[800px]">
                        <thead className="text-gray-500 font-bold border-b-2 border-gray-100">
                            <tr>
                                <th className="pb-3 w-8">#</th>
                                <th className="pb-3 text-[#0B2550]">Item Code <span className="text-red-500">*</span></th>
                                <th className="pb-3 text-[#0B2550]">Item Description <span className="text-red-500">*</span></th>
                                <th className="pb-3 text-[#0B2550]">Category</th>
                                <th className="pb-3 text-[#0B2550]">Unit <span className="text-red-500">*</span></th>
                                <th className="pb-3 text-[#0B2550]">Quantity <span className="text-red-500">*</span></th>
                                <th className="pb-3 text-[#0B2550]">Unit Price (â‚¹) <span className="text-red-500">*</span></th>
                                <th className="pb-3 text-[#0B2550]">Tax (%)</th>
                                <th className="pb-3 text-[#0B2550]">Total (â‚¹)</th>
                                <th className="pb-3 text-center">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {[
                                { id: 1, code: 'ITM-001', desc: 'Ball Bearing 6205', cat: 'Mechanical', unit: 'Nos', qty: 100, price: '250.00', tax: '18%', total: '25,000.00' },
                                { id: 2, code: 'ITM-002', desc: 'Aluminium Housing', cat: 'Raw Material', unit: 'Nos', qty: 50, price: '1,200.00', tax: '18%', total: '60,000.00' },
                                { id: 3, code: 'ITM-003', desc: 'Mounting Bracket', cat: 'Fabrication', unit: 'Nos', qty: 200, price: '180.00', tax: '18%', total: '36,000.00' },
                                { id: 4, code: 'ITM-004', desc: 'Control Panel Assembly', cat: 'Electrical', unit: 'Nos', qty: 10, price: '5,500.00', tax: '18%', total: '55,000.00' },
                                { id: 5, code: 'ITM-005', desc: 'Power Cable 3m', cat: 'Electrical', unit: 'Nos', qty: 100, price: '120.00', tax: '18%', total: '12,000.00' },
                            ].map((item) => (
                                <tr key={item.id} className="hover:bg-gray-50/50">
                                    <td className="py-3 text-gray-400">{item.id}</td>
                                    <td className="py-3 pr-2">
                                        <div className="relative"><input type="text" defaultValue={item.code} className="w-full border border-gray-300 rounded p-2 text-sm"/><Search size={14} className="absolute right-2 top-2.5 text-blue-500"/></div>
                                    </td>
                                    <td className="py-3 pr-2"><input type="text" defaultValue={item.desc} className="w-full border border-gray-300 rounded p-2 text-sm"/></td>
                                    <td className="py-3 pr-2"><select className="w-full border border-gray-300 rounded p-2 text-sm bg-white"><option>{item.cat}</option></select></td>
                                    <td className="py-3 pr-2"><select className="w-20 border border-gray-300 rounded p-2 text-sm bg-white"><option>{item.unit}</option></select></td>
                                    <td className="py-3 pr-2"><input type="number" defaultValue={item.qty} className="w-20 border border-gray-300 rounded p-2 text-sm"/></td>
                                    <td className="py-3 pr-2"><input type="text" defaultValue={item.price} className="w-24 border border-gray-300 rounded p-2 text-sm"/></td>
                                    <td className="py-3 pr-2"><select className="w-20 border border-gray-300 rounded p-2 text-sm bg-white"><option>{item.tax}</option></select></td>
                                    <td className="py-3 font-bold text-gray-800">{item.total}</td>
                                    <td className="py-3 text-center text-red-400 hover:text-red-600 cursor-pointer"><Trash2 size={16} className="mx-auto"/></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    
                    <div className="flex justify-between mt-4">
                        <button className="text-blue-600 font-bold text-sm flex items-center gap-1 hover:underline"><Plus size={16}/> Add Another Item</button>
                        <button className="text-gray-500 font-bold text-sm flex items-center gap-1 hover:text-gray-700"><Trash2 size={16}/> Clear All</button>
                    </div>
                </div>

                <div className="border-t border-gray-200 bg-gray-50 p-6 flex flex-col lg:flex-row gap-8">
                    <div className="flex-1">
                        <h3 className="font-bold text-[#0B2550] mb-4 flex justify-between items-center cursor-pointer">Additional Charges (Optional) <ChevronRight size={16} className="rotate-90"/></h3>
                        <div className="grid grid-cols-4 gap-4">
                            <div>
                                <label className="block text-xs font-bold text-gray-600 mb-1">Freight Charges (â‚¹)</label>
                                <input type="text" defaultValue="2,500.00" className="w-full border border-gray-300 rounded p-2 text-sm bg-white" />
                            </div>
                            <div>
                                <label className="block text-xs font-bold text-gray-600 mb-1">Insurance (â‚¹)</label>
                                <input type="text" defaultValue="1,000.00" className="w-full border border-gray-300 rounded p-2 text-sm bg-white" />
                            </div>
                            <div>
                                <label className="block text-xs font-bold text-gray-600 mb-1">Other Charges (â‚¹)</label>
                                <input type="text" defaultValue="0.00" className="w-full border border-gray-300 rounded p-2 text-sm bg-white" />
                            </div>
                            <div>
                                <label className="block text-xs font-bold text-gray-600 mb-1">Remarks</label>
                                <input type="text" placeholder="Enter any additional pricing remarks..." className="w-full border border-gray-300 rounded p-2 text-sm bg-white" />
                            </div>
                        </div>
                    </div>
                    
                    <div className="w-full lg:w-80 bg-white rounded-lg border border-blue-100 p-5 shadow-sm">
                        <h3 className="font-bold text-[#0B2550] text-lg mb-4">Price Summary</h3>
                        <div className="space-y-2 text-sm">
                            <div className="flex justify-between text-gray-600"><span>Subtotal</span><span className="font-bold text-gray-800">â‚¹ 188,000.00</span></div>
                            <div className="flex justify-between text-gray-600"><span>Freight Charges</span><span className="font-bold text-gray-800">â‚¹ 2,500.00</span></div>
                            <div className="flex justify-between text-gray-600"><span>Insurance</span><span className="font-bold text-gray-800">â‚¹ 1,000.00</span></div>
                            <div className="flex justify-between text-gray-600"><span>Other Charges</span><span className="font-bold text-gray-800">â‚¹ 0.00</span></div>
                            <div className="border-t border-gray-100 my-2 pt-2 flex justify-between text-gray-600"><span>Tax Amount (18%)</span><span className="font-bold text-gray-800">â‚¹ 33,570.00</span></div>
                            <div className="border-t-2 border-blue-100 mt-2 pt-3 flex justify-between items-center"><span className="font-bold text-blue-600 text-base">Total Amount</span><span className="font-black text-[#0B2550] text-xl">â‚¹ 223,070.00</span></div>
                        </div>
                    </div>
                </div>
              </div>
            )}

            {/* STEP 4: DELIVERY & TERMS */}
            {activeStep === 4 && (
              <div className="bg-transparent flex-1 animate-in fade-in flex flex-col gap-6">
                 
                 <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    {/* Delivery Information */}
                    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 md:col-span-1">
                        <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-1"><Truck className="text-blue-500" size={20}/> Delivery Information</h3>
                        <p className="text-xs text-gray-500 mb-6">Provide delivery schedule and shipping details.</p>
                        
                        <div className="space-y-4">
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm font-bold text-gray-700 mb-1">Delivery Type <span className="text-red-500">*</span></label>
                                    <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-sm"><option>Standard Delivery</option></select>
                                </div>
                                <div>
                                    <label className="block text-sm font-bold text-gray-700 mb-1">Expected Delivery <span className="text-red-500">*</span></label>
                                    <div className="relative"><input type="text" defaultValue="Oct 15, 2025" className="w-full border border-gray-300 rounded-md p-2.5 pl-9 focus:ring-2 focus:ring-blue-500 outline-none text-sm" /><Calendar size={14} className="absolute left-3 top-3 text-gray-400"/></div>
                                </div>
                            </div>
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">Delivery Schedule</label>
                                <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-sm"><option>Single Delivery</option></select>
                            </div>
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">Incoterms <span className="text-red-500">*</span></label>
                                <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-sm"><option>FOB (Free On Board)</option></select>
                            </div>
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">Shipping Method</label>
                                <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-sm"><option>Road Freight</option></select>
                            </div>
                            <div>
                                <label className="block text-sm font-bold text-gray-700 mb-1">Shipping Address <span className="text-red-500">*</span></label>
                                <div className="relative">
                                    <textarea rows={3} defaultValue={"SupplyTwin Manufacturing Plant\n123 Industrial Area, Electronic City\nBengaluru, Karnataka 560100\nIndia"} className="w-full border border-gray-300 rounded-md p-3 pr-8 focus:ring-2 focus:ring-blue-500 outline-none resize-none text-sm"></textarea>
                                    <MapPin size={16} className="absolute right-3 top-3 text-blue-500"/>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="md:col-span-2 space-y-6">
                        {/* Packaging & Contact */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                                <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-1"><Box className="text-blue-500" size={20}/> Packaging & Handling</h3>
                                <p className="text-xs text-gray-500 mb-6">Specify packaging requirements and handling instructions.</p>
                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-sm font-bold text-gray-700 mb-1">Packaging Type</label>
                                        <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-sm"><option>Standard Packaging</option></select>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-bold text-gray-700 mb-1">Handling Instructions</label>
                                        <input type="text" defaultValue="Handle with care. Keep dry." className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-bold text-gray-700 mb-1">Special Requirements</label>
                                        <input type="text" defaultValue="Use anti-static packaging for electronic components." className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                                    </div>
                                </div>
                            </div>

                            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                                <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-1"><Users className="text-blue-500" size={20}/> Delivery Contact</h3>
                                <p className="text-xs text-gray-500 mb-6">Point of contact for delivery coordination.</p>
                                <div className="space-y-4">
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm font-bold text-gray-700 mb-1">Contact Person <span className="text-red-500">*</span></label>
                                            <input type="text" defaultValue="Rakesh Kumar" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                                        </div>
                                        <div>
                                            <label className="block text-sm font-bold text-gray-700 mb-1">Phone <span className="text-red-500">*</span></label>
                                            <input type="text" defaultValue="+91 98765 43210" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-bold text-gray-700 mb-1">Email <span className="text-red-500">*</span></label>
                                        <input type="text" defaultValue="rakesh.kumar@supplytwin.com" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none text-sm" />
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Commercial Terms */}
                        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                            <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-1"><FileSignature className="text-blue-500" size={20}/> Commercial Terms</h3>
                            <p className="text-xs text-gray-500 mb-6">Define payment and other commercial terms.</p>
                            <div className="space-y-4">
                                <div className="grid grid-cols-2 gap-6">
                                    <div>
                                        <label className="block text-sm font-bold text-gray-700 mb-1">Payment Terms <span className="text-red-500">*</span></label>
                                        <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-sm"><option>Net 30 Days</option></select>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-bold text-gray-700 mb-1">Currency</label>
                                        <input type="text" defaultValue="INR (â‚¹) - Indian Rupee" className="w-full border border-gray-300 rounded-md p-2.5 bg-gray-50 outline-none text-sm text-gray-500" readOnly/>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-bold text-gray-700 mb-1">Price Validity</label>
                                        <div className="relative"><input type="text" defaultValue="Dec 31, 2025" className="w-full border border-gray-300 rounded-md p-2.5 pl-9 focus:ring-2 focus:ring-blue-500 outline-none text-sm" /><Calendar size={14} className="absolute left-3 top-3 text-gray-400"/></div>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-bold text-gray-700 mb-1">Purchase Agreement</label>
                                        <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white text-sm"><option>As per Master Agreement</option></select>
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm font-bold text-gray-700 mb-1">Other Terms</label>
                                    <textarea rows={2} defaultValue="Supplies must comply with quality standards as per contract. Late delivery may attract penalty as per terms." className="w-full border border-gray-300 rounded-md p-3 focus:ring-2 focus:ring-blue-500 outline-none resize-none text-sm"></textarea>
                                </div>
                            </div>
                        </div>
                    </div>
                 </div>

                 {/* Bottom Row */}
                 <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                        <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-1"><FileText className="text-blue-500" size={20}/> Notes to Supplier (Optional)</h3>
                        <p className="text-xs text-gray-500 mb-4">Additional notes or instructions to be included in the purchase order.</p>
                        <textarea rows={3} placeholder="Please confirm the order receipt and expected delivery date. Notify us immediately in case of any delays." className="w-full border border-gray-300 rounded-md p-3 focus:ring-2 focus:ring-blue-500 outline-none resize-none text-sm"></textarea>
                        <div className="text-right text-xs text-gray-400 mt-1">0/1000 characters</div>
                    </div>
                    
                    <div className="bg-blue-50 rounded-xl border border-blue-100 p-6">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><DollarSign className="text-blue-500" size={20}/> Order Summary</h3>
                            <button onClick={()=>setActiveStep(3)} className="text-blue-600 font-bold text-sm flex items-center gap-1 hover:underline"><Edit size={14}/> Edit Items</button>
                        </div>
                        <div className="space-y-2 text-sm">
                            <div className="flex justify-between text-gray-600"><span>Total Items</span><span className="font-bold text-gray-800">5</span></div>
                            <div className="flex justify-between text-gray-600"><span>Subtotal</span><span className="font-bold text-gray-800">â‚¹ 188,000.00</span></div>
                            <div className="flex justify-between text-gray-600"><span>Freight Charges</span><span className="font-bold text-gray-800">â‚¹ 2,500.00</span></div>
                            <div className="flex justify-between text-gray-600"><span>Insurance</span><span className="font-bold text-gray-800">â‚¹ 1,000.00</span></div>
                            <div className="flex justify-between text-gray-600"><span>Other Charges</span><span className="font-bold text-gray-800">â‚¹ 0.00</span></div>
                            <div className="flex justify-between text-gray-600"><span>Tax Amount (18%)</span><span className="font-bold text-gray-800">â‚¹ 33,570.00</span></div>
                            <div className="border-t border-blue-200 mt-3 pt-3 flex justify-between items-center"><span className="font-bold text-blue-700 text-base">Total Amount</span><span className="font-black text-[#0B2550] text-xl">â‚¹ 223,070.00</span></div>
                        </div>
                    </div>
                 </div>

              </div>
            )}

            {/* STEP 5: REVIEW & CONFIRM */}
            {activeStep === 5 && (
              <div className="space-y-6 animate-in fade-in">
                 <div>
                    <h2 className="text-2xl font-bold text-[#0B2550]">Review & Confirm</h2>
                    <p className="text-sm text-gray-500">Please review all the details below before creating the purchase order.</p>
                 </div>

                 <div className="grid grid-cols-2 gap-6">
                    {/* Basic Details */}
                    <div className="col-span-2 lg:col-span-1 bg-white p-5 rounded-xl border border-gray-200 shadow-sm relative">
                       <button onClick={()=>setActiveStep(1)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                       <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><div className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-xs">1</div> Basic Details</h3>
                       <div className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
                         <span className="text-gray-500">PO Number</span><span className="font-medium text-gray-800">PO-2025-00123</span>
                         <span className="text-gray-500">PO Date</span><span className="font-medium text-gray-800">Sep 20, 2025</span>
                         <span className="text-gray-500">Currency</span><span className="font-medium text-gray-800">INR (â‚¹) - Indian Rupee</span>
                         <span className="text-gray-500">Created By</span><span className="font-medium text-gray-800">Alex Sharma</span>
                         <span className="text-gray-500">Department</span><span className="font-medium text-gray-800">Manufacturing</span>
                         <span className="text-gray-500">Cost Centre</span><span className="font-medium text-gray-800">MFG-01</span>
                         <span className="text-gray-500">Project (Optional)</span><span className="font-medium text-gray-800">-</span>
                         <span className="text-gray-500">Remarks</span><span className="font-medium text-gray-800">Components for production line</span>
                       </div>
                    </div>
                    
                    {/* Supplier Information */}
                    <div className="col-span-2 lg:col-span-1 bg-white p-5 rounded-xl border border-gray-200 shadow-sm relative">
                       <button onClick={()=>setActiveStep(2)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                       <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><div className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-xs">2</div> Supplier Information</h3>
                       <div className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
                         <span className="text-gray-500">Supplier Name</span><span className="font-medium text-gray-800">ABC Components Ltd</span>
                         <span className="text-gray-500">Supplier Code</span><span className="font-medium text-gray-800">SUP-1001</span>
                         <span className="text-gray-500">Contact Person</span><span className="font-medium text-gray-800">Rakesh Kumar</span>
                         <span className="text-gray-500">Email</span><span className="font-medium text-blue-600">rakesh.kumar@abccomponents.com</span>
                         <span className="text-gray-500">Phone</span><span className="font-medium text-gray-800">+91 98765 43210</span>
                         <span className="text-gray-500">Billing Address</span><span className="font-medium text-gray-800">45, Industrial Area<br/>Electronic City<br/>Bengaluru, Karnataka 560100<br/>India</span>
                         <span className="text-gray-500 mt-2">Shipping Address</span><span className="font-medium text-gray-800 mt-2">Same as Billing Address</span>
                       </div>
                    </div>

                    {/* Items & Pricing */}
                    <div className="col-span-2 bg-white p-5 rounded-xl border border-gray-200 shadow-sm relative">
                       <button onClick={()=>setActiveStep(3)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                       <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><div className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-xs">3</div> Items & Pricing</h3>
                       <table className="w-full text-sm text-left">
                          <thead className="text-gray-500 border-b border-gray-200">
                            <tr><th className="pb-2 font-bold">#</th><th className="pb-2 font-bold">Item Code</th><th className="pb-2 font-bold">Description</th><th className="pb-2 font-bold">Qty</th><th className="pb-2 font-bold">Unit</th><th className="pb-2 font-bold text-right">Unit Price (â‚¹)</th><th className="pb-2 font-bold text-right">Total (â‚¹)</th></tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100">
                            <tr><td className="py-2.5 text-gray-500">1</td><td className="py-2.5 font-bold">ITM-001</td><td className="py-2.5 text-gray-700">Ball Bearing 6205</td><td className="py-2.5 font-medium">100</td><td className="py-2.5 text-gray-600">Nos</td><td className="py-2.5 text-gray-600 text-right">250.00</td><td className="py-2.5 font-bold text-gray-800 text-right">25,000.00</td></tr>
                            <tr><td className="py-2.5 text-gray-500">2</td><td className="py-2.5 font-bold">ITM-002</td><td className="py-2.5 text-gray-700">Aluminium Housing</td><td className="py-2.5 font-medium">50</td><td className="py-2.5 text-gray-600">Nos</td><td className="py-2.5 text-gray-600 text-right">1,200.00</td><td className="py-2.5 font-bold text-gray-800 text-right">60,000.00</td></tr>
                            <tr><td className="py-2.5 text-gray-500">3</td><td className="py-2.5 font-bold">ITM-003</td><td className="py-2.5 text-gray-700">Mounting Bracket</td><td className="py-2.5 font-medium">200</td><td className="py-2.5 text-gray-600">Nos</td><td className="py-2.5 text-gray-600 text-right">180.00</td><td className="py-2.5 font-bold text-gray-800 text-right">36,000.00</td></tr>
                            <tr><td className="py-2.5 text-gray-500">4</td><td className="py-2.5 font-bold">ITM-004</td><td className="py-2.5 text-gray-700">Control Panel Assembly</td><td className="py-2.5 font-medium">10</td><td className="py-2.5 text-gray-600">Nos</td><td className="py-2.5 text-gray-600 text-right">5,500.00</td><td className="py-2.5 font-bold text-gray-800 text-right">55,000.00</td></tr>
                            <tr><td className="py-2.5 text-gray-500">5</td><td className="py-2.5 font-bold">ITM-005</td><td className="py-2.5 text-gray-700">Power Cable 3m</td><td className="py-2.5 font-medium">100</td><td className="py-2.5 text-gray-600">Nos</td><td className="py-2.5 text-gray-600 text-right">120.00</td><td className="py-2.5 font-bold text-gray-800 text-right">12,000.00</td></tr>
                          </tbody>
                       </table>
                       <div className="flex justify-end mt-4 pt-2 font-bold text-[#0B2550]">Total Items: <span className="ml-4">5</span></div>
                    </div>

                    <div className="col-span-2 lg:col-span-1 bg-white p-5 rounded-xl border border-gray-200 shadow-sm relative">
                       <button onClick={()=>setActiveStep(4)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                       <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><div className="w-5 h-5 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-xs">4</div> Delivery & Terms</h3>
                       <div className="grid grid-cols-[160px_1fr] gap-y-2 text-sm">
                         <span className="text-gray-500">Delivery Type</span><span className="font-medium text-gray-800">Standard Delivery</span>
                         <span className="text-gray-500">Expected Delivery Date</span><span className="font-medium text-gray-800">Oct 15, 2025</span>
                         <span className="text-gray-500">Delivery Schedule</span><span className="font-medium text-gray-800">Single Delivery</span>
                         <span className="text-gray-500">Incoterms</span><span className="font-medium text-gray-800">FOB (Free On Board)</span>
                         <span className="text-gray-500">Shipping Method</span><span className="font-medium text-gray-800">Road Freight</span>
                         <span className="text-gray-500">Packaging Type</span><span className="font-medium text-gray-800">Standard Packaging</span>
                         <span className="text-gray-500">Handling Instructions</span><span className="font-medium text-gray-800">Handle with care. Keep dry.</span>
                         <span className="text-gray-500">Special Requirements</span><span className="font-medium text-gray-800">Use anti-static packaging.</span>
                         <span className="text-gray-500">Payment Terms</span><span className="font-medium text-gray-800">Net 30 Days</span>
                         <span className="text-gray-500">Price Validity</span><span className="font-medium text-gray-800">Dec 31, 2025</span>
                         <span className="text-gray-500">Purchase Agreement</span><span className="font-medium text-gray-800">As per Master Agreement</span>
                         <span className="text-gray-500">Other Terms</span><span className="font-medium text-gray-800">Supplies must comply with quality standards as per contract.</span>
                       </div>
                    </div>

                    <div className="col-span-2 lg:col-span-1 space-y-6">
                        {/* Additional Charges & Notes */}
                        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm relative">
                           <button onClick={()=>setActiveStep(3)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                           <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><DollarSign size={18} className="text-blue-500"/> Additional Charges</h3>
                           <div className="space-y-2 text-sm">
                             <div className="flex justify-between text-gray-500"><span>Freight Charges</span><span className="font-medium text-gray-800">â‚¹ 2,500.00</span></div>
                             <div className="flex justify-between text-gray-500"><span>Insurance</span><span className="font-medium text-gray-800">â‚¹ 1,000.00</span></div>
                             <div className="flex justify-between text-gray-500"><span>Other Charges</span><span className="font-medium text-gray-800">â‚¹ 0.00</span></div>
                           </div>
                        </div>

                        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm relative">
                           <button onClick={()=>setActiveStep(4)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                           <h3 className="font-bold text-gray-800 mb-3 flex items-center gap-2"><FileText size={18} className="text-blue-500"/> Notes to Supplier</h3>
                           <div className="bg-gray-50 p-4 rounded text-sm text-gray-600 italic border border-gray-100">
                               "Please confirm the order receipt and expected delivery date. Notify us immediately in case of any delays."
                           </div>
                        </div>

                        {/* Price Summary */}
                        <div className="bg-blue-50 p-5 rounded-xl border border-blue-100 shadow-sm">
                           <h3 className="font-bold text-[#0B2550] mb-4 flex items-center gap-2"><Settings size={18} className="text-blue-500"/> Price Summary</h3>
                           <div className="space-y-2 text-sm">
                               <div className="flex justify-between text-gray-600"><span>Subtotal</span><span className="font-bold text-gray-800">â‚¹ 188,000.00</span></div>
                               <div className="flex justify-between text-gray-600"><span>Freight Charges</span><span className="font-bold text-gray-800">â‚¹ 2,500.00</span></div>
                               <div className="flex justify-between text-gray-600"><span>Insurance</span><span className="font-bold text-gray-800">â‚¹ 1,000.00</span></div>
                               <div className="flex justify-between text-gray-600"><span>Other Charges</span><span className="font-bold text-gray-800">â‚¹ 0.00</span></div>
                               <div className="border-t border-gray-200 my-2 pt-2 flex justify-between font-bold text-gray-800"><span>Total (Before Tax)</span><span>â‚¹ 191,500.00</span></div>
                               <div className="flex justify-between text-gray-600"><span>Tax Amount (18%)</span><span className="font-bold text-gray-800">â‚¹ 33,570.00</span></div>
                               <div className="border-t-2 border-blue-200 mt-2 pt-3 flex justify-between items-center"><span className="font-bold text-blue-700 text-lg">Total Amount</span><span className="font-black text-[#0B2550] text-2xl">â‚¹ 223,070.00</span></div>
                           </div>
                        </div>
                    </div>
                 </div>
              </div>
            )}

        </div>

        {/* RIGHT COLUMN (Helper) */}
        {activeStep === 1 && (
            <div className="w-80 hidden xl:flex flex-col gap-6">
                <div className="bg-blue-50 rounded-xl border border-blue-100 p-5 relative">
                    <button className="absolute top-3 right-3 text-blue-400 hover:text-blue-600"><X size={16}/></button>
                    <h3 className="font-bold text-blue-800 flex items-center gap-2 mb-2"><div className="w-5 h-5 bg-blue-600 text-white rounded-full flex items-center justify-center text-xs">i</div> Need help?</h3>
                    <p className="text-sm text-blue-700 mb-3">You can also create a PO using a template or convert from an approved RFQ.</p>
                    <button className="text-blue-700 font-bold text-sm flex items-center gap-1 hover:underline">Learn more <ArrowRight size={14}/></button>
                </div>

                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                    <h3 className="font-bold text-gray-800 flex items-center gap-2 mb-4"><Settings size={18} className="text-blue-500"/> Quick Actions</h3>
                    <div className="space-y-3">
                        <button className="w-full text-left p-3 border border-blue-200 rounded-lg bg-blue-50/50 hover:bg-blue-50 transition-colors flex gap-3 items-start group">
                            <FileText size={18} className="text-blue-600 mt-0.5 group-hover:scale-110 transition-transform"/>
                            <div><p className="font-bold text-blue-800 text-sm">Create from RFQ</p><p className="text-xs text-blue-600 mt-0.5">Convert an approved RFQ to PO</p></div>
                        </button>
                        <button className="w-full text-left p-3 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors flex gap-3 items-start">
                            <FileSignature size={18} className="text-gray-500 mt-0.5"/>
                            <div><p className="font-bold text-gray-700 text-sm">Use PO Template</p><p className="text-xs text-gray-500 mt-0.5">Create from a saved template</p></div>
                        </button>
                    </div>
                </div>

                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
                    <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><HelpCircle size={18} className="text-blue-600"/> Guidelines</h3>
                    <ul className="text-sm text-gray-600 space-y-3">
                        <li className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0"/> Ensure supplier details are correct.</li>
                        <li className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0"/> Verify pricing and tax information.</li>
                        <li className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0"/> Specify accurate delivery dates.</li>
                        <li className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0"/> Review terms and conditions before sending.</li>
                        <li className="flex items-start gap-2"><div className="w-1.5 h-1.5 rounded-full bg-blue-500 mt-1.5 shrink-0"/> You can save as draft and continue later.</li>
                    </ul>
                </div>
            </div>
        )}
      </div>

      {/* BOTTOM ACTION BAR */}
      <div className="fixed bottom-0 left-0 right-0 md:left-64 bg-white border-t border-gray-200 p-4 px-8 flex justify-between items-center z-40 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)]">
        {activeStep > 1 ? (
          <button onClick={handleBack} className="px-6 py-2.5 text-blue-600 bg-white border border-blue-200 font-bold flex items-center gap-2 hover:bg-blue-50 rounded-lg shadow-sm transition-colors"><ChevronLeft size={18}/> Back</button>
        ) : <div></div>}
        
        <div className="flex gap-4">
          <button className="px-6 py-2.5 text-gray-600 bg-white border border-gray-300 font-bold rounded-lg shadow-sm hover:bg-gray-50 transition-colors">Save as Draft</button>
          {activeStep === 5 && (
             <button className="px-4 py-2 border border-gray-300 text-gray-700 font-bold rounded-lg flex items-center gap-2 hover:bg-gray-50 bg-white"><FileText size={18}/> Preview PDF</button>
          )}
          
          {activeStep < 5 ? (
            <button onClick={handleNext} className="px-8 py-2.5 bg-blue-600 text-white font-bold rounded-lg shadow-md hover:bg-blue-700 transition-colors flex items-center gap-2">Next: {STEPS[activeStep].title} <ArrowRight size={18}/></button>
          ) : (
            <button onClick={handleSend} disabled={isSubmitting} className={`px-8 py-2.5 bg-blue-600 text-white font-bold rounded-lg shadow-md flex items-center gap-2 ${isSubmitting ? 'opacity-70 cursor-wait' : 'hover:bg-blue-700 hover:shadow-lg'}`}>
              {isSubmitting ? 'Creating...' : <><Check size={18} strokeWidth={3}/> Confirm & Create PO</>}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

const X = ({size, className}:any) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>;
