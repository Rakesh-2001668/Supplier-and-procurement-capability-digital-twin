"""ILLUSTRATIVE SAMPLE, NOT LEGAL ADVICE, REPLACE WITH LEGAL-APPROVED TEXT.

Clause library for the Contracts module (M07, flow F4), written as a realistic stand-in for the legal-approved library the
product owner does not have yet. The wording was drafted by the engineering team to exercise every code path of the module
(drafting by contract type, category overlays, governing-law variants, playbook positions, fallbacks, risk and escalation).
No lawyer has reviewed it. Do not rely on it in a real contract. Every statute named in the text is named only so the sample
reads like an Indian procurement contract; whether it applies, and how, is a question for the client's counsel.

What it holds
  CLAUSES        the standard clauses per contract type (MASTER_AGREEMENT, QUANTITY_CONTRACT, VALUE_CONTRACT,
                 SCHEDULING_AGREEMENT, RATE_CARD, SOW, NDA): standard wording, one or two pre-approved fallback positions,
                 a risk weight (1 low .. 10 high) and the role a deviation escalates to
  OVERLAYS       category overlays (castings and forgings, electronics, IT services and software licences, logistics freight,
                 construction works, healthcare supplies, professional services, MRO), each listed under the category codes it
                 applies to
  JURISDICTIONS  governing-law variants: India (Tamil Nadu, Maharashtra, Karnataka, Gujarat) and foreign suppliers
                 (England and Wales, Singapore, Delaware USA)

How it reaches a tenant
  1. ``playbook_patch()`` turns it into the keys of the CLM-PLAYBOOK rule set (clauseLibrary, categoryClauses, jurisdictions,
     fallbacks). New tenants get it in the bootstrap (seed/reference.py); existing tenants get a new effective-dated version
     from ``reference.ensure_extensions`` (a version is never edited).
  2. To replace it with the client's legal-approved text, write a CSV or JSON file in the same format
     (docs/runbooks/clause_library.md) and load it with ``python -m app.pic.tools.clause_library_load --tenant CODE --file F``.
     No code changes: the loader validates the file and adds a new CLM-PLAYBOOK version.

Placeholders allowed in clause text: {terms} {incoterms} {supplier} {band} {over} {under} (filled when a contract is drafted).
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Optional

SOURCE = "ILLUSTRATIVE_SAMPLE"
VERSION = "2026.3-SAMPLE"
DISCLAIMER = "ILLUSTRATIVE SAMPLE, NOT LEGAL ADVICE, REPLACE WITH LEGAL-APPROVED TEXT"

MA, QC, VC, SA, RC, SOW, NDA = ("MASTER_AGREEMENT", "QUANTITY_CONTRACT", "VALUE_CONTRACT", "SCHEDULING_AGREEMENT", "RATE_CARD", "SOW", "NDA")
CONTRACT_TYPES = (MA, QC, VC, SA, RC, SOW, NDA)
COMMERCIAL = (MA, QC, VC, SA, RC, SOW)
GOODS = (MA, QC, VC, SA)
SERVICES = (MA, VC, RC, SOW)
CALL_OFF = (QC, VC, SA, RC, SOW)
ESCALATION_ROLES = ("LEGAL", "FINANCE_CONTROLLER", "CPO", "PROCUREMENT_HEAD", "CATEGORY_MANAGER", "CONTRACT_MANAGER", "SUPPLIER_MANAGER", "DEPT_HEAD")
PLACEHOLDERS = {"terms": "N30", "incoterms": "FCA", "supplier": "Sample Supplier Pvt Ltd", "band": "3", "over": "2", "under": "5"}
GROUPS = ("Commercial", "Risk", "Legal", "Quality", "Delivery", "Service", "Compliance", "Confidentiality")


def _c(code: str, title: str, group: str, types: tuple, text: str, weight: int, role: str, *fallbacks: str, variants: Optional[dict] = None) -> dict:
    """One library clause. ``fallbacks`` are pre-approved alternative wordings, as 'label :: text'."""
    entry = {"code": code, "title": title, "group": group, "types": list(types), "text": text, "riskWeight": weight, "escalationRole": role,
             "fallbacks": [{"label": f.split(" :: ")[0], "text": f.split(" :: ")[1]} for f in fallbacks]}
    if variants:
        entry["variants"] = variants
    return entry


CLAUSES = [
    # ------------------------------------------------------------------ scope and commercial terms
    _c("SCOPE", "Scope", "Commercial", (MA, RC, SOW),
       "{supplier} supplies the goods or performs the services described in this contract and in each purchase order, call-off or statement of work "
       "issued under it; each of them refers to this contract, states its own items, quantities, prices and dates, and is governed by these terms.", 4,
       "CONTRACT_MANAGER", "Supplier terms of supply accepted only where they do not conflict :: Supplier's standard terms of supply apply to the extent "
       "they do not conflict with this contract; this contract prevails in any conflict.",
       variants={RC: "{supplier} provides the services priced in the rate card on request, at the rates stated for each role or service, under written "
                     "work orders that name the people, the period and the place of work.",
                 SOW: "{supplier} performs the work and delivers the deliverables described in this statement of work, by the milestones and at the "
                      "place stated in it."}),
    _c("PAYMENT", "Payment terms and MSME compliance", "Commercial", COMMERCIAL,
       "Payment {terms} from receipt of a correct tax invoice and, where applicable, the goods receipt note or the approved service entry. For a supplier "
       "registered as a micro or small enterprise the agreed period never exceeds 45 days from the day of acceptance or deemed acceptance (Micro, Small "
       "and Medium Enterprises Development Act, 2006, section 15), and interest at three times the bank rate notified by the Reserve Bank of India is "
       "payable on any delay (section 16). The supplier confirms its Udyam registration status in writing and tells the buyer within 30 days if it "
       "changes.", 8, "FINANCE_CONTROLLER",
       "Net 45 days for every supplier :: Payment within 45 days from receipt of a correct tax invoice and the goods receipt note or approved service entry.",
       "Net 60 days for large-enterprise suppliers only :: Payment within 60 days for a supplier that is not a micro or small enterprise; a micro or small "
       "enterprise is paid within 45 days of acceptance (MSMED Act, 2006, section 15)."),
    _c("PRICE", "Price and taxes", "Commercial", (QC, VC, SA, RC),
       "Prices are in Indian rupees and exclude GST, which the supplier charges at the rate in force on the date of supply and shows on a valid tax "
       "invoice. Prices are fixed for the validity of the contract and include packing, marking and documentation. No other charge is payable unless the "
       "buyer agrees to it in writing before it arises.", 6, "FINANCE_CONTROLLER",
       "Packing and forwarding charged at actuals up to 1.5% :: Packing and forwarding are charged at actual cost, capped at 1.5% of the invoice value, "
       "supported by the supplier's cost statement.",
       variants={MA: "Prices are agreed per call-off or purchase order and exclude GST, which the supplier charges at the rate in force on the date of "
                     "supply; this agreement fixes no volume or value commitment."}),
    _c("PRICE_VARIATION", "Price variation and indexation", "Commercial", (MA, QC, VC, SA, RC),
       "Prices stay firm for the validity of the contract. A price changes only (a) through the published index, base value, formula, absorption band and "
       "reset dates named in the contract, with each reset applied from its effective date and never backdated, or (b) by an approved written amendment "
       "supported by documents showing a change in a statutory levy. A change in GST is passed on at the rate the law sets.", 7, "CATEGORY_MANAGER",
       "Index-linked with a cap of 10% a year :: The price follows the named index with an absorption band of 3% either way and a cap of 10% on any "
       "change in a contract year.",
       "Annual revision limited to the wholesale price index :: One revision a year on the anniversary, limited to the change in the Wholesale Price "
       "Index (all commodities) over the previous twelve months."),
    _c("REBATE", "Volume rebate", "Commercial", (MA, QC, VC, SA),
       "The supplier pays a rebate on the buyer's cumulative net purchases in each financial year at the rate of the tier reached, as set out in the "
       "rebate schedule. The supplier issues a credit note within 30 days after the end of the financial year; the buyer may set the rebate off against "
       "any amount it owes the supplier.", 4, "CATEGORY_MANAGER",
       "Slab rebate instead of retroactive :: The rebate rate applies only to the purchases above each tier threshold (slab basis), not to all purchases "
       "of the year."),
    # ------------------------------------------------------------------ delivery and quality
    _c("DELIVERY", "Delivery and tolerance", "Delivery", (QC, VC, SA),
       "Goods are delivered to the plant and on the dates in the purchase order or delivery schedule, on the Incoterms 2020 rule stated in the contract; "
       "time is of the essence. Each delivery may vary by +{over}% / -{under}% of the ordered quantity. Deliveries more than five days early may be "
       "returned or held at the supplier's risk and cost.", 6, "CATEGORY_MANAGER",
       "Delivery window of two days either side :: Delivery is on time if made within two working days before or after the confirmed date."),
    _c("LIQUIDATED_DAMAGES", "Liquidated damages for late delivery", "Delivery", (QC, VC, SA, SOW),
       "If the supplier delivers late, it pays liquidated damages of 0.5% of the value of the late goods or milestone for each week of delay, a part of a "
       "week counting as a full week, up to 10% of that value. The parties agree the amount is a genuine pre-estimate of the loss (Indian Contract Act, "
       "1872, section 74). It does not limit the buyer's right to terminate for prolonged delay.", 6, "CATEGORY_MANAGER",
       "0.5% a week capped at 5% :: Liquidated damages of 0.5% a week, capped at 5% of the value of the late goods or milestone.",
       "No liquidated damages for delay caused by the buyer :: Liquidated damages do not apply to the extent the delay is caused by the buyer's late "
       "drawings, approvals or schedule changes inside the agreed lead time."),
    _c("QUALITY", "Quality and certificate of conformity", "Quality", (MA, QC, VC, SA),
       "Goods conform to the drawing, specification and standards in the contract. A certificate of conformity (CoC) with the material test certificates "
       "(EN 10204 type 3.1 where the specification asks for it) travels with every lot. The supplier keeps its quality certificates (IATF 16949 or ISO "
       "9001 as agreed) valid throughout, tells the buyer before any change of process, tool, material or site, and rejects nothing silently: "
       "non-conforming lots are reported within 24 hours and replaced at the supplier's cost.", 8, "PROCUREMENT_HEAD",
       "Certificate of conformity per lot, test certificates on request :: A certificate of conformity accompanies every lot; material test certificates "
       "are supplied on request within two working days.",
       "ISO 9001 accepted in place of IATF 16949 for non-safety parts :: ISO 9001 certification is accepted for parts the buyer classifies as "
       "non-safety, non-regulatory parts."),
    _c("PPAP", "Production part approval (PPAP)", "Quality", (MA, QC, SA),
       "Before first delivery, and after any change that needs it, the supplier obtains the buyer's production part approval (PPAP) at the level the buyer "
       "names for the part, and re-submits it on the buyer's request. Problems found in the buyer's plant or in the field are answered with an 8D report "
       "within ten working days.", 7, "PROCUREMENT_HEAD",
       "PPAP level 2 for catalogue parts :: PPAP level 2 applies to standard catalogue parts; level 3 stays for parts made to the buyer's drawing.",
       "8D report within 15 working days :: The 8D report is due within 15 working days of the complaint where the root cause needs lab analysis."),
    _c("WARRANTY", "Warranty", "Quality", COMMERCIAL,
       "Goods are new, of merchantable quality and free from defects in material, workmanship and (where the supplier designed them) design, and conform "
       "to the specification, for 24 months from delivery or 18 months from first use, whichever ends first. The supplier repairs or replaces defective "
       "goods free of charge, including freight and the buyer's reasonable line-stoppage and sorting cost; replaced goods carry a new warranty.", 8,
       "PROCUREMENT_HEAD",
       "12 months from delivery, replacement only :: Warranty for 12 months from delivery; the supplier's duty is to repair or replace the defective goods.",
       "18 months, line-stoppage cost excluded :: Warranty for 18 months from delivery; the supplier is not liable for the buyer's line-stoppage cost.",
       variants={VC: "Goods are new, of merchantable quality and conform to the specification for 12 months from delivery; services are performed with "
                     "reasonable skill and care. Defective goods are repaired or replaced, and defective services re-performed, free of charge.",
                 RC: "Services are performed with reasonable skill and care by suitably qualified people; defective services are re-performed free of charge "
                     "if the buyer reports them within 90 days of the work.",
                 SOW: "Deliverables conform to the statement of work and are free of defects for 90 days after acceptance; the supplier corrects defects "
                      "free of charge and promptly."}),
    _c("SLA", "Service levels and credits", "Service", (MA, VC, RC, SOW),
       "Services meet the response and resolution times in the service level schedule. For each month in which a service level is missed the supplier "
       "gives a service credit of 2% of that month's charges for each missed level, up to 10% of the month's charges. A missed level in three months of any "
       "six is a material breach.", 6, "DEPT_HEAD",
       "Credits capped at 5% of monthly charges :: Service credits are capped at 5% of the month's charges.",
       variants=None),
    _c("RATES", "Rates", "Commercial", (RC, VC),
       "Rates are per unit as listed on the contract lines and fixed for the contract term unless revised by an approved amendment. No rate applies that is "
       "not on the rate card, and time and expenses are payable only if the buyer approved them in writing before they were incurred.", 6, "CATEGORY_MANAGER",
       "Annual rate revision of up to 5% :: Rates may be revised once a year on the anniversary by up to 5%, with 60 days' written notice and the "
       "buyer's approval."),
    _c("DELIVERABLES", "Deliverables and milestones", "Delivery", (SOW,),
       "Deliverables are accepted milestone by milestone; a milestone is complete, and its payment falls due, only when the buyer has accepted it in "
       "writing. Dates in the statement of work are binding; the supplier tells the buyer at once of any risk to a date.", 6, "DEPT_HEAD",
       "Payment of 10% of each milestone held until final acceptance :: The buyer holds back 10% of each milestone payment until the final deliverable is "
       "accepted."),
    _c("ACCEPTANCE", "Acceptance", "Delivery", (SOW,),
       "The buyer accepts or rejects a deliverable in writing within 10 working days of delivery, giving reasons for a rejection; silence is not "
       "acceptance. The supplier corrects a rejected deliverable and delivers it again within five working days.", 5, "DEPT_HEAD",
       "Deemed acceptance after 15 working days with a reminder :: A deliverable is treated as accepted if the buyer does not respond within 15 working "
       "days of a written reminder sent after day 10."),
    # ------------------------------------------------------------------ risk allocation
    _c("LIABILITY", "Limitation of liability", "Risk", COMMERCIAL,
       "Each party's total liability under or in connection with this contract in a contract year is limited to 100% of the annual contract value (or the "
       "value of the affected purchase orders where there is no annual value). The limit does not apply to death or personal injury, fraud or wilful "
       "misconduct, breach of confidentiality, the indemnity for infringement of intellectual property, or any liability the law does not allow to be "
       "limited. Neither party is liable for loss of profit or indirect loss, except as stated in this clause.", 9, "LEGAL",
       "Cap at 150% of annual value, indirect loss excluded :: Liability is capped at 150% of the annual contract value; loss of profit and indirect "
       "loss are excluded.",
       "Cap at 50% of annual value, carve-outs unchanged :: Liability is capped at 50% of the annual contract value; the carve-outs for injury, fraud, "
       "confidentiality and infringement are unchanged."),
    _c("CONFIDENTIALITY", "Confidentiality", "Confidentiality", COMMERCIAL,
       "Each party keeps the other's confidential information confidential during the contract and for five years after it ends (trade secrets for as "
       "long as they stay secret), uses it only for this contract, and discloses it only to employees, advisers and subcontractors who need it and are "
       "bound by equal duties, or as the law requires after notice to its owner where the law allows.", 6, "LEGAL",
       "Three years after the end of the contract :: The duty lasts for three years after the contract ends.",
       "Seven years for technical data :: The duty lasts seven years after the contract ends for drawings and technical data."),
    _c("INDEMNITY", "Indemnity", "Risk", COMMERCIAL,
       "The supplier indemnifies the buyer against third-party claims, and the losses and reasonable costs that follow, arising from the supplier's "
       "negligence, its breach of law, injury or damage to property caused by its people or goods, or the infringement of a third party's intellectual "
       "property by the goods or services as supplied. The buyer tells the supplier promptly of a claim and lets it conduct the defence, with the buyer's "
       "consent for any settlement that affects the buyer.", 8, "LEGAL",
       "Mutual indemnity limited to third-party claims :: Each party indemnifies the other against third-party claims caused by its negligence or breach "
       "of law, subject to the limitation of liability clause.",
       "Infringement indemnity only for goods made to the supplier's design :: The infringement indemnity applies to goods made to the supplier's own "
       "design, not to goods made to the buyer's drawing."),
    _c("IP", "Intellectual property", "Legal", COMMERCIAL,
       "Each party keeps its pre-existing intellectual property. Drawings, specifications, tooling and data the buyer provides or pays for remain the "
       "buyer's property and are used only for the buyer's orders. Intellectual property in bespoke deliverables paid for by the buyer vests in the buyer "
       "on payment, and the supplier grants the buyer a perpetual, royalty-free licence to use the supplier's pre-existing material embedded in them.", 7,
       "LEGAL",
       "Supplier keeps IP in deliverables, buyer gets a perpetual licence :: The supplier keeps the intellectual property in deliverables and grants the "
       "buyer a perpetual, irrevocable, royalty-free licence to use them for its own business.",
       "Improvements owned by the party that makes them :: Improvements to the other party's material belong to the party that makes them, and the other "
       "party receives a licence to use them.",
       variants={SOW: "Deliverables paid for belong to the buyer; the supplier keeps its pre-existing materials and grants the buyer a licence to use them "
                      "with the deliverables."}),
    _c("TERMINATION", "Termination for convenience", "Risk", COMMERCIAL,
       "Either party may terminate this contract for convenience with 90 days' written notice. Orders accepted before the notice run to completion unless "
       "the buyer cancels them in writing. The buyer pays for conforming goods delivered and services accepted up to the termination date and for agreed, "
       "unavoidable work in progress, and nothing else.", 6, "LEGAL",
       "Termination for convenience by the buyer only :: Only the buyer may terminate for convenience, on 60 days' written notice.",
       "120 days' notice for the supplier :: The supplier's notice period is 120 days; the buyer's remains 60 days.",
       variants={RC: "Either party may terminate this contract for convenience with 60 days' written notice; work done and accepted to the termination "
                     "date is paid.",
                 SOW: "Either party may terminate this statement of work for convenience with 30 days' written notice; work accepted to date is paid and "
                      "work in progress is paid at the rates in the contract."}),
    _c("TERMINATION_CAUSE", "Termination for cause", "Risk", COMMERCIAL,
       "Either party may terminate this contract at once by written notice if the other (a) commits a material breach that it does not cure within 30 days "
       "of written notice, (b) becomes insolvent or is the subject of a corporate insolvency resolution process under the Insolvency and Bankruptcy Code, "
       "2016, or (c) in the supplier's case, breaches the anti-bribery, sanctions or code-of-conduct clauses. Termination does not affect rights that have "
       "already arisen.", 7, "LEGAL",
       "Cure period of 45 days :: The cure period for a material breach is 45 days.",
       "No termination for cause on a petition withdrawn within 30 days :: A petition under the Insolvency and Bankruptcy Code, 2016 that is dismissed or "
       "withdrawn within 30 days does not give a right to terminate."),
    _c("FORCE_MAJEURE", "Force majeure", "Risk", COMMERCIAL,
       "Neither party is liable for delay or failure caused by an event beyond its reasonable control, such as natural disaster, epidemic, war, a government "
       "order or a strike outside its own workforce, if it tells the other party within seven days and does what it reasonably can to limit the effect. If "
       "the event lasts more than 60 days either party may terminate the affected orders, and the buyer may buy elsewhere meanwhile.", 5, "LEGAL",
       "90 days before termination :: The period after which the affected orders may be terminated is 90 days.",
       "Buyer may source elsewhere only after 30 days :: The buyer may buy elsewhere only if the event lasts more than 30 days."),
    _c("SUBCONTRACTING", "Subcontracting", "Risk", COMMERCIAL,
       "The supplier does not subcontract any material part of the work without the buyer's written consent. It stays fully liable for its subcontractors, "
       "passes down the quality, confidentiality, anti-bribery, audit and data protection terms of this contract, and replaces a subcontractor the buyer "
       "reasonably objects to.", 5, "CATEGORY_MANAGER",
       "Consent not needed for catalogue items and carriers :: Consent is not needed for standard bought-out items and for carriers; the supplier stays "
       "liable for them."),
    _c("INSURANCE", "Insurance", "Risk", COMMERCIAL,
       "The supplier keeps, at its own cost, commercial general liability and product liability insurance of at least INR 5 crore per occurrence, employees' "
       "compensation cover as the law requires, and, for work on the buyer's premises, professional indemnity and motor cover where relevant. It gives "
       "certificates on request and tells the buyer before a policy lapses.", 5, "FINANCE_CONTROLLER",
       "INR 2 crore for contracts under INR 50 lakh a year :: The required cover is INR 2 crore per occurrence where the annual contract value is under "
       "INR 50 lakh.",
       "Umbrella policy accepted :: The supplier's group umbrella policy is accepted if it gives the same cover and names the buyer as additional insured."),
    _c("ASSIGNMENT", "Assignment and change of control", "Legal", COMMERCIAL,
       "Neither party may assign or transfer this contract without the other's written consent, which is not unreasonably withheld. The supplier tells the "
       "buyer within 15 days of a change of its control; the buyer may terminate the contract within 90 days after that notice if the new owner is a "
       "competitor of the buyer or a sanctioned person.", 4, "LEGAL",
       "Assignment to group companies allowed on notice :: Either party may assign to a group company on 30 days' notice if the assignee takes over all "
       "duties."),
    # ------------------------------------------------------------------ compliance
    _c("AUDIT_RIGHTS", "Audit rights", "Compliance", COMMERCIAL,
       "On 10 working days' notice and during working hours the buyer, its auditors and, for regulated goods, its customers or regulators may audit the "
       "supplier's relevant facilities, quality system, statutory compliance and records for this contract, during the contract and for three years "
       "after it ends. The supplier helps reasonably. Each party bears its own cost unless the audit finds an overcharge above 2% or a serious "
       "non-compliance.", 5, "LEGAL",
       "Once a year with 15 working days' notice :: The buyer may audit once in each contract year on 15 working days' notice, and at any time after a "
       "serious quality or compliance incident.",
       "Quality and statutory compliance only :: The audit covers the quality system and statutory compliance, not the supplier's cost records."),
    _c("DATA_PROTECTION", "Personal data (DPDP Act, 2023)", "Compliance", CONTRACT_TYPES,
       "Each party processes the personal data it receives under this contract only for this contract and in line with the Digital Personal Data "
       "Protection Act, 2023 and its rules. It keeps reasonable security safeguards, tells the other party of a personal data breach within 72 hours, "
       "deletes or returns the data at the end of the contract, and does not transfer it outside India to a country the Central Government has restricted.",
       6, "LEGAL",
       "Breach notice within 96 hours :: A personal data breach is notified within 96 hours of discovery.",
       "Processing details in a data schedule :: The categories of data, purposes and retention periods are listed in a data schedule signed by both parties."),
    _c("ANTI_BRIBERY", "Anti-bribery and sanctions", "Compliance", COMMERCIAL,
       "The supplier does not offer, give or accept any bribe or improper advantage and complies with the Prevention of Corruption Act, 1988 and the "
       "anti-bribery laws that apply to it. It keeps accurate records, discloses any conflict of interest, does not deal with a sanctioned person on this "
       "contract, and reports a suspected breach at once. A breach is a material breach.", 9, "LEGAL",
       "Supplier's own equivalent policy accepted after Legal review :: The supplier's own anti-bribery policy is accepted if Legal has found it "
       "equivalent to the buyer's.",
       "Knowledge qualifier for sub-tier suppliers :: The supplier's duty for its sub-tier suppliers is to use reasonable efforts and report what it "
       "knows."),
    _c("ESG_CONDUCT", "Code of conduct and ESG", "Compliance", COMMERCIAL,
       "The supplier follows the buyer's Supplier Code of Conduct: no child or forced labour, wages and working hours as the law requires, safe workplaces, "
       "environmental consents from the State Pollution Control Board, responsible sourcing of minerals, and yearly energy and emissions data on request. "
       "The buyer may require a corrective action plan within 30 days of a finding.", 6, "SUPPLIER_MANAGER",
       "Supplier's own code accepted if equivalent :: The supplier's own code of conduct is accepted where the supplier management team has found it "
       "equivalent.",
       "Emissions data once a year, aggregate only :: Emissions data is supplied once a year at plant level, not per product."),
    _c("TAX_COMPLIANCE", "GST and tax compliance", "Compliance", COMMERCIAL,
       "The supplier issues a valid tax invoice (with an e-invoice reference where required), files its GST returns on time so that the buyer can claim "
       "input tax credit, and keeps its registration valid. If the buyer loses input tax credit or pays interest because the supplier did not file or "
       "pay the tax, the supplier reimburses it.", 7, "FINANCE_CONTROLLER",
       "Reimbursement limited to the tax, interest only if the supplier was at fault :: The supplier reimburses the lost credit; interest is reimbursed "
       "only where the supplier caused the delay.",
       variants=None),
    _c("DISPUTE_RESOLUTION", "Dispute resolution and arbitration", "Legal", COMMERCIAL,
       "Disputes are first referred to senior managers of both parties for 30 days. If unresolved, they are settled by arbitration under the Arbitration "
       "and Conciliation Act, 1996 by a sole arbitrator appointed by agreement (three arbitrators where the claim exceeds INR 5 crore); the language is "
       "English. The seat and the courts are those named in the governing-law clause, or New Delhi if it names none; the courts have exclusive jurisdiction for interim relief and for enforcement. Pre-"
       "institution mediation under the Commercial Courts Act, 2015 is followed first for a commercial dispute that needs it.", 5, "LEGAL",
       "Institutional arbitration (MCIA or DIAC) :: Arbitration is administered by the Mumbai Centre for International Arbitration or the Delhi International "
       "Arbitration Centre under its rules.",
       "Mediation first for 45 days :: The parties first try to settle through mediation for 45 days before arbitration starts."),
    # ------------------------------------------------------------------ NDA
    _c("DEFINITION", "Confidential information", "Confidentiality", (NDA,),
       "Confidential information is all non-public information disclosed by either party to the other, in any form, including information about "
       "{supplier}, its products, prices, drawings, processes and customers, and the existence and terms of the discussions.", 6, "LEGAL",
       "Only information marked confidential or confirmed in writing :: Confidential information is information marked confidential or confirmed as "
       "confidential in writing within 30 days of disclosure."),
    _c("USE", "Use and disclosure", "Confidentiality", (NDA,),
       "The recipient uses confidential information only for the stated purpose and discloses it only to employees, advisers and affiliates who need it and "
       "are bound by equal duties. It protects the information with at least the care it uses for its own, and tells the discloser at once of any "
       "unauthorised use or disclosure.", 6, "LEGAL",
       "Disclosure to affiliates only with consent :: Disclosure to affiliates needs the discloser's prior written consent."),
    _c("TERM", "Term of the duty", "Confidentiality", (NDA,),
       "The duty of confidentiality lasts for five years from the date of disclosure; trade secrets stay protected as long as they remain secret.", 5,
       "LEGAL", "Three years from disclosure :: The duty of confidentiality lasts for three years from the date of disclosure.",
       "Seven years for technical data :: The duty lasts seven years from disclosure for technical data and drawings."),
    _c("PERMITTED_DISCLOSURE", "Disclosure required by law", "Confidentiality", (NDA,),
       "The recipient may disclose confidential information to the extent a court, a regulator or stock-exchange rules require it, if it first tells the "
       "discloser where the law allows, discloses only what is required and helps the discloser to seek protection.", 4, "LEGAL",
       "Notice after the disclosure to a regulator :: Where prior notice is not practicable, the recipient tells the discloser promptly after disclosing to a regulator."),
    _c("RETURN", "Return and destruction", "Confidentiality", (NDA,),
       "On request or when the purpose ends the recipient returns or destroys the confidential information and confirms this in writing; it may keep one "
       "archive copy where the law or its backup rules require, which stays confidential.", 4, "LEGAL",
       "Destruction certificate within 30 days :: The recipient confirms destruction by an officer's certificate within 30 days of the request."),
    _c("NO_LICENCE", "No licence and no commitment", "Confidentiality", (NDA,),
       "No licence or right in any intellectual property is given by this agreement, and neither party is bound to enter into any further contract or to "
       "disclose any particular information.", 3, "LEGAL",
       "Each party bears its own costs of the discussions :: Each party bears its own costs of the discussions and of any evaluation."),
    _c("REMEDIES", "Remedies", "Confidentiality", (NDA,),
       "A breach may cause harm that damages cannot repair; the discloser may seek injunctive relief in addition to other remedies.", 5, "LEGAL",
       "Injunction after five days' notice to cure :: The discloser may seek an injunction after giving the recipient five days' written notice to cure the breach."),
]


# ---------------------------------------------------------------------------------------------------------------------------------
# Category overlays: added to every draft of a contract whose category is one of ``categories`` (optionally only for some types).
# ---------------------------------------------------------------------------------------------------------------------------------
OVERLAYS = [
    {"name": "CASTINGS_FORGINGS", "categories": ["CASTINGS-FORGINGS", "FERROUS-CASTINGS", "ALU-DIECAST", "FORGINGS"], "clauses": [
        _c("TOOLING_OWNERSHIP", "Tooling, dies and patterns", "Quality", (MA, QC, SA),
           "Dies, patterns, moulds and gauges paid for by the buyer remain its property, are marked as such, insured by the supplier at replacement value, "
           "kept in good order and released to the buyer or its nominee within seven days of a written request, free of any lien.", 7, "CATEGORY_MANAGER",
           "Tooling maintenance cost shared above 50,000 shots :: The supplier maintains the tooling free of charge up to the agreed die life; later "
           "refurbishment is shared equally."),
        _c("CASTING_INTEGRITY", "Material and casting integrity", "Quality", (MA, QC, SA),
           "Each heat or lot has a chemical and mechanical test certificate; castings and forgings are checked by the non-destructive tests named in the "
           "drawing (X-ray, dye-penetrant, ultrasonic). The supplier keeps heat and lot traceability for ten years.", 8, "PROCUREMENT_HEAD",
           "Sampling plan for non-critical parts :: Non-destructive tests follow the agreed sampling plan for parts the buyer classifies as non-critical."),
        _c("METAL_PRICE_LINK", "Metal price link", "Commercial", (QC, SA),
           "Where the price is linked to a metal index, the metal content of the price is reset from the monthly average of the index named in the contract and "
           "the conversion cost stays fixed; changes inside the absorption band are not passed on.", 6, "CATEGORY_MANAGER",
           "Reset quarterly instead of monthly :: The metal content is reset every quarter from the quarterly average of the index."),
    ]},
    {"name": "ELECTRONICS", "categories": ["ELECTRONICS", "ELECTRONICS-COMPONENTS"], "clauses": [
        _c("COUNTERFEIT_PARTS", "Counterfeit and authorised sources", "Quality", (MA, QC, SA),
           "The supplier buys components only from the manufacturer or its authorised distributors, gives traceability to the manufacturer's lot on request, "
           "and replaces any counterfeit or suspect part at its cost and pays the cost of removing it from the buyer's products.", 8, "PROCUREMENT_HEAD",
           "Independent distributors only with prior approval and testing :: Parts from independent distributors need the buyer's prior written approval "
           "and an independent test report."),
        _c("OBSOLESCENCE_LTB", "End of life and last-time buy", "Delivery", (MA, QC, SA),
           "The supplier gives at least 12 months' written notice of the end of life of a part, offers a last-time buy at the current price, and "
           "proposes a form, fit and function replacement for the buyer's approval.", 6, "CATEGORY_MANAGER",
           "Six months' notice for commodity parts :: Notice of end of life is six months for commodity parts."),
        _c("ROHS_REACH", "RoHS and hazardous substances", "Compliance", (MA, QC, SA),
           "Goods comply with the restrictions on hazardous substances in the E-Waste (Management) Rules, 2022, and the supplier gives a declaration of "
           "compliance with each first delivery and on any change of material.", 6, "SUPPLIER_MANAGER",
           "Declaration once a year for unchanged parts :: For parts with no change of material the declaration is renewed once a year."),
    ]},
    {"name": "IT_SERVICES_SOFTWARE", "categories": ["IT-SERVICES", "SOFTWARE-LICENCES", "IT-HARDWARE"], "clauses": [
        _c("SOFTWARE_LICENCE", "Software licence", "Legal", (MA, VC, RC, SOW),
           "The supplier grants the buyer and its affiliates a non-exclusive, non-transferable licence to use the software for the licensed users, sites and "
           "volumes in the order, for the licence term. The buyer may take backup copies and use the software for disaster recovery and test at no extra "
           "charge. A licence audit starts with the buyer's own usage report; an independent auditor is used at most once a year.", 7, "LEGAL",
           "Named-user licence with a 5% true-up band :: Licences are named-user; a shortfall of up to 5% is settled at the next renewal without penalty.",
           "Perpetual licence with annual support :: The licence is perpetual; support and updates are charged yearly at no more than 20% of the licence "
           "fee."),
        _c("INFOSEC", "Information security and incident reporting", "Compliance", (MA, VC, RC, SOW),
           "The supplier keeps an information security programme in line with ISO/IEC 27001, tells the buyer of a security incident that affects the "
           "buyer's data without delay and in any case within six hours of becoming aware, as the CERT-In directions of 28 April 2022 require, and "
           "cooperates in the investigation.", 8, "LEGAL",
           "Incident notice within 24 hours for incidents with no data impact :: Incidents that did not affect the buyer's data are notified within 24 "
           "hours."),
        _c("DATA_LOCATION", "Data location and exit", "Compliance", (MA, VC, SOW),
           "The buyer's data is stored in India unless the buyer agrees otherwise in writing. At the end of the contract the supplier returns the data in an "
           "open format within 30 days and then deletes it and confirms the deletion.", 6, "LEGAL",
           "Backups in an approved cloud region outside India :: Backups may be kept in the approved regions listed in the order."),
        _c("SOURCE_ESCROW", "Source code escrow", "Risk", (MA, VC, SOW),
           "For bespoke software the supplier deposits the source code with an escrow agent, and the buyer may use it to keep the software running if the "
           "supplier becomes insolvent or stops supporting it.", 5, "LEGAL",
           "Escrow only above INR 1 crore of licence fees :: Escrow applies only where the licence fees exceed INR 1 crore."),
    ]},
    {"name": "LOGISTICS_FREIGHT", "categories": ["LOGISTICS", "LOGISTICS-FREIGHT", "FREIGHT"], "clauses": [
        _c("CARRIER_LIABILITY", "Carrier liability for loss and damage", "Risk", (MA, VC, RC, SA),
           "The carrier is liable for loss, damage and delay of goods from receipt to proof of delivery as the Carriage by Road Act, 2007 and the "
           "applicable transport law provide, and does not rely on any limit lower than the declared value of the consignment.", 8, "LEGAL",
           "Liability limited to the declared value :: The carrier's liability is limited to the declared value stated in the consignment note.",
           "INR 5 lakh a consignment unless a higher value is declared :: Liability is INR 5 lakh a consignment unless a higher value is declared in "
           "writing before loading."),
        _c("TRANSIT_DOCUMENTS", "Transit documents and proof of delivery", "Delivery", (MA, VC, RC, SA),
           "Every consignment travels with a valid e-way bill and consignment note. The signed proof of delivery is sent within 48 hours; payment of freight "
           "is released only against it. Shortage or damage is recorded on the proof of delivery and claimed within 30 days.", 5, "CATEGORY_MANAGER",
           "Proof of delivery within 5 days, claims within 15 days :: The signed proof of delivery is sent within five days and a shortage or damage is claimed within 15 days."),
        _c("DETENTION", "Detention and demurrage", "Commercial", (MA, VC, RC, SA),
           "Detention is payable only after 24 hours of free time at loading or unloading and only if the delay is the buyer's fault, at the rate in the rate "
           "card; the carrier records arrival and departure times and gets the plant's counter-signature.", 4, "CATEGORY_MANAGER",
           "Free time of 12 hours :: Free time is 12 hours at the plants listed in the rate card."),
    ]},
    {"name": "CONSTRUCTION_WORKS", "categories": ["CIVIL-SUBCONTRACT", "CONSTRUCTION-MATERIALS", "CONSTRUCTION", "CIVIL-WORKS"], "clauses": [
        _c("RETENTION_MONEY", "Retention money", "Commercial", (MA, VC, SOW),
           "The buyer retains 5% of each running bill as retention money. Half is released on the completion certificate and the rest at the end of the "
           "defect liability period, or earlier against an equal bank guarantee.", 6, "FINANCE_CONTROLLER",
           "Retention reduced to 3% against a performance bank guarantee :: Retention is 3% where the contractor gives a performance bank guarantee of 5% "
           "of the contract value."),
        _c("DEFECT_LIABILITY", "Defect liability period", "Quality", (MA, VC, SOW),
           "The contractor makes good, at its cost and without delay, any defect in the works that appears within 12 months of the completion certificate "
           "(24 months for waterproofing and structural items). If it does not, the buyer may do the work and recover the cost.", 8, "DEPT_HEAD",
           "12 months for all items :: The defect liability period is 12 months for every item."),
        _c("SITE_SAFETY", "Site safety and labour laws", "Compliance", (MA, VC, SOW),
           "The contractor follows the Building and Other Construction Workers Act, 1996, the Contract Labour (Regulation and Abolition) Act, 1970 and the "
           "buyer's site safety plan, keeps its registrations and labour licences valid, pays workers at least minimum wages directly, and reports any "
           "serious accident at once.", 9, "LEGAL",
           "Monthly proof of statutory payments :: Proof of provident fund and insurance payments is given monthly with the bill."),
        _c("PERFORMANCE_GUARANTEE", "Performance bank guarantee", "Risk", (MA, VC, SOW),
           "The contractor gives an unconditional bank guarantee of 10% of the contract value within 15 days of the order, valid until 60 days after the "
           "defect liability period.", 6, "FINANCE_CONTROLLER",
           "5% guarantee for contracts under INR 1 crore :: The guarantee is 5% for contracts below INR 1 crore."),
    ]},
    {"name": "HEALTHCARE_SUPPLIES", "categories": ["PHARMA-COLD", "PHARMA", "HEALTHCARE", "MEDICAL-SUPPLIES"], "clauses": [
        _c("REGULATORY_LICENCES", "Licences and regulatory status", "Compliance", (MA, QC, SA),
           "The supplier holds, and keeps valid, every licence needed to make or sell the goods under the Drugs and Cosmetics Act, 1940 and the Medical Devices "
           "Rules, 2017, and tells the buyer within five days of a suspension, a not-of-standard-quality finding or an import alert.", 9, "LEGAL",
           "Notice within ten days for findings that do not affect supplied batches :: A finding that does not affect a batch supplied to the buyer is notified within ten days."),
        _c("SHELF_LIFE", "Shelf life and cold chain", "Quality", (MA, QC, SA),
           "Goods arrive with at least 75% of their shelf life left and a temperature log for the whole transit. A consignment outside the stated "
           "temperature range is rejected and replaced at the supplier's cost.", 8, "PROCUREMENT_HEAD",
           "At least 60% shelf life for slow-moving items :: At least 60% of shelf life remains for the items the buyer lists as slow-moving."),
        _c("RECALL", "Recall and traceability", "Quality", (MA, QC, SA),
           "The supplier keeps batch traceability, tells the buyer of a recall within 24 hours, and bears the cost of the recall, replacement and disposal.", 9,
           "LEGAL", "Recall cost shared where the buyer's storage caused the defect :: Where the buyer's storage or handling caused the defect, the cost of the recall is shared in proportion to fault."),
    ]},
    {"name": "PROFESSIONAL_SERVICES", "categories": ["PROF-SERVICES", "PROFESSIONAL-SERVICES", "CONSULTING"], "clauses": [
        _c("KEY_PERSONNEL", "Key personnel", "Service", (MA, VC, RC, SOW),
           "The people named in the order do the work. The supplier replaces one only with the buyer's consent, with a person of equal skill, at its own "
           "cost for the handover.", 5, "DEPT_HEAD",
           "Replacement on resignation or illness with 10 days' notice :: A named person may be replaced on resignation, illness or leave with 10 days' "
           "notice."),
        _c("CONFLICT_OF_INTEREST", "Conflict of interest and independence", "Compliance", (MA, VC, RC, SOW),
           "The supplier declares any interest that could affect its advice, does not act for a party adverse to the buyer on the same matter without the "
           "buyer's written consent, and keeps its people independent of the buyer's suppliers it evaluates.", 7, "LEGAL",
           "Information barrier instead of consent :: The supplier may act for another party on a related matter if it keeps an information barrier and discloses the work."),
        _c("PROFESSIONAL_INDEMNITY", "Professional indemnity insurance", "Risk", (MA, VC, RC, SOW),
           "The supplier keeps professional indemnity insurance of at least the contract value (not less than INR 1 crore) during the contract and for three "
           "years after.", 5, "FINANCE_CONTROLLER",
           "Cover of INR 50 lakh for contracts under INR 25 lakh :: Cover of INR 50 lakh applies where the contract value is under INR 25 lakh."),
    ]},
    {"name": "MRO", "categories": ["MRO", "MRO-LUBRICANTS", "MRO-CHEMICALS", "TOOLING", "OFFICE-SAFETY"], "clauses": [
        _c("GENUINE_SPARES", "Genuine spares and availability", "Quality", (MA, QC, VC, RC),
           "Spares and consumables are genuine, from the original manufacturer or its authorised channel, and the supplier keeps them available for at least "
           "seven years from the date of supply of the equipment.", 6, "CATEGORY_MANAGER",
           "Five years' availability for consumables :: Availability is five years for consumable items."),
        _c("EMERGENCY_RESPONSE", "Emergency response", "Service", (MA, VC, RC),
           "For breakdown calls the supplier responds within four hours and delivers or attends within 24 hours, at the rates in the contract, with no premium "
           "for out-of-hours calls.", 5, "DEPT_HEAD",
           "Response within eight hours outside the main hubs :: Response is within eight hours for plants outside the cities listed in the order."),
        _c("CONSIGNMENT_STOCK", "Consignment stock", "Commercial", (MA, QC, VC),
           "Where the supplier holds consignment stock at the buyer's plant it stays the supplier's property until it is drawn, the buyer takes reasonable "
           "care of it, counts it each quarter and pays for it 45 days after the month in which it was drawn.", 4, "CATEGORY_MANAGER",
           "Stock counted twice a year :: The buyer and the supplier count the consignment stock twice a year."),
    ]},
]

# ---------------------------------------------------------------------------------------------------------------------------------
# Governing-law variants. The keys name/law/seat/forum/stamp/data fill the jurisdiction clauses (GOVERNING_LAW, DISPUTES, STAMP_DUTY,
# DATA_PROTECTION); the other keys are information for the contract manager.
# ---------------------------------------------------------------------------------------------------------------------------------
_IN_DATA = "the Digital Personal Data Protection Act, 2023"
JURISDICTIONS = {
    "IN-TN": {"name": "Tamil Nadu", "law": "the laws of India", "seat": "Chennai", "forum": "the courts at Chennai",
              "stamp": "the Indian Stamp Act, 1899 as amended for Tamil Nadu", "data": _IN_DATA, "foreign": False,
              "note": "Stamp duty depends on the instrument and its value; e-stamping applies. Chennai arbitration."},
    "IN-MH": {"name": "Maharashtra", "law": "the laws of India", "seat": "Mumbai", "forum": "the courts at Mumbai",
              "stamp": "the Maharashtra Stamp Act, 1958", "data": _IN_DATA, "foreign": False,
              "note": "Stamp duty under the Maharashtra Stamp Act, 1958 is paid before the contract is relied on; Mumbai arbitration."},
    "IN-KA": {"name": "Karnataka", "law": "the laws of India", "seat": "Bengaluru", "forum": "the courts at Bengaluru",
              "stamp": "the Karnataka Stamp Act, 1957", "data": _IN_DATA, "foreign": False,
              "note": "Stamp duty under the Karnataka Stamp Act, 1957; Bengaluru arbitration."},
    "IN-GJ": {"name": "Gujarat", "law": "the laws of India", "seat": "Ahmedabad", "forum": "the courts at Ahmedabad",
              "stamp": "the Gujarat Stamp Act, 1958", "data": _IN_DATA, "foreign": False,
              "note": "Stamp duty under the Gujarat Stamp Act, 1958; Ahmedabad arbitration."},
    "GB": {"name": "England and Wales", "law": "the laws of England and Wales", "seat": "London", "forum": "the courts of England and Wales",
           "stamp": "the stamp taxes applicable in England and Wales (none is expected on a supply contract)",
           "data": "the UK GDPR and the Data Protection Act 2018", "foreign": True,
           "note": "Foreign supplier. Seat London, LCIA Rules suggested. Prefer arbitration: an award is enforceable in India under the New York Convention."},
    "SG": {"name": "Singapore", "law": "the laws of Singapore", "seat": "Singapore", "forum": "the courts of Singapore",
           "stamp": "the Stamp Duties Act 1929 of Singapore", "data": "the Personal Data Protection Act 2012", "foreign": True,
           "note": "Foreign supplier. Seat Singapore, SIAC Rules suggested; an award is enforceable in India under the New York Convention."},
    "US-DE": {"name": "Delaware, USA", "law": "the laws of the State of Delaware, USA, without regard to its conflict-of-laws rules",
              "seat": "Wilmington, Delaware", "forum": "the state and federal courts located in Delaware",
              "stamp": "no stamp duty is expected in Delaware; Indian stamp duty applies if the contract is brought into India for enforcement",
              "data": "the privacy laws that apply to the party processing the data and the data protection terms of this contract", "foreign": True,
              "note": "Foreign supplier. Delaware law and courts; consider ICC or ICDR arbitration for enforcement in India under the New York Convention."},
}


# ---------------------------------------------------------------------------------------------------------------------------------
# The library as one document, validation, and the playbook patch
# ---------------------------------------------------------------------------------------------------------------------------------
def library() -> dict:
    """The illustrative sample as a library document (same shape as a JSON replacement file)."""
    return {"version": VERSION, "source": SOURCE, "disclaimer": DISCLAIMER, "clauses": json.loads(json.dumps(CLAUSES)),
            "overlays": json.loads(json.dumps(OVERLAYS)), "jurisdictions": json.loads(json.dumps(JURISDICTIONS))}


class LibraryError(ValueError):
    """The library file is not usable; the message lists every problem found."""


_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,29}$")
_JURISDICTION = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")
JURISDICTION_KEYS = ("name", "law", "seat", "forum", "stamp", "data")


def _check_text(where: str, text: str, problems: list) -> None:
    try:
        text.format(**PLACEHOLDERS)
    except (KeyError, IndexError, ValueError) as exc:
        problems.append(f"{where}: text has a placeholder that is not allowed or a stray brace ({exc!r}); allowed: "
                        + ", ".join("{" + k + "}" for k in PLACEHOLDERS))


def _check_clause(where: str, c: dict, problems: list) -> None:
    code = c.get("code") or ""
    where = f"{where} {code or '(no code)'}"
    if not _CODE.match(code):
        problems.append(f"{where}: code must be 2-30 characters of A-Z, 0-9 and _")
    if not (c.get("title") or "").strip():
        problems.append(f"{where}: title is empty")
    if not (c.get("text") or "").strip():
        problems.append(f"{where}: text is empty")
    else:
        _check_text(where, c["text"], problems)
    types = c.get("types") or []
    if not types or any(t not in CONTRACT_TYPES for t in types):
        problems.append(f"{where}: types must be a non-empty subset of {', '.join(CONTRACT_TYPES)}")
    weight = c.get("riskWeight")
    if not isinstance(weight, int) or isinstance(weight, bool) or not 1 <= weight <= 10:
        problems.append(f"{where}: riskWeight must be a whole number from 1 to 10")
    if c.get("escalationRole") not in ESCALATION_ROLES:
        problems.append(f"{where}: escalationRole must be one of {', '.join(ESCALATION_ROLES)}")
    fallbacks = c.get("fallbacks") or []
    if len(fallbacks) > 2:
        problems.append(f"{where}: at most two fallback positions")
    for f in fallbacks:
        if not (f.get("label") or "").strip() or not (f.get("text") or "").strip():
            problems.append(f"{where}: a fallback needs a label and a text, written 'label :: text' in the CSV")
        else:
            _check_text(f"{where} fallback", f["text"], problems)
    for t, text in (c.get("variants") or {}).items():
        if t not in CONTRACT_TYPES:
            problems.append(f"{where}: variant for unknown type {t}")
        else:
            _check_text(f"{where} variant {t}", text, problems)


def validate(doc: dict) -> dict:
    """Check a library document; raises LibraryError listing every problem, returns it unchanged otherwise."""
    problems: list = []
    seen: set = set()
    for c in doc.get("clauses") or []:
        _check_clause("clause", c, problems)
        if c.get("code") in seen:
            problems.append(f"clause {c.get('code')}: listed twice")
        seen.add(c.get("code"))
    if not doc.get("clauses"):
        problems.append("the library has no clauses")
    for o in doc.get("overlays") or []:
        if not o.get("name") or not o.get("categories"):
            problems.append(f"overlay {o.get('name') or '(no name)'}: needs a name and at least one category code")
        codes: set = set()
        for c in o.get("clauses") or []:
            _check_clause(f"overlay {o.get('name')}", c, problems)
            if c.get("code") in codes:
                problems.append(f"overlay {o.get('name')}: clause {c.get('code')} listed twice")
            codes.add(c.get("code"))
    for code, j in (doc.get("jurisdictions") or {}).items():
        if not _JURISDICTION.match(code):
            problems.append(f"jurisdiction {code}: code must look like IN-TN or SG")
        missing = [k for k in JURISDICTION_KEYS if not (j.get(k) or "").strip()]
        if missing:
            problems.append(f"jurisdiction {code}: missing {', '.join(missing)}")
    if problems:
        raise LibraryError("; ".join(problems))
    return doc


def clauses_for(doc: dict, type: str) -> list:
    """The library clauses of one contract type, with the type's own wording where the library has one."""
    return [{**c, "text": (c.get("variants") or {}).get(type, c["text"])} for c in doc.get("clauses") or [] if type in c["types"]]


def playbook_patch(doc: Optional[dict] = None) -> dict:
    """The CLM-PLAYBOOK keys the library adds: ``clauseLibrary`` (the clauses with weights, escalation and fallbacks), ``categoryClauses`` (the
    overlays under each category code), ``jurisdictions`` and ``fallbacks`` (code -> first pre-approved fallback, the string the AI review shows)."""
    doc = validate(doc or library())
    overlay_clauses = [c for o in doc.get("overlays") or [] for c in o["clauses"]]
    category_clauses: dict = {}
    for overlay in doc.get("overlays") or []:
        entries = [{"code": c["code"], "title": c["title"], "text": c["text"], "types": c["types"]} for c in overlay["clauses"]]
        for category in overlay["categories"]:
            category_clauses[category.strip().upper()] = entries
    fallbacks = {c["code"]: c["fallbacks"][0]["text"] for c in [*(doc.get("clauses") or []), *overlay_clauses] if c.get("fallbacks")}
    return {
        "clauseLibrary": {"version": doc.get("version") or VERSION, "source": doc.get("source") or SOURCE, "disclaimer": doc.get("disclaimer") or DISCLAIMER,
                          "precedence": "LIBRARY", "clauses": doc["clauses"], "overlayClauses": overlay_clauses},
        "categoryClauses": category_clauses,
        "jurisdictions": doc.get("jurisdictions") or {},
        "fallbacks": fallbacks,
    }


def merge_into(body: dict, patch: dict, *, replace: bool = False) -> dict:
    """A playbook body with the library patch merged in. By default whatever the tenant already has wins (its categoryClauses, jurisdictions
    and fallbacks per key); ``replace=True`` is a deliberate load of a client's library: the library wins per key and the tenant's other keys stay."""
    out = {**body, "clauseLibrary": patch["clauseLibrary"]}
    for key in ("categoryClauses", "jurisdictions", "fallbacks"):
        mine, theirs = patch.get(key) or {}, body.get(key) or {}
        out[key] = {**theirs, **mine} if replace else {**mine, **theirs}
    return out


def metadata(playbook_body: dict) -> dict:
    """code -> {riskWeight, escalationRole, fallbackPositions} for the review screens (library and overlay clauses)."""
    library_ = playbook_body.get("clauseLibrary") or {}
    out: dict = {}
    for c in [*(library_.get("clauses") or []), *(library_.get("overlayClauses") or [])]:
        out.setdefault(c["code"], {"riskWeight": c["riskWeight"], "escalationRole": c["escalationRole"], "fallbackPositions": c.get("fallbacks") or []})
    return out


def library_clauses(playbook_body: dict, type: str) -> list:
    """The clauses a draft of this type takes from the library in a playbook body (empty when the playbook has none)."""
    library_ = playbook_body.get("clauseLibrary")
    return clauses_for(library_, type) if library_ else []


# ---------------------------------------------------------------------------------------------------------------------------------
# File formats: JSON (the library document) and CSV (one row per clause, overlay clause or jurisdiction)
# ---------------------------------------------------------------------------------------------------------------------------------
CSV_COLUMNS = ["kind", "code", "category", "title", "group", "types", "text", "risk_weight", "escalation_role", "fallback_1", "fallback_2",
               "variants", "name", "law", "seat", "forum", "stamp", "data", "note"]


def to_csv(doc: dict) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()

    def clause_row(kind: str, c: dict, category: str = "") -> dict:
        fb = [f"{f['label']} :: {f['text']}" for f in c.get("fallbacks") or []] + ["", ""]
        return {"kind": kind, "code": c["code"], "category": category, "title": c["title"], "group": c.get("group", ""), "types": "|".join(c["types"]),
                "text": c["text"], "risk_weight": c["riskWeight"], "escalation_role": c["escalationRole"], "fallback_1": fb[0], "fallback_2": fb[1],
                "variants": json.dumps(c["variants"], sort_keys=True) if c.get("variants") else ""}

    for c in doc.get("clauses") or []:
        writer.writerow(clause_row("CLAUSE", c))
    for o in doc.get("overlays") or []:
        for c in o["clauses"]:
            writer.writerow(clause_row("OVERLAY", c, "|".join(o["categories"])))
    for code, j in (doc.get("jurisdictions") or {}).items():
        writer.writerow({"kind": "JURISDICTION", "code": code, **{k: j.get(k, "") for k in (*JURISDICTION_KEYS, "note")}})
    return buffer.getvalue()


def from_csv(text: str) -> dict:
    """Parse the CSV format into a library document (validate() checks it)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = [c for c in ("kind", "code") if c not in (reader.fieldnames or [])]
    if missing:
        raise LibraryError(f"the CSV header lacks column(s) {', '.join(missing)}; expected {', '.join(CSV_COLUMNS)}")
    clauses, overlays, jurisdictions, problems = [], {}, {}, []
    for number, row in enumerate(reader, start=2):
        row = {k: (v or "").strip() for k, v in row.items() if k}
        kind = row.get("kind", "").upper()
        if not any(row.values()):
            continue
        if kind == "JURISDICTION":
            jurisdictions[row["code"].upper()] = {k: row.get(k, "") for k in (*JURISDICTION_KEYS, "note") if row.get(k) or k in JURISDICTION_KEYS}
            continue
        if kind not in ("CLAUSE", "OVERLAY"):
            problems.append(f"row {number}: kind must be CLAUSE, OVERLAY or JURISDICTION")
            continue
        try:
            weight = int(row.get("risk_weight") or 0)
        except ValueError:
            weight = 0
        fallbacks = []
        for col in ("fallback_1", "fallback_2"):
            if row.get(col):
                label, sep, body = row[col].partition(" :: ")
                fallbacks.append({"label": label.strip(), "text": body.strip()} if sep else {"label": "", "text": ""})
        try:
            variants = json.loads(row["variants"]) if row.get("variants") else None
        except ValueError:
            problems.append(f"row {number}: variants must be a JSON object")
            variants = None
        clause = {"code": row["code"].upper(), "title": row.get("title", ""), "group": row.get("group", ""),
                  "types": [t.strip().upper() for t in row.get("types", "").split("|") if t.strip()], "text": row.get("text", ""), "riskWeight": weight,
                  "escalationRole": row.get("escalation_role", "").upper(), "fallbacks": fallbacks}
        if variants:
            clause["variants"] = variants
        if kind == "CLAUSE":
            clauses.append(clause)
        else:
            categories = [c.strip().upper() for c in row.get("category", "").split("|") if c.strip()]
            overlays.setdefault("|".join(categories), {"name": categories[0] if categories else "", "categories": categories, "clauses": []})["clauses"].append(clause)
    if problems:
        raise LibraryError("; ".join(problems))
    return {"version": "FILE", "source": "FILE", "disclaimer": "", "clauses": clauses, "overlays": list(overlays.values()), "jurisdictions": jurisdictions}


def read_file(path) -> dict:
    """A library document from a .json or .csv file (validated)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LibraryError(f"{path.name} is not valid JSON: {exc}") from exc
        doc.setdefault("source", "FILE")
        doc.setdefault("version", "FILE")
    else:
        doc = from_csv(text)
    return validate(doc)


def summary(doc: Optional[dict] = None) -> dict:
    doc = doc or library()
    overlay_clauses = [c for o in doc.get("overlays") or [] for c in o["clauses"]]
    return {"clauses": len(doc.get("clauses") or []), "clausesPerType": {t: len(clauses_for(doc, t)) for t in CONTRACT_TYPES},
            "overlays": len(doc.get("overlays") or []), "overlayClauses": len(overlay_clauses),
            "fallbacks": sum(len(c.get("fallbacks") or []) for c in [*(doc.get("clauses") or []), *overlay_clauses]),
            "jurisdictions": len(doc.get("jurisdictions") or {})}
