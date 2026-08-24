import os
from typing import Any

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    _provider = TracerProvider()
    _otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if _otlp_endpoint:
        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint)))
    trace.set_tracer_provider(_provider)
    tracer = trace.get_tracer("governance-engine")
    HAS_OTEL = True
except Exception:
    HAS_OTEL = False
    tracer = None

try:
    from langfuse import observe
    HAS_LANGFUSE = True
except Exception:
    HAS_LANGFUSE = False
    def observe(name: str = ""):  # type: ignore
        def decorator(fn): return fn
        return decorator

class langfuse_context:  # type: ignore
    @staticmethod
    def update_current_observation(**_: Any) -> None: pass

DATABASE_URL        = os.getenv("DATABASE_URL", "sqlite:///./governance.db")
CERBOS_URL          = os.getenv("CERBOS_URL",   "http://localhost:3592")
KEYCLOAK_JWKS_URL   = os.getenv("KEYCLOAK_JWKS_URL",  "")
KEYCLOAK_AUDIENCE   = os.getenv("KEYCLOAK_AUDIENCE",  "ai-control-plane")
KEYCLOAK_ISSUER     = os.getenv("KEYCLOAK_ISSUER",    "")
MINIO_ENDPOINT      = os.getenv("MINIO_ENDPOINT",     "")
MINIO_ACCESS_KEY    = os.getenv("MINIO_ACCESS_KEY",   "minioadmin")
MINIO_SECRET_KEY    = os.getenv("MINIO_SECRET_KEY",   "minioadmin")
MINIO_BUCKET        = os.getenv("MINIO_BUCKET",       "manifold-evidence")
ALERT_WEBHOOK_URL   = os.getenv("ALERT_WEBHOOK_URL",  "")

_audit_secret_env = os.getenv("AUDIT_HMAC_SECRET")
if not _audit_secret_env:
    if not DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("AUDIT_HMAC_SECRET environment variable is required in production (non-sqlite) mode.")
    _audit_secret_env = "dev-secret-change-in-production"
AUDIT_HMAC_SECRET   = _audit_secret_env.encode()

CONTROLS_DB = {
    "SOC2-CC-6.1":    {"name": "Access Control Security",   "description": "Ensure authorized access to assets and models."},
    "GDPR-Art-32":    {"name": "Security of Processing",    "description": "Implement appropriate technical controls."},
    "EU-AI-Act-Art-9":{"name": "Risk Management System",    "description": "Establish compliance frameworks for AI workflows."},
}

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False
