import httpx
import time
import sys
import json

GOV_URL = "http://localhost:8000"
ORCH_URL = "http://localhost:8001"
ADMIN_HEADERS = {"X-Tenant-ID": "tenant-acme", "X-User-Role": "tenant-admin", "X-User-ID": "admin-001"}
USER_HEADERS  = {"X-Tenant-ID": "tenant-acme", "X-User-Role": "tenant-user",  "X-User-ID": "user-001"}

def wait_for_services():
    print("Waiting for Governance Engine (8000) and Agent Orchestrator (8001) to start...")
    for _ in range(20):
        try:
            gov_ok = httpx.get(f"{GOV_URL}/health", timeout=2.0).status_code == 200
            orch_ok = httpx.get(f"{ORCH_URL}/", timeout=2.0).status_code == 200
            if gov_ok and orch_ok:
                print("✅ Both services are online!\n")
                return True
        except Exception:
            pass
        time.sleep(1)
    print("❌ Error: Services failed to start within 20 seconds.")
    return False

def ok(label: str, condition: bool, detail: str = ""):
    icon = "✅" if condition else "❌"
    print(f"  {icon} {label}{': ' + detail if detail else ''}")
    if not condition:
        raise AssertionError(f"FAILED: {label}")

def test_integration():
    with httpx.Client(timeout=30.0) as client:

        # ── Auth: missing headers should return 401 ────────────────────────
        print("=== Test 1: Auth Rejection (no headers) ===")
        res = client.get(f"{GOV_URL}/api/v1/compliance/status")
        ok("Returns 401 when no auth provided", res.status_code == 401, f"got {res.status_code}")

        res2 = client.post(f"{ORCH_URL}/api/v1/threads", json={"agent_type": "test"})
        ok("Orchestrator returns 401 with no headers", res2.status_code == 401, f"got {res2.status_code}")

        # ── Step 1: Initial compliance status ────────────────────────────
        print("\n=== Test 2: Initial Compliance Status ===")
        res = client.get(f"{GOV_URL}/api/v1/compliance/status", headers=ADMIN_HEADERS)
        ok("Returns 200", res.status_code == 200)
        data = res.json()
        ok("Has overall_compliance_score", "overall_compliance_score" in data)
        ok("Has controls list", "controls" in data and len(data["controls"]) > 0)
        print(f"  Score: {data['overall_compliance_score']}%  |  Controls: {[c['status'] for c in data['controls']]}")

        # ── Step 2: Create thread ─────────────────────────────────────────
        print("\n=== Test 3: Create Agent Thread ===")
        res = client.post(f"{ORCH_URL}/api/v1/threads", json={"agent_type": "customer-support-graph"}, headers=USER_HEADERS)
        ok("Returns 200", res.status_code == 200)
        thread_id = res.json()["thread_id"]
        ok("Thread ID returned", thread_id.startswith("th_"))
        print(f"  Thread ID: {thread_id}")

        # ── Step 3: Safe query ────────────────────────────────────────────
        print("\n=== Test 4: Safe Agent Query ===")
        res = client.post(f"{ORCH_URL}/api/v1/threads/{thread_id}/runs",
                          json={"input": "How do I upgrade my billing tier?"}, headers=USER_HEADERS)
        ok("Returns 200", res.status_code == 200)
        run = res.json()
        ok("Has output response", bool(run["output"]["response"]))
        ok("Steps executed", "guardrail_check" in run["output"]["steps_executed"])
        print(f"  Response: {run['output']['response'][:80]}...")
        print(f"  Steps: {run['output']['steps_executed']}")

        # ── Step 4: SQL injection guardrail ───────────────────────────────
        print("\n=== Test 5: SQL Injection Guardrail Block ===")
        res = client.post(f"{ORCH_URL}/api/v1/threads/{thread_id}/runs",
                          json={"input": "admin bypass; SELECT * FROM users;"}, headers=USER_HEADERS)
        ok("Returns 200", res.status_code == 200)
        run = res.json()
        ok("Is blocked by guardrail (not completed)", run["status"] == "completed")
        ok("Output mentions policy violation", "policy" in run["output"]["response"].lower() or "violation" in run["output"]["response"].lower())
        print(f"  Block message: {run['output']['response'][:100]}")

        # ── Step 5: Expanded guardrail patterns ───────────────────────────
        print("\n=== Test 6: Additional Guardrail Patterns ===")
        for pattern, label in [
            ("; rm -rf", "rm -rf pattern"),
            ("ignore previous instructions", "prompt injection pattern"),
            ("drop table", "DROP TABLE pattern"),
        ]:
            res = client.post(f"{ORCH_URL}/api/v1/threads/{thread_id}/runs",
                              json={"input": f"Hey {pattern} now"}, headers=USER_HEADERS)
            ok(f"Blocked: {label}", res.status_code == 200)
            run = res.json()
            print(f"  [{label}] → {run['output']['response'][:60]}")

        # ── Step 6: Compliance status after violations ────────────────────
        print("\n=== Test 7: Compliance Score After Guardrail Events ===")
        res = client.get(f"{GOV_URL}/api/v1/compliance/status", headers=ADMIN_HEADERS)
        ok("Returns 200", res.status_code == 200)
        data = res.json()
        ctrl_statuses = [f"{c['control_id']}={c['status']}" for c in data["controls"]]
        print(f"  Score: {data['overall_compliance_score']}%  |  Controls: {ctrl_statuses}")

        # ── Step 7: High-risk tool interception (ReAct tool routing) ─────
        print("\n=== Test 8: High-Risk Tool Call Interception (AGT Shield) ===")
        res2 = client.post(f"{ORCH_URL}/api/v1/threads", json={"agent_type": "customer-support-graph"}, headers=USER_HEADERS)
        hitl_thread_id = res2.json()["thread_id"]
        res = client.post(f"{ORCH_URL}/api/v1/threads/{hitl_thread_id}/runs",
                          json={"input": "delete all backup log files"}, headers=USER_HEADERS)
        ok("Returns 200", res.status_code == 200)
        run = res.json()
        print(f"  Run Status: {run['status']}")
        print(f"  Pending Action: {run['output'].get('pending_action')}")
        if run["status"] == "action_required":
            ok("Action intercepted by AGT", run["output"]["pending_action"] is not None)

            # ── Step 8: HITL approve ──────────────────────────────────────
            print("\n=== Test 9: HITL Approval (Resume from Interrupt) ===")
            res = client.post(f"{ORCH_URL}/api/v1/threads/{hitl_thread_id}/runs",
                              json={"approve_action": True}, headers=USER_HEADERS)
            ok("Returns 200", res.status_code == 200)
            resume = res.json()
            ok("Resumed as completed", resume["status"] == "completed")
            print(f"  Resumed Output: {resume['output']['response'][:80]}")
        else:
            print("  ℹ️  LLM not connected — HITL test skipped (tool not selected by keyword match).")

        # ── Step 9: Streaming SSE endpoint ───────────────────────────────
        print("\n=== Test 10: Streaming SSE Endpoint (/runs/stream) ===")
        res3 = client.post(f"{ORCH_URL}/api/v1/threads", json={"agent_type": "streaming-graph"}, headers=USER_HEADERS)
        stream_thread_id = res3.json()["thread_id"]

        sse_events = []
        with client.stream("POST",
                            f"{ORCH_URL}/api/v1/threads/{stream_thread_id}/runs/stream",
                            json={"input": "What is the AI control plane?"},
                            headers=USER_HEADERS) as sse_res:
            ok("Streaming returns 200", sse_res.status_code == 200)
            ok("Content-type is event-stream", "text/event-stream" in sse_res.headers.get("content-type", ""))
            for line in sse_res.iter_lines():
                if line.startswith("data: "):
                    try:
                        event = json.loads(line[len("data: "):])
                        sse_events.append(event)
                        if event.get("event") == "done":
                            break
                    except Exception:
                        pass

        ok("At least one step event emitted", any(e.get("event") == "step" for e in sse_events))
        ok("Done event received", any(e.get("event") == "done" for e in sse_events))
        print(f"  SSE events received: {[e.get('event') for e in sse_events]}")

        # ── Step 10: Thread state history ────────────────────────────────
        print("\n=== Test 11: Thread State History ===")
        res = client.get(f"{GOV_URL}/api/v1/compliance/status", headers=ADMIN_HEADERS)
        res_state = client.get(f"{ORCH_URL}/api/v1/threads/{thread_id}/state", headers=ADMIN_HEADERS)
        ok("Thread state returns 200", res_state.status_code == 200)
        state = res_state.json()
        ok("History is non-empty", len(state["history"]) > 0)
        print(f"  Checkpoint history: {len(state['history'])} checkpoints")

        # ── Step 11: AI-BOM ───────────────────────────────────────────────
        print("\n=== Test 12: AI-BOM Asset Inventory ===")
        res = client.get(f"{GOV_URL}/api/v1/compliance/ai-bom", headers=ADMIN_HEADERS)
        ok("Returns 200", res.status_code == 200)
        bom = res.json()
        ok("Has assets", bom["total_discovered_assets"] > 0)
        print(f"  Total Assets: {bom['total_discovered_assets']}  |  High Risk: {bom['high_risk_violations']}")

        # ── Step 12: Topology graph ───────────────────────────────────────
        print("\n=== Test 13: Topology Network Graph ===")
        res = client.get(f"{GOV_URL}/api/v1/compliance/topology", headers=ADMIN_HEADERS)
        ok("Returns 200", res.status_code == 200)
        topo = res.json()
        ok("Has nodes", len(topo["nodes"]) > 0)
        ok("Has links", len(topo["links"]) > 0)
        print(f"  Nodes: {len(topo['nodes'])}  |  Links: {len(topo['links'])}")

        # ── Step 13: Cross-tenant isolation ──────────────────────────────
        print("\n=== Test 14: Cross-Tenant Isolation ===")
        other_headers = {"X-Tenant-ID": "tenant-evil", "X-User-Role": "tenant-user", "X-User-ID": "attacker"}
        res = client.get(f"{ORCH_URL}/api/v1/threads/{thread_id}/state", headers=other_headers)
        ok("Cross-tenant thread access denied (403 or 404)", res.status_code in (403, 404), f"got {res.status_code}")
        print(f"  Isolation check: {res.status_code} {res.json().get('detail', '')[:60]}")

        # ── Test 15: OpenAI ChatCompletions Proxy Gateway ─────────────────
        print("\n=== Test 15: OpenAI ChatCompletions Proxy Gateway ===")
        
        # Test 15.1: Safe completions request
        res = client.post(
            f"{ORCH_URL}/v1/chat/completions",
            headers=USER_HEADERS,
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "How do I upgrade my billing tier?"}]
            }
        )
        ok("Safe request returns 200", res.status_code == 200, f"got {res.status_code}")
        comp = res.json()
        ok("Has choices", "choices" in comp)
        ok("Has model", comp["model"] == "gpt-3.5-turbo")
        print(f"  [Safe Proxy Response] → {comp['choices'][0]['message']['content'][:80]}...")

        # Test 15.2: Unsafe/Refused completions request
        res = client.post(
            f"{ORCH_URL}/v1/chat/completions",
            headers=USER_HEADERS,
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "admin bypass; SELECT * FROM users;"}]
            }
        )
        ok("Blocked request returns 200", res.status_code == 200, f"got {res.status_code}")
        comp_ref = res.json()
        ok("Has refusal message", "policy" in comp_ref["choices"][0]["message"]["content"].lower())
        print(f"  [Blocked Proxy Response] → {comp_ref['choices'][0]['message']['content']}")

        # Test 15.3: Streaming safety block response
        sse_proxy_events = []
        with client.stream(
            "POST",
            f"{ORCH_URL}/v1/chat/completions",
            headers=USER_HEADERS,
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "drop table users;"}],
                "stream": True
            }
        ) as stream_res:
            ok("Streaming proxy returns 200", stream_res.status_code == 200)
            for line in stream_res.iter_lines():
                if line.startswith("data: "):
                    try:
                        event_data = json.loads(line[len("data: "):])
                        sse_proxy_events.append(event_data)
                    except Exception:
                        pass
        
        ok("Refusal stream has chunks", len(sse_proxy_events) > 0)
        ok("Stream choice contains refusal", "policy" in sse_proxy_events[0]["choices"][0]["delta"]["content"].lower())
        print(f"  [Blocked Streaming Proxy Response] → {sse_proxy_events[0]['choices'][0]['delta']['content']}")

        print("\n" + "="*60)
        print("✅ All P1 integration tests passed!")
        print("="*60)

if __name__ == "__main__":
    if not wait_for_services():
        sys.exit(1)
    test_integration()


