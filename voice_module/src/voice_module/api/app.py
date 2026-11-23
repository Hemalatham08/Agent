"""FastAPI application exposing the Stage 4 voice controls.

The controller is created lazily on the first voice endpoint call. Importing
this module and calling ``GET /health`` does not construct a controller, load
Kokoro or Whisper, or touch microphone hardware.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..control import VoiceControlError, VoiceController, VoiceState
from .schemas import (
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    ListenStopResponse,
    SpeakRequest,
    VoiceActionResponse,
    VoiceStatusResponse,
)

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"

_ERROR_STATUS_CODES = {
    "BUSY": 409,
    "INVALID_STATE": 409,
    "INVALID_TEXT": 400,
    "NO_MICROPHONE": 503,
    "START_FAILED": 500,
    "STOP_FAILED": 500,
    "SPEAK_FAILED": 500,
}


class _ControllerHolder:
    """Lazily create and share a single controller per application instance."""

    def __init__(self, factory: Callable[[], VoiceController]):
        self._factory = factory
        self._controller: Optional[VoiceController] = None
        self._lock = threading.Lock()

    def get(self) -> VoiceController:
        """Return the shared controller, creating it on first use."""
        if self._controller is None:
            with self._lock:
                if self._controller is None:
                    self._controller = self._factory()
        return self._controller


def get_controller(request: Request) -> VoiceController:
    """FastAPI dependency that returns the application's shared controller."""
    holder: _ControllerHolder = request.app.state.controller_holder
    return holder.get()


def _error_detail(error: Optional[VoiceControlError]) -> Optional[ErrorDetail]:
    if error is None:
        return None
    return ErrorDetail(
        code=error.code,
        message=error.message,
        details=error.details,
    )


def _raise_controller_error(controller: VoiceController) -> None:
    """Re-raise a controller-recorded error so the API can return structured JSON."""
    if controller.state is VoiceState.ERROR and controller.last_error is not None:
        raise controller.last_error


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(VoiceControlError)
    async def _handle_voice_control_error(
        request: Request,
        exc: VoiceControlError,
    ) -> JSONResponse:
        status_code = _ERROR_STATUS_CODES.get(exc.code, 500)
        if status_code >= 500:
            logger.error("Voice control failure [%s]: %s", exc.code, exc.message)
        body = ErrorResponse(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                details=exc.details,
            )
        )
        return JSONResponse(status_code=status_code, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        location = ".".join(
            str(part) for part in first.get("loc", ()) if part != "body"
        )
        message = str(first.get("msg", "Invalid request"))
        if location:
            message = f"{location}: {message}"
        body = ErrorResponse(
            error=ErrorDetail(code="VALIDATION_ERROR", message=message)
        )
        return JSONResponse(status_code=422, content=body.model_dump())

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled voice API exception")
        body = ErrorResponse(
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred",
            )
        )
        return JSONResponse(status_code=500, content=body.model_dump())


def _register_routes(app: FastAPI) -> None:
    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        """Report that the voice API is running without loading any models."""
        return HealthResponse()

    @app.get("/voice/status", response_model=VoiceStatusResponse, tags=["voice"])
    def voice_status(
        controller: VoiceController = Depends(get_controller),
    ) -> VoiceStatusResponse:
        """Return the current voice state, busy flag, and last error."""
        return VoiceStatusResponse(
            state=controller.state,
            busy=controller.is_busy,
            last_error=_error_detail(controller.last_error),
        )

    @app.post(
        "/voice/listen/start",
        response_model=VoiceActionResponse,
        tags=["voice"],
    )
    def start_listening(
        controller: VoiceController = Depends(get_controller),
    ) -> VoiceActionResponse:
        """Start microphone recording (no transcription)."""
        changed = controller.start_listening()
        return VoiceActionResponse(
            changed=bool(changed),
            state=controller.state,
            message="Listening started" if changed else "Already listening",
        )

    @app.post(
        "/voice/listen/stop",
        response_model=ListenStopResponse,
        tags=["voice"],
    )
    def stop_listening(
        controller: VoiceController = Depends(get_controller),
    ) -> ListenStopResponse:
        """Stop microphone recording and report whether audio was captured."""
        result = controller.stop_listening()
        _raise_controller_error(controller)
        captured = result is not None
        return ListenStopResponse(
            success=True,
            captured=captured,
            state=controller.state,
            message="Recording captured" if captured else "No active recording",
        )

    @app.post(
        "/voice/speak",
        response_model=VoiceActionResponse,
        tags=["voice"],
    )
    def start_speaking(
        payload: SpeakRequest,
        controller: VoiceController = Depends(get_controller),
    ) -> VoiceActionResponse:
        """Synthesize and start speaking the supplied non-empty text."""
        changed = controller.start_speaking(payload.text)
        return VoiceActionResponse(
            changed=bool(changed),
            state=controller.state,
            message="Speech started" if changed else "Already speaking",
        )

    @app.post(
        "/voice/speak/stop",
        response_model=VoiceActionResponse,
        tags=["voice"],
    )
    def stop_speaking(
        controller: VoiceController = Depends(get_controller),
    ) -> VoiceActionResponse:
        """Stop speech playback immediately."""
        changed = controller.stop_speaking()
        _raise_controller_error(controller)
        return VoiceActionResponse(
            changed=bool(changed),
            state=controller.state,
            message="Speech stopped" if changed else "No active speech",
        )

    @app.post("/voice/stop", response_model=VoiceActionResponse, tags=["voice"])
    def stop_all(
        controller: VoiceController = Depends(get_controller),
    ) -> VoiceActionResponse:
        """Stop listening and speech, then enter the STOPPED state."""
        controller.stop_all()
        return VoiceActionResponse(
            changed=True,
            state=controller.state,
            message="All voice activity stopped",
        )

    @app.post("/voice/reset", response_model=VoiceActionResponse, tags=["voice"])
    def reset(
        controller: VoiceController = Depends(get_controller),
    ) -> VoiceActionResponse:
        """Safely return the controller to IDLE."""
        controller.return_to_idle()
        return VoiceActionResponse(
            changed=True,
            state=controller.state,
            message="Controller reset to idle",
        )


def create_app(
    controller_factory: Optional[Callable[[], VoiceController]] = None,
) -> FastAPI:
    """Create a FastAPI app with a lazily-created, shared voice controller.

    Args:
        controller_factory: Optional factory for tests or dependency injection.
            Defaults to constructing a ``VoiceController`` on first use.
    """
    app = FastAPI(title="iFive Voice API", version=API_VERSION)
    app.state.controller_holder = _ControllerHolder(
        controller_factory or VoiceController
    )
    _register_exception_handlers(app)
    _register_routes(app)
    return app


app = create_app()
