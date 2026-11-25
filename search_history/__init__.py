"""iFive ERP conversation history module.

This package is self-contained: it stores conversation history in
``search_history/history.db`` and never reads or writes the ERP database.

Core entry points:

* :class:`search_history.repository.ConversationRepository` - persistence
* :class:`search_history.service.ConversationService` - lifecycle logic
* :func:`search_history.app.create_app` - standalone FastAPI application
"""

from .app import create_app
from .errors import (
    AssistantPayloadError,
    HistoryError,
    HistoryValidationError,
    InvalidMessageRoleError,
    InvalidPayloadError,
    SessionNotFoundError,
)
from .repository import ConversationRepository
from .service import (
    AnswerGenerator,
    ConversationService,
    MockAnswerGenerator,
)

__version__ = "1.0.0"

__all__ = [
    "AnswerGenerator",
    "AssistantPayloadError",
    "ConversationRepository",
    "ConversationService",
    "HistoryError",
    "HistoryValidationError",
    "InvalidMessageRoleError",
    "InvalidPayloadError",
    "MockAnswerGenerator",
    "SessionNotFoundError",
    "create_app",
    "__version__",
]
