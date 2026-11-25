"""Standalone application factory for the conversation history module.

Run independently with either::

    python -m search_history.app
    uvicorn search_history.app:app --port 8010

This app is intentionally isolated from the ERP backend.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from .repository import ConversationRepository
from .router import router
from .service import (
    AnswerGenerator,
    ConversationService,
    MockAnswerGenerator,
)


def create_app(
    answer_generator: AnswerGenerator | None = None,
    db_path: str | Path | None = None,
) -> FastAPI:
    """Build a FastAPI app wired to an isolated history database."""
    app = FastAPI(
        title="iFive ERP Conversation History",
        version="1.0.0",
    )

    repository = ConversationRepository(db_path)
    repository.initialize()

    app.state.conversation_service = ConversationService(
        repository=repository,
        answer_generator=answer_generator or MockAnswerGenerator(),
    )
    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8010)
