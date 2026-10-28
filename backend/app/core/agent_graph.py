import json
from typing import TypedDict, Annotated, Sequence
import operator
from langgraph.graph import StateGraph, END

# Define the State
class AgentState(TypedDict):
    messages: Annotated[Sequence[str], operator.add]
    intent: str
    evidence: list
    confidence: str
    model_used: str
    action_link: str
    action_label: str
    final_answer: str

# Mock LLM calls for prototype
def router_node(state: AgentState) -> AgentState:
    query = state["messages"][-1].lower()
    intent = "synthesis"
    if "risk" in query or "vulnerab" in query:
        intent = "risk"
    elif "find" in query or "which" in query or "capacity" in query:
        intent = "discovery"
    return {"intent": intent}

def discovery_agent(state: AgentState) -> AgentState:
    # Mock capability graph query
    return {
        "evidence": ["Capability Graph v3", "Live Capacity Feed (MES)"],
        "confidence": "0.86",
        "model_used": "Graph Traversal (DEPENDS_ON)",
        "final_answer": "6 suppliers hold the required capability on verified evidence. 3 of them have >=15% free CNC capacity: Precision AutoComp (22%), Chennai Metal Forms (18%), Sri Balaji Precision (15%).",
        "action_label": "View Match Report →",
        "action_link": "/discovery"
    }

def risk_agent(state: AgentState) -> AgentState:
    # Mock risk model query
    return {
        "evidence": ["Financial Indicators Feed", "Geopolitical News API"],
        "confidence": "0.71",
        "model_used": "Risk-TSF v2.1 (90-day horizon)",
        "final_answer": "4 suppliers show financial vulnerability signals: Trichy Forge Works (strongest indicator drift), plus 3 with rising customer concentration risk. Trichy is sole-source for 2 active programs.",
        "action_label": "Review Risk Mitigations →",
        "action_link": "/risk"
    }

def synthesis_agent(state: AgentState) -> AgentState:
    # If it didn't hit a specific agent, provide a generic answer
    if not state.get("final_answer"):
        return {
            "evidence": ["Platform General DB"],
            "confidence": "0.99",
            "model_used": "Base Canned Router",
            "final_answer": "I am the SupplyTwin AI Copilot. I can query the capability graph for supplier discovery or run risk prediction models. Try asking: 'Which suppliers have unused CNC capacity?'",
            "action_label": "Explore Command Centre",
            "action_link": "/command-centre"
        }
    return state

# Conditional routing logic
def route_intent(state: AgentState) -> str:
    return state["intent"]

# Build the Graph
workflow = StateGraph(AgentState)

workflow.add_node("router", router_node)
workflow.add_node("discovery", discovery_agent)
workflow.add_node("risk", risk_agent)
workflow.add_node("synthesis", synthesis_agent)

workflow.set_entry_point("router")
workflow.add_conditional_edges(
    "router",
    route_intent,
    {
        "discovery": "discovery",
        "risk": "risk",
        "synthesis": "synthesis"
    }
)

workflow.add_edge("discovery", "synthesis")
workflow.add_edge("risk", "synthesis")
workflow.add_edge("synthesis", END)

# Compile the graph
copilot_graph = workflow.compile()
