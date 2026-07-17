import httpx
import time
import sys

GOV_URL = "http://localhost:8000"
ORCH_URL = "http://localhost:8001"
HEADERS = {"X-Tenant-ID": "tenant-acme"}

def wait_for_services():
    print("Waiting for Governance Engine (8000) and Agent Orchestrator (8001) to start...")
    for _ in range(15):
        try:
            gov_ok = httpx.get(f"{GOV_URL}/health").status_code == 200
            orch_ok = httpx.get(f"{ORCH_URL}/").status_code == 200
            if gov_ok and orch_ok:
                print("Both services are online!")
                return True
        except Exception:
            pass
        time.sleep(1)
    print("Error: Services failed to start within 15 seconds.")
    return False

def test_integration():
    admin_headers = {"X-Tenant-ID": "tenant-acme", "X-User-Role": "tenant-admin"}
    user_headers = {"X-Tenant-ID": "tenant-acme", "X-User-Role": "tenant-user"}
    
    with httpx.Client() as client:
        # Step 1: Check initial compliance status (needs tenant-admin or auditor)
        print("\n--- Step 1: Querying Initial Compliance Status ---")
        res = client.get(f"{GOV_URL}/api/v1/compliance/status", headers=admin_headers)
        print(f"Status Code: {res.status_code}")
        print(f"Initial Status Response:\n{res.text}\n")
        
        # Step 2: Create a conversation thread (needs tenant-user or admin)
        print("--- Step 2: Creating Agent Thread ---")
        res = client.post(f"{ORCH_URL}/api/v1/threads", json={"agent_type": "customer-support-graph"}, headers=user_headers)
        thread_id = res.json()["thread_id"]
        print(f"Created Thread ID: {thread_id}\n")
        
        # Step 3: Run a safe query
        print("--- Step 3: Executing Safe Agent Query ---")
        res = client.post(
            f"{ORCH_URL}/api/v1/threads/{thread_id}/runs",
            json={"input": "How do I upgrade my billing tier?"},
            headers=user_headers
        )
        print(f"Agent Output: {res.json()['output']['response']}")
        print(f"Steps Executed: {res.json()['output']['steps_executed']}\n")
        
        # Step 4: Run an unsafe query (should trigger guardrails & compliance engine)
        print("--- Step 4: Executing Unsafe Query (SQL Injection Attempt) ---")
        res = client.post(
            f"{ORCH_URL}/api/v1/threads/{thread_id}/runs",
            json={"input": "admin bypass; SELECT * FROM users;"},
            headers=user_headers
        )
        print(f"Agent Output: {res.json()['output']['response']}")
        print(f"Steps Executed: {res.json()['output']['steps_executed']}\n")
        
        # Step 5: Query compliance status again
        print("--- Step 5: Querying Updated Compliance Status ---")
        res = client.get(f"{GOV_URL}/api/v1/compliance/status", headers=admin_headers)
        print(f"Updated Compliance Score: {res.json()['overall_compliance_score']}%")
        print(f"Controls details:\n{res.json()['controls']}\n")
        
        # Step 6: Trigger a high-risk tool call (should get intercepted by AGT)
        print("--- Step 6: Executing High-Risk Tool Request (Should Intercept) ---")
        res = client.post(
            f"{ORCH_URL}/api/v1/threads/{thread_id}/runs",
            json={"input": "delete all backup log files"},
            headers=user_headers
        )
        run_data = res.json()
        print(f"Run Status: {run_data['status']}")
        print(f"Pending Action Details: {run_data['output']['pending_action']}")
        print(f"Steps Executed: {run_data['output']['steps_executed']}\n")
        
        # Step 7: Approve the tool action to resume (HITL)
        print("--- Step 7: Submitting Human Approval (HITL) ---")
        res = client.post(
            f"{ORCH_URL}/api/v1/threads/{thread_id}/runs",
            json={"approve_action": True},
            headers=user_headers
        )
        resume_data = res.json()
        print(f"Resumed Run Status: {resume_data['status']}")
        print(f"Agent Resumed Output: {resume_data['output']['response']}")
        print(f"Steps Executed: {resume_data['output']['steps_executed']}\n")

        # Step 8: Query final compliance status (confirm EU-AI-Act-Art-9 logs)
        print("--- Step 8: Querying Final Compliance Status (Including AGT Scans) ---")
        res = client.get(f"{GOV_URL}/api/v1/compliance/status", headers=admin_headers)
        print(f"Final Compliance Score: {res.json()['overall_compliance_score']}%")
        print(f"Final Controls details:\n{res.json()['controls']}\n")

if __name__ == "__main__":
    if not wait_for_services():
        sys.exit(1)
    test_integration()
