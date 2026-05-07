from datetime import datetime
from decimal import Decimal
from typing import Optional, List
import enum

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint,
    Index, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    client = "client"
    agent = "agent"
    director = "director"
    developer = "developer"


class PropertyType(str, enum.Enum):
    apartment = "apartment"
    house = "house"
    commercial = "commercial"


class PropertyStatus(str, enum.Enum):
    active = "active"
    sold = "sold"
    hidden = "hidden"


class FileType(str, enum.Enum):
    photo = "photo"
    video = "video"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    pending_payment = "pending_payment"
    expired = "expired"
    blocked = "blocked"


class PaymentMethod(str, enum.Enum):
    click = "click"
    humo = "humo"
    uzcard = "uzcard"
    crypto = "crypto"


class ScheduledPostStatus(str, enum.Enum):
    pending = "pending"
    published = "published"
    failed = "failed"


class NotificationType(str, enum.Enum):
    payment_reminder_3days = "payment_reminder_3days"
    payment_due = "payment_due"
    blocked = "blocked"
    payment_received = "payment_received"


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_channel_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    users: Mapped[List["User"]] = relationship("User", back_populates="company")
    properties: Mapped[List["Property"]] = relationship("Property", back_populates="company")
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="company")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="uz")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.client)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("companies.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    company: Mapped[Optional["Company"]] = relationship("Company", back_populates="users")
    properties: Mapped[List["Property"]] = relationship("Property", back_populates="agent")
    favorites: Mapped[List["ClientFavorite"]] = relationship("ClientFavorite", back_populates="user")
    search_requests: Mapped[List["SearchRequest"]] = relationship("SearchRequest", back_populates="user")
    notifications: Mapped[List["NotificationLog"]] = relationship("NotificationLog", back_populates="user")
    confirmed_subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="confirmed_by_user", foreign_keys="Subscription.confirmed_by"
    )

    __table_args__ = (
        Index("ix_users_telegram_user_id", "telegram_user_id", unique=True),
    )


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), nullable=False)
    agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    location_district: Mapped[str] = mapped_column(String(255), nullable=False)
    location_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    floor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_floors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    area_sqm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    property_type: Mapped[PropertyType] = mapped_column(Enum(PropertyType), nullable=False)
    status: Mapped[PropertyStatus] = mapped_column(Enum(PropertyStatus), default=PropertyStatus.active)
    telegram_post_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company: Mapped["Company"] = relationship("Company", back_populates="properties")
    agent: Mapped["User"] = relationship("User", back_populates="properties")
    media: Mapped[List["PropertyMedia"]] = relationship(
        "PropertyMedia", back_populates="property", cascade="all, delete-orphan", order_by="PropertyMedia.order_index"
    )
    favorites: Mapped[List["ClientFavorite"]] = relationship("ClientFavorite", back_populates="property")
    scheduled_posts: Mapped[List["ScheduledPost"]] = relationship("ScheduledPost", back_populates="property")

    __table_args__ = (
        Index("ix_properties_company_status", "company_id", "status"),
        Index("ix_properties_search", "location_district", "price_usd", "rooms"),
    )


class PropertyMedia(Base):
    __tablename__ = "property_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    file_id: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[FileType] = mapped_column(Enum(FileType), nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    property: Mapped["Property"] = relationship("Property", back_populates="media")


class SearchRequest(Base):
    __tablename__ = "search_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    location_district: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    price_min_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    price_max_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    rooms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="search_requests")


class ClientFavorite(Base):
    __tablename__ = "client_favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    property_id: Mapped[int] = mapped_column(Integer, ForeignKey("properties.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="favorites")
    property: Mapped["Property"] = relationship("Property", back_populates="favorites")

    __table_args__ = (
        UniqueConstraint("user_id", "property_id", name="uq_favorite_user_property"),
    )


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(Integer, ForeignKey("properties.id"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ScheduledPostStatus] = mapped_column(Enum(ScheduledPostStatus), default=ScheduledPostStatus.pending)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    property: Mapped["Property"] = relationship("Property", back_populates="scheduled_posts")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("49.00"))
    price_uzs: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus), default=SubscriptionStatus.pending_payment)
    payment_method: Mapped[Optional[PaymentMethod]] = mapped_column(Enum(PaymentMethod), nullable=True)
    payment_proof_file_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship("Company", back_populates="subscriptions")
    confirmed_by_user: Mapped[Optional["User"]] = relationship(
        "User", back_populates="confirmed_subscriptions", foreign_keys=[confirmed_by]
    )
    notifications: Mapped[List["NotificationLog"]] = relationship("NotificationLog", back_populates="subscription")

    __table_args__ = (
        Index("ix_subscriptions_company_status", "company_id", "status"),
    )


class NotificationLog(Base):
    __tablename__ = "notifications_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    notification_type: Mapped[NotificationType] = mapped_column(Enum(NotificationType), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    related_subscription_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("subscriptions.id"), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="notifications")
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", back_populates="notifications")


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
