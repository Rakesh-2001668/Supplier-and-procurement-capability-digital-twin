'use client';

import { useState } from 'react';
import { Button, Dialog, Field, Input, Select, Textarea } from '@/components/pic/ui';
import { inr, rupeesToMinor } from '@/lib/pic/format';

export type CategoryTemplateCode = 'SVC-PROFESSIONAL' | 'IT-HARDWARE-SOFTWARE' | 'MKT-CAMPAIGN-EVENT' | 'FAC-MAINTENANCE';

export type CategorySowLineData = {
  item_type: 'SERVICE' | 'FREE_TEXT';
  purchase_type: string;
  source: string;
  template: string;
  description: string;
  material_group: string;
  category: string;
  qty: string;
  uom: string;
  price: string;
  priceFixed: boolean;
  aat: string;
  aac: string;
  need_date: string;
  attributes: Record<string, unknown>;
};

function inDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

// ---------------------------------------------------------------- Professional Services SOW State
type Milestone = { id: string; title: string; deliverable: string; dueDate: string; pct: number; amountRupees: number };

export function CategorySowModal({
  code,
  onClose,
  onApply,
}: {
  code: CategoryTemplateCode;
  onClose: () => void;
  onApply: (line: CategorySowLineData) => void;
}) {
  if (code === 'SVC-PROFESSIONAL') {
    return <ProfessionalServicesModal onClose={onClose} onApply={onApply} />;
  }
  if (code === 'MKT-CAMPAIGN-EVENT') {
    return <MarketingSowModal onClose={onClose} onApply={onApply} />;
  }
  if (code === 'IT-HARDWARE-SOFTWARE') {
    return <ItCategoryModal onClose={onClose} onApply={onApply} />;
  }
  if (code === 'FAC-MAINTENANCE') {
    return <FacilitiesSowModal onClose={onClose} onApply={onApply} />;
  }
  return null;
}

// ---------------------------------------------------------------- 1. Professional Services SOW Modal
function ProfessionalServicesModal({
  onClose,
  onApply,
}: {
  onClose: () => void;
  onApply: (line: CategorySowLineData) => void;
}) {
  const [title, setTitle] = useState('');
  const [subcategory, setSubcategory] = useState('IT Architecture & Engineering');
  const [startDate, setStartDate] = useState(inDays(7));
  const [endDate, setEndDate] = useState(inDays(120));
  const [deliveryModel, setDeliveryModel] = useState('MILESTONE');
  const [milestones, setMilestones] = useState<Milestone[]>([
    { id: 'm1', title: 'Phase 1: Architecture Blueprint & Technical Design', deliverable: 'Architecture document & sign-off', dueDate: inDays(30), pct: 30, amountRupees: 600000 },
    { id: 'm2', title: 'Phase 2: Integration Pipeline & Test Verification', deliverable: 'Deployed test environment & verification report', dueDate: inDays(75), pct: 40, amountRupees: 800000 },
    { id: 'm3', title: 'Phase 3: Production Cutover, UAT & Hypercare', deliverable: 'UAT sign-off and 30-day hypercare support', dueDate: inDays(120), pct: 30, amountRupees: 600000 },
  ]);
  const [staffing, setStaffing] = useState('1 Lead Solution Architect (12+ yrs), 2 Senior Integration Engineers (7+ yrs)');
  const [slaCriteria, setSlaCriteria] = useState('Deliverables accepted within 10 business days of review; defect resolution SLA < 48 hours for Critical items.');
  const [costCenter, setCostCenter] = useState('CC-TECH-1002');

  const totalAmount = milestones.reduce((sum, m) => sum + (Number(m.amountRupees) || 0), 0);

  function fillMockData() {
    setTitle('SAP S/4HANA Process Twin Integration & Data Pipeline Architecture');
    setSubcategory('Enterprise Software & Consulting');
    setStartDate(inDays(10));
    setEndDate(inDays(140));
    setDeliveryModel('MILESTONE');
    setMilestones([
      { id: 'm1', title: 'Phase 1: Architecture Blueprint & Gap Specification', deliverable: 'Technical blueprint & data schema specification sign-off', dueDate: inDays(35), pct: 30, amountRupees: 750000 },
      { id: 'm2', title: 'Phase 2: Bidirectional OData / IDoc Integration Engine', deliverable: 'Verified integration test bench with automated unit coverage', dueDate: inDays(85), pct: 40, amountRupees: 1000000 },
      { id: 'm3', title: 'Phase 3: Pilot Cutover, UAT Sign-off & 30-Day Hypercare', deliverable: 'Production cutover sign-off, runbook & training manuals', dueDate: inDays(140), pct: 30, amountRupees: 750000 },
    ]);
    setStaffing('1 Principal Enterprise Architect, 1 Senior Integration Consultant, 1 Data Pipeline QA Lead');
    setSlaCriteria('Deliverable review turnaround: 10 working days; zero Sev-1 defects prior to production cutover; 30-day post-go-live warranty.');
    setCostCenter('CC-TECH-1002');
  }

  function updateMilestone(id: string, patch: Partial<Milestone>) {
    setMilestones((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }

  function addMilestone() {
    const nextIdx = milestones.length + 1;
    setMilestones((prev) => [
      ...prev,
      {
        id: `m${Date.now()}`,
        title: `Phase ${nextIdx}: Deliverable & Sign-off`,
        deliverable: 'Milestone completion report',
        dueDate: inDays(nextIdx * 30),
        pct: 0,
        amountRupees: 250000,
      },
    ]);
  }

  function removeMilestone(id: string) {
    if (milestones.length <= 1) return;
    setMilestones((prev) => prev.filter((m) => m.id !== id));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title) return;

    const formattedDescription = [
      `STATEMENT OF WORK (SOW): ${title.trim()}`,
      `Subcategory: ${subcategory}`,
      `Period of Performance: ${startDate} to ${endDate}`,
      `Delivery Model: ${deliveryModel === 'MILESTONE' ? 'Milestone-Based Fixed Price' : 'Time & Materials'}`,
      `Key Staffing: ${staffing}`,
      `Milestone Schedule:`,
      ...milestones.map((m, i) => `  ${i + 1}. ${m.title} — ${m.deliverable} (Due: ${m.dueDate}) — ₹${m.amountRupees.toLocaleString('en-IN')}`),
      `Acceptance & SLA: ${slaCriteria}`,
    ].join('\n');

    onApply({
      item_type: 'SERVICE',
      purchase_type: 'SERVICE',
      source: 'Category SOW · Professional Services',
      template: 'SVC-PROFESSIONAL',
      description: formattedDescription,
      material_group: 'PROF-SERVICES',
      category: 'PROFESSIONAL-SERVICES',
      qty: '1',
      uom: 'AU',
      price: String(totalAmount),
      priceFixed: false,
      aat: 'COST_CENTER',
      aac: costCenter,
      need_date: endDate,
      attributes: {
        sowType: 'PROFESSIONAL_SERVICES',
        title,
        subcategory,
        startDate,
        endDate,
        deliveryModel,
        milestones,
        staffing,
        slaCriteria,
        totalAmountMinor: rupeesToMinor(totalAmount),
      },
    });
    onClose();
  }

  return (
    <Dialog open wide title="Professional Services Statement of Work (SOW) Generator" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-blue-50/70 p-3 text-xs text-blue-900 border border-blue-200">
          <p>
            <strong>M04 Category Form:</strong> Generates a structured Professional Services Statement of Work (SOW) with milestone schedule, deliverable acceptance criteria, and cost-center pre-assignment.
          </p>
          <Button type="button" variant="secondary" onClick={fillMockData} className="!py-1 !text-xs font-semibold">
            ⚡ Fill Sample SOW Mock
          </Button>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Engagement / Project Title" required>
            {(id) => (
              <Input
                id={id}
                required
                placeholder="e.g. S/4HANA Architecture & Quality Assurance Review"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            )}
          </Field>

          <Field label="Service Subcategory" required>
            {(id) => (
              <Select
                id={id}
                value={subcategory}
                onChange={(e) => setSubcategory(e.target.value)}
                options={[
                  { value: 'IT Architecture & Engineering', label: 'IT Architecture & Engineering' },
                  { value: 'Management Consulting & Strategy', label: 'Management Consulting & Strategy' },
                  { value: 'Legal & Regulatory Compliance', label: 'Legal & Regulatory Compliance' },
                  { value: 'Financial & Internal Audit', label: 'Financial & Internal Audit' },
                  { value: 'Cybersecurity & Penetration Testing', label: 'Cybersecurity & Penetration Testing' },
                ]}
              />
            )}
          </Field>

          <Field label="Start Date" required>
            {(id) => <Input id={id} type="date" required value={startDate} onChange={(e) => setStartDate(e.target.value)} />}
          </Field>

          <Field label="Target Completion Date" required>
            {(id) => <Input id={id} type="date" required value={endDate} onChange={(e) => setEndDate(e.target.value)} />}
          </Field>
        </div>

        {/* Milestones Schedule */}
        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3.5 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
              Milestone & Payment Deliverables Schedule ({milestones.length})
            </h4>
            <Button type="button" onClick={addMilestone} className="!py-1 !text-xs">
              + Add Milestone
            </Button>
          </div>

          <div className="space-y-2">
            {milestones.map((m, idx) => (
              <div key={m.id} className="grid grid-cols-12 gap-2 rounded border border-slate-200 bg-white p-2.5 text-xs">
                <div className="col-span-12 md:col-span-4">
                  <label className="text-[10px] font-semibold text-slate-500">Phase {idx + 1} Title</label>
                  <Input
                    value={m.title}
                    placeholder="Milestone title"
                    onChange={(e) => updateMilestone(m.id, { title: e.target.value })}
                  />
                </div>
                <div className="col-span-12 md:col-span-4">
                  <label className="text-[10px] font-semibold text-slate-500">Deliverable / Output</label>
                  <Input
                    value={m.deliverable}
                    placeholder="Key deliverable"
                    onChange={(e) => updateMilestone(m.id, { deliverable: e.target.value })}
                  />
                </div>
                <div className="col-span-6 md:col-span-2">
                  <label className="text-[10px] font-semibold text-slate-500">Due Date</label>
                  <Input
                    type="date"
                    value={m.dueDate}
                    onChange={(e) => updateMilestone(m.id, { dueDate: e.target.value })}
                  />
                </div>
                <div className="col-span-5 md:col-span-2">
                  <label className="text-[10px] font-semibold text-slate-500">Amount (₹)</label>
                  <Input
                    type="number"
                    min="0"
                    value={m.amountRupees}
                    onChange={(e) => updateMilestone(m.id, { amountRupees: Number(e.target.value) || 0 })}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between border-t border-slate-200 pt-2 text-xs">
            <span className="font-semibold text-slate-600">Calculated Total SOW Value:</span>
            <span className="font-bold tabular-nums text-sm text-[#1A56DB]">{inr(rupeesToMinor(totalAmount))}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Key Personnel / Resource Roles">
            {(id) => (
              <Input
                id={id}
                placeholder="e.g. 1 Solution Architect, 2 Senior Engineers"
                value={staffing}
                onChange={(e) => setStaffing(e.target.value)}
              />
            )}
          </Field>

          <Field label="Account Assignment (Cost Center)" required>
            {(id) => (
              <Input
                id={id}
                required
                placeholder="e.g. CC-TECH-1002"
                value={costCenter}
                onChange={(e) => setCostCenter(e.target.value)}
              />
            )}
          </Field>
        </div>

        <Field label="Deliverable Acceptance & SLA Terms">
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              value={slaCriteria}
              onChange={(e) => setSlaCriteria(e.target.value)}
              placeholder="e.g. Review within 10 business days; 30-day warranty on code deliverables."
            />
          )}
        </Field>

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" disabled={!title || totalAmount <= 0}>
            Apply SOW to Requisition ({inr(rupeesToMinor(totalAmount))})
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- 2. Marketing SOW Modal
function MarketingSowModal({
  onClose,
  onApply,
}: {
  onClose: () => void;
  onApply: (line: CategorySowLineData) => void;
}) {
  const [title, setTitle] = useState('');
  const [channel, setChannel] = useState('Digital Performance & SEM');
  const [targetAudience, setTargetAudience] = useState('Automotive B2B Fleet Owners & Procurement Heads');
  const [campaignDates, setCampaignDates] = useState(`${inDays(14)} to ${inDays(104)}`);
  const [agencyFee, setAgencyFee] = useState(450000);
  const [mediaSpend, setMediaSpend] = useState(1200000);
  const [deliverables, setDeliverables] = useState('6 Video Variants, 24 Responsive Display Banners, 2 High-Conversion Landing Pages, Weekly Analytics Dashboards');
  const [targetKpis, setTargetKpis] = useState('Target 8.5M impressions, 12,000 qualified lead inquiries, blended CPL < ₹140');
  const [costCenter, setCostCenter] = useState('CC-MKTG-2001');

  const totalAmount = (Number(agencyFee) || 0) + (Number(mediaSpend) || 0);

  function fillMockData() {
    setTitle('FY27 Commercial EV Launch — Pan-India Digital Performance & Trade Campaign');
    setChannel('Integrated Digital, Print & B2B Exhibition');
    setTargetAudience('Fleet operators, supply chain directors, industrial logistics managers in Tier 1 & Tier 2 auto corridors');
    setCampaignDates(`${inDays(15)} to ${inDays(120)}`);
    setAgencyFee(650000);
    setMediaSpend(1850000);
    setDeliverables('1 Master Brand Film (60s), 4 Social Cutdowns, 16 Display Variants, Auto Expo 2027 Booth Experience Graphics, Lead Nurturing Email Engine');
    setTargetKpis('15M verified B2B impressions; 22,000 lead form submissions; Target ROAS 4.2x; 500 test drive bookings');
    setCostCenter('CC-MKTG-2001');
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title || totalAmount <= 0) return;

    const formattedDescription = [
      `MARKETING SOW: ${title.trim()}`,
      `Primary Channels: ${channel}`,
      `Target Audience: ${targetAudience}`,
      `Campaign Flight: ${campaignDates}`,
      `Agency Creative & Management: ₹${agencyFee.toLocaleString('en-IN')}`,
      `Media Spend Allocation: ₹${mediaSpend.toLocaleString('en-IN')}`,
      `Total Campaign Budget: ₹${totalAmount.toLocaleString('en-IN')}`,
      `Deliverables: ${deliverables}`,
      `Performance KPIs: ${targetKpis}`,
    ].join('\n');

    onApply({
      item_type: 'SERVICE',
      purchase_type: 'SERVICE',
      source: 'Category SOW · Marketing & Media',
      template: 'MKT-CAMPAIGN-EVENT',
      description: formattedDescription,
      material_group: 'MARKETING',
      category: 'MARKETING-SERVICES',
      qty: '1',
      uom: 'AU',
      price: String(totalAmount),
      priceFixed: false,
      aat: 'COST_CENTER',
      aac: costCenter,
      need_date: inDays(120),
      attributes: {
        sowType: 'MARKETING_CAMPAIGN',
        title,
        channel,
        targetAudience,
        campaignDates,
        agencyFeeMinor: rupeesToMinor(agencyFee),
        mediaSpendMinor: rupeesToMinor(mediaSpend),
        deliverables,
        targetKpis,
        totalAmountMinor: rupeesToMinor(totalAmount),
      },
    });
    onClose();
  }

  return (
    <Dialog open wide title="Marketing Campaign & Agency SOW Generator" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-purple-50/70 p-3 text-xs text-purple-900 border border-purple-200">
          <p>
            <strong>M04 Category Form:</strong> Formulates Marketing Statement of Work with channel mix, agency creative retainer, media buy budget, and target KPIs.
          </p>
          <Button type="button" variant="secondary" onClick={fillMockData} className="!py-1 !text-xs font-semibold">
            ⚡ Fill Sample Marketing Mock
          </Button>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Campaign / Event Name" required>
            {(id) => (
              <Input
                id={id}
                required
                placeholder="e.g. Q4 EV Commercial Launch Campaign"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            )}
          </Field>

          <Field label="Primary Media Channels" required>
            {(id) => (
              <Select
                id={id}
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                options={[
                  { value: 'Digital Performance & SEM', label: 'Digital Performance & SEM' },
                  { value: 'Integrated Digital, Print & B2B Exhibition', label: 'Integrated Digital, Print & B2B Exhibition' },
                  { value: 'Brand Film Production & TV/OTT', label: 'Brand Film Production & TV/OTT' },
                  { value: 'B2B Trade Conference & Roadshow Event', label: 'B2B Trade Conference & Roadshow Event' },
                  { value: 'Influencer, PR & Industry Media', label: 'Influencer, PR & Industry Media' },
                ]}
              />
            )}
          </Field>

          <Field label="Campaign Flight Window">
            {(id) => (
              <Input
                id={id}
                placeholder="e.g. Nov 15, 2026 to Mar 15, 2027"
                value={campaignDates}
                onChange={(e) => setCampaignDates(e.target.value)}
              />
            )}
          </Field>

          <Field label="Target Audience / Persona">
            {(id) => (
              <Input
                id={id}
                placeholder="e.g. Fleet owners, tier-1 auto component executives"
                value={targetAudience}
                onChange={(e) => setTargetAudience(e.target.value)}
              />
            )}
          </Field>

          <Field label="Agency Fee / Creative Production (₹)" required>
            {(id) => (
              <Input
                id={id}
                type="number"
                min="0"
                required
                value={agencyFee}
                onChange={(e) => setAgencyFee(Number(e.target.value) || 0)}
              />
            )}
          </Field>

          <Field label="Media Buy / Channel Placement Spend (₹)" required>
            {(id) => (
              <Input
                id={id}
                type="number"
                min="0"
                required
                value={mediaSpend}
                onChange={(e) => setMediaSpend(Number(e.target.value) || 0)}
              />
            )}
          </Field>
        </div>

        <div className="rounded-lg bg-slate-50 p-3 border border-slate-200 flex items-center justify-between text-xs">
          <span className="font-semibold text-slate-700">Combined Marketing Spend Budget:</span>
          <span className="font-bold text-sm text-[#1A56DB] tabular-nums">{inr(rupeesToMinor(totalAmount))}</span>
        </div>

        <Field label="Creative Assets & Deliverables Schedule" required>
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              required
              value={deliverables}
              onChange={(e) => setDeliverables(e.target.value)}
              placeholder="e.g. Master video, responsive banners, landing pages, weekly analytics."
            />
          )}
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Target KPIs & Success Metrics">
            {(id) => (
              <Input
                id={id}
                placeholder="e.g. 10M impressions, 15k B2B leads, ROAS > 3.5"
                value={targetKpis}
                onChange={(e) => setTargetKpis(e.target.value)}
              />
            )}
          </Field>

          <Field label="Marketing Cost Center" required>
            {(id) => (
              <Input
                id={id}
                required
                placeholder="e.g. CC-MKTG-2001"
                value={costCenter}
                onChange={(e) => setCostCenter(e.target.value)}
              />
            )}
          </Field>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" disabled={!title || totalAmount <= 0}>
            Apply Marketing SOW ({inr(rupeesToMinor(totalAmount))})
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- 3. IT Hardware, Software & SaaS Modal
function ItCategoryModal({
  onClose,
  onApply,
}: {
  onClose: () => void;
  onApply: (line: CategorySowLineData) => void;
}) {
  const [productName, setProductName] = useState('');
  const [classification, setClassification] = useState('SaaS Cloud Subscription');
  const [oemVendor, setOemVendor] = useState('CrowdStrike / Redington');
  const [seatCount, setSeatCount] = useState(250);
  const [unitPricePerSeat, setUnitPricePerSeat] = useState(4800);
  const [termMonths, setTermMonths] = useState(12);
  const [securityTier, setSecurityTier] = useState('SOC-2 Type II + ISO 27001 Certified');
  const [dataResidency, setDataResidency] = useState('India (AWS ap-south-1 / Mumbai)');
  const [specs, setSpecs] = useState('Next-gen endpoint detection and response (EDR), threat intelligence feed, 24/7 cloud threat graph analysis');
  const [costCenter, setCostCenter] = useState('CC-IT-3001');

  const totalAmount = (Number(seatCount) || 1) * (Number(unitPricePerSeat) || 0);
  const isCapitalAsset = classification.includes('Server') || classification.includes('Laptop') || (totalAmount >= 50000 && !classification.includes('SaaS'));

  function fillMockData() {
    setProductName('CrowdStrike Falcon Enterprise EDR & Identity Threat Defense');
    setClassification('SaaS Cloud Subscription');
    setOemVendor('CrowdStrike Inc.');
    setSeatCount(350);
    setUnitPricePerSeat(5200);
    setTermMonths(12);
    setSecurityTier('SOC-2 Type II, ISO 27001, CSA STAR Level 2');
    setDataResidency('India Cloud (AWS Mumbai / ap-south-1)');
    setSpecs('Enterprise sensor licenses with managed threat hunting, automated incident containment, and SIEM ingestion APIs.');
    setCostCenter('CC-IT-3001');
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!productName || totalAmount <= 0) return;

    const formattedDescription = [
      `IT REQUISITION: ${productName.trim()}`,
      `Classification: ${classification}`,
      `OEM / Vendor: ${oemVendor}`,
      `Seat Count: ${seatCount} licenses (${termMonths} Months Term)`,
      `Unit Rate: ₹${unitPricePerSeat.toLocaleString('en-IN')} / seat`,
      `Security Clearance: ${securityTier}`,
      `Data Residency: ${dataResidency}`,
      `Specifications: ${specs}`,
      isCapitalAsset ? '[POLICY] Capital Asset threshold satisfied (P22 Asset Route applies)' : '[POLICY] Operating Expense (OPEX)',
    ].join('\n');

    onApply({
      item_type: 'FREE_TEXT',
      purchase_type: isCapitalAsset ? 'ASSET' : 'NON_STOCK',
      source: 'Category Form · IT Hardware & Software',
      template: 'IT-HARDWARE-SOFTWARE',
      description: formattedDescription,
      material_group: 'IT-EQUIP',
      category: 'IT-EQUIPMENT',
      qty: String(seatCount),
      uom: classification.includes('SaaS') ? 'AU' : 'EA',
      price: String(unitPricePerSeat),
      priceFixed: false,
      aat: isCapitalAsset ? 'ASSET' : 'COST_CENTER',
      aac: costCenter,
      need_date: inDays(30),
      attributes: {
        itemType: 'IT_HARDWARE_SOFTWARE',
        productName,
        classification,
        oemVendor,
        seatCount,
        unitPricePerSeat,
        termMonths,
        securityTier,
        dataResidency,
        specs,
        isCapitalAsset,
        totalAmountMinor: rupeesToMinor(totalAmount),
      },
    });
    onClose();
  }

  return (
    <Dialog open wide title="IT Hardware, Software & Cloud Requisition Generator" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-cyan-50/70 p-3 text-xs text-cyan-950 border border-cyan-200">
          <p>
            <strong>M04 Category Form:</strong> Configures IT hardware and software licensing with automatic Asset Capitalisation check ($&gt; ₹50,000 threshold per P22 policy).
          </p>
          <Button type="button" variant="secondary" onClick={fillMockData} className="!py-1 !text-xs font-semibold">
            ⚡ Fill Sample IT Mock
          </Button>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Product / Software Name" required>
            {(id) => (
              <Input
                id={id}
                required
                placeholder="e.g. CrowdStrike Falcon EDR"
                value={productName}
                onChange={(e) => setProductName(e.target.value)}
              />
            )}
          </Field>

          <Field label="Item Classification" required>
            {(id) => (
              <Select
                id={id}
                value={classification}
                onChange={(e) => setClassification(e.target.value)}
                options={[
                  { value: 'SaaS Cloud Subscription', label: 'SaaS Cloud Subscription' },
                  { value: 'Enterprise On-Premises Perpetual License', label: 'Enterprise On-Premises Perpetual License' },
                  { value: 'Developer / Engineering Workstation Laptop', label: 'Developer / Engineering Workstation Laptop' },
                  { value: 'Data Center Rack Server / Switch', label: 'Data Center Rack Server / Switch' },
                  { value: 'Cloud Infrastructure Credits (AWS / GCP / Azure)', label: 'Cloud Infrastructure Credits (AWS / GCP / Azure)' },
                ]}
              />
            )}
          </Field>

          <Field label="OEM / Vendor Name">
            {(id) => (
              <Input
                id={id}
                placeholder="e.g. CrowdStrike / Microsoft / Dell"
                value={oemVendor}
                onChange={(e) => setOemVendor(e.target.value)}
              />
            )}
          </Field>

          <Field label="License Term Duration">
            {(id) => (
              <Select
                id={id}
                value={termMonths}
                onChange={(e) => setTermMonths(Number(e.target.value))}
                options={[
                  { value: 12, label: '12 Months (Annual)' },
                  { value: 24, label: '24 Months (2 Years)' },
                  { value: 36, label: '36 Months (3 Years)' },
                ]}
              />
            )}
          </Field>

          <Field label="Seats / Quantity Count" required>
            {(id) => (
              <Input
                id={id}
                type="number"
                min="1"
                required
                value={seatCount}
                onChange={(e) => setSeatCount(Number(e.target.value) || 1)}
              />
            )}
          </Field>

          <Field label="Unit Price per Seat / Item (₹)" required>
            {(id) => (
              <Input
                id={id}
                type="number"
                min="0"
                required
                value={unitPricePerSeat}
                onChange={(e) => setUnitPricePerSeat(Number(e.target.value) || 0)}
              />
            )}
          </Field>
        </div>

        <div className={`rounded-lg p-3 border text-xs flex items-center justify-between ${isCapitalAsset ? 'bg-amber-50 border-amber-200 text-amber-900' : 'bg-slate-50 border-slate-200'}`}>
          <div>
            <span className="font-semibold">Total Estimated Value: </span>
            <span className="font-bold text-sm text-[#1A56DB] tabular-nums">{inr(rupeesToMinor(totalAmount))}</span>
          </div>
          {isCapitalAsset && (
            <span className="rounded bg-amber-200 px-2 py-0.5 font-bold uppercase tracking-wide text-amber-900 text-[10px]">
              Asset Capitalisation Route (P22)
            </span>
          )}
        </div>

        <Field label="Technical Specifications & Scope">
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              value={specs}
              onChange={(e) => setSpecs(e.target.value)}
              placeholder="e.g. Cloud sensor licenses, SIEM ingestion, 24/7 support SLA."
            />
          )}
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Security Clearance">
            {(id) => (
              <Input
                id={id}
                value={securityTier}
                onChange={(e) => setSecurityTier(e.target.value)}
              />
            )}
          </Field>

          <Field label="Data Residency">
            {(id) => (
              <Input
                id={id}
                value={dataResidency}
                onChange={(e) => setDataResidency(e.target.value)}
              />
            )}
          </Field>

          <Field label="Cost Center" required>
            {(id) => (
              <Input
                id={id}
                required
                value={costCenter}
                onChange={(e) => setCostCenter(e.target.value)}
              />
            )}
          </Field>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" disabled={!productName || totalAmount <= 0}>
            Apply IT Line Item ({inr(rupeesToMinor(totalAmount))})
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- 4. Facilities & Maintenance SOW Modal
function FacilitiesSowModal({
  onClose,
  onApply,
}: {
  onClose: () => void;
  onApply: (line: CategorySowLineData) => void;
}) {
  const [siteLocation, setSiteLocation] = useState('Plant 1000 — Pune Heavy Stamping');
  const [serviceType, setServiceType] = useState('Annual Maintenance Contract (AMC)');
  const [equipmentTag, setEquipmentTag] = useState('HYD-PRESS-400T / Press Line 3');
  const [serviceWindow, setServiceWindow] = useState('Bi-weekly scheduled shutdown service + 24/7 on-call breakdown response');
  const [period, setPeriod] = useState(`${inDays(7)} to ${inDays(365)}`);
  const [totalCost, setTotalCost] = useState(850000);
  const [safetyCompliance, setSafetyCompliance] = useState('Permit-to-work (PTW) mandatory, contractor third-party liability insurance ₹50L confirmed.');
  const [costCenter, setCostCenter] = useState('CC-PLANT-1000');

  function fillMockData() {
    setSiteLocation('Plant 1000 — Pune Heavy Stamping Works');
    setServiceType('Hydraulic Press Overhaul & Preventive AMC');
    setEquipmentTag('KOMATSU-400T-PRESS / Bay 2');
    setServiceWindow('Fortnightly preventive maintenance, vibration analysis, hydraulic seal replacements & emergency breakdown support < 4hr SLA');
    setPeriod(`${inDays(10)} to ${inDays(375)}`);
    setTotalCost(1150000);
    setSafetyCompliance('EHS Level 3 Contractor Clearance, Confined Space Work Permit, PPE Class 2 Compliant.');
    setCostCenter('CC-PLANT-1000');
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!equipmentTag || totalCost <= 0) return;

    const formattedDescription = [
      `FACILITIES / MAINTENANCE SOW: ${serviceType}`,
      `Site / Plant: ${siteLocation}`,
      `Equipment / Machine Tag: ${equipmentTag}`,
      `Period of Service: ${period}`,
      `Service Window: ${serviceWindow}`,
      `Safety & Statutory Compliance: ${safetyCompliance}`,
      `Total Annual AMC Value: ₹${totalCost.toLocaleString('en-IN')}`,
    ].join('\n');

    onApply({
      item_type: 'SERVICE',
      purchase_type: 'SERVICE',
      source: 'Category SOW · Facilities & Maintenance',
      template: 'FAC-MAINTENANCE',
      description: formattedDescription,
      material_group: 'FACILITIES',
      category: 'FACILITIES-SERVICES',
      qty: '1',
      uom: 'AU',
      price: String(totalCost),
      priceFixed: false,
      aat: 'COST_CENTER',
      aac: costCenter,
      need_date: inDays(365),
      attributes: {
        sowType: 'FACILITIES_MAINTENANCE',
        siteLocation,
        serviceType,
        equipmentTag,
        serviceWindow,
        period,
        safetyCompliance,
        totalAmountMinor: rupeesToMinor(totalCost),
      },
    });
    onClose();
  }

  return (
    <Dialog open wide title="Facilities & Maintenance SOW Generator" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-emerald-50/70 p-3 text-xs text-emerald-950 border border-emerald-200">
          <p>
            <strong>M04 Category Form:</strong> Configures site maintenance agreements, equipment overhaul scopes, and contractor safety compliance rules.
          </p>
          <Button type="button" variant="secondary" onClick={fillMockData} className="!py-1 !text-xs font-semibold">
            ⚡ Fill Sample Facilities Mock
          </Button>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Site / Plant Location" required>
            {(id) => (
              <Input
                id={id}
                required
                value={siteLocation}
                onChange={(e) => setSiteLocation(e.target.value)}
              />
            )}
          </Field>

          <Field label="Service / Maintenance Type" required>
            {(id) => (
              <Select
                id={id}
                value={serviceType}
                onChange={(e) => setServiceType(e.target.value)}
                options={[
                  { value: 'Annual Maintenance Contract (AMC)', label: 'Annual Maintenance Contract (AMC)' },
                  { value: 'Equipment Overhaul & Hydraulic Retrofit', label: 'Equipment Overhaul & Hydraulic Retrofit' },
                  { value: 'Civil Infrastructure & Roof Maintenance', label: 'Civil Infrastructure & Roof Maintenance' },
                  { value: 'Industrial Housekeeping & Waste Disposal', label: 'Industrial Housekeeping & Waste Disposal' },
                  { value: 'HVAC & Environmental Chamber Servicing', label: 'HVAC & Environmental Chamber Servicing' },
                ]}
              />
            )}
          </Field>

          <Field label="Equipment / Asset Tag *" required>
            {(id) => (
              <Input
                id={id}
                required
                placeholder="e.g. HYD-PRESS-400T / Press Line 3"
                value={equipmentTag}
                onChange={(e) => setEquipmentTag(e.target.value)}
              />
            )}
          </Field>

          <Field label="Total Annual Service Fee (₹)" required>
            {(id) => (
              <Input
                id={id}
                type="number"
                min="0"
                required
                value={totalCost}
                onChange={(e) => setTotalCost(Number(e.target.value) || 0)}
              />
            )}
          </Field>
        </div>

        <Field label="Service Window & SLA">
          {(id) => (
            <Input
              id={id}
              value={serviceWindow}
              onChange={(e) => setServiceWindow(e.target.value)}
            />
          )}
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Safety & Environmental Permits">
            {(id) => (
              <Input
                id={id}
                value={safetyCompliance}
                onChange={(e) => setSafetyCompliance(e.target.value)}
              />
            )}
          </Field>

          <Field label="Cost Center" required>
            {(id) => (
              <Input
                id={id}
                required
                value={costCenter}
                onChange={(e) => setCostCenter(e.target.value)}
              />
            )}
          </Field>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" disabled={!equipmentTag || totalCost <= 0}>
            Apply Facilities SOW ({inr(rupeesToMinor(totalCost))})
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
