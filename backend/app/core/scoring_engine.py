from datetime import datetime

class ScoringEngine:
    def __init__(self, model_version_id: str):
        self.model_version_id = model_version_id
        # In a real system, we would load the 'rules_payload' JSON from the DB here
        
    def calculate_dimension(self, base_score: float, evidence_level: int, age_days: int) -> float:
        # 1. Apply Evidence Discount
        # L1 (Self-declared) gets heavily discounted vs L5 (Computationally inferred)
        evidence_multipliers = {1: 0.6, 2: 0.8, 3: 0.9, 4: 0.95, 5: 1.0}
        discounted_score = base_score * evidence_multipliers.get(evidence_level, 0.5)
        
        # 2. Apply Time Decay
        # Scores decay slowly over time if not refreshed by new events
        decay_factor = max(0.5, 1.0 - (age_days * 0.001)) 
        
        return round(discounted_score * decay_factor, 2)
        
    def run_scoring(self, supplier_id: str, twin_state: dict) -> dict:
        # Mocking the calculation across the 12 dimensions based on twin_state
        dimensions = {
            "manufacturing": self.calculate_dimension(95, 4, 10),
            "quality": self.calculate_dimension(88, 3, 45),
            "engineering": self.calculate_dimension(85, 2, 100),
            "capacity": self.calculate_dimension(90, 5, 2),
            "technology": self.calculate_dimension(75, 1, 200),
            "workforce": self.calculate_dimension(80, 2, 50),
            "supply_chain": self.calculate_dimension(70, 3, 30),
            "financial_resilience": self.calculate_dimension(92, 4, 5),
            "digital_maturity": self.calculate_dimension(65, 1, 300),
            "esg": self.calculate_dimension(84, 3, 60),
            "industry_readiness": self.calculate_dimension(88, 4, 15),
            "future_readiness": self.calculate_dimension(78, 2, 90)
        }
        
        overall = round(sum(dimensions.values()) / 12, 2)
        
        return {
            "supplier_id": supplier_id,
            "model_version_id": self.model_version_id,
            "computed_at": datetime.utcnow().isoformat(),
            "dimensions": dimensions,
            "overall_score": overall
        }
