"""
main.py — Agent Orchestrator FastAPI application entry point. (Phase 1 refactor)

Responsibilities of this file (ONLY):
  - App instantiation and lifespan (DB init + LangGraph compilation)
  - Mounting API routers
  - Root health endpoint

All other logic lives in dedicated modules:
  auth/       — JWT verification, principal resolution
  db/         — SQLAlchemy models, session dependency
  agents/     — LangGraph state, nodes, graph definition
  api/        — Thread and run route handlers  (added in Phase 2)
"""
import os

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# OpenTelemetry setup (optional — gracefully disabled if not installed)
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    _provider = TracerProvider()
    _otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if _otlp_endpoint:
        _provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=_otlp_endpoint))
        )
    trace.set_tracer_provider(_provider)
    tracer = trace.get_tracer("agent-orchestrator")
    HAS_OTEL = True
except Exception:
    HAS_OTEL = False
    tracer = None

# Langfuse SDK initialisation (reads LANGFUSE_* env vars automatically)
try:
    from langfuse import Langfuse  # noqa: F401 — initialises the global instance
    HAS_LANGFUSE = True
except ImportError:
    HAS_LANGFUSE = False

from agents.graph import build_graph
from db.session import DATABASE_URL, engine
from db.models import Base

# Import the in-process route handlers (previously inline in the monolith).
# These are kept in this file during the Phase 1 transition. In Phase 2 they
# move into api/threads.py and api/runs.py routers.
from api.threads import router as threads_router
from api.runs    import router as runs_router
from api.rules   import router as rules_router


# ---------------------------------------------------------------------------
# Lifespan: initialise DB tables and compile LangGraph once at startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure all tables exist
    Base.metadata.create_all(bind=engine)
    print("[Lifespan] Database tables ensured.")

    # Compile LangGraph with the correct persistent checkpointer
    build_graph(DATABASE_URL)
    print("[Lifespan] LangGraph pipeline compiled.")

    yield  # application runs here

    print("[Lifespan] Shutting down Agent Orchestrator.")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Agent Orchestrator API",
    description=(
        "Multi-tenant AI agent orchestration service built on LangGraph. "
        "Provides guardrailed, audited, human-in-the-loop agent execution."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your dashboard origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(threads_router, prefix="/api/v1")
app.include_router(runs_router,    prefix="/api/v1")
app.include_router(rules_router,   prefix="/api/v1")


# ---------------------------------------------------------------------------
# Root / health
# ---------------------------------------------------------------------------
@app.get("/", tags=["health"])
def read_root():
    return {
        "service": "agent-orchestrator",
        "version": "2.0.0",
        "status":  "running",
        "otel":    HAS_OTEL,
        "langfuse": HAS_LANGFUSE,
    }


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
