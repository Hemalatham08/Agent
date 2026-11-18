from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend.agent.services.ai_model_manager import (
    ProviderInfo,
    ProviderUnavailableError,
    RuntimeAiModelManager,
)

AI_SWITCH_TOKEN_ENV = "AI_SWITCH_TOKEN"

_bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/ai/models", tags=["ai-models"])


class AiModelInfo(BaseModel):
    provider: str
    model: str
    base_url: str
    available: bool
    active: bool
    reason: str | None = None


class AiModelsResponse(BaseModel):
    providers: list[AiModelInfo]
    active: AiModelInfo


class SwitchModelRequest(BaseModel):
    provider: str


class SwitchModelResponse(AiModelInfo):
    previous_provider: str | None = None


def require_ai_switch_authorization(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> None:
    """Authorize model switching with the configured administrator token.

    This repository does not yet contain a full authentication system, so the
    switch endpoint is protected by a bearer token configured through
    ``AI_SWITCH_TOKEN``. When no token is configured, switching is disabled
    rather than exposed without authentication.
    """
    expected = os.getenv(AI_SWITCH_TOKEN_ENV, "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "AI model switching is disabled because no administrator token "
                "is configured. Set AI_SWITCH_TOKEN on the backend and "
                "VITE_AI_SWITCH_TOKEN on the frontend."
            ),
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to switch AI models.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required to switch AI models.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid administrator token.",
        )


def _get_manager(request: Request) -> RuntimeAiModelManager:
    manager = getattr(request.app.state, "ai_model_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI model manager is not available.",
        )
    return manager


def _to_info(info: ProviderInfo) -> AiModelInfo:
    return AiModelInfo(**info.as_dict())


@router.get("", response_model=AiModelsResponse)
def list_ai_models(request: Request) -> AiModelsResponse:
    """List supported providers, availability, and the active provider."""
    manager = _get_manager(request)
    providers = [_to_info(info) for info in manager.list_providers()]
    active = next((info for info in providers if info.active), None)
    if active is None:
        active = _to_info(manager.active_descriptor())
    return AiModelsResponse(providers=providers, active=active)


@router.get("/active", response_model=AiModelInfo)
def get_active_ai_model(request: Request) -> AiModelInfo:
    """Return the currently active provider, model, and availability."""
    return _to_info(_get_manager(request).active_descriptor())


@router.post(
    "/switch",
    response_model=SwitchModelResponse,
    dependencies=[Depends(require_ai_switch_authorization)],
)
def switch_ai_model(
    payload: SwitchModelRequest,
    request: Request,
) -> SwitchModelResponse:
    """Switch the runtime provider after validating the target."""
    manager = _get_manager(request)
    previous = manager.active_provider
    try:
        info = manager.switch(payload.provider)
    except ProviderUnavailableError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        ) from err
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except RuntimeError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(err),
        ) from err

    return SwitchModelResponse(
        **info.as_dict(),
        previous_provider=previous,
    )


def register_ai_model_routes(app: FastAPI) -> None:
    """Attach the AI model routes directly to the application.

    FastAPI 0.162 stores routers included with ``include_router`` as a lazy
    ``_IncludedRouter`` entry. Existing diagnostics enumerate ``app.routes``
    and expect every entry to expose ``path``, so the concrete ``APIRoute``
    objects are appended instead. Their paths already contain the router
    prefix and their dependencies are attached at route level.
    """
    app.router.routes.extend(router.routes)


__all__ = [
    "AI_SWITCH_TOKEN_ENV",
    "AiModelInfo",
    "AiModelsResponse",
    "SwitchModelRequest",
    "SwitchModelResponse",
    "register_ai_model_routes",
    "require_ai_switch_authorization",
    "router",
]
