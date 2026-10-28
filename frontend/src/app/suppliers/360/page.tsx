'use client';

import React, { useState } from 'react';
import { 
  ChevronRight, Star, TrendingUp, AlertTriangle, ShieldCheck, 
  MapPin, Phone, Mail, FileText, Activity, Clock, Box, DollarSign, 
  Award, RefreshCw, Zap, Check
} from 'lucide-react';
import Link from 'next/link';

export default function Supplier360Scorecard() {
  const [activeTab, setActiveTab] = useState('performance');

  const supplier = {
    name: 'ABC Components Ltd',
    code: 'SUP-1001',
    status: 'Approved',
    riskLevel: 'Low',
    rating: 4.8,
    category: 'Mechanical Parts',
    onboarded: 'Jan 2022',
    spend: 'â‚¹ 12.4M',
  };

  const performanceMetrics = [
    { label: 'On-Time Delivery', value: '98%', target: '95%', trend: '+2%', status: 'good' },
    { label: 'Quality / Defect Rate', value: '0.4%', target: '< 1%', trend: '-0.1%', status: 'good' },
    { label: 'Invoice Accuracy', value: '99%', target: '98%', trend: '0%', status: 'good' },
    { label: 'Responsiveness', value: '4 hrs', target: '< 24 hrs', trend: '-2 hrs', status: 'good' },
  ];

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-20 pt-6">
      {/* HEADER & BREADCRUMBS */}
      <div className="flex justify-between items-end">
        <div>
            <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
               <Link href="/suppliers" className="hover:text-blue-600 transition-colors">Suppliers</Link> <ChevronRight size={12}/> <span className="text-[#0B2550]">Supplier 360</span>
            </div>
            <div className="flex items-center gap-4">
               <div className="w-16 h-16 bg-blue-600 text-white font-black text-2xl rounded-xl flex items-center justify-center shadow-sm">
                  ABC
               </div>
               <div>
                  <h1 className="text-3xl font-black text-[#0B2550] mb-1">{supplier.name}</h1>
                  <div className="flex gap-3 items-center">
                     <span className="text-sm font-bold text-gray-500">{supplier.code}</span>
                     <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs font-bold border border-green-200 flex items-center gap-1">
                        <ShieldCheck size={12}/> {supplier.status}
                     </span>
                     <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-bold border border-blue-200 flex items-center gap-1">
                        <Star size={12} className="fill-blue-700"/> {supplier.rating} / 5.0
                     </span>
                  </div>
               </div>
            </div>
        </div>
        
        <div className="flex gap-3">
            <button className="px-4 py-2 border border-blue-200 text-blue-700 font-bold rounded-lg shadow-sm hover:bg-blue-50 text-sm bg-white flex items-center gap-2">
                <FileText size={16}/> View Contract
            </button>
            <button className="px-4 py-2 bg-blue-600 text-white font-bold rounded-lg shadow-md hover:bg-blue-700 text-sm flex items-center gap-2">
                <Activity size={16}/> Request Audit
            </button>
        </div>
      </div>

      {/* QUICK STATS */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
         <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex items-center gap-4">
            <div className="w-12 h-12 bg-blue-50 text-blue-600 rounded-full flex items-center justify-center"><Box size={20}/></div>
            <div><p className="text-xs font-bold text-gray-500 uppercase">Primary Category</p><p className="font-bold text-[#0B2550]">{supplier.category}</p></div>
         </div>
         <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex items-center gap-4">
            <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-full flex items-center justify-center"><DollarSign size={20}/></div>
            <div><p className="text-xs font-bold text-gray-500 uppercase">YTD Spend</p><p className="font-bold text-[#0B2550]">{supplier.spend}</p></div>
         </div>
         <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex items-center gap-4">
            <div className="w-12 h-12 bg-amber-50 text-amber-600 rounded-full flex items-center justify-center"><AlertTriangle size={20}/></div>
            <div><p className="text-xs font-bold text-gray-500 uppercase">Risk Level</p><p className="font-bold text-[#0B2550]">{supplier.riskLevel}</p></div>
         </div>
         <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex items-center gap-4">
            <div className="w-12 h-12 bg-purple-50 text-purple-600 rounded-full flex items-center justify-center"><Award size={20}/></div>
            <div><p className="text-xs font-bold text-gray-500 uppercase">Compliance Score</p><p className="font-bold text-[#0B2550]">100%</p></div>
         </div>
      </div>

      {/* TABS */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
          <div className="flex border-b border-gray-200 overflow-x-auto hide-scrollbar">
             {[
               { id: 'performance', label: 'Performance Scorecard' },
               { id: 'risk', label: 'Risk & Compliance' },
               { id: 'transactions', label: 'Transactions (Orders & RFQs)' },
               { id: 'profile', label: 'Company Profile & Contacts' }
             ].map(tab => (
               <button 
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)} 
                  className={`px-6 py-4 whitespace-nowrap font-bold text-sm transition-colors ${activeTab === tab.id ? 'border-b-2 border-blue-600 text-blue-700 bg-blue-50/30' : 'text-gray-500 hover:bg-gray-50'}`}
               >
                  {tab.label}
               </button>
             ))}
          </div>

          <div className="p-8">
              {/* PERFORMANCE TAB */}
              {activeTab === 'performance' && (
                 <div className="space-y-8 animate-in fade-in">
                     <div className="flex justify-between items-center mb-6">
                        <h2 className="text-xl font-bold text-[#0B2550]">Q3 2025 Performance Scorecard</h2>
                        <span className="text-sm font-bold text-gray-500 flex items-center gap-1"><RefreshCw size={14}/> Last updated: Today</span>
                     </div>

                     <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        {/* Metrics Grid */}
                        <div className="grid grid-cols-2 gap-4">
                           {performanceMetrics.map((metric, i) => (
                              <div key={i} className="bg-gray-50 rounded-xl p-5 border border-gray-200 relative overflow-hidden group hover:border-blue-300 transition-colors cursor-default">
                                 <div className="absolute top-0 right-0 w-16 h-16 bg-blue-500/5 rounded-bl-full -z-10 group-hover:bg-blue-500/10 transition-colors"></div>
                                 <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-1">{metric.label}</p>
                                 <div className="flex items-end gap-2 mb-2">
                                    <h3 className="text-3xl font-black text-[#0B2550]">{metric.value}</h3>
                                    <span className="text-sm font-bold text-green-600 flex items-center mb-1"><TrendingUp size={14} className="mr-0.5"/> {metric.trend}</span>
                                 </div>
                                 <div className="w-full bg-gray-200 rounded-full h-1.5 mb-1">
                                    <div className="bg-green-500 h-1.5 rounded-full" style={{ width: metric.status === 'good' ? '90%' : '50%' }}></div>
                                 </div>
                                 <p className="text-xs text-gray-400">Target: {metric.target}</p>
                              </div>
                           ))}
                        </div>

                        {/* AI Insights */}
                        <div className="bg-gradient-to-br from-indigo-900 to-[#0B2550] rounded-xl p-6 text-white relative overflow-hidden shadow-lg">
                           <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 blur-2xl rounded-full"></div>
                           <h3 className="font-bold text-indigo-200 flex items-center gap-2 mb-4 uppercase text-xs tracking-widest"><Zap size={14}/> AI Performance Insight</h3>
                           
                           <div className="space-y-4">
                              <p className="text-sm leading-relaxed text-blue-50 font-medium">
                                 ABC Components Ltd is performing in the <strong>Top 5%</strong> of all Mechanical Parts suppliers. Their on-time delivery rate has improved by 2% this quarter due to their new automated dispatch system.
                              </p>
                              <div className="bg-white/10 p-3 rounded-lg border border-white/20 backdrop-blur-sm">
                                 <p className="text-xs text-indigo-200 font-bold mb-1">Recommendation</p>
                                 <p className="text-sm">Consider promoting ABC Components to "Strategic Partner" tier to unlock volume discounts on contract renewal next month.</p>
                              </div>
                           </div>
                        </div>
                     </div>

                     {/* Issue Log */}
                     <div className="mt-8">
                         <h3 className="text-lg font-bold text-[#0B2550] mb-4">Recent Quality Exceptions</h3>
                         <div className="border border-gray-200 rounded-lg overflow-hidden">
                            <table className="w-full text-sm text-left">
                               <thead className="bg-gray-50 text-gray-500 border-b border-gray-200">
                                  <tr><th className="p-3">Date</th><th className="p-3">PO Reference</th><th className="p-3">Issue Type</th><th className="p-3">Status</th></tr>
                               </thead>
                               <tbody className="divide-y divide-gray-100">
                                  <tr className="hover:bg-gray-50">
                                     <td className="p-3 text-gray-600">Aug 12, 2025</td>
                                     <td className="p-3 font-bold text-blue-600">PO-2025-00045</td>
                                     <td className="p-3">Slight scratch on 2 housings</td>
                                     <td className="p-3"><span className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs font-bold border border-green-200">Resolved - Replaced</span></td>
                                  </tr>
                                  <tr className="hover:bg-gray-50">
                                     <td className="p-3 text-gray-600">Jun 05, 2025</td>
                                     <td className="p-3 font-bold text-blue-600">PO-2025-00012</td>
                                     <td className="p-3">Missing documentation</td>
                                     <td className="p-3"><span className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs font-bold border border-green-200">Resolved - Uploaded</span></td>
                                  </tr>
                               </tbody>
                            </table>
                         </div>
                     </div>
                 </div>
              )}

              {activeTab === 'risk' && (
                 <div className="animate-in fade-in space-y-6">
                    <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex gap-3">
                        <ShieldCheck className="text-green-600 shrink-0" size={24}/>
                        <div>
                           <h4 className="font-bold text-green-900">Compliant & Low Risk</h4>
                           <p className="text-sm text-green-800">Supplier has passed all automated risk checks (Financial, Sanctions, ESG). All critical certifications are up to date.</p>
                        </div>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-6">
                       <div className="border border-gray-200 rounded-lg p-5">
                          <h4 className="font-bold text-gray-800 mb-4 text-sm uppercase tracking-wide">Certifications</h4>
                          <div className="space-y-3 text-sm">
                             <div className="flex justify-between items-center"><span className="text-gray-600">ISO 9001:2015</span><span className="text-green-600 font-bold flex items-center gap-1"><Check size={14}/> Valid till 2027</span></div>
                             <div className="flex justify-between items-center"><span className="text-gray-600">ISO 14001 (ESG)</span><span className="text-green-600 font-bold flex items-center gap-1"><Check size={14}/> Valid till 2026</span></div>
                             <div className="flex justify-between items-center"><span className="text-gray-600">Information Security</span><span className="text-amber-600 font-bold">Expires in 45 days</span></div>
                          </div>
                       </div>
                    </div>
                 </div>
              )}

              {activeTab === 'transactions' && (
                 <div className="animate-in fade-in py-10 text-center text-gray-500">
                    <Activity size={48} className="mx-auto mb-4 text-gray-300 stroke-1"/>
                    <p>Transaction history (POs, RFQs, Invoices) will be listed here.</p>
                 </div>
              )}

              {activeTab === 'profile' && (
                 <div className="animate-in fade-in grid grid-cols-2 gap-8">
                    <div>
                       <h3 className="font-bold text-[#0B2550] mb-4 flex items-center gap-2"><MapPin size={18} className="text-blue-500"/> Corporate Headquarters</h3>
                       <div className="bg-gray-50 p-4 rounded-lg border border-gray-200 text-sm text-gray-600 space-y-1">
                          <p className="font-bold text-gray-800">ABC Components Ltd</p>
                          <p>45, Industrial Area, Electronic City</p>
                          <p>Bengaluru, Karnataka 560100</p>
                          <p>India</p>
                       </div>
                    </div>
                    <div>
                       <h3 className="font-bold text-[#0B2550] mb-4 flex items-center gap-2"><Phone size={18} className="text-blue-500"/> Key Contacts</h3>
                       <div className="bg-gray-50 p-4 rounded-lg border border-gray-200 text-sm space-y-3">
                          <div>
                             <p className="font-bold text-gray-800">Rakesh Kumar (Account Manager)</p>
                             <p className="text-gray-600 flex items-center gap-2 mt-1"><Mail size={14}/> rakesh.kumar@abccomponents.com</p>
                             <p className="text-gray-600 flex items-center gap-2 mt-1"><Phone size={14}/> +91 98765 43210</p>
                          </div>
                       </div>
                    </div>
                 </div>
              )}

          </div>
      </div>
    </div>
  );
}
