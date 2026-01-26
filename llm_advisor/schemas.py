from typing import List, TypedDict, Optional

class PolicyContext(TypedDict):
    regime_id: int
    transition_mode: str
    transition_probability: float
    allowed_actions: List[str]
    max_risk_multiplier: float
    positioning_mode: str
    policy_notes: str

class NarrativeOutput(TypedDict):
    selected_policy: str
    rationale: str
    confidence: str # "STRUCTURAL", "UNCERTAIN"
