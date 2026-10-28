'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/apiClient';
import { Send, CheckCircle, Clock, FileText } from 'lucide-react';
import { useParams } from 'next/navigation';

export default function NegotiationRoom() {
  const { quoteId } = useParams();
  const [tenantId, setTenantId] = useState('');
  const [message, setMessage] = useState('');
  const [proposedAmount, setProposedAmount] = useState('');

  // Fetch tenantId
  if (typeof window !== 'undefined' && !tenantId) {
    const tid = localStorage.getItem('tenant_id');
    if (tid) setTenantId(tid);
  }

  // Fetch negotiation messages
  const { data: messages, isLoading, refetch } = useQuery({
    queryKey: ['negotiations', quoteId],
    queryFn: async () => {
      if (!tenantId || !quoteId) return [];
      const res = await apiClient.get(`/api/v1/actions/quotations/${quoteId}/negotiations?tenant_id=${tenantId}`);
      return res.data;
    },
    enabled: !!tenantId && !!quoteId,
    refetchInterval: 5000 // poll every 5s for demo
  });

  const handleSend = async () => {
    if (!message) return;
    try {
      await apiClient.post(`/api/v1/actions/quotations/${quoteId}/negotiate?tenant_id=${tenantId}`, {
        message,
        proposed_amount: proposedAmount ? parseFloat(proposedAmount) : null
      });
      setMessage('');
      setProposedAmount('');
      refetch();
    } catch (err) {
      alert("Error sending message");
    }
  };

  const handleAccept = async () => {
    try {
      await apiClient.post(`/api/v1/actions/quotations/${quoteId}/accept?tenant_id=${tenantId}`);
      alert("Offer accepted! Purchase Order generated.");
      window.location.href = "/buyer/approvals";
    } catch (err) {
      alert("Error accepting offer");
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto h-[calc(100vh-80px)] flex flex-col">
      <div>
        <h1 className="text-3xl font-bold text-[#0B2550] flex items-center gap-2">
          <FileText size={32} />
          Strategic Negotiation Room
        </h1>
        <p className="text-gray-500 mt-1">Real-time counter-offers and messaging for Quote #{quoteId}</p>
      </div>

      <div className="bg-white rounded-xl shadow-md border border-gray-100 flex-1 flex flex-col overflow-hidden">
        {/* Messages View */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4 bg-gray-50">
          {isLoading ? (
             <div className="text-center text-gray-400">Loading thread...</div>
          ) : messages?.length === 0 ? (
             <div className="text-center text-gray-400 mt-10">No negotiation history yet. Start by sending a counter-offer.</div>
          ) : (
            messages?.map((msg: any) => {
              const isMe = msg.sender_tenant_id === tenantId;
              return (
                <div key={msg.id} className={`flex flex-col ${isMe ? 'items-end' : 'items-start'}`}>
                   <div className={`max-w-[70%] p-4 rounded-xl ${isMe ? 'bg-[#0B2550] text-white rounded-br-none' : 'bg-white border border-gray-200 text-gray-800 rounded-bl-none shadow-sm'}`}>
                      <p className="text-xs opacity-70 mb-1 flex items-center gap-1">
                        <Clock size={12} />
                        {new Date(msg.created_at).toLocaleTimeString()}
                      </p>
                      <p>{msg.message}</p>
                      {msg.proposed_amount && (
                        <div className={`mt-3 p-2 rounded-lg font-bold text-center ${isMe ? 'bg-blue-900/50' : 'bg-gray-100'}`}>
                           Counter-Offer: ${msg.proposed_amount.toLocaleString(undefined, {minimumFractionDigits: 2})}
                        </div>
                      )}
                   </div>
                </div>
              );
            })
          )}
        </div>

        {/* Input Area */}
        <div className="p-4 bg-white border-t border-gray-100">
           <div className="flex gap-4 mb-4">
              <button 
                onClick={handleAccept}
                className="flex items-center gap-2 px-6 py-2 bg-green-600 text-white font-bold rounded-lg hover:bg-green-700 transition-colors"
              >
                <CheckCircle size={20} />
                Accept Latest Offer
              </button>
           </div>
           
           <div className="flex gap-3">
             <div className="flex-1 space-y-2">
                <textarea 
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Type your negotiation message..."
                  className="w-full border border-gray-300 rounded-lg p-3 outline-none focus:ring-2 focus:ring-[#0B2550] resize-none h-20"
                />
                <div className="flex gap-2 items-center">
                   <span className="text-gray-500 font-medium text-sm">Proposed Amount ($):</span>
                   <input 
                     type="number"
                     value={proposedAmount}
                     onChange={(e) => setProposedAmount(e.target.value)}
                     className="border border-gray-300 rounded-md p-2 outline-none focus:ring-2 focus:ring-[#0B2550] w-48"
                     placeholder="e.g. 115000"
                   />
                </div>
             </div>
             <button 
               onClick={handleSend}
               disabled={!message}
               className="bg-[#0B2550] text-white px-6 rounded-lg hover:bg-blue-900 transition-colors disabled:opacity-50 flex items-center justify-center"
             >
               <Send size={24} />
             </button>
           </div>
        </div>
      </div>
    </div>
  );
}
