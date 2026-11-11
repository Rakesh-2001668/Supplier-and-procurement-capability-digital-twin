// The single menu of the platform: Purchasing Intelligence Cloud (PIC) and the Supplier Capability Digital Twin ("twin").
// The one shell (components/pic/WorkspaceShell.tsx) renders it on every page; which groups a person sees depends on whether
// they are a supplier user, on their roles (role filters below) and on whether the twin screens are switched on (twin groups).
import {
  Activity, ArrowLeftRight, Award, BarChart3, Bell, Bot, Box, Building2, CalendarClock, ClipboardList, Clock, Code, CreditCard, Database, DollarSign,
  Factory, FileText, Gauge, Globe, Inbox, Landmark, Layers, LayoutDashboard, Leaf, LineChart, Navigation, Receipt, Scale, Search, Settings, Shield,
  ShieldAlert, ShieldCheck, ShoppingCart, Sliders, Sparkles, Target, TrendingUp, Truck, UserCog, Workflow, type LucideIcon,
} from 'lucide-react';

export type PicNavItem = { href: string; label: string; icon: LucideIcon; roles?: string[] };
/** `twin`: a group of Supplier Capability Digital Twin screens, shown only where they are switched on (not in production). */
export type PicNavGroup = { group: string; items: PicNavItem[]; twin?: boolean };

export const PIC_INTERNAL_NAV: PicNavGroup[] = [
  { group: 'Decide', items: [
    { href: '/pic', label: 'Command centre', icon: Activity },
    { href: '/pic/copilot', label: 'Copilot', icon: Bot },
    { href: '/pic/spend', label: 'Spend', icon: BarChart3, roles: ['CATEGORY_MANAGER', 'FINANCE_CONTROLLER', 'CFO', 'PROCUREMENT_HEAD', 'CPO'] },
    { href: '/pic/savings', label: 'Savings', icon: DollarSign },
    { href: '/pic/kpis', label: 'KPI explorer', icon: Gauge },
  ] },
  { group: 'My work', items: [
    { href: '/pic/tasks', label: 'Task inbox', icon: Inbox },
    { href: '/pic/notifications', label: 'Notifications', icon: Bell },
    { href: '/pic/account', label: 'My account & security', icon: UserCog },
  ] },
  { group: 'Plan & request', items: [
    { href: '/pic/mrp', label: 'MRP & planning', icon: Layers },
    { href: '/pic/mrp/forecast', label: 'Demand forecast', icon: TrendingUp, roles: ['MRP_CONTROLLER', 'TENANT_ADMIN'] },
    { href: '/pic/requisitions', label: 'Requisitions', icon: ClipboardList },
    { href: '/pic/buyer', label: 'Buyer workbench', icon: LayoutDashboard, roles: ['BUYER'] },
    { href: '/pic/materials', label: 'Materials & MDM', icon: Database },
  ] },
  { group: 'Source & contract', items: [
    { href: '/pic/sourcing', label: 'Sourcing events', icon: Target },
    { href: '/pic/contracts', label: 'Contracts', icon: Scale },
    { href: '/pic/contracts/obligations', label: 'Obligations & renewals', icon: CalendarClock },
    { href: '/pic/suppliers', label: 'Suppliers', icon: Building2 },
    { href: '/pic/suppliers/performance', label: 'Supplier performance', icon: Award },
    { href: '/pic/suppliers/risk', label: 'Supplier risk', icon: ShieldAlert },
  ] },
  { group: 'Order to pay', items: [
    { href: '/pic/purchase-orders', label: 'Purchase orders', icon: ShoppingCart },
    { href: '/pic/purchase-orders/changes', label: 'Confirmations & changes', icon: ArrowLeftRight },
    { href: '/pic/purchase-orders/expediting', label: 'Expediting', icon: Clock },
    { href: '/pic/receiving', label: 'Receiving & quality', icon: Truck },
    { href: '/pic/inventory', label: 'Inventory', icon: Box },
    { href: '/pic/invoices', label: 'Invoices & payments', icon: FileText },
    { href: '/pic/invoices/reconciliation', label: 'Posting & reconciliation', icon: Receipt, roles: ['AP_CLERK', 'FINANCE_CONTROLLER'] },
    { href: '/pic/invoices/insights', label: 'Payables insights', icon: LineChart, roles: ['AP_CLERK', 'FINANCE_CONTROLLER', 'CFO', 'CPO', 'PROCUREMENT_HEAD'] },
    { href: '/pic/invoices/tax', label: 'TDS, Form 16A & MSME', icon: Landmark, roles: ['AP_CLERK', 'FINANCE_CONTROLLER'] },
    { href: '/pic/industry', label: 'Industry controls', icon: Factory },
  ] },
  { group: 'Govern', items: [
    { href: '/pic/processes', label: 'Process monitor', icon: Workflow },
    { href: '/pic/agents', label: 'AI agents', icon: Bot },
    { href: '/pic/admin', label: 'Administration', icon: Settings, roles: ['TENANT_ADMIN'] },
  ] },
];

export const PIC_SUPPLIER_NAV: PicNavGroup[] = [
  { group: 'Supplier portal', items: [
    { href: '/pic/portal', label: 'Overview', icon: LayoutDashboard },
    { href: '/pic/copilot', label: 'Ask about my documents', icon: Bot },
    { href: '/pic/notifications', label: 'Notifications', icon: Bell },
    { href: '/pic/account', label: 'My account & security', icon: UserCog },
  ] },
];

// Supplier Capability Digital Twin screens (outside /pic). They run on the twin's demonstration data.
export const TWIN_BUYER_NAV: PicNavGroup[] = [
  { group: 'Supplier capability twin', twin: true, items: [
    { href: '/command-centre', label: 'Twin command centre', icon: Activity },
    { href: '/buyer/dashboard', label: 'Buyer dashboard', icon: LayoutDashboard },
    { href: '/approvals', label: 'Unified approvals & SoD', icon: ShieldCheck },
    { href: '/bpmn-flows', label: 'BPMN swimlane flows', icon: Workflow },
    { href: '/workbenches', label: 'Specialist workbenches', icon: Sliders },
    { href: '/industry-templates', label: 'Industry templates', icon: Building2 },
    { href: '/spend/cube', label: 'Spend cube', icon: BarChart3 },
    { href: '/sourcing', label: 'Strategic sourcing', icon: Target },
    { href: '/contracts/agreements', label: 'Buy-side agreements', icon: Scale },
    { href: '/savings', label: 'Savings realisation', icon: DollarSign },
    { href: '/p2p', label: 'P2P cockpit', icon: ShoppingCart },
    { href: '/mrp/planner-workbench', label: 'MRP workbench', icon: Layers },
    { href: '/mdm/requests', label: 'MDM governance', icon: ShieldCheck },
    { href: '/mdm/studio', label: 'MDM duplicate shield', icon: ShieldCheck },
    { href: '/command-centre/ai-agents', label: 'AI agents fleet', icon: Bot },
    { href: '/copilot', label: 'AI copilot', icon: Bot },
    { href: '/network', label: 'Supplier network', icon: Globe },
    { href: '/buyer/discovery', label: 'Discovery', icon: Search },
    { href: '/dfsc', label: 'Generative DFSC', icon: Sparkles },
    { href: '/simulation', label: 'Monte Carlo simulation', icon: LineChart },
    { href: '/evidence', label: 'Evidence vault', icon: ShieldCheck },
    { href: '/development', label: 'Development & CAPA', icon: TrendingUp },
    { href: '/contracts', label: 'Smart contracts', icon: Code },
    { href: '/risk', label: 'Risk command', icon: ShieldAlert },
    { href: '/rfqs', label: 'RFQs & orders', icon: FileText },
    { href: '/invoices', label: 'Invoices', icon: FileText },
    { href: '/invoices/3-way-match', label: '3-way match & disputes', icon: Receipt },
    { href: '/finance/payments', label: 'Payments', icon: CreditCard },
    { href: '/inventory', label: 'Inventory', icon: Box },
    { href: '/admin', label: 'Admin & RBAC', icon: Shield },
    { href: '/admin/governance', label: 'Governance & SoD', icon: ShieldAlert },
    { href: '/notifications', label: 'Twin notifications', icon: Bell },
  ] },
];

export const TWIN_SUPPLIER_NAV: PicNavGroup[] = [
  { group: 'Supplier capability twin', twin: true, items: [
    { href: '/supplier/dashboard', label: 'Supplier dashboard', icon: LayoutDashboard },
    { href: '/supplier/profile', label: 'My digital twin', icon: Factory },
    { href: '/supplier/telemetry', label: 'Machine telemetry', icon: Activity },
    { href: '/supplier/transit', label: 'Transit monitor', icon: Navigation },
    { href: '/supplier/esg-reporting', label: 'ESG compliance', icon: Leaf },
    { href: '/supplier/rfqs', label: 'Incoming RFQs', icon: FileText },
    { href: '/supplier/orders', label: 'Active orders', icon: Truck },
    { href: '/supplier/invoices', label: 'Invoices sent', icon: FileText },
    { href: '/supplier/payments', label: 'Payments received', icon: CreditCard },
    { href: '/supplier/smart-contracts', label: 'Smart contracts', icon: Code },
    { href: '/supplier/inventory', label: 'Inventory', icon: Box },
    { href: '/p2p', label: 'P2P orders & invoices', icon: ShoppingCart },
    { href: '/development', label: 'Development & CAPA', icon: TrendingUp },
    { href: '/copilot', label: 'AI copilot', icon: Bot },
    { href: '/notifications', label: 'Twin notifications', icon: Bell },
  ] },
];

/** The menu of one person: PIC groups, then the twin group, filtered by role; twin groups only where the twin screens are on. */
export function navigationFor(roles: readonly string[], twinEnabled: boolean): PicNavGroup[] {
  const supplier = roles.includes('SUPPLIER_USER');
  const groups = supplier ? [...PIC_SUPPLIER_NAV, ...TWIN_SUPPLIER_NAV] : [...PIC_INTERNAL_NAV, ...TWIN_BUYER_NAV];
  return groups
    .filter((g) => twinEnabled || !g.twin)
    .map((g) => ({ ...g, items: g.items.filter((i) => !i.roles || i.roles.some((r) => roles.includes(r))) }))
    .filter((g) => g.items.length);
}

/** True for a page of the Supplier Capability Digital Twin (everything outside /pic and the API). */
export function isTwinPage(pathname: string): boolean {
  return !(pathname === '/pic' || pathname.startsWith('/pic/'));
}
