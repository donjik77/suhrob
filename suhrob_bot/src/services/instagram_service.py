import logging

from src.services.ai_service import chat_with_client
from src.db.session import AsyncSessionFactory


async def process_instagram_message(
    message: str,
    user_id: int,
    company_id: int = 1
):

    try:
        logging.info(
            f"Instagram AI start user={user_id}"
        )

        async with AsyncSessionFactory() as session:

            answer = await chat_with_client(
                user_message=message,
                conversation_history=[],
                client_profile={},
                company_id=company_id,
                session=session,
                property_id=None,
            )

        logging.info(
            f"Instagram AI answer generated"
        )

        return answer


    except Exception as exc:

        logging.exception(
            "Instagram AI error"
        )

        return "Произошла ошибка. Попробуйте ещё раз."
