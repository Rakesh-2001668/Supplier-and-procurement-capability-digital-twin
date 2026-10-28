"""
Rules & Decision Tables Engine (DMN & PO Risk Score)
AlphaHelion Purchasing Intelligence Cloud
Implements DMN-01, DMN-02, DMN-03, and the explainable additive PO Risk Score formula.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel

class DMN01RequisitionRule:
    """
    DMN-01: Requisition approval route
    Value (INR) | Account Assignment | Purchase Type | Output Approver Chain
    < 25,000    | any                | catalogue/contract | auto
    25k - 2L    | cost centre/WBS    | any                | cost-object owner
    2L - 10L    | any                | any                | cost-object owner -> department head
    > 10L       | any                | any                | cost-object owner -> dept head -> procurement head -> finance controller
    any         | asset              | capital asset      | + capex committee
    """
    @staticmethod
    def evaluate(value_inr: float, account_assignment_type: str, purchase_type: str) -> List[str]:
        chain = []
        is_capital = (purchase_type.upper() == "CAPITAL_ASSET" or account_assignment_type.upper() == "ASSET")

        if value_inr < 25000 and purchase_type.upper() in ["CATALOGUE", "CONTRACT"]:
            chain = ["AUTO_APPROVED (Touchless Policy)"]
        elif value_inr <= 200000:
            chain = ["Cost-Object Owner"]
        elif value_inr <= 1000000:
            chain = ["Cost-Object Owner", "Department Head"]
        else:
            chain = ["Cost-Object Owner", "Department Head", "Procurement Head", "Finance Controller"]

        if is_capital and "Capital Committee / Board" not in chain:
            chain.append("Capital Asset Committee")

        return chain

class DMN02TouchlessPO:
    """
    DMN-02: Touchless PO decision
    Price source: contract / catalogue
    Supplier status: Qualified / Preferred
    Value band: <= touchless band (e.g. 5,00,000 INR)
    Split pattern: none
    Late-risk prob: < 0.30
    Risk score: < 30
    Output: release (Touchless PO Agent, L4) vs route to buyer/approval
    """
    @staticmethod
    def evaluate(
        price_source: str,
        supplier_status: str,
        value_inr: float,
        touchless_band_max: float,
        has_split_pattern: bool,
        late_risk_prob: float,
        risk_score: int
    ) -> Dict[str, Any]:
        reasons_failed = []
        if price_source.upper() not in ["CONTRACT", "CATALOGUE"]:
            reasons_failed.append(f"Price source '{price_source}' is not contract/catalogue")
        if supplier_status.upper() not in ["QUALIFIED", "PREFERRED"]:
            reasons_failed.append(f"Supplier status '{supplier_status}' is not Qualified/Preferred")
        if value_inr > touchless_band_max:
            reasons_failed.append(f"Value ₹{value_inr:,.2f} exceeds touchless band max ₹{touchless_band_max:,.2f}")
        if has_split_pattern:
            reasons_failed.append("Potential order-splitting pattern detected in past 7 days")
        if late_risk_prob >= 0.30:
            reasons_failed.append(f"Late-delivery probability ({late_risk_prob:.2f}) >= 0.30 threshold")
        if risk_score >= 30:
            reasons_failed.append(f"PO risk score ({risk_score}) exceeds touchless limit (30)")

        is_touchless = len(reasons_failed) == 0
        return {
            "touchless_approved": is_touchless,
            "decision": "TOUCHLESS_RELEASE" if is_touchless else "ROUTE_TO_BUYER_APPROVAL",
            "agent": "Touchless PO Agent (L4)" if is_touchless else None,
            "reasons": reasons_failed
        }

class DMN03InvoiceTolerance:
    """
    DMN-03: Invoice Tolerance Engine
    Price per unit: +/- 1% or 500 INR per line (whichever lower) -> price exception
    Quantity vs accepted GR: 0% for 3-way match -> quantity exception
    Quantity vs SES: 0% -> service exception
    Tax: exact, IRN validated for e-invoices -> tax exception
    Duplicate: same supplier + invoice number, or amount +/- 1 and date +/- 3 days -> duplicate hold
    """
    @staticmethod
    def check_tolerances(
        po_price: float,
        invoice_price: float,
        po_qty: float,
        gr_accepted_qty: float,
        invoiced_qty: float,
        tax_matches: bool,
        is_duplicate: bool,
        gr_required: bool = True
    ) -> Dict[str, Any]:
        exceptions = []
        suggested_actions = []

        if is_duplicate:
            exceptions.append({"type": "DUPLICATE_HOLD", "detail": "Potential duplicate invoice detected with matching amount/date."})
            suggested_actions.append("Hold invoice payment pending duplicate investigation.")

        # Price Tolerance: min(1% * po_price, 500 INR)
        price_delta = invoice_price - po_price
        max_allowed_price_tol = min(0.01 * po_price, 500.0)
        if abs(price_delta) > max_allowed_price_tol:
            exceptions.append({
                "type": "PRICE_EXCEPTION",
                "delta": price_delta,
                "detail": f"Unit price variance ₹{price_delta:+.2f} exceeds allowed tolerance of ₹{max_allowed_price_tol:.2f}."
            })
            suggested_actions.append("Request credit note or buyer price-variance signoff.")

        # Quantity Tolerance (3-way vs GR)
        if gr_required:
            qty_delta = invoiced_qty - gr_accepted_qty
            if qty_delta > 0:
                exceptions.append({
                    "type": "QUANTITY_EXCEPTION",
                    "delta": qty_delta,
                    "detail": f"Invoiced quantity ({invoiced_qty}) exceeds accepted goods receipt ({gr_accepted_qty}) by +{qty_delta:g} units."
                })
                suggested_actions.append(f"Request Credit Note for {qty_delta:g} rejected/missing units from supplier.")
        else:
            # 2-way vs PO
            qty_delta = invoiced_qty - po_qty
            if qty_delta > 0:
                exceptions.append({
                    "type": "QUANTITY_EXCEPTION",
                    "delta": qty_delta,
                    "detail": f"Invoiced quantity exceeds PO quantity by +{qty_delta:g} units."
                })
                suggested_actions.append("Hold payment until PO line amendment or credit note.")

        if not tax_matches:
            exceptions.append({"type": "TAX_EXCEPTION", "detail": "Tax rate mismatch or GST IRN QR signature failed validation."})
            suggested_actions.append("Verify HSN/SAC code and valid e-invoice IRN.")

        is_matched = len(exceptions) == 0
        return {
            "is_matched": is_matched,
            "status": "MATCHED" if is_matched else "EXCEPTION",
            "exceptions": exceptions,
            "suggested_actions": suggested_actions
        }

class PORiskScoreCalculator:
    """
    Additive explainable PO risk score (0-100) formula:
    risk = 18*(late_prob >= 0.15) + 35*(late_prob >= 0.30)
         + 18*price_dev_vs_contract + 40*supplier_not_qualified
         + 15*value_above_band + 25*split_pattern + 12*acct_assignment_changed
    risk = min(risk, 100)
    """
    @staticmethod
    def calculate(
        late_delivery_prob: float,
        price_deviation_vs_contract: bool,
        supplier_not_qualified: bool,
        value_above_band: bool,
        split_pattern: bool,
        account_assignment_changed: bool
    ) -> Dict[str, Any]:
        factors = []
        score = 0

        # Late delivery probability steps
        if late_delivery_prob >= 0.30:
            score += 35
            factors.append({
                "code": "LATE_RISK_HIGH",
                "points": 35,
                "evidence": f"AI model eta-v3 predicted late probability {late_delivery_prob:.2f} >= 0.30"
            })
        elif late_delivery_prob >= 0.15:
            score += 18
            factors.append({
                "code": "LATE_RISK_MED",
                "points": 18,
                "evidence": f"AI model eta-v3 predicted late probability {late_delivery_prob:.2f} >= 0.15"
            })

        if price_deviation_vs_contract:
            score += 18
            factors.append({
                "code": "PRICE_DEVIATION",
                "points": 18,
                "evidence": "PO price deviates from active contract reference without approved override"
            })

        if supplier_not_qualified:
            score += 40
            factors.append({
                "code": "SUPPLIER_NOT_QUALIFIED",
                "points": 40,
                "evidence": "Supplier status is Conditional, Under Qualification, or Blocked for this commodity"
            })

        if value_above_band:
            score += 15
            factors.append({
                "code": "VALUE_ABOVE_BAND",
                "points": 15,
                "evidence": "Total order amount exceeds plant standard single-PO release band"
            })

        if split_pattern:
            score += 25
            factors.append({
                "code": "SPLIT_PATTERN_DETECTED",
                "points": 25,
                "evidence": "Multiple orders to same vendor within 7 days summing above approval threshold"
            })

        if account_assignment_changed:
            score += 12
            factors.append({
                "code": "ACCT_ASSIGNMENT_CHANGED",
                "points": 12,
                "evidence": "Account assignment modified from original requisition line"
            })

        final_score = min(score, 100)
        return {
            "risk_score": final_score,
            "risk_level": "LOW" if final_score < 30 else ("MEDIUM" if final_score < 60 else "HIGH"),
            "touchless_eligible": final_score < 30,
            "factors": factors
        }
