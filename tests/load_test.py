import os
import asyncio
import httpx
import time
import random
import uuid

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:30081/api/v1")
TENANTS = ["manifold-finance", "stark-industries", "wayne-enterprises"]
NUM_REQUESTS_PER_TENANT = 20

async def make_request(client: httpx.AsyncClient, tenant_id: str, req_id: int):
    # 1. Create a thread
    thread_resp = await client.post(
        f"{ORCHESTRATOR_URL}/threads",
        json={"agent_type": "compliance-agent"},
        headers={"X-Tenant-ID": tenant_id, "X-User-Role": "tenant-admin", "X-User-ID": f"user-{req_id}"}
    )
    if thread_resp.status_code != 200:
        return {"tenant": tenant_id, "req_id": req_id, "status": "failed_thread", "code": thread_resp.status_code}
    
    thread_id = thread_resp.json()["thread_id"]

    # 2. Run a query
    run_resp = await client.post(
        f"{ORCHESTRATOR_URL}/threads/{thread_id}/runs",
        json={"input": "What are our compliance controls?"},
        headers={"X-Tenant-ID": tenant_id, "X-User-Role": "tenant-admin", "X-User-ID": f"user-{req_id}"},
        timeout=30.0
    )
    
    if run_resp.status_code != 200:
        return {"tenant": tenant_id, "req_id": req_id, "status": "failed_run", "code": run_resp.status_code}
    
    return {"tenant": tenant_id, "req_id": req_id, "status": "success", "time": time.time()}

async def main():
    print(f"🚀 Starting Multi-Tenant Load Test...")
    print(f"Target: {ORCHESTRATOR_URL}")
    print(f"Tenants: {TENANTS}")
    print(f"Requests per tenant: {NUM_REQUESTS_PER_TENANT}")
    print("-" * 50)

    start_time = time.time()
    
    async with httpx.AsyncClient() as client:
        tasks = []
        for tenant in TENANTS:
            for i in range(NUM_REQUESTS_PER_TENANT):
                tasks.append(make_request(client, tenant, i))
                
        # Run all requests concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

    end_time = time.time()
    
    # Aggregate results
    success_count = 0
    failure_count = 0
    tenant_success = {t: 0 for t in TENANTS}
    
    for r in results:
        if isinstance(r, dict) and r.get("status") == "success":
            success_count += 1
            tenant_success[r["tenant"]] += 1
        else:
            failure_count += 1
            print(f"Error: {r}")

    print("-" * 50)
    print(f"📊 Load Test Results")
    print(f"Total Time: {end_time - start_time:.2f} seconds")
    print(f"Total Requests: {len(tasks)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failure_count}")
    print("Success by Tenant:")
    for t, count in tenant_success.items():
        print(f"  - {t}: {count}/{NUM_REQUESTS_PER_TENANT}")

if __name__ == "__main__":
    asyncio.run(main())
