import random
import uuid
import json
from locust import HttpUser, task, between, events

# Simulate 3 different tenants to test data isolation and Row-Level Security
TENANTS = ["tenant-alpha", "tenant-beta", "tenant-gamma"]

class MultiTenantAgentUser(HttpUser):
    # Wait 1-3 seconds between tasks
    wait_time = between(1, 3)

    def on_start(self):
        """
        Executed when a simulated user starts.
        We assign them a permanent tenant ID for their session to ensure
        all their requests are consistently scoped.
        """
        self.tenant_id = random.choice(TENANTS)
        self.user_id = f"user-{uuid.uuid4().hex[:8]}"
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id,
            "X-User-Role": "tenant-user"
        }
        self.active_thread_ids = []

    @task(3)
    def create_thread(self):
        """Create a new agent thread under the user's tenant."""
        payload = {
            "agent_type": "react-agent",
            "metadata": {"load_test": True}
        }
        
        with self.client.post(
            "/api/v1/threads",
            json=payload,
            headers=self.headers,
            name="Create Thread",
            catch_response=True
        ) as response:
            if response.status_code == 201:
                try:
                    data = response.json()
                    self.active_thread_ids.append(data.get("thread_id"))
                    response.success()
                except json.JSONDecodeError:
                    response.failure("Failed to decode JSON response")
            else:
                response.failure(f"Failed to create thread: {response.status_code} {response.text}")

    @task(5)
    def run_agent(self):
        """Run an agent task on an existing thread."""
        if not self.active_thread_ids:
            return  # No threads yet
            
        thread_id = random.choice(self.active_thread_ids)
        payload = {
            "prompt": "Can you analyze the recent financial reports for anomalies?"
        }
        
        with self.client.post(
            f"/api/v1/threads/{thread_id}/runs",
            json=payload,
            headers=self.headers,
            name="Run Agent Task",
            catch_response=True
        ) as response:
            if response.status_code in (200, 202):
                response.success()
            else:
                response.failure(f"Run failed on {thread_id}: {response.status_code} {response.text}")

    @task(1)
    def list_threads(self):
        """List threads to verify tenant isolation (should only see own tenant's threads)."""
        with self.client.get(
            "/api/v1/threads",
            headers=self.headers,
            name="List Threads",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to list threads: {response.status_code}")

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("Starting multi-tenant isolation load test...")
    print("Targeting Agent Orchestrator with simulated traffic for 3 tenants.")
