'use client';

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Search,
  LayoutDashboard,
  CheckSquare,
  FileText,
  Target,
  FileSignature,
  Package,
  Truck,
  CreditCard,
  ShieldAlert,
  TrendingUp,
  Workflow,
  Database,
  Sliders,
  Sun,
  Moon,
  Laptop,
  Bell,
  Copy,
  ExternalLink,
  ArrowRight,
  X,
} from 'lucide-react';
import { saveChoice } from '@/lib/theme';
import { useToast } from './toast';

export type CommandItem = {
  id: string;
  category: 'Modules' | 'Actions' | 'Lookup';
  title: string;
  subtitle?: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  badge?: string;
  keywords?: string[];
  onSelect: () => void;
};

export default function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const inputId = useId();

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIndex(0);
      const timer = setTimeout(() => inputRef.current?.focus(), 40);
      return () => clearTimeout(timer);
    }
  }, [open]);

  // Command item definitions
  const items = useMemo<CommandItem[]>(() => {
    const nav = (href: string) => {
      onClose();
      router.push(href);
    };

    const modules: CommandItem[] = [
      {
        id: 'cmd-dashboard',
        category: 'Modules',
        title: 'Command Centre',
        subtitle: 'Live operational pulse, real-time telemetry & spend KPIs',
        icon: LayoutDashboard,
        badge: 'AIX-01',
        keywords: ['overview', 'home', 'kpi', 'metrics', 'analytics', 'telemetry'],
        onSelect: () => nav('/pic'),
      },
      {
        id: 'cmd-tasks',
        category: 'Modules',
        title: 'Tasks & Approvals',
        subtitle: 'My pending workflow inbox, 4-eye sign-offs & delegations',
        icon: CheckSquare,
        badge: 'Inbox',
        keywords: ['inbox', 'approvals', 'todo', 'signoff', 'reviews', 'actions'],
        onSelect: () => nav('/pic/tasks'),
      },
      {
        id: 'cmd-requisitions',
        category: 'Modules',
        title: 'Requisitions',
        subtitle: 'Purchase requests, material requisitions & approvals',
        icon: FileText,
        badge: 'P2P',
        keywords: ['pr', 'request', 'demand', 'purchase request', 'items'],
        onSelect: () => nav('/pic/requisitions'),
      },
      {
        id: 'cmd-sourcing',
        category: 'Modules',
        title: 'Sourcing & RFQs',
        subtitle: 'Tenders, supplier bids, auctions & award recommendations',
        icon: Target,
        badge: 'S2C',
        keywords: ['rfq', 'rfp', 'bids', 'tender', 'awards', 'negotiation'],
        onSelect: () => nav('/pic/sourcing'),
      },
      {
        id: 'cmd-contracts',
        category: 'Modules',
        title: 'Contracts & Agreements',
        subtitle: 'Master service agreements, rate cards, SLAs & renewals',
        icon: FileSignature,
        badge: 'Legal',
        keywords: ['msa', 'rate cards', 'terms', 'clauses', 'agreements'],
        onSelect: () => nav('/pic/contracts'),
      },
      {
        id: 'cmd-purchase-orders',
        category: 'Modules',
        title: 'Purchase Orders',
        subtitle: 'Released POs, revisions, line tracking & change orders',
        icon: Package,
        badge: 'Orders',
        keywords: ['po', 'orders', 'lines', 'commitments', 'releases'],
        onSelect: () => nav('/pic/purchase-orders'),
      },
      {
        id: 'cmd-receiving',
        category: 'Modules',
        title: 'Receiving & Goods Receipt',
        subtitle: 'Inbound receipts, ASN delivery, inspections & warehouse stock',
        icon: Truck,
        badge: 'Logistics',
        keywords: ['receipt', 'grn', 'asn', 'warehouse', 'inspection', 'inventory', 'delivery'],
        onSelect: () => nav('/pic/receiving'),
      },
      {
        id: 'cmd-invoices',
        category: 'Modules',
        title: 'Invoices & 3-Way Match',
        subtitle: 'AP processing, 3-way reconciliation, dispute resolution & holds',
        icon: CreditCard,
        badge: 'Payables',
        keywords: ['ap', 'bills', 'reconciliation', '3-way match', 'payments', 'credits'],
        onSelect: () => nav('/pic/invoices'),
      },
      {
        id: 'cmd-suppliers-risk',
        category: 'Modules',
        title: 'Supplier Twin & Risk',
        subtitle: 'Geopolitical resilience, tier-n mapping, ESG & financial health',
        icon: ShieldAlert,
        badge: 'Risk Twin',
        keywords: ['vendors', 'tier-n', 'risk', 'esg', 'resilience', 'disruption'],
        onSelect: () => nav('/pic/suppliers/risk'),
      },
      {
        id: 'cmd-savings',
        category: 'Modules',
        title: 'Savings Tracker',
        subtitle: 'Negotiated, cost-avoidance & realised procurement savings',
        icon: TrendingUp,
        badge: 'Value',
        keywords: ['savings', 'cost reduction', 'value', 'realised', 'avoidance'],
        onSelect: () => nav('/pic/savings'),
      },
      {
        id: 'cmd-bpmn',
        category: 'Modules',
        title: 'BPMN Process Flows',
        subtitle: 'Executable workflow definitions, token positions & audit paths',
        icon: Workflow,
        badge: 'BPMN',
        keywords: ['workflow', 'process', 'diagram', 'camunda', 'tokens', 'orchestration'],
        onSelect: () => nav('/pic/bpmn-flows'),
      },
      {
        id: 'cmd-mdm',
        category: 'Modules',
        title: 'Master Data (MDM)',
        subtitle: 'Material masters, purch org hierarchies & legal entities',
        icon: Database,
        badge: 'Master',
        keywords: ['master data', 'materials', 'purch org', 'legal entity', 'taxonomy'],
        onSelect: () => nav('/pic/mdm'),
      },
      {
        id: 'cmd-admin',
        category: 'Modules',
        title: 'Tenant Admin & Connectors',
        subtitle: 'User roles, ERP connectors, audit rules & integrations',
        icon: Sliders,
        badge: 'Admin',
        keywords: ['admin', 'roles', 'sap', 'oracle', 'connectors', 'settings'],
        onSelect: () => nav('/pic/admin'),
      },
    ];

    const actions: CommandItem[] = [
      {
        id: 'act-theme-light',
        category: 'Actions',
        title: 'Switch to Light Theme',
        subtitle: 'Crisp high-contrast daytime interface',
        icon: Sun,
        keywords: ['theme', 'light', 'white', 'day'],
        onSelect: () => {
          saveChoice('light');
          toast.success('Switched to Light theme');
          onClose();
        },
      },
      {
        id: 'act-theme-dark',
        category: 'Actions',
        title: 'Switch to Dark Theme',
        subtitle: 'Sleek midnight palette easy on the eyes',
        icon: Moon,
        keywords: ['theme', 'dark', 'night', 'black'],
        onSelect: () => {
          saveChoice('dark');
          toast.success('Switched to Dark theme');
          onClose();
        },
      },
      {
        id: 'act-theme-system',
        category: 'Actions',
        title: 'Use System Theme Preference',
        subtitle: 'Sync automatically with your operating system',
        icon: Laptop,
        keywords: ['theme', 'system', 'auto'],
        onSelect: () => {
          saveChoice('system');
          toast.success('Synchronized with system theme');
          onClose();
        },
      },
      {
        id: 'act-notifications',
        category: 'Actions',
        title: 'View Notifications',
        subtitle: 'Real-time alert log & event callbacks',
        icon: Bell,
        keywords: ['alerts', 'messages', 'notifications'],
        onSelect: () => nav('/pic/notifications'),
      },
      {
        id: 'act-copy-link',
        category: 'Actions',
        title: 'Copy Current Page Link',
        subtitle: 'Copy URL to share with team members',
        icon: Copy,
        keywords: ['share', 'copy', 'url', 'clipboard'],
        onSelect: () => {
          try {
            navigator.clipboard.writeText(window.location.href);
            toast.success('Page URL copied to clipboard');
          } catch {
            toast.problem(new Error('Could not copy URL to clipboard'));
          }
          onClose();
        },
      },
    ];

    return [...modules, ...actions];
  }, [router, onClose, toast]);

  // Filter items based on user search query
  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;

    // Direct document prefix lookup support
    const isDocRef = /^(PO|REQ|INV|VEND|ASN|GR|CONT)-/i.test(q) || /^[A-Z0-9]{4,}-[0-9]+/i.test(q);

    const matched = items.filter((item) => {
      if (item.title.toLowerCase().includes(q)) return true;
      if (item.subtitle?.toLowerCase().includes(q)) return true;
      if (item.badge?.toLowerCase().includes(q)) return true;
      return item.keywords?.some((k) => k.toLowerCase().includes(q));
    });

    if (isDocRef) {
      const lookupItem: CommandItem = {
        id: `lookup-${q}`,
        category: 'Lookup',
        title: `Search Reference: "${q.toUpperCase()}"`,
        subtitle: 'Quick-jump to purchase orders, requisitions, or invoices matching this ID',
        icon: ExternalLink,
        badge: 'Lookup',
        onSelect: () => {
          onClose();
          const upper = q.toUpperCase();
          if (upper.startsWith('PO-')) router.push(`/pic/purchase-orders?q=${encodeURIComponent(upper)}`);
          else if (upper.startsWith('REQ-')) router.push(`/pic/requisitions?q=${encodeURIComponent(upper)}`);
          else if (upper.startsWith('INV-')) router.push(`/pic/invoices?q=${encodeURIComponent(upper)}`);
          else router.push(`/pic?q=${encodeURIComponent(upper)}`);
        },
      };
      return [lookupItem, ...matched];
    }

    return matched;
  }, [query, items, onClose, router]);

  // Keep active index in bounds
  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  // Scroll active item into view
  useEffect(() => {
    if (!listRef.current) return;
    const activeEl = listRef.current.children[activeIndex] as HTMLElement | undefined;
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  // Global keyboard shortcuts (Ctrl+K / Cmd+K and Esc / Arrows)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => (prev + 1) % Math.max(1, filteredItems.length));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => (prev - 1 + filteredItems.length) % Math.max(1, filteredItems.length));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const current = filteredItems[activeIndex];
      if (current) current.onSelect();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-14 backdrop-blur-md transition-opacity duration-200"
      onClick={onClose}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-label="Universal Command Palette"
    >
      <div
        className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-line-strong bg-surface text-ink shadow-2xl transition-all animate-pop"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Glow Header Accent Line */}
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand via-accent to-sky-400" />

        {/* Search Input Bar */}
        <div className="flex items-center gap-3 border-b border-line px-4 py-3.5">
          <Search size={18} className="shrink-0 text-brand-ink" />
          <input
            ref={inputRef}
            id={inputId}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search modules, actions, or jump to PO / REQ / INV..."
            className="w-full bg-transparent text-sm font-medium text-ink placeholder:text-ink-3 focus:outline-none"
            role="combobox"
            aria-expanded="true"
            aria-controls="command-list"
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="rounded-md p-1 text-ink-3 hover:bg-surface-3 hover:text-ink"
              aria-label="Clear query"
            >
              <X size={14} />
            </button>
          ) : (
            <kbd className="hidden sm:inline-flex items-center gap-1 rounded border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
              ESC
            </kbd>
          )}
        </div>

        {/* Results List */}
        <div className="max-h-[380px] overflow-y-auto p-2">
          {filteredItems.length === 0 ? (
            <div className="py-10 text-center">
              <p className="text-sm font-medium text-ink-2">No matching modules or actions found</p>
              <p className="mt-1 text-xs text-ink-3">Try searching for &quot;PO&quot;, &quot;tasks&quot;, &quot;dark theme&quot;, or a document number</p>
            </div>
          ) : (
            <ul ref={listRef} id="command-list" role="listbox" className="space-y-1">
              {filteredItems.map((item, index) => {
                const isSelected = index === activeIndex;
                const Icon = item.icon;
                return (
                  <li
                    key={item.id}
                    role="option"
                    aria-selected={isSelected}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={item.onSelect}
                    className={`group flex cursor-pointer items-center justify-between rounded-xl px-3.5 py-2.5 transition-colors ${
                      isSelected
                        ? 'bg-brand/10 text-brand-ink ring-1 ring-inset ring-brand/30'
                        : 'text-ink hover:bg-surface-2'
                    }`}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <span
                        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors ${
                          isSelected
                            ? 'bg-brand text-white shadow-sm'
                            : 'bg-surface-3 text-ink-2 group-hover:bg-brand-soft group-hover:text-brand-ink'
                        }`}
                      >
                        <Icon size={16} />
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-semibold leading-snug">
                            {item.title}
                          </span>
                          {item.badge && (
                            <span
                              className={`rounded-full px-2 py-0.2 font-mono text-[10px] font-semibold uppercase tracking-wider ${
                                isSelected
                                  ? 'bg-brand/20 text-brand-ink'
                                  : 'bg-surface-3 text-ink-3'
                              }`}
                            >
                              {item.badge}
                            </span>
                          )}
                        </div>
                        {item.subtitle && (
                          <p className="truncate text-xs text-ink-3">{item.subtitle}</p>
                        )}
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-2 pl-2">
                      {isSelected && (
                        <span className="flex items-center gap-1 text-xs font-medium text-brand-ink">
                          <span className="hidden sm:inline">Open</span>
                          <ArrowRight size={13} />
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Footer Navigation Hints */}
        <div className="flex items-center justify-between border-t border-line bg-surface-2/80 px-4 py-2 text-[11px] text-ink-3">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1">
              <kbd className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px]">↑</kbd>
              <kbd className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px]">↓</kbd>
              <span>navigate</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <kbd className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px]">↵</kbd>
              <span>select</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <kbd className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px]">ESC</kbd>
              <span>close</span>
            </span>
          </div>
          <span className="font-medium text-brand-ink">AlphaHelion Intelligent Twin</span>
        </div>
      </div>
    </div>
  );
}
