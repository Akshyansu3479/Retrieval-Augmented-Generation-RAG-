"""Persist user feedback on assistant messages."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.database.models import Feedback, Message
from app.schemas.chat import FeedbackRequest, FeedbackResponse


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, request: FeedbackRequest) -> FeedbackResponse:
        message = await self.session.get(Message, request.message_id)
        if message is None:
            raise NotFoundError(
                f"Message '{request.message_id}' not found",
                details={"message_id": str(request.message_id)},
            )
        if request.rating not in {"thumbs_up", "thumbs_down"}:
            raise ValidationError("rating must be thumbs_up or thumbs_down")

        feedback = Feedback(
            message_id=request.message_id,
            rating=request.rating,
            comment=request.comment,
            meta={},
        )
        self.session.add(feedback)
        await self.session.commit()
        await self.session.refresh(feedback)
        return FeedbackResponse.model_validate(feedback)
