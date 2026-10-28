'use client';
import React, { useState, useEffect } from 'react';
import { PageHeader } from '@/components/ui/PageHeader';
import { StatusBadge } from '@/components/ui/StatusBadge';

export default function NegotiationTheater() {
  const handleGenericAction = (actionName: string) => {
    alert(`Action triggered: ${actionName}\n\nThis feature is currently being integrated with the backend APIs.`);
  };

  const [messages, setMessages] = useState<any[]>([]);
  const [negotiationState, setNegotiationState] = useState('idle'); // idle, negotiating, completed
  const [awarded, setAwarded] = useState(false);

  // Simulated negotiation sequence
  useEffect(() => {
    if (negotiationState === 'negotiating') {
       const sequence = [
          { sender: 'AI Buyer (You)', text: "Hello Kovai Diecast. We need 60k units of HPDC AlSi9Cu3. Our target price is $14.20.", type: 'buyer', delay: 1000 },
          { sender: 'Kovai ERP', text: "Current baseline for 60k units is $15.80 due to aluminum spot prices.", type: 'supplier', delay: 3500 },
          { sender: 'AI Buyer (You)', text: "Based on our Digital Twin telemetry, your Chennai plant currently has 18% idle capacity. If we commit to a 2-year blanket order to fill that capacity, can you meet $14.60?", type: 'buyer_tactic', delay: 6000 },
          { sender: 'Kovai ERP', text: "Analyzing capacity... We can accept $14.80 for a 2-year commitment.", type: 'supplier', delay: 9000 },
          { sender: 'AI Buyer (You)', text: "We accept $14.80, provided we can lock the lead time to 3 weeks.", type: 'buyer', delay: 11000 },
          { sender: 'Kovai ERP', text: "Agreed. $14.80 at 3-week lead time. Generating final quote...", type: 'supplier_success', delay: 13500 }
       ];

       let timeouts: NodeJS.Timeout[] = [];
       sequence.forEach((msg) => {
          const timeout = setTimeout(() => {
             setMessages(prev => [...prev, msg]);
             if (msg.type === 'supplier_success') {
                setTimeout(() => setNegotiationState('completed'), 1000);
             }
          }, msg.delay);
          timeouts.push(timeout);
       });

       return () => timeouts.forEach(clearTimeout);
    }
  }, [negotiationState]);

  return (
    <div className="max-w-[1600px] mx-auto pb-12">
      <PageHeader 
        title="Autonomous Negotiation Theater" 
        subtitle="Deploy LangGraph Sourcing Agents to actively negotiate price, volume, and lead times with suppliers on your behalf."
        actions={
          <div className="flex gap-3">
             <button onClick={() => handleGenericAction('Configure Agent Guardrails')}  className="bg-white border border-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium hover:bg-slate-50 shadow-sm transition-colors">
                Configure Agent Guardrails
             </button>
             {negotiationState === 'idle' && (
                <button onClick={() => setNegotiationState('negotiating')} className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 shadow-sm transition-colors flex items-center gap-2">
                   <span className="text-xl">🤖</span> Deploy Agent to Kovai Diecast
                </button>
             )}
             {negotiationState === 'negotiating' && (
                <button onClick={() => handleGenericAction('Negotiating...')}  disabled className="bg-slate-200 text-slate-600 px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 cursor-wait">
                   <span className="w-2 h-2 rounded-full bg-blue-500 animate-ping"></span> Negotiating...
                </button>
             )}
             {negotiationState === 'completed' && (
                <button onClick={() => handleGenericAction('✓ Negotiation Concluded')}  disabled className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2">
                   <span className="text-xl">✓</span> Negotiation Concluded
                </button>
             )}
          </div>
        }
      />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        
        {/* The Live Negotiation Chat Feed */}
        <div className="xl:col-span-2 bg-white rounded-xl border border-[var(--border-light)] shadow-sm flex flex-col h-[700px]">
           <div className="p-4 border-b border-slate-100 bg-slate-50 flex justify-between items-center">
              <div className="flex items-center gap-3">
                 <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xl border border-blue-200 shadow-sm">
                    🤖
                 </div>
                 <div>
                    <h3 className="font-bold text-slate-900 text-sm">Agent: Procurement_Bot_v4</h3>
                    <p className="text-xs text-slate-500">Engaging Kovai Diecast ERP (API/EDI Interface)</p>
                 </div>
              </div>
              <StatusBadge status={negotiationState === 'negotiating' ? 'Active' : negotiationState === 'completed' ? 'Completed' : 'Idle'} />
           </div>

           <div className="flex-1 overflow-y-auto p-6 bg-slate-50/50 space-y-6">
              {messages.length === 0 && negotiationState === 'idle' && (
                 <div className="flex flex-col items-center justify-center h-full text-slate-400">
                    <span className="text-4xl mb-3">💬</span>
                    <p>Agent is standing by. Click Deploy to initiate negotiation.</p>
                 </div>
              )}

              {messages.map((msg, i) => (
                 <div key={i} className={`flex ${msg.sender.includes('Buyer') ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-[75%] rounded-2xl p-4 shadow-sm ${
                       msg.type === 'buyer' ? 'bg-blue-600 text-white rounded-br-none' : 
                       msg.type === 'buyer_tactic' ? 'bg-gradient-to-r from-blue-600 to-purple-600 text-white border border-purple-400 rounded-br-none' :
                       msg.type === 'supplier_success' ? 'bg-green-50 border border-green-200 text-green-900 rounded-bl-none' :
                       'bg-white border border-slate-200 text-slate-800 rounded-bl-none'
                    }`}>
                       {msg.type === 'buyer_tactic' && (
                          <div className="text-[10px] uppercase font-bold text-purple-200 mb-1 flex items-center gap-1">
                             <span className="animate-pulse">⚡</span> Digital Twin Leverage Applied
                          </div>
                       )}
                       <div className="text-[10px] opacity-70 mb-1 font-bold">{msg.sender}</div>
                       <div className="text-sm leading-relaxed">{msg.text}</div>
                    </div>
                 </div>
              ))}
              
              {negotiationState === 'negotiating' && (
                 <div className="flex justify-start">
                    <div className="bg-white border border-slate-200 rounded-2xl rounded-bl-none p-4 shadow-sm flex items-center gap-2 text-slate-400">
                       <span className="w-2 h-2 rounded-full bg-slate-300 animate-bounce"></span>
                       <span className="w-2 h-2 rounded-full bg-slate-300 animate-bounce" style={{animationDelay: '150ms'}}></span>
                       <span className="w-2 h-2 rounded-full bg-slate-300 animate-bounce" style={{animationDelay: '300ms'}}></span>
                    </div>
                 </div>
              )}
           </div>
        </div>

        {/* Human-in-the-Loop Approval Queue */}
        <div className="space-y-6">
           <div className="bg-white border border-[var(--border-light)] rounded-xl shadow-sm overflow-hidden flex flex-col">
              <div className="p-5 border-b border-slate-100 bg-slate-50">
                 <h3 className="font-bold text-slate-900 flex items-center">
                    <span className="text-xl mr-2 text-green-600">⚖️</span> Final Deal Approval
                 </h3>
                 <p className="text-xs text-slate-500 mt-1">Human-in-the-loop sign-off queue.</p>
              </div>

              <div className="p-5 space-y-5">
                 {negotiationState !== 'completed' ? (
                    <div className="text-center py-8 text-slate-400">
                       <p className="text-sm">Awaiting agent conclusion...</p>
                    </div>
                 ) : (
                    <div className="animate-fade-in-up">
                       <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
                          <h4 className="font-bold text-green-900 mb-3 text-sm">Optimized Terms Secured</h4>
                          
                          <div className="space-y-2 mb-4">
                             <div className="flex justify-between items-center text-xs">
                                <span className="text-slate-600">Final Price:</span>
                                <span className="font-bold text-green-700 text-sm">$14.80 / unit</span>
                             </div>
                             <div className="flex justify-between items-center text-xs">
                                <span className="text-slate-600">Lead Time:</span>
                                <span className="font-bold text-slate-900 text-sm">3 Weeks</span>
                             </div>
                             <div className="flex justify-between items-center text-xs">
                                <span className="text-slate-600">Savings vs Baseline:</span>
                                <span className="font-bold text-green-600 text-sm">-$60,000</span>
                             </div>
                          </div>

                          {!awarded ? (
                             <button onClick={() => setAwarded(true)} className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 rounded-lg text-sm transition-colors shadow-sm flex items-center justify-center gap-2">
                                ✍️ Award Contract to Kovai
                             </button>
                          ) : (
                             <div className="bg-white border border-green-200 rounded-lg p-3 text-center text-sm font-bold text-green-700 flex flex-col items-center gap-2">
                                <span className="text-2xl">🎉</span>
                                Contract Awarded! Smart Contract generation initialized.
                             </div>
                          )}
                       </div>
                    </div>
                 )}
              </div>
           </div>
        </div>

      </div>
    </div>
  );
}
