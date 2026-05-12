from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    BalanceTransaction,
    BotSetting,
    ClientAlert,
    ClientConversation,
    ClientFavorite,
    ClientProfile,
    LeadAssignment,
    NotificationLog,
    Property,
    PropertyMedia,
    ScheduledPost,
    SearchRequest,
    Subscription,
    User,
    UserBalance,
    UserRole,
)


class ProtectedUserDeleteError(ValueError):
    pass


async def delete_property_with_dependencies(
    session: AsyncSession,
    property_id: int,
    *,
    commit: bool = True,
) -> None:
    """Hard-delete a property after clearing tables that reference it."""
    await session.execute(
        delete(ClientFavorite).where(ClientFavorite.property_id == property_id)
    )
    await session.execute(
        delete(ScheduledPost).where(ScheduledPost.property_id == property_id)
    )
    await session.execute(
        update(LeadAssignment)
        .where(LeadAssignment.property_id == property_id)
        .values(property_id=None)
    )
    await session.execute(
        update(ClientConversation)
        .where(ClientConversation.property_id == property_id)
        .values(property_id=None)
    )
    await session.execute(
        update(NotificationLog)
        .where(NotificationLog.related_property_id == property_id)
        .values(related_property_id=None)
    )
    await session.execute(
        delete(PropertyMedia).where(PropertyMedia.property_id == property_id)
    )
    await session.execute(delete(Property).where(Property.id == property_id))

    if commit:
        await session.commit()


async def count_user_properties(session: AsyncSession, user_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(Property.id)).where(Property.agent_id == user_id)
        )
        or 0
    )


async def delete_user_with_dependencies(
    session: AsyncSession,
    user_id: int,
    *,
    delete_agent_properties: bool = False,
    commit: bool = True,
) -> None:
    """Hard-delete a client/agent and the dependent rows that block FK deletes."""
    user = await session.get(User, user_id)
    if not user:
        return
    if user.role in (UserRole.director, UserRole.developer):
        raise ProtectedUserDeleteError("director/developer users are protected")

    property_ids = list(
        (
            await session.execute(
                select(Property.id).where(Property.agent_id == user_id)
            )
        ).scalars()
    )
    if property_ids and not delete_agent_properties:
        raise ProtectedUserDeleteError("user still owns properties")

    for property_id in property_ids:
        await delete_property_with_dependencies(session, property_id, commit=False)

    await session.execute(
        delete(LeadAssignment).where(
            or_(
                LeadAssignment.client_user_id == user_id,
                LeadAssignment.agent_user_id == user_id,
            )
        )
    )
    await session.execute(
        delete(ClientFavorite).where(ClientFavorite.user_id == user_id)
    )
    await session.execute(
        delete(SearchRequest).where(SearchRequest.user_id == user_id)
    )
    await session.execute(delete(ClientAlert).where(ClientAlert.user_id == user_id))
    await session.execute(
        delete(ClientConversation).where(ClientConversation.user_id == user_id)
    )
    await session.execute(
        delete(ClientProfile).where(ClientProfile.user_id == user_id)
    )
    await session.execute(
        delete(NotificationLog).where(NotificationLog.user_id == user_id)
    )
    await session.execute(
        delete(BalanceTransaction).where(BalanceTransaction.user_id == user_id)
    )
    await session.execute(delete(UserBalance).where(UserBalance.user_id == user_id))
    await session.execute(
        update(Subscription)
        .where(Subscription.confirmed_by == user_id)
        .values(confirmed_by=None)
    )
    await session.execute(
        update(BotSetting).where(BotSetting.updated_by == user_id).values(updated_by=None)
    )
    await session.execute(delete(User).where(User.id == user_id))

    if commit:
        await session.commit()
