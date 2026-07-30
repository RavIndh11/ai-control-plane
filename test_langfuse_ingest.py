"""
test_langfuse_ingest.py — Diagnostic script to test Langfuse trace ingestion directly.
"""
import os
import sys

# Read keys from environment or .env file
pk = os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-3637633c-0c03-4652-b446-50ae29012030").strip("\"' \t\n\r")
sk = os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-bd3b6ac1-70e6-4bef-badd-d870be9602eb").strip("\"' \t\n\r")
host = os.getenv("LANGFUSE_HOST", "http://localhost:30083").strip("\"' \t\n\r")

print("=============================================")
print("🧪 Langfuse Ingestion Diagnostic Test")
print("=============================================")
print(f"  Public Key: {pk[:10]}...")
print(f"  Host:       {host}")
print("=============================================")

try:
    from langfuse import Langfuse
except ImportError:
    print("❌ langfuse library not installed. Install with: pip install langfuse")
    sys.exit(1)

try:
    langfuse = Langfuse(
        public_key=pk,
        secret_key=sk,
        host=host
    )
    print("⏳ Creating test trace...")
    trace = langfuse.trace(
        name="diagnostic_test_trace",
        user_id="test_user",
        metadata={"test": "manual_ingestion_check"}
    )
    trace.generation(
        name="test_llm_generation",
        model="mistral-cpu",
        input={"prompt": "Ping Langfuse API"},
        output={"response": "Pong! Trace ingestion verified."}
    )
    
    print("⏳ Flushing trace to server...")
    langfuse.flush()
    print("✅ Trace flushed to Langfuse successfully!")
    print("👉 Check your Langfuse UI under Traces / Generations to confirm.")

except Exception as exc:
    print(f"❌ Langfuse Ingestion Failed: {exc}")
