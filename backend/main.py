
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.services.agent_service import AgentService
from backend.tools.database import (
    get_all_products,
    get_product_by_id,
    get_inventory_status,
    get_low_stock_products,
    get_pending_sales_orders,
    get_pending_purchase_orders,
    get_dispatch_issues,
    get_quality_issues,
    get_unpaid_invoices,
    get_invoice_outstanding,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    platform: ErpToolPlatform | None = None
    agent_service: AgentService | None = None
    app.state.erp_tools = None
    app.state.erp_runner = None
    app.state.agent_service = None
    try:
        platform = ErpToolPlatform.from_env()
        agent_service = AgentService.from_platform(platform)
        app.state.erp_tools = platform
        app.state.erp_runner = platform.runner
        app.state.agent_service = agent_service
        yield
    finally:
        try:
            if agent_service is not None:
                agent_service.close()
        finally:
            try:
                if platform is not None:
                    platform.close()
            finally:
                app.state.erp_tools = None
                app.state.erp_runner = None
                app.state.agent_service = None


# Create the FastAPI application
app = FastAPI(
    title="iFive AI ERP Agent API",
    description="API for ABC Fasteners ERP demo system",
    version="1.0.0",
    lifespan=lifespan,
)


# Home endpoint
@app.get("/")
def home():
    return {
        "message": "Welcome to iFive AI ERP Agent API",
        "status": "running",
    }


# 1. Get all products
@app.get("/products")
def products():
    return get_all_products()


# 2. Search a product by ID
@app.get("/products/{product_id}")
def product(product_id: str):
    result = get_product_by_id(product_id)

    if result is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return result



# 3. Get inventory for a product
@app.get("/inventory/{product_id}")
def inventory(product_id: str):
    return get_inventory_status(product_id)


# 4. Get low-stock products
@app.get("/inventory/alerts/low-stock")
def low_stock():
    return get_low_stock_products()


# 5. Get pending sales orders
@app.get("/sales/pending")
def pending_sales():
    return get_pending_sales_orders()


# 6. Get pending purchase orders
@app.get("/purchase/pending")
def pending_purchase():
    return get_pending_purchase_orders()


# 7. Get dispatch issues
@app.get("/dispatch/issues")
def dispatch_issues():
    return get_dispatch_issues()


# 8. Get quality issues
@app.get("/quality/issues")
def quality_issues():
    return get_quality_issues()


# 9. Get unpaid invoices
@app.get("/accounting/unpaid")
def unpaid_invoices():
    return get_unpaid_invoices()


# 10. Get outstanding amount for a particular invoice
@app.get("/accounting/invoices/{invoice_id}")
def invoice_outstanding(invoice_id: str):
    result = get_invoice_outstanding(invoice_id)

    if result is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return result


# ---------------------------------------------------------------------------
# 11. AI Agent Chat Endpoints (Phase 3E)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str | None = None
    question: str | None = None
    session_id: str | None = None
    history: list[dict[str, Any]] | None = None


class ToolCallSummaryResponse(BaseModel):
    tool_name: str
    status: str
    duration_ms: float | None = None
    error: str | None = None


class ChatResponse(BaseModel):
    answer: str
    tool_calls: list[ToolCallSummaryResponse] = Field(default_factory=list)
    status: str
    model: str
    error: str | None = None


@app.post("/api/agent/chat", response_model=ChatResponse)
@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest, req: Request):
    text = (request.message or request.question or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Question or message must not be empty.")

    agent_service: AgentService | None = getattr(req.app.state, "agent_service", None)
    if agent_service is None:
        platform: ErpToolPlatform | None = getattr(req.app.state, "erp_tools", None)
        if platform is not None:
            agent_service = AgentService.from_platform(platform)
            req.app.state.agent_service = agent_service
        else:
            raise HTTPException(status_code=503, detail="Agent service is not available.")

    result = agent_service.answer_question(text, session_id=request.session_id)

    tool_summaries = [
        ToolCallSummaryResponse(
            tool_name=tc.tool_name,
            status=tc.status,
            duration_ms=tc.duration_ms,
            error=tc.error,
        )
        for tc in result.tool_calls
    ]

    model_name = getattr(agent_service.client.config, "model", "llama3.2")

    return ChatResponse(
        answer=result.answer,
        tool_calls=tool_summaries,
        status=result.status,
        model=model_name,
        error=result.error,
    )
