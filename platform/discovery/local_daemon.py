#!/usr/bin/env python3
# File: platform/discovery/local_daemon.py
"""
Manifold Endpoint Discovery Daemon
Periodically scans local developer workstation for shadow AI runners (e.g., local Ollama)
and reports discovered models/assets to the central Governance Engine.
"""

import time
import sys
import os
import argparse
import urllib.request
import json

# Default Settings
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_GOV_URL = "http://localhost:8000"
DEFAULT_TENANT = "tenant-acme"
DEFAULT_INTERVAL = 10  # seconds

def check_local_ollama(url: str):
    """Hits the local Ollama instance tags API to fetch running models."""
    try:
        req = urllib.request.Request(f"{url}/api/tags")
        with urllib.request.urlopen(req, timeout=3.0) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return data.get("models", [])
    except Exception:
        # Silently skip if Ollama is not running locally
        pass
    return []

def report_asset(gov_url: str, tenant: str, asset_id: str, asset_name: str, location: str):
    """Sends a discovery record to the Governance Engine."""
    evidence_payload = {
        "control_id": "SOC2-CC-6.1",
        "source_component": "local-endpoint-daemon",
        "event_type": "asset_discovered",
        "severity": "info",
        "payload": {
            "asset_id": asset_id,
            "name": asset_name,
            "type": "llm_model_runtime",
            "location": location,
            "status": "active"
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Tenant-ID": tenant,
        "X-User-Role": "system-workload",
        "X-User-ID": "local-daemon-daemon"
    }
    
    try:
        body = json.dumps(evidence_payload).encode("utf-8")
        req = urllib.request.Request(
            f"{gov_url}/api/v1/evidence",
            data=body,
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=3.0) as res:
            if res.status == 201:
                print(f"[Discovery] Successfully reported local asset: {asset_name} ({asset_id})")
                return True
    except Exception as e:
        print(f"[Discovery Warning] Failed to report asset to Governance Engine: {e}")
    return False

def main():
    parser = argparse.ArgumentParser(description="Manifold Endpoint Discovery Daemon")
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL), help="Local Ollama base URL")
    parser.add_argument("--gov-url", default=os.getenv("GOV_URL", DEFAULT_GOV_URL), help="Central Governance Engine base URL")
    parser.add_argument("--tenant", default=os.getenv("TENANT_ID", DEFAULT_TENANT), help="Company tenant identifier")
    parser.add_argument("--interval", type=int, default=int(os.getenv("INTERVAL", DEFAULT_INTERVAL)), help="Poll interval in seconds")
    parser.add_argument("--one-shot", action="store_true", help="Run once and exit immediately")
    args = parser.parse_args()

    print(f"=====================================================")
    print(f"🚀 Manifold Local Discovery Daemon Started")
    print(f"   Target Tenant:   {args.tenant}")
    print(f"   Governance URL:  {args.gov_url}")
    print(f"   Ollama URL:      {args.ollama_url}")
    print(f"   Interval:        {args.interval}s")
    print(f"=====================================================")

    reported_assets = set()

    while True:
        models = check_local_ollama(args.ollama_url)
        if models:
            print(f"[Discovery] Found {len(models)} local running models.")
            for model in models:
                model_name = model.get("name")
                if not model_name:
                    continue
                
                # Sanitize asset ID
                clean_name = model_name.replace(":", "_").replace(".", "_").replace("-", "_")
                asset_id = f"ast_local_model_{clean_name}"
                
                if asset_id not in reported_assets:
                    # Report to server
                    success = report_asset(
                        gov_url=args.gov_url,
                        tenant=args.tenant,
                        asset_id=asset_id,
                        asset_name=f"Local LLM: {model_name} (Ollama)",
                        location=f"Local Workstation ({args.ollama_url})"
                    )
                    if success:
                        reported_assets.add(asset_id)
        else:
            # If Ollama is offline or has no models, log/skip
            pass

        if args.one_shot:
            print("[Discovery] One-shot execution complete. Exiting.")
            sys.exit(0)

        time.sleep(args.interval)

if __name__ == "__main__":
    main()
