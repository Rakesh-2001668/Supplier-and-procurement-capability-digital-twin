'use client';

import React, { useState } from 'react';
import { 
  Check, ChevronRight, UploadCloud, Info, AlertCircle, FileText, Settings, 
  Users, Edit, Eye, Plus, Search, Filter, HelpCircle, Lightbulb, Trash2,
  Calendar, MapPin, CheckCircle2, ChevronLeft, Send, Flag, ShieldCheck, Mail,
  Download, MoreVertical, MessageSquare, Clock
} from 'lucide-react';
import Link from 'next/link';

export default function CreateRFQFlow() {
  const [activeStep, setActiveStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const STEPS = [
    { id: 1, title: 'Basic Information', subtitle: 'Provide general details about the RFQ.' },
    { id: 2, title: 'Items & Specifications', subtitle: 'Add items, quantities and technical specifications.' },
    { id: 3, title: 'Suppliers', subtitle: 'Select and invite suppliers.' },
    { id: 4, title: 'Terms & Conditions', subtitle: 'Set commercial and compliance requirements.' },
    { id: 5, title: 'Review & Send', subtitle: 'Review all details and publish the RFQ.' }
  ];

  const handleNext = () => setActiveStep(prev => Math.min(prev + 1, 5));
  const handleBack = () => setActiveStep(prev => Math.max(prev - 1, 1));
  
  const handleSend = () => {
    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      setIsSuccess(true);
    }, 1500);
  };

  if (isSuccess) {
    return (
      <div className="max-w-7xl mx-auto space-y-6 pb-20 animate-in fade-in duration-500">
        {/* HEADER */}
        <div className="flex justify-between items-start">
          <div>
            <div className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest mb-1.5 flex items-center gap-2">
              <span>RFQ Management</span> <ChevronRight size={12}/> <span>Create RFQ</span> <ChevronRight size={12}/> <span className="text-[#0B2550]">RFQ Sent</span>
            </div>
            <h1 className="text-3xl font-black text-[#0B2550] tracking-tight mb-1">RFQ Sent Successfully</h1>
            <p className="text-slate-500 text-sm font-medium">The RFQ has been sent to the selected suppliers. You can track responses and manage the RFQ from this page.</p>
          </div>
          <button className="px-4 py-2 bg-white border border-slate-300 text-slate-700 font-bold rounded-lg hover:bg-slate-50 text-sm shadow-sm transition-colors">
            View RFQ Details
          </button>
        </div>

        {/* GREEN BANNER */}
        <div className="bg-[#e6f4ea] border border-[#ceead6] rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-[#1e8e3e] text-white rounded-full flex items-center justify-center shrink-0">
                <Check size={20} strokeWidth={3}/>
            </div>
            <div>
                <h3 className="font-bold text-[#1e8e3e] text-lg leading-none mb-1">RFQ Sent Successfully!</h3>
                <p className="text-sm text-[#1e8e3e]">The RFQ (RFQ-2024-001) has been sent to 3 suppliers on Sep 10, 2024 at 10:45 AM.</p>
            </div>
          </div>
          <button className="px-4 py-2 bg-white border border-slate-200 text-[#0B2550] font-bold rounded-lg hover:bg-slate-50 text-sm shadow-sm flex items-center gap-2">
            <Mail size={16}/> Send Reminder
          </button>
        </div>

        <div className="flex flex-col xl:flex-row gap-6">
          {/* LEFT COLUMN */}
          <div className="flex-1 space-y-6">
            {/* CARD 1: RFQ Summary */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                <div className="flex flex-wrap items-center justify-between mb-6 gap-4">
                  <div className="flex items-center gap-3">
                      <div className="p-2 bg-blue-50 rounded-lg text-blue-500"><FileText size={24} /></div>
                      <h2 className="text-xl font-bold text-[#0B2550]">CNC Machined Components - Q4 2024</h2>
                      <span className="bg-[#e6f4ea] text-[#1e8e3e] px-2 py-0.5 rounded text-xs font-bold border border-[#ceead6]">Active</span>
                  </div>
                  <span className="font-bold text-[#0B2550] text-lg">RFQ-2024-001</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-y-4 gap-x-2 text-sm">
                  <div className="grid grid-cols-[130px_1fr]"><span className="text-slate-500">Category</span><span className="font-medium text-slate-800">: Mechanical Parts</span></div>
                  <div className="grid grid-cols-[150px_1fr]"><span className="text-slate-500">Expected Award Date</span><span className="font-medium text-slate-800">: Oct 15, 2024</span></div>
                  <div className="grid grid-cols-[140px_1fr]"><span className="text-slate-500">Items</span><span className="font-medium text-slate-800">: 5</span></div>
                  
                  <div className="grid grid-cols-[130px_1fr]"><span className="text-slate-500">Subcategory</span><span className="font-medium text-slate-800">: CNC Machining</span></div>
                  <div className="grid grid-cols-[150px_1fr]"><span className="text-slate-500">Required Delivery Date</span><span className="font-medium text-slate-800">: Dec 15, 2024</span></div>
                  <div className="grid grid-cols-[140px_1fr]"><span className="text-slate-500">Suppliers Invited</span><span className="font-medium text-slate-800">: 3</span></div>
                  
                  <div className="grid grid-cols-[130px_1fr]"><span className="text-slate-500">Procurement Type</span><span className="font-medium text-slate-800">: Goods</span></div>
                  <div className="grid grid-cols-[150px_1fr]"><span className="text-slate-500">Currency</span><span className="font-medium text-slate-800">: USD - US Dollar</span></div>
                  <div className="grid grid-cols-[140px_1fr]"><span className="text-slate-500">Response Deadline</span><span className="font-medium text-slate-800">: Sep 25, 2024</span></div>
                  
                  <div className="grid grid-cols-[130px_1fr]"><span className="text-slate-500">Business Unit</span><span className="font-medium text-slate-800">: Manufacturing</span></div>
                  <div className="grid grid-cols-[150px_1fr]"><span className="text-slate-500">Pricing Model</span><span className="font-medium text-slate-800">: Fixed Price</span></div>
                  <div className="grid grid-cols-[140px_1fr] items-center"><span className="text-slate-500">Days Remaining</span><div className="flex gap-1">: <span className="bg-blue-50 text-blue-600 px-2 py-0.5 rounded font-bold">15 Days</span></div></div>
                  
                  <div className="grid grid-cols-[130px_1fr] items-center"><span className="text-slate-500">Priority</span><div className="flex gap-1">: <span className="bg-red-50 text-red-600 px-2 py-0.5 rounded font-bold">High</span></div></div>
                  <div className="grid grid-cols-[150px_1fr]"><span className="text-slate-500">Payment Terms</span><span className="font-medium text-slate-800">: Net 30</span></div>
                  <div className="grid grid-cols-[140px_1fr]"><span className="text-slate-500">Created By</span><span className="font-medium text-slate-800">: Alex Sharma</span></div>

                  <div className="hidden md:block"></div>
                  <div className="hidden md:block"></div>
                  <div className="grid grid-cols-[140px_1fr]"><span className="text-slate-500">Created On</span><span className="font-medium text-slate-800">: Sep 10, 2024 10:35 AM</span></div>
                </div>
            </div>

            {/* CARD 2: Tabs Section */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                <div className="flex border-b border-slate-200 px-4 pt-4 gap-6 bg-slate-50 overflow-x-auto">
                  <button className="px-2 py-3 border-b-2 border-blue-600 text-blue-600 font-bold text-sm whitespace-nowrap">Supplier Responses (3)</button>
                  <button className="px-2 py-3 border-b-2 border-transparent text-slate-500 font-semibold hover:text-slate-700 text-sm whitespace-nowrap">Messages</button>
                  <button className="px-2 py-3 border-b-2 border-transparent text-slate-500 font-semibold hover:text-slate-700 text-sm whitespace-nowrap">Clarifications (0)</button>
                  <button className="px-2 py-3 border-b-2 border-transparent text-slate-500 font-semibold hover:text-slate-700 text-sm whitespace-nowrap">Activity Log</button>
                  <button className="px-2 py-3 border-b-2 border-transparent text-slate-500 font-semibold hover:text-slate-700 text-sm whitespace-nowrap">Documents</button>
                  <div className="flex-1 flex justify-end pb-3 min-w-[100px]">
                      <button className="px-4 py-1.5 bg-white border border-slate-300 rounded text-sm font-bold flex items-center gap-2 hover:bg-slate-50 text-slate-700 shadow-sm"><Download size={16}/> Export</button>
                  </div>
                </div>
                
                <div className="p-6">
                  <div className="flex flex-col md:flex-row justify-between items-start md:items-end mb-6 gap-4">
                      <div>
                        <h3 className="text-lg font-bold text-[#0B2550]">Invited Suppliers (3)</h3>
                        <p className="text-sm text-slate-500 mt-1">Track supplier responses, view submitted quotations and manage communications.</p>
                      </div>
                      <div className="flex gap-4 w-full md:w-auto">
                        <div className="relative flex-1 md:w-64">
                            <Search className="absolute left-3 top-2.5 text-slate-400" size={16}/>
                            <input type="text" placeholder="Search suppliers..." className="w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg outline-none text-sm"/>
                        </div>
                        <button className="px-4 py-2 border border-slate-300 rounded-lg text-slate-600 flex items-center gap-2 text-sm hover:bg-slate-50 font-bold shadow-sm"><Filter size={16}/> Filter</button>
                      </div>
                  </div>

                  <div className="overflow-x-auto border border-slate-200 rounded-lg">
                      <table className="w-full text-sm text-left">
                        <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-semibold whitespace-nowrap">
                            <tr>
                              <th className="p-4 w-10">#</th>
                              <th className="p-4">Supplier Name</th>
                              <th className="p-4">Location</th>
                              <th className="p-4">Supplier Tier</th>
                              <th className="p-4">Invitation Date</th>
                              <th className="p-4">Response Status</th>
                              <th className="p-4">Quotation</th>
                              <th className="p-4 text-center">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 whitespace-nowrap">
                            {/* Row 1 */}
                            <tr className="hover:bg-slate-50/50 transition-colors">
                              <td className="p-4 text-slate-500">1</td>
                              <td className="p-4 font-bold text-[#0B2550] flex items-center gap-2 mt-1.5"><div className="w-7 h-7 rounded bg-[#0B2550] flex items-center justify-center text-xs font-bold text-white shrink-0">G</div> ABC Components Pvt Ltd</td>
                              <td className="p-4 text-slate-500">Chennai, India</td>
                              <td className="p-4"><span className="bg-[#e6f4ea] text-[#1e8e3e] px-2 py-1 rounded text-xs font-bold">Tier 1</span></td>
                              <td className="p-4 text-slate-600"><p>Sep 10, 2024</p><p className="text-xs text-slate-400">10:45 AM</p></td>
                              <td className="p-4">
                                  <div className="flex items-start gap-2">
                                    <div className="w-2 h-2 rounded-full bg-[#1e8e3e] mt-1.5 shrink-0"></div>
                                    <div><p className="font-bold text-slate-800">Submitted</p><p className="text-xs text-slate-500">Sep 12, 2024</p><p className="text-xs text-slate-500">02:30 PM</p></div>
                                  </div>
                              </td>
                              <td className="p-4">
                                  <button className="flex items-center gap-2 text-blue-600 hover:text-blue-800 group">
                                    <Download size={16} className="group-hover:translate-y-0.5 transition-transform"/>
                                    <div className="text-left"><p className="text-xs font-bold">View Quote</p><p className="text-xs font-semibold">$48,500.00</p></div>
                                  </button>
                              </td>
                              <td className="p-4 text-center text-slate-400 cursor-pointer hover:text-blue-600"><MoreVertical size={18} className="mx-auto"/></td>
                            </tr>
                            {/* Row 2 */}
                            <tr className="hover:bg-slate-50/50 transition-colors">
                              <td className="p-4 text-slate-500">2</td>
                              <td className="p-4 font-bold text-[#0B2550] flex items-center gap-2"><div className="w-7 h-7 rounded bg-[#0da2e7] flex items-center justify-center text-xs font-bold text-white shrink-0">XX</div> XYZ Manufacturing Co.</td>
                              <td className="p-4 text-slate-500">Bengaluru, India</td>
                              <td className="p-4"><span className="bg-[#e6f4ea] text-[#1e8e3e] px-2 py-1 rounded text-xs font-bold">Tier 1</span></td>
                              <td className="p-4 text-slate-600"><p>Sep 10, 2024</p><p className="text-xs text-slate-400">10:45 AM</p></td>
                              <td className="p-4">
                                  <div className="flex items-center gap-2">
                                    <div className="w-2 h-2 rounded-full bg-[#fbbc04] shrink-0"></div>
                                    <p className="font-bold text-slate-800">In Progress</p>
                                  </div>
                              </td>
                              <td className="p-4 text-slate-400 font-bold text-center">-</td>
                              <td className="p-4 text-center text-slate-400 cursor-pointer hover:text-blue-600"><MoreVertical size={18} className="mx-auto"/></td>
                            </tr>
                            {/* Row 3 */}
                            <tr className="hover:bg-slate-50/50 transition-colors">
                              <td className="p-4 text-slate-500">3</td>
                              <td className="p-4 font-bold text-[#0B2550] flex items-center gap-2"><div className="w-7 h-7 rounded bg-[#9333ea] flex items-center justify-center text-xs font-bold text-white shrink-0">O</div> JKL Fabrication</td>
                              <td className="p-4 text-slate-500">Coimbatore, India</td>
                              <td className="p-4"><span className="bg-blue-50 text-blue-600 px-2 py-1 rounded text-xs font-bold">Tier 2</span></td>
                              <td className="p-4 text-slate-600"><p>Sep 10, 2024</p><p className="text-xs text-slate-400">10:45 AM</p></td>
                              <td className="p-4">
                                  <div className="flex items-center gap-2">
                                    <div className="w-2 h-2 rounded-full bg-slate-400 shrink-0"></div>
                                    <p className="font-bold text-slate-800">Not Responded</p>
                                  </div>
                              </td>
                              <td className="p-4 text-slate-400 font-bold text-center">-</td>
                              <td className="p-4 text-center text-slate-400 cursor-pointer hover:text-blue-600"><MoreVertical size={18} className="mx-auto"/></td>
                            </tr>
                        </tbody>
                      </table>
                  </div>
                </div>
            </div>

            {/* Bottom Side-by-Side Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Communication History */}
                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <div className="flex justify-between items-center mb-6">
                      <h3 className="font-bold text-[#0B2550] flex items-center gap-2"><MessageSquare size={18} className="text-blue-500"/> Communication History</h3>
                      <button className="text-blue-600 font-bold text-sm hover:underline">View All</button>
                  </div>
                  <div className="space-y-6">
                      <div className="flex gap-4 relative">
                        <div className="absolute left-1.5 top-5 bottom-[-24px] w-px bg-slate-200"></div>
                        <div className="w-3 h-3 rounded-full bg-blue-500 mt-1 shrink-0 relative z-10"></div>
                        <div className="flex-1 grid grid-cols-[130px_1fr_100px] text-sm items-start gap-4">
                            <span className="text-slate-500 text-xs mt-0.5">Sep 10, 2024 10:45 AM</span>
                            <span className="text-slate-800 font-medium">RFQ sent to 3 suppliers</span>
                            <span className="text-slate-500 text-right">Alex Sharma</span>
                        </div>
                      </div>
                      <div className="flex gap-4 relative">
                        <div className="absolute left-1.5 top-5 bottom-[-24px] w-px bg-slate-200"></div>
                        <div className="w-3 h-3 rounded-full bg-green-500 mt-1 shrink-0 relative z-10"></div>
                        <div className="flex-1 grid grid-cols-[130px_1fr_100px] text-sm items-start gap-4">
                            <span className="text-slate-500 text-xs mt-0.5">Sep 12, 2024 02:30 PM</span>
                            <span className="text-slate-800 font-medium">Quote submitted by ABC Components Pvt Ltd</span>
                            <span className="text-slate-500 text-right">Supplier</span>
                        </div>
                      </div>
                      <div className="flex gap-4 relative">
                        <div className="w-3 h-3 rounded-full bg-slate-300 mt-1 shrink-0 relative z-10"></div>
                        <div className="flex-1 grid grid-cols-[130px_1fr_100px] text-sm items-start gap-4">
                            <span className="text-slate-500 text-xs mt-0.5">Sep 12, 2024 02:32 PM</span>
                            <span className="text-slate-800 font-medium">Auto notification sent to team</span>
                            <span className="text-slate-500 text-right">System</span>
                        </div>
                      </div>
                  </div>
                </div>

                {/* Next Actions */}
                <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                  <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-6"><Clock size={18} className="text-blue-500"/> Next Actions</h3>
                  <div className="space-y-4">
                      <label className="flex items-center gap-3 cursor-pointer group">
                        <div className="w-4 h-4 border-2 border-slate-300 rounded group-hover:border-blue-500 transition-colors"></div>
                        <span className="text-sm text-slate-700 font-medium group-hover:text-blue-700">Monitor supplier responses</span>
                      </label>
                      <label className="flex items-center gap-3 cursor-pointer group">
                        <div className="w-4 h-4 border-2 border-slate-300 rounded group-hover:border-blue-500 transition-colors"></div>
                        <span className="text-sm text-slate-700 font-medium group-hover:text-blue-700">Send reminder to pending suppliers</span>
                      </label>
                      <label className="flex items-center gap-3 cursor-pointer group">
                        <div className="w-4 h-4 border-2 border-slate-300 rounded group-hover:border-blue-500 transition-colors"></div>
                        <span className="text-sm text-slate-700 font-medium group-hover:text-blue-700">Answer supplier clarifications</span>
                      </label>
                      <label className="flex items-center gap-3 cursor-pointer group">
                        <div className="w-4 h-4 border-2 border-slate-300 rounded group-hover:border-blue-500 transition-colors"></div>
                        <span className="text-sm text-slate-700 font-medium group-hover:text-blue-700">Compare quotations</span>
                      </label>
                      <label className="flex items-center gap-3 cursor-pointer group">
                        <div className="w-4 h-4 border-2 border-slate-300 rounded group-hover:border-blue-500 transition-colors"></div>
                        <span className="text-sm text-slate-700 font-medium group-hover:text-blue-700">Finalize and award</span>
                      </label>
                  </div>
                </div>
            </div>
          </div>

          {/* RIGHT COLUMN */}
          <div className="w-80 shrink-0 space-y-6 hidden xl:block">
            {/* RFQ Progress */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                <h3 className="font-bold text-[#0B2550] text-lg mb-6">RFQ Progress</h3>
                <div className="space-y-6">
                  {/* Step 1 */}
                  <div className="flex gap-4 relative">
                      <div className="absolute left-3.5 top-8 bottom-[-24px] w-0.5 bg-blue-600"></div>
                      <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0 z-10"><Check size={14} strokeWidth={3}/></div>
                      <div><h4 className="font-bold text-sm text-[#0B2550]">Basic Information</h4><p className="text-xs text-slate-500">Completed</p></div>
                  </div>
                  {/* Step 2 */}
                  <div className="flex gap-4 relative">
                      <div className="absolute left-3.5 top-8 bottom-[-24px] w-0.5 bg-blue-600"></div>
                      <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0 z-10"><Check size={14} strokeWidth={3}/></div>
                      <div><h4 className="font-bold text-sm text-[#0B2550]">Items & Specifications</h4><p className="text-xs text-slate-500">Completed</p></div>
                  </div>
                  {/* Step 3 */}
                  <div className="flex gap-4 relative">
                      <div className="absolute left-3.5 top-8 bottom-[-24px] w-0.5 bg-blue-600"></div>
                      <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0 z-10"><Check size={14} strokeWidth={3}/></div>
                      <div><h4 className="font-bold text-sm text-[#0B2550]">Suppliers</h4><p className="text-xs text-slate-500">Completed</p></div>
                  </div>
                  {/* Step 4 */}
                  <div className="flex gap-4 relative">
                      <div className="absolute left-3.5 top-8 bottom-[-24px] w-0.5 bg-blue-600"></div>
                      <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0 z-10"><Check size={14} strokeWidth={3}/></div>
                      <div><h4 className="font-bold text-sm text-[#0B2550]">Terms & Conditions</h4><p className="text-xs text-slate-500">Completed</p></div>
                  </div>
                  {/* Step 5 */}
                  <div className="flex gap-4 relative">
                      <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0 z-10 font-bold text-sm">5</div>
                      <div><h4 className="font-bold text-sm text-[#0B2550]">Review & Send</h4><p className="text-xs text-slate-500">RFQ Sent</p></div>
                  </div>
                </div>
            </div>

            {/* Key Dates */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-6"><Calendar size={18} className="text-blue-500"/> Key Dates</h3>
                <div className="space-y-4">
                  <div className="flex justify-between text-sm"><span className="text-slate-500">RFQ Sent On</span><span className="font-medium text-slate-800 text-right">Sep 10, 2024 10:45 AM</span></div>
                  <div className="flex justify-between text-sm"><span className="text-slate-500">Response Deadline</span><span className="font-medium text-slate-800 text-right">Sep 25, 2024 05:00 PM</span></div>
                  <div className="flex justify-between items-center text-sm"><span className="text-slate-500">Days Remaining</span><span className="font-bold text-blue-600 bg-blue-50 px-2 py-0.5 rounded text-right">15 Days</span></div>
                  <div className="flex justify-between text-sm"><span className="text-slate-500">Expected Award Date</span><span className="font-medium text-slate-800 text-right">Oct 15, 2024</span></div>
                  <div className="flex justify-between text-sm"><span className="text-slate-500">Required Delivery Date</span><span className="font-medium text-slate-800 text-right">Dec 15, 2024</span></div>
                </div>
            </div>

            {/* Tips */}
            <div className="bg-[#fff9e6] rounded-xl border border-[#ffe082] p-6">
                <h3 className="font-bold text-amber-900 flex items-center gap-2 mb-4"><Lightbulb size={18} className="text-amber-500"/> Tips</h3>
                <ul className="text-sm text-amber-800 space-y-3">
                  <li className="flex items-start gap-2"><Check size={16} className="text-amber-500 shrink-0 mt-0.5"/> <span>Monitor supplier responses regularly.</span></li>
                  <li className="flex items-start gap-2"><Check size={16} className="text-amber-500 shrink-0 mt-0.5"/> <span>Use the message center for clarifications.</span></li>
                  <li className="flex items-start gap-2"><Check size={16} className="text-amber-500 shrink-0 mt-0.5"/> <span>Compare quotations using the comparison tool.</span></li>
                  <li className="flex items-start gap-2"><Check size={16} className="text-amber-500 shrink-0 mt-0.5"/> <span>Send reminders to pending suppliers.</span></li>
                  <li className="flex items-start gap-2"><Check size={16} className="text-amber-500 shrink-0 mt-0.5"/> <span>You can modify the RFQ before the deadline if needed.</span></li>
                </ul>
            </div>

            {/* Need Help */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><HelpCircle size={18} className="text-blue-600"/> Need Help?</h3>
                <ul className="space-y-3 text-sm text-blue-600 mb-6">
                  <li className="hover:underline cursor-pointer transition-colors">View RFQ management guide</li>
                  <li className="hover:underline cursor-pointer transition-colors">Learn how to compare quotations</li>
                  <li className="hover:underline cursor-pointer transition-colors">Watch video: Managing supplier responses</li>
                </ul>
                <button className="text-blue-600 text-sm font-bold flex items-center gap-1 hover:underline transition-all">Open Guide <ChevronRight size={14}/></button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-20">
      {/* HEADER */}
      <div>
        <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
          <span>RFQ Management</span> <ChevronRight size={12}/> <span className="text-[#0B2550]">Create RFQ</span>
        </div>
        <h1 className="text-3xl font-bold text-[#0B2550]">Create RFQ</h1>
        <p className="text-gray-500 mt-1">Define your requirements and invite suppliers to respond.</p>
      </div>

      {/* HORIZONTAL STEPPER */}
      <div className="w-full relative py-6">
        <div className="absolute top-1/2 left-0 w-full h-1 bg-gray-200 -translate-y-1/2 z-0"></div>
        <div className="absolute top-1/2 left-0 h-1 bg-blue-600 transition-all duration-500 z-0" style={{ width: `${((activeStep - 1) / 4) * 100}%` }}></div>
        
        <div className="relative z-10 flex justify-between">
          {STEPS.map((step) => {
            const isCompleted = step.id < activeStep;
            const isActive = step.id === activeStep;
            return (
              <div key={step.id} className="flex flex-col items-center">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-colors border-2 
                  ${isCompleted ? 'bg-blue-600 border-blue-600 text-white' : 
                    isActive ? 'bg-white border-blue-600 text-blue-600 shadow-md ring-4 ring-blue-50' : 
                    'bg-white border-gray-300 text-gray-400'}`}>
                  {isCompleted ? <Check size={18} /> : step.id}
                </div>
                <span className={`mt-3 text-xs font-bold whitespace-nowrap ${isActive ? 'text-blue-600' : isCompleted ? 'text-gray-800' : 'text-gray-400'}`}>
                  {step.title}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col xl:flex-row gap-8">
        {/* MAIN CONTENT AREA */}
        <div className="flex-1 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col min-h-[600px]">
          <div className="p-8 flex-1">
            
            {/* STEP 1: BASIC INFORMATION */}
            {activeStep === 1 && (
              <div className="space-y-6 animate-in fade-in">
                <div>
                  <h2 className="text-xl font-bold text-[#0B2550]">Basic Information</h2>
                  <p className="text-sm text-gray-500">Provide the key details for this RFQ. These details will be visible to invited suppliers.</p>
                </div>
                
                <div className="grid grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">RFQ Title <span className="text-red-500">*</span></label>
                    <input type="text" defaultValue="CNC Machined Components - Q4 2024" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1 flex items-center gap-1">RFQ Reference No. <Info size={14} className="text-gray-400"/></label>
                    <div className="flex gap-2">
                       <input type="text" defaultValue="RFQ-2024-001" className="w-full border border-gray-300 rounded-md p-2.5 bg-gray-50 outline-none text-gray-600 font-mono" />
                       <button className="p-2.5 border border-gray-300 rounded-md hover:bg-gray-50"><RefreshCw size={18} className="text-gray-500"/></button>
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Category <span className="text-red-500">*</span></label>
                    <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white">
                      <option>Mechanical Parts</option>
                      <option>Electrical Components</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Subcategory</label>
                    <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white">
                      <option>CNC Machining</option>
                      <option>Sheet Metal</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">Procurement Type <span className="text-red-500">*</span></label>
                    <div className="flex gap-6 mt-2">
                      <label className="flex items-center gap-2 cursor-pointer"><input type="radio" name="type" defaultChecked className="w-4 h-4 text-blue-600"/> <span className="text-sm text-gray-700">Goods</span></label>
                      <label className="flex items-center gap-2 cursor-pointer"><input type="radio" name="type" className="w-4 h-4 text-blue-600"/> <span className="text-sm text-gray-700">Services</span></label>
                      <label className="flex items-center gap-2 cursor-pointer"><input type="radio" name="type" className="w-4 h-4 text-blue-600"/> <span className="text-sm text-gray-700">Both</span></label>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Business Unit <span className="text-red-500">*</span></label>
                    <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white">
                      <option>Manufacturing</option>
                      <option>R&D</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Project / Program (Optional)</label>
                    <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white">
                      <option>Production Line Upgrade</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Priority <span className="text-red-500">*</span></label>
                    <div className="relative">
                      <select className="w-full border border-gray-300 rounded-md p-2.5 pl-10 focus:ring-2 focus:ring-blue-500 outline-none bg-red-50 text-red-700 font-bold appearance-none">
                        <option>High</option>
                        <option>Medium</option>
                        <option>Low</option>
                      </select>
                      <Flag size={16} className="absolute left-3 top-3.5 text-red-500" />
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Expected Award Date</label>
                    <div className="relative">
                       <input type="date" defaultValue="2024-10-15" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Required Delivery Date</label>
                    <div className="relative">
                       <input type="date" defaultValue="2024-12-15" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                    </div>
                  </div>
                  
                  <div className="col-span-2">
                    <label className="block text-sm font-bold text-gray-700 mb-1">Currency <span className="text-red-500">*</span></label>
                    <select className="w-1/2 border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white">
                      <option>USD - US Dollar</option>
                      <option>EUR - Euro</option>
                    </select>
                  </div>

                  <div className="col-span-2">
                    <label className="block text-sm font-bold text-gray-700 mb-1">Description <span className="text-red-500">*</span></label>
                    <textarea rows={3} defaultValue="We are seeking quotes for precision CNC machined components as per attached specifications. Suppliers must meet quality, delivery and compliance requirements." className="w-full border border-gray-300 rounded-md p-3 focus:ring-2 focus:ring-blue-500 outline-none resize-none"></textarea>
                    <div className="text-right text-xs text-gray-400 mt-1">118/2000</div>
                  </div>

                  <div className="col-span-2">
                    <label className="block text-sm font-bold text-gray-700 mb-2">Attachments (Optional)</label>
                    <div className="flex gap-4">
                       <div className="flex-1 border-2 border-dashed border-blue-200 bg-blue-50 rounded-lg flex flex-col items-center justify-center py-6 hover:bg-blue-100 transition-colors cursor-pointer text-center">
                         <UploadCloud size={24} className="text-blue-500 mb-2" />
                         <p className="text-sm text-blue-700 font-medium">Drag and drop files here, or <span className="underline">click to upload</span></p>
                         <p className="text-xs text-blue-500 mt-1">Supported files: PDF, DOC, XLS, ZIP (Max 20 MB each)</p>
                       </div>
                       <div className="w-1/3 space-y-2">
                         <div className="flex items-center justify-between border border-gray-200 rounded p-2 bg-white">
                           <div className="flex items-center gap-2"><div className="w-8 h-8 bg-red-100 rounded flex items-center justify-center text-red-600 font-bold text-xs">PDF</div><div className="text-xs"><p className="font-bold text-gray-700 truncate w-32">Technical_Specification.pdf</p><p className="text-gray-400">2.4 MB</p></div></div>
                           <button className="text-gray-400 hover:text-red-500"><X size={16}/></button>
                         </div>
                         <div className="flex items-center justify-between border border-gray-200 rounded p-2 bg-white">
                           <div className="flex items-center gap-2"><div className="w-8 h-8 bg-green-100 rounded flex items-center justify-center text-green-600 font-bold text-xs">XLS</div><div className="text-xs"><p className="font-bold text-gray-700 truncate w-32">Component_List.xlsx</p><p className="text-gray-400">1.1 MB</p></div></div>
                           <button className="text-gray-400 hover:text-red-500"><X size={16}/></button>
                         </div>
                       </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* STEP 2: ITEMS & SPECIFICATIONS */}
            {activeStep === 2 && (
              <div className="space-y-6 animate-in fade-in">
                <div className="flex justify-between items-end">
                  <div>
                    <h2 className="text-xl font-bold text-[#0B2550]">Items & Specifications</h2>
                    <p className="text-sm text-gray-500">Add the required items with quantities, technical specifications and delivery requirements.</p>
                  </div>
                  <div className="flex gap-2">
                    <button className="px-3 py-1.5 border border-gray-300 text-gray-700 text-sm font-bold rounded hover:bg-gray-50 flex items-center gap-2"><UploadCloud size={16}/> Import from Excel</button>
                    <button className="px-3 py-1.5 bg-blue-600 text-white text-sm font-bold rounded hover:bg-blue-700 flex items-center gap-2"><Plus size={16}/> Add Item</button>
                  </div>
                </div>

                <div className="border border-gray-200 rounded-lg overflow-x-auto">
                  <table className="w-full text-sm text-left whitespace-nowrap">
                    <thead className="bg-gray-50 border-b border-gray-200 text-gray-600 font-semibold">
                      <tr>
                        <th className="p-3 w-10"><input type="checkbox" className="rounded border-gray-300" /></th>
                        <th className="p-3">#</th>
                        <th className="p-3">Item Name <span className="text-red-500">*</span></th>
                        <th className="p-3">Description</th>
                        <th className="p-3">Category</th>
                        <th className="p-3">Quantity <span className="text-red-500">*</span></th>
                        <th className="p-3">Unit <span className="text-red-500">*</span></th>
                        <th className="p-3">Target Price</th>
                        <th className="p-3">Req. Delivery</th>
                        <th className="p-3 text-center">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {[
                        { id: 1, name: 'CNC Machined Housing', desc: 'Aluminium housing as per dwg', cat: 'Mechanical Parts', qty: 500, unit: 'Nos', price: 120.00, date: 'Dec 15, 2024' },
                        { id: 2, name: 'Precision Shaft', desc: 'SS 304 shaft Ã˜20mm tol Â±0.01', cat: 'Mechanical Parts', qty: 1000, unit: 'Nos', price: 45.00, date: 'Dec 15, 2024' },
                        { id: 3, name: 'Control Panel Assembly', desc: 'Electrical panel with PLC', cat: 'Electrical', qty: 50, unit: 'Sets', price: 850.00, date: 'Dec 30, 2024' }
                      ].map((item) => (
                        <tr key={item.id} className="hover:bg-blue-50/50">
                          <td className="p-3"><input type="checkbox" className="rounded border-gray-300" /></td>
                          <td className="p-3 text-gray-500">{item.id}</td>
                          <td className="p-3 font-medium text-gray-800">{item.name}</td>
                          <td className="p-3 text-gray-500 truncate max-w-[150px]">{item.desc}</td>
                          <td className="p-3 text-gray-600">{item.cat}</td>
                          <td className="p-3 font-medium">{item.qty}</td>
                          <td className="p-3 text-gray-600">{item.unit}</td>
                          <td className="p-3 text-gray-600">{item.price.toFixed(2)}</td>
                          <td className="p-3 text-gray-600 flex items-center gap-1"><Calendar size={14}/> {item.date}</td>
                          <td className="p-3 text-center text-gray-400 hover:text-blue-600 cursor-pointer"><Settings size={16} className="mx-auto"/></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="pt-4 border-t border-gray-100">
                  <h3 className="font-bold text-gray-800 mb-2">Technical Specifications (Optional)</h3>
                  <p className="text-sm text-gray-500 mb-4">Attach drawings, technical specifications, standards and any other reference documents.</p>
                  <div className="flex gap-4">
                     <div className="flex-1 border-2 border-dashed border-gray-300 bg-gray-50 rounded-lg flex flex-col items-center justify-center py-6 hover:bg-gray-100 transition-colors cursor-pointer text-center">
                       <UploadCloud size={24} className="text-blue-500 mb-2" />
                       <p className="text-sm text-gray-700 font-medium">Drag and drop files here, or <span className="underline text-blue-600">click to upload</span></p>
                     </div>
                     <div className="w-1/3 grid grid-cols-1 gap-2">
                         <div className="flex items-center justify-between border border-gray-200 rounded p-2 bg-white">
                           <div className="flex items-center gap-2"><div className="w-8 h-8 bg-red-100 rounded flex items-center justify-center text-red-600 font-bold text-xs">PDF</div><div className="text-xs"><p className="font-bold text-gray-700 truncate w-32">CNC_Drawing.pdf</p><p className="text-gray-400">4.2 MB</p></div></div>
                           <button className="text-gray-400 hover:text-red-500"><X size={16}/></button>
                         </div>
                     </div>
                  </div>
                </div>

                <div>
                   <h3 className="font-bold text-gray-800 mb-2">Additional Requirements (Optional)</h3>
                   <textarea rows={3} defaultValue="All components must comply with ISO 9001 standards. Suppliers to provide material test certificates and dimensional reports." className="w-full border border-gray-300 rounded-md p-3 focus:ring-2 focus:ring-blue-500 outline-none resize-none text-sm"></textarea>
                </div>
              </div>
            )}

            {/* STEP 3: SUPPLIERS */}
            {activeStep === 3 && (
              <div className="space-y-6 animate-in fade-in">
                <div className="flex justify-between items-end">
                  <div>
                    <h2 className="text-xl font-bold text-[#0B2550]">Select Suppliers</h2>
                    <p className="text-sm text-gray-500">Choose suppliers from your network or invite new suppliers to participate.</p>
                  </div>
                  <button className="px-4 py-2 border border-blue-600 text-blue-600 text-sm font-bold rounded hover:bg-blue-50 flex items-center gap-2"><Plus size={16}/> Invite New Supplier</button>
                </div>

                {/* Tabs */}
                <div className="flex border-b border-gray-200">
                  <button className="px-4 py-3 border-b-2 border-blue-600 text-blue-600 font-bold text-sm">From Supplier Network (28)</button>
                  <button className="px-4 py-3 border-b-2 border-transparent text-gray-500 hover:text-gray-700 font-semibold text-sm">Search & Add Suppliers</button>
                  <button className="px-4 py-3 border-b-2 border-transparent text-gray-500 hover:text-gray-700 font-semibold text-sm">Invite New Supplier</button>
                </div>

                {/* Filters */}
                <div className="flex gap-4">
                  <div className="relative flex-1">
                    <Search className="absolute left-3 top-2.5 text-gray-400" size={16}/>
                    <input type="text" placeholder="Search suppliers by name, category, location..." className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded outline-none text-sm"/>
                  </div>
                  <select className="border border-gray-300 rounded px-3 py-2 text-sm outline-none text-gray-600"><option>All Categories</option></select>
                  <select className="border border-gray-300 rounded px-3 py-2 text-sm outline-none text-gray-600"><option>All Tiers</option></select>
                  <button className="px-3 py-2 border border-gray-300 rounded text-gray-600 flex items-center gap-2 text-sm hover:bg-gray-50"><Filter size={16}/> More Filters</button>
                </div>

                <div className="border border-gray-200 rounded-lg overflow-x-auto">
                  <table className="w-full text-sm text-left whitespace-nowrap">
                    <thead className="bg-gray-50 border-b border-gray-200 text-gray-600 font-semibold">
                      <tr>
                        <th className="p-3 w-10"><input type="checkbox" className="rounded border-gray-300" /></th>
                        <th className="p-3">Supplier Name</th>
                        <th className="p-3">Location</th>
                        <th className="p-3">Categories</th>
                        <th className="p-3">Supplier Tier</th>
                        <th className="p-3">Past Performance</th>
                        <th className="p-3">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {[
                        { name: 'ABC Components Pvt Ltd', loc: 'Chennai, India', cat: 'CNC Machining', tier: 'Tier 1', score: '4.8', status: 'Invited', sel: true },
                        { name: 'XYZ Manufacturing Co.', loc: 'Bengaluru, India', cat: 'Control Panels', tier: 'Tier 1', score: '4.5', status: 'Invited', sel: true },
                        { name: 'GHI Precision Ltd', loc: 'Pune, India', cat: 'Precision Components', tier: 'Tier 2', score: '4.2', status: 'Invited', sel: true },
                        { name: 'JKL Fabrication', loc: 'Coimbatore, India', cat: 'Fabrication', tier: 'Tier 2', score: '4.0', status: 'Not Invited', sel: false }
                      ].map((sup, i) => (
                        <tr key={i} className={`hover:bg-blue-50/50 ${sup.sel ? 'bg-blue-50/30' : ''}`}>
                          <td className="p-3"><input type="checkbox" defaultChecked={sup.sel} className="rounded border-gray-300 text-blue-600" /></td>
                          <td className="p-3 font-bold text-[#0B2550] flex items-center gap-2"><div className="w-6 h-6 rounded bg-blue-100 flex items-center justify-center text-xs font-bold text-blue-700">{sup.name.charAt(0)}</div> {sup.name}</td>
                          <td className="p-3 text-gray-500">{sup.loc}</td>
                          <td className="p-3"><span className="bg-gray-100 text-gray-600 text-xs px-2 py-1 rounded border border-gray-200">{sup.cat}</span></td>
                          <td className="p-3"><span className={`text-xs font-bold px-2 py-1 rounded ${sup.tier === 'Tier 1' ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'}`}>{sup.tier}</span></td>
                          <td className="p-3 text-amber-500 font-bold text-xs flex items-center gap-1 mt-1.5">â˜… {sup.score}</td>
                          <td className="p-3"><span className={`text-xs font-bold ${sup.status === 'Invited' ? 'text-green-600' : 'text-gray-400'}`}>{sup.status}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* STEP 4: TERMS & CONDITIONS */}
            {activeStep === 4 && (
              <div className="space-y-8 animate-in fade-in">
                <div>
                  <h2 className="text-xl font-bold text-[#0B2550]">Commercial Terms</h2>
                  <p className="text-sm text-gray-500">Define the pricing, payment and contractual terms for this RFQ.</p>
                </div>

                <div className="grid grid-cols-4 gap-6">
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Pricing Model <span className="text-red-500">*</span></label>
                    <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white"><option>Fixed Price</option></select>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Payment Terms <span className="text-red-500">*</span></label>
                    <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white"><option>Net 30</option><option>Net 60</option></select>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Price Validity (Days) <span className="text-red-500">*</span></label>
                    <input type="number" defaultValue="60" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-1">Currency <span className="text-red-500">*</span></label>
                    <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white"><option>$ USD - US Dollar</option></select>
                  </div>
                </div>

                <div className="pt-6 border-t border-gray-100">
                  <h3 className="font-bold text-gray-800 mb-4">Delivery Requirements</h3>
                  <div className="grid grid-cols-4 gap-6">
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Required Delivery Date <span className="text-red-500">*</span></label>
                      <input type="date" defaultValue="2024-12-15" className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Delivery Location <span className="text-red-500">*</span></label>
                      <div className="relative">
                        <MapPin size={16} className="absolute left-3 top-3 text-gray-400"/>
                        <input type="text" defaultValue="Chennai, India" className="w-full pl-9 border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none" />
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Incoterms <Info size={14} className="inline text-blue-500"/></label>
                      <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white"><option>DAP - Delivered at Place</option></select>
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-1">Packaging Requirements</label>
                      <select className="w-full border border-gray-300 rounded-md p-2.5 focus:ring-2 focus:ring-blue-500 outline-none bg-white"><option>Standard Industrial Packaging</option></select>
                    </div>
                  </div>
                </div>

                <div className="pt-6 border-t border-gray-100">
                  <h3 className="font-bold text-gray-800 mb-4">Evaluation Criteria</h3>
                  <p className="text-sm text-gray-500 mb-4">Define how supplier responses will be evaluated.</p>
                  <div className="grid grid-cols-2 gap-x-12 gap-y-4">
                    <div className="flex items-center justify-between"><span className="text-sm text-gray-600">Price</span><div className="flex items-center gap-3"><div className="w-32 h-2 bg-gray-200 rounded-full"><div className="w-[40%] h-full bg-blue-500 rounded-full"></div></div><span className="text-sm font-bold text-gray-600 w-8 text-right">40 %</span></div></div>
                    <div className="flex items-center justify-between"><span className="text-sm text-gray-600">Quality & Certifications</span><div className="flex items-center gap-3"><div className="w-32 h-2 bg-gray-200 rounded-full"><div className="w-[10%] h-full bg-blue-500 rounded-full"></div></div><span className="text-sm font-bold text-gray-600 w-8 text-right">10 %</span></div></div>
                    <div className="flex items-center justify-between"><span className="text-sm text-gray-600">Technical Compliance</span><div className="flex items-center gap-3"><div className="w-32 h-2 bg-gray-200 rounded-full"><div className="w-[25%] h-full bg-blue-500 rounded-full"></div></div><span className="text-sm font-bold text-gray-600 w-8 text-right">25 %</span></div></div>
                    <div className="flex items-center justify-between"><span className="text-sm text-gray-600">Supplier Risk Rating</span><div className="flex items-center gap-3"><div className="w-32 h-2 bg-gray-200 rounded-full"><div className="w-[5%] h-full bg-blue-500 rounded-full"></div></div><span className="text-sm font-bold text-gray-600 w-8 text-right">5 %</span></div></div>
                    <div className="flex items-center justify-between"><span className="text-sm text-gray-600">Delivery Capability</span><div className="flex items-center gap-3"><div className="w-32 h-2 bg-gray-200 rounded-full"><div className="w-[15%] h-full bg-blue-500 rounded-full"></div></div><span className="text-sm font-bold text-gray-600 w-8 text-right">15 %</span></div></div>
                    <div className="flex items-center justify-between"><span className="text-sm text-gray-600">Sustainability / ESG</span><div className="flex items-center gap-3"><div className="w-32 h-2 bg-gray-200 rounded-full"><div className="w-[5%] h-full bg-blue-500 rounded-full"></div></div><span className="text-sm font-bold text-gray-600 w-8 text-right">5 %</span></div></div>
                  </div>
                </div>

                <div className="pt-6 border-t border-gray-100">
                  <h3 className="font-bold text-gray-800 mb-4">Compliance & Additional Conditions</h3>
                  <div className="grid grid-cols-2 gap-3 mb-4">
                     <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" defaultChecked className="rounded text-blue-600 w-4 h-4"/> Suppliers must comply with Supplier Code of Conduct</label>
                     <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" defaultChecked className="rounded text-blue-600 w-4 h-4"/> Compliance with applicable ISO standards</label>
                     <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" defaultChecked className="rounded text-blue-600 w-4 h-4"/> Certificates and test reports must be provided</label>
                     <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" defaultChecked className="rounded text-blue-600 w-4 h-4"/> Disclosure of conflicts of interest</label>
                     <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" defaultChecked className="rounded text-blue-600 w-4 h-4"/> Suppliers must accept standard purchase terms and conditions</label>
                     <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" className="rounded text-blue-600 w-4 h-4"/> Other (specify below)</label>
                  </div>
                  <textarea rows={2} defaultValue="All components must comply with RoHS and REACH regulations. Suppliers must provide material test certificates." className="w-full border border-gray-300 rounded-md p-3 focus:ring-2 focus:ring-blue-500 outline-none resize-none text-sm"></textarea>
                </div>
              </div>
            )}

            {/* STEP 5: REVIEW & SEND */}
            {activeStep === 5 && (
              <div className="space-y-6 animate-in fade-in">
                 <div className="flex justify-between items-center mb-4">
                    <div>
                      <h2 className="text-2xl font-bold text-[#0B2550]">Review RFQ</h2>
                      <p className="text-sm text-gray-500">Please review all the details before sending the RFQ to suppliers.</p>
                    </div>
                    <button className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg text-sm font-bold text-gray-700 hover:bg-gray-50"><Eye size={16}/> Preview as Supplier</button>
                 </div>

                 <div className="grid grid-cols-2 gap-6">
                    <div className="col-span-2 lg:col-span-1 bg-gray-50 p-5 rounded-xl border border-gray-200 relative">
                       <button onClick={()=>setActiveStep(1)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                       <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><FileText size={18} className="text-blue-500"/> Basic Information</h3>
                       <div className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
                         <span className="text-gray-500">RFQ Title</span><span className="font-medium text-gray-800">: CNC Machined Components - Q4 2024</span>
                         <span className="text-gray-500">RFQ Reference No.</span><span className="font-medium text-gray-800">: RFQ-2024-001</span>
                         <span className="text-gray-500">Category</span><span className="font-medium text-gray-800">: Mechanical Parts</span>
                         <span className="text-gray-500">Subcategory</span><span className="font-medium text-gray-800">: CNC Machining</span>
                         <span className="text-gray-500">Procurement Type</span><span className="font-medium text-gray-800">: Goods</span>
                         <span className="text-gray-500">Business Unit</span><span className="font-medium text-gray-800">: Manufacturing</span>
                         <span className="text-gray-500">Project / Program</span><span className="font-medium text-gray-800">: Production Line Upgrade</span>
                         <span className="text-gray-500">Priority</span><span className="font-bold text-red-600 bg-red-50 px-2 py-0.5 rounded w-max mt-1">: High</span>
                         <span className="text-gray-500 mt-1">Expected Award Date</span><span className="font-medium text-gray-800 mt-1">: Oct 15, 2024</span>
                         <span className="text-gray-500">Required Delivery</span><span className="font-medium text-gray-800">: Dec 15, 2024</span>
                         <span className="text-gray-500">Currency</span><span className="font-medium text-gray-800">: USD - US Dollar</span>
                         <span className="text-gray-500 pt-2 border-t border-gray-200 mt-2">Description</span><span className="font-medium text-gray-800 pt-2 border-t border-gray-200 mt-2">: We are seeking quotes for precision CNC machined components as per attached specifications.</span>
                       </div>
                    </div>

                    <div className="col-span-2 lg:col-span-1 space-y-6">
                        <div className="bg-gray-50 p-5 rounded-xl border border-gray-200 relative">
                           <button onClick={()=>setActiveStep(3)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                           <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><Users size={18} className="text-purple-500"/> Suppliers (3 Selected)</h3>
                           <table className="w-full text-sm text-left">
                              <thead className="text-gray-500 border-b border-gray-200">
                                <tr><th className="pb-2 font-medium">#</th><th className="pb-2 font-medium">Supplier Name</th><th className="pb-2 font-medium">Location</th><th className="pb-2 font-medium">Tier</th></tr>
                              </thead>
                              <tbody className="divide-y divide-gray-100">
                                <tr><td className="py-2 text-gray-500">1</td><td className="py-2 font-medium">ABC Components Pvt Ltd</td><td className="py-2 text-gray-600">Chennai, India</td><td className="py-2"><span className="text-xs bg-green-100 text-green-700 px-1 rounded">Tier 1</span></td></tr>
                                <tr><td className="py-2 text-gray-500">2</td><td className="py-2 font-medium">XYZ Manufacturing Co.</td><td className="py-2 text-gray-600">Bengaluru, India</td><td className="py-2"><span className="text-xs bg-green-100 text-green-700 px-1 rounded">Tier 1</span></td></tr>
                                <tr><td className="py-2 text-gray-500">3</td><td className="py-2 font-medium">JKL Fabrication</td><td className="py-2 text-gray-600">Coimbatore, India</td><td className="py-2"><span className="text-xs bg-blue-100 text-blue-700 px-1 rounded">Tier 2</span></td></tr>
                              </tbody>
                           </table>
                        </div>

                        <div className="bg-gray-50 p-5 rounded-xl border border-gray-200 relative">
                           <button onClick={()=>setActiveStep(4)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                           <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><FileText size={18} className="text-amber-500"/> Terms & Conditions</h3>
                           <div className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
                             <span className="text-gray-500">Pricing Model</span><span className="font-medium text-gray-800">: Fixed Price</span>
                             <span className="text-gray-500">Payment Terms</span><span className="font-medium text-gray-800">: Net 30</span>
                             <span className="text-gray-500">Price Validity</span><span className="font-medium text-gray-800">: 60 Days</span>
                             <span className="text-gray-500">Currency</span><span className="font-medium text-gray-800">: USD - US Dollar</span>
                             <span className="text-gray-500">Required Delivery</span><span className="font-medium text-gray-800">: Dec 15, 2024</span>
                             <span className="text-gray-500">Delivery Location</span><span className="font-medium text-gray-800">: Chennai, India</span>
                             <span className="text-gray-500">Incoterms</span><span className="font-medium text-gray-800">: DAP - Delivered at Place</span>
                             <span className="text-gray-500">Packaging</span><span className="font-medium text-gray-800">: Standard Industrial Packaging</span>
                           </div>
                        </div>
                    </div>

                    <div className="col-span-2 bg-gray-50 p-5 rounded-xl border border-gray-200 relative">
                       <button onClick={()=>setActiveStep(2)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                       <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><Box size={18} className="text-indigo-500"/> Items & Specifications</h3>
                       <table className="w-full text-sm text-left">
                          <thead className="text-gray-500 border-b border-gray-200">
                            <tr><th className="pb-2 font-medium">#</th><th className="pb-2 font-medium">Item Name</th><th className="pb-2 font-medium">Category</th><th className="pb-2 font-medium">Quantity</th><th className="pb-2 font-medium">Unit</th><th className="pb-2 font-medium">Target Price</th></tr>
                          </thead>
                          <tbody className="divide-y divide-gray-100">
                            <tr><td className="py-3 text-gray-500">1</td><td className="py-3 font-medium">CNC Machined Housing</td><td className="py-3 text-gray-600">Mechanical Parts</td><td className="py-3 font-medium">500</td><td className="py-3 text-gray-600">Nos</td><td className="py-3 text-gray-600">120.00</td></tr>
                            <tr><td className="py-3 text-gray-500">2</td><td className="py-3 font-medium">Precision Shaft</td><td className="py-3 text-gray-600">Mechanical Parts</td><td className="py-3 font-medium">1,000</td><td className="py-3 text-gray-600">Nos</td><td className="py-3 text-gray-600">45.00</td></tr>
                            <tr><td className="py-3 text-gray-500">3</td><td className="py-3 font-medium">Control Panel Assembly</td><td className="py-3 text-gray-600">Electrical</td><td className="py-3 font-medium">50</td><td className="py-3 text-gray-600">Sets</td><td className="py-3 text-gray-600">850.00</td></tr>
                            <tr><td className="py-3 text-gray-500">4</td><td className="py-3 font-medium">Mounting Bracket</td><td className="py-3 text-gray-600">Mechanical Parts</td><td className="py-3 font-medium">2,000</td><td className="py-3 text-gray-600">Nos</td><td className="py-3 text-gray-600">15.00</td></tr>
                            <tr><td className="py-3 text-gray-500">5</td><td className="py-3 font-medium">Calibration Service</td><td className="py-3 text-gray-600">Services</td><td className="py-3 font-medium">5</td><td className="py-3 text-gray-600">Lots</td><td className="py-3 text-gray-600">500.00</td></tr>
                          </tbody>
                       </table>
                       <div className="mt-4 pt-4 border-t border-gray-200">
                          <h4 className="font-bold text-gray-700 text-sm mb-2">Attachments (2)</h4>
                          <div className="flex gap-2">
                             <div className="flex items-center gap-2 border border-gray-300 rounded p-1.5 px-3 bg-white w-max">
                               <div className="w-5 h-5 bg-red-100 rounded flex items-center justify-center text-red-600 font-bold" style={{fontSize: '8px'}}>PDF</div>
                               <div className="text-xs"><p className="font-bold text-gray-700 truncate w-32">Technical_Specification.pdf</p><p className="text-gray-400">2.4 MB</p></div>
                             </div>
                             <div className="flex items-center gap-2 border border-gray-300 rounded p-1.5 px-3 bg-white w-max">
                               <div className="w-5 h-5 bg-green-100 rounded flex items-center justify-center text-green-600 font-bold" style={{fontSize: '8px'}}>XLS</div>
                               <div className="text-xs"><p className="font-bold text-gray-700 truncate w-32">Component_List.xlsx</p><p className="text-gray-400">1.1 MB</p></div>
                             </div>
                          </div>
                       </div>
                    </div>
                    
                    <div className="col-span-2 bg-gray-50 p-5 rounded-xl border border-gray-200 relative">
                       <button onClick={()=>setActiveStep(4)} className="absolute top-4 right-4 text-blue-600 flex items-center gap-1 text-sm font-bold hover:underline"><Edit size={14}/> Edit</button>
                       <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2"><ShieldCheck size={18} className="text-teal-500"/> Evaluation Criteria & Compliance</h3>
                       <div className="grid grid-cols-2 gap-x-12 gap-y-2">
                          <div className="flex items-center justify-between text-sm"><span className="text-gray-600">Price</span><span className="font-bold text-gray-800">: 40%</span></div>
                          <div className="flex items-center justify-between text-sm"><span className="text-gray-600">Quality & Certifications</span><span className="font-bold text-gray-800">: 10%</span></div>
                          <div className="flex items-center justify-between text-sm"><span className="text-gray-600">Technical Compliance</span><span className="font-bold text-gray-800">: 25%</span></div>
                          <div className="flex items-center justify-between text-sm"><span className="text-gray-600">Supplier Risk Rating</span><span className="font-bold text-gray-800">: 5%</span></div>
                          <div className="flex items-center justify-between text-sm"><span className="text-gray-600">Delivery Capability</span><span className="font-bold text-gray-800">: 15%</span></div>
                          <div className="flex items-center justify-between text-sm"><span className="text-gray-600">Sustainability / ESG</span><span className="font-bold text-gray-800">: 5%</span></div>
                       </div>
                    </div>
                 </div>
              </div>
            )}

          </div>

          {/* BOTTOM ACTION BAR */}
          <div className="p-4 border-t border-gray-200 bg-gray-50 flex justify-between items-center">
            {activeStep > 1 ? (
              <button onClick={handleBack} className="px-6 py-2.5 text-blue-600 bg-white border border-gray-300 font-bold flex items-center gap-2 hover:bg-gray-50 rounded shadow-sm transition-colors"><ChevronLeft size={18}/> Back</button>
            ) : <div></div>}
            
            <div className="flex gap-4">
              <button className="px-6 py-2.5 text-gray-600 bg-white border border-gray-300 font-bold rounded shadow-sm hover:bg-gray-50 transition-colors">Save as Draft</button>
              {activeStep < 5 ? (
                <button onClick={handleNext} className="px-8 py-2.5 bg-[#0B2550] text-white font-bold rounded shadow hover:bg-blue-900 transition-colors flex items-center gap-2">Next <ArrowRight size={18}/></button>
              ) : (
                <button onClick={handleSend} disabled={isSubmitting} className={`px-8 py-2.5 bg-blue-600 text-white font-bold rounded shadow flex items-center gap-2 ${isSubmitting ? 'opacity-70 cursor-wait' : 'hover:bg-blue-700 hover:shadow-lg'}`}>
                  {isSubmitting ? 'Sending...' : <><Send size={18}/> Send RFQ</>}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN (Helper / Stepper Summary) */}
        <div className="w-80 hidden xl:flex flex-col gap-6">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="font-bold text-gray-800 text-lg mb-6">Create RFQ</h3>
            <div className="space-y-6">
              {STEPS.map((step, idx) => {
                const isCompleted = step.id < activeStep;
                const isActive = step.id === activeStep;
                return (
                  <div key={step.id} className="flex gap-4 relative">
                    {idx !== STEPS.length - 1 && <div className={`absolute left-4 top-10 bottom-[-24px] w-0.5 ${isCompleted ? 'bg-blue-600' : 'bg-gray-200'}`}></div>}
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm shrink-0 z-10 transition-colors
                      ${isCompleted ? 'bg-blue-600 text-white' : isActive ? 'bg-blue-600 text-white shadow-md ring-4 ring-blue-50' : 'bg-gray-100 text-gray-400'}`}>
                      {isCompleted ? <Check size={16} /> : step.id}
                    </div>
                    <div>
                      <h4 className={`font-bold text-sm ${isActive ? 'text-[#0B2550]' : 'text-gray-800'}`}>{step.title}</h4>
                      <p className="text-xs text-gray-500 mt-1 leading-relaxed">{step.subtitle}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {activeStep === 5 ? (
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
               <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-4"><Send size={18} className="text-blue-600"/> Send RFQ</h3>
               <div className="space-y-4 mb-6">
                 <label className="flex items-start gap-3 p-3 border border-blue-600 bg-blue-50 rounded-lg cursor-pointer">
                   <input type="radio" name="sendOpts" defaultChecked className="mt-1 text-blue-600"/>
                   <div><p className="font-bold text-[#0B2550] text-sm">Send Now</p><p className="text-xs text-gray-500">Send RFQ to selected suppliers immediately.</p></div>
                 </label>
                 <label className="flex items-start gap-3 p-3 border border-gray-200 rounded-lg cursor-pointer hover:bg-gray-50">
                   <input type="radio" name="sendOpts" className="mt-1"/>
                   <div><p className="font-bold text-gray-700 text-sm">Schedule for Later</p><p className="text-xs text-gray-500">Choose a date and time to send.</p></div>
                 </label>
                 <div className="pt-4 border-t border-gray-100">
                    <h4 className="font-bold text-gray-700 flex items-center gap-2 text-sm mb-2"><Users size={16} className="text-blue-500"/> Selected Suppliers</h4>
                    <p className="text-xs text-gray-500 mb-4">3 suppliers will be invited.</p>
                    <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2"><input type="checkbox" defaultChecked className="rounded text-blue-600"/> Send email notifications to suppliers</label>
                    <label className="flex items-center gap-2 text-sm font-medium text-gray-700"><input type="checkbox" className="rounded text-blue-600"/> Allow suppliers to ask questions</label>
                 </div>
               </div>
               <div className="bg-amber-50 rounded-lg border border-amber-100 p-4">
                 <h3 className="font-bold text-amber-900 flex items-center gap-2 mb-2 text-sm"><Lightbulb size={16} className="text-amber-500"/> Tips</h3>
                 <ul className="text-xs text-amber-800 space-y-1.5">
                   <li className="flex gap-1.5"><Check size={14} className="text-amber-500 shrink-0"/> Review all information before sending.</li>
                   <li className="flex gap-1.5"><Check size={14} className="text-amber-500 shrink-0"/> Ensure all specifications and documents are attached.</li>
                   <li className="flex gap-1.5"><Check size={14} className="text-amber-500 shrink-0"/> Check supplier list and contact details.</li>
                   <li className="flex gap-1.5"><Check size={14} className="text-amber-500 shrink-0"/> You can monitor responses in My RFQs.</li>
                 </ul>
               </div>
            </div>
          ) : (
            <>
              <div className="bg-amber-50 rounded-xl border border-amber-100 p-6">
                <h3 className="font-bold text-amber-900 flex items-center gap-2 mb-3"><Lightbulb size={18} className="text-amber-500"/> Tips</h3>
                <ul className="text-sm text-amber-800 space-y-2">
                  <li className="flex gap-2"><Check size={16} className="text-blue-500 shrink-0"/> Use a clear and specific title.</li>
                  <li className="flex gap-2"><Check size={16} className="text-blue-500 shrink-0"/> Attach technical drawings or specifications.</li>
                  <li className="flex gap-2"><Check size={16} className="text-blue-500 shrink-0"/> Set realistic timelines.</li>
                  <li className="flex gap-2"><Check size={16} className="text-blue-500 shrink-0"/> Include compliance requirements if needed.</li>
                </ul>
              </div>

              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <h3 className="font-bold text-[#0B2550] flex items-center gap-2 mb-2"><HelpCircle size={18} className="text-blue-600"/> Need Help?</h3>
                <ul className="space-y-2 text-sm text-gray-600 mb-4">
                  <li className="hover:underline cursor-pointer">View RFQ template</li>
                  <li className="hover:underline cursor-pointer">Learn about best practices for creating an effective RFQ.</li>
                </ul>
                <button className="text-blue-600 text-sm font-bold flex items-center gap-1 hover:underline">Open Guide <ArrowRight size={14}/></button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const RefreshCw = ({size, className}:any) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>;
const X = ({size, className}:any) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>;
const Box = ({size, className}:any) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>;
const ArrowRight = ({size, className}:any) => <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>;
