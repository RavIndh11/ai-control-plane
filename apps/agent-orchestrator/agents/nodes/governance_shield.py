"""
agents/nodes/governance_shield.py — Microsoft AGT proactive governance node.
"""
from typing import Dict, Any
from langchain_core.runnables import RunnableConfig
from agents.state import AgentState

# Microsoft AGT Imports
from agent_governance.policy import AgentEvaluationPolicy
from agent_governance.models import AgentIdentity, ActionRequest

def governance_shield_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """
    Acts as the security kernel (Microsoft AGT) between the agent's reasoning
    and tool execution. Maps Keycloak identity to AGT policy.
    """
    action = state.get("pending_action")
    if not action:
        return state

    # 1. Retrieve the Keycloak JWT principal passed through LangGraph config
    principal = config.get("configurable", {}).get("principal", {})
    client_id = principal.get("id", "anonymous_agent")
    roles = principal.get("roles", [])
    
    # 2. Map Keycloak Identity to AGT Identity
    agt_identity = AgentIdentity(
        agent_id=client_id,
        roles=roles,
        tenant_id=principal.get("tenant_id", "default")
    )

    # 3. Define Proactive AGT Policy based on the mapped identity
    # Load the policy from the ACS manifest file
    policy = AgentEvaluationPolicy(
        policy_path="apps/agent-orchestrator/policies/policy.yaml",
        identity=agt_identity
    )

    # 4. Evaluate the Action
    request = ActionRequest(
        tool_name=action.get("tool"),
        tool_inputs=action.get("tool_input", {})
    )
    
    try:
        eval_result = policy.evaluate(request)
        
        # 5. Apply AGT Governance Rules to the Agent State
        state["action_risk_score"] = getattr(eval_result, "risk_score", 0.0)
        
        if getattr(eval_result, "requires_hitl", False):
            # AGT triggered a Human-in-the-Loop interrupt
            state["requires_hitl"] = True
            state["steps"] = list(state.get("steps", [])) + ["governance_shield_interrupt"]
            state["approval_chain"] = getattr(eval_result, "required_roles", ["tenant-admin"])
        
        elif not getattr(eval_result, "is_allowed", True):
            # AGT proactively blocked the action
            state["output"] = {"error": f"AGT Blocked: {getattr(eval_result, 'reason', 'Unauthorized tool')}"}
            state["pending_action"] = None  # Clear action to skip execute node
            state["steps"] = list(state.get("steps", [])) + ["governance_blocked"]
            
        else:
            # Action is safe
            state["steps"] = list(state.get("steps", [])) + ["governance_approved"]

    except Exception as e:
        # Fail closed on AGT error
        state["output"] = {"error": f"AGT Evaluation Failure: {str(e)}"}
        state["pending_action"] = None
        state["steps"] = list(state.get("steps", [])) + ["governance_blocked"]

    return state
