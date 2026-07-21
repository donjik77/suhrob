import logging

from sqlalchemy import select, desc

from src.services.ai_service import chat_with_client
from src.db.session import AsyncSessionFactory
from src.db.models import (
    User,
    ClientConversation,
)


async def get_or_create_instagram_user(
    session,
    instagram_id: int,
    company_id: int
):

    result = await session.execute(
        select(User).where(
            User.telegram_user_id == instagram_id,
            User.company_id == company_id
        )
    )

    user = result.scalar_one_or_none()


    if not user:

        user = User(
            telegram_user_id=instagram_id,
            username=f"instagram_{instagram_id}",
            role="client",
            company_id=company_id,
        )

        session.add(user)

        await session.commit()

        await session.refresh(user)


    return user



async def get_history(
    session,
    user_id: int
):

    result = await session.execute(
        select(ClientConversation)
        .where(
            ClientConversation.user_id == user_id
        )
        .order_by(
            desc(ClientConversation.created_at)
        )
        .limit(20)
    )


    messages = result.scalars().all()

    messages.reverse()


    history = []


    for msg in messages:

        history.append(
            {
                "role": msg.role,
                "content": msg.message
            }
        )


    return history



async def save_message(
    session,
    user_id: int,
    role: str,
    text: str
):

    msg = ClientConversation(
        user_id=user_id,
        role=role,
        message=text,
    )


    session.add(msg)

    await session.commit()



async def process_instagram_message(
    message: str,
    user_id: int,
    company_id: int = 1
):

    try:

        async with AsyncSessionFactory() as session:


            # Получаем или создаём Instagram клиента
            user = await get_or_create_instagram_user(
                session,
                user_id,
                company_id
            )


            # Получаем историю сообщений
            history = await get_history(
                session,
                user.id
            )


            # Пока профиль пустой
            # Добавим позже через отдельный запрос
            profile = {}



            # сохраняем сообщение клиента
            await save_message(
                session,
                user.id,
                "user",
                message
            )



            # отправляем в AI
            answer = await chat_with_client(
                user_message=message,
                conversation_history=history,
                client_profile=profile,
                company_id=company_id,
                session=session,
                property_id=None,
            )



            # сохраняем ответ AI
            await save_message(
                session,
                user.id,
                "assistant",
                answer
            )


            return answer



    except Exception as e:

        logging.exception(
            "Instagram AI error"
        )


        return (
            "Xatolik yuz berdi. "
            "Iltimos qaytadan yozing."
        )
