from datetime import datetime
from decimal import Decimal
from typing import Optional, List
import enum

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint,
    Index, func, JSON,
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
    draft = "draft"


class FileType(str, enum.Enum):
    photo = "photo"
    video = "video"


class SubscriptionType(str, enum.Enum):
    base = "base"
    instagram = "instagram"


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
    balance = "balance"


class PaymentSource(str, enum.Enum):
    balance = "balance"
    manual_proof = "manual_proof"


class TransactionType(str, enum.Enum):
    topup = "topup"
    subscription_charge = "subscription_charge"
    instagram_charge = "instagram_charge"
    refund = "refund"


class TransactionStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class ScheduledPostStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    published = "published"
    failed = "failed"


class PostPlatform(str, enum.Enum):
    telegram = "telegram"
    instagram = "instagram"


class PurchaseTimeline(str, enum.Enum):
    urgent = "urgent"
    months_1_3 = "1-3months"
    months_3_6 = "3-6months"
    just_looking = "just_looking"


class ClientPaymentMethod(str, enum.Enum):
    cash = "cash"
    mortgage = "mortgage"
    installment = "installment"


class LeadStatus(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    showing_scheduled = "showing_scheduled"
    negotiation = "negotiation"
    closed_won = "closed_won"
    closed_lost = "closed_lost"


class NotificationType(str, enum.Enum):
    payment_reminder_7days = "payment_reminder_7days"
    payment_reminder_3days = "payment_reminder_3days"
    payment_due = "payment_due"
    blocked = "blocked"
    payment_received = "payment_received"
    follow_up_3d = "follow_up_3d"
    follow_up_7d = "follow_up_7d"
    follow_up_14d = "follow_up_14d"
    new_property_alert = "new_property_alert"
    hot_lead = "hot_lead"


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    bot_token: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    bot_username: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    bot_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    telegram_channel_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    instagram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    instagram_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[List["User"]] = relationship("User", back_populates="company")
    properties: Mapped[List["Property"]] = relationship("Property", back_populates="company")
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="company")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    language: Mapped[str] = mapped_column(String(5), default="uz")
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
    balance: Mapped[Optional["UserBalance"]] = relationship("UserBalance", back_populates="user", uselist=False)
    client_profile: Mapped[Optional["ClientProfile"]] = relationship("ClientProfile", back_populates="user", uselist=False)
    conversations: Mapped[List["ClientConversation"]] = relationship("ClientConversation", back_populates="user")
    alerts: Mapped[List["ClientAlert"]] = relationship("ClientAlert", back_populates="user")
    balance_transactions: Mapped[List["BalanceTransaction"]] = relationship("BalanceTransaction", back_populates="user")
    confirmed_subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="confirmed_by_user", foreign_keys="Subscription.confirmed_by"
    )
    assigned_leads: Mapped[List["LeadAssignment"]] = relationship(
        "LeadAssignment", back_populates="agent", foreign_keys="LeadAssignment.agent_user_id"
    )
    client_leads: Mapped[List["LeadAssignment"]] = relationship(
        "LeadAssignment", back_populates="client", foreign_keys="LeadAssignment.client_user_id"
    )

    __table_args__ = (
        Index("ix_users_telegram_user_id", "telegram_user_id"),
        Index(
            "ix_users_telegram_company_active",
            "telegram_user_id",
            "company_id",
            unique=True,
            postgresql_where=(company_id.is_not(None) & (telegram_user_id != 0)),
        ),
        Index(
            "ix_users_telegram_global_active",
            "telegram_user_id",
            unique=True,
            postgresql_where=(company_id.is_(None) & (telegram_user_id != 0)),
        ),
        Index("ix_users_company_role", "company_id", "role"),
    )


class UserBalance(Base):
    __tablename__ = "user_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    balance_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    balance_uzs: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="balance")


class BalanceTransaction(Base):
    __tablename__ = "balance_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    amount_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    amount_uzs: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    payment_method: Mapped[Optional[PaymentMethod]] = mapped_column(Enum(PaymentMethod), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    related_subscription_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(Enum(TransactionStatus), default=TransactionStatus.pending)
    payment_proof_file_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="balance_transactions")
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", foreign_keys=[related_subscription_id])

    __table_args__ = (
        Index("ix_balance_transactions_user_created", "user_id", "created_at"),
    )


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), nullable=False)
    agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custom_text_entities_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    custom_text_source_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    custom_text_source_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    custom_text_source_has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    location_district: Mapped[str] = mapped_column(String(100), nullable=False)
    location_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location_lat: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    location_lng: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    floor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_floors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    area_sqm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    property_type: Mapped[PropertyType] = mapped_column(Enum(PropertyType), nullable=False)
    features: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    status: Mapped[PropertyStatus] = mapped_column(Enum(PropertyStatus), default=PropertyStatus.active)
    telegram_post_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    instagram_post_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    views_count: Mapped[int] = mapped_column(Integer, default=0)
    contacts_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company: Mapped["Company"] = relationship("Company", back_populates="properties")
    agent: Mapped["User"] = relationship("User", back_populates="properties")
    media: Mapped[List["PropertyMedia"]] = relationship(
        "PropertyMedia", back_populates="property", cascade="all, delete-orphan",
        order_by="PropertyMedia.order_index",
    )
    favorites: Mapped[List["ClientFavorite"]] = relationship("ClientFavorite", back_populates="property")
    scheduled_posts: Mapped[List["ScheduledPost"]] = relationship("ScheduledPost", back_populates="property")
    lead_assignments: Mapped[List["LeadAssignment"]] = relationship("LeadAssignment", back_populates="property")

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
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_quality_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 1), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    property: Mapped["Property"] = relationship("Property", back_populates="media")


class ClientProfile(Base):
    """Lead qualification data extracted by AI from client conversations."""
    __tablename__ = "client_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    budget_min_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    budget_max_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    preferred_districts: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    preferred_rooms: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    property_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    purchase_timeline: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    qualification_score: Mapped[int] = mapped_column(Integer, default=0)
    qualified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0)
    unsubscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="client_profile")


class ClientConversation(Base):
    """History of AI dialog messages per client."""
    __tablename__ = "client_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    property_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("properties.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user / assistant
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="conversations")

    __table_args__ = (
        Index("ix_client_conversations_user_created", "user_id", "created_at"),
    )


class ClientAlert(Base):
    """Client subscriptions to new property notifications."""
    __tablename__ = "client_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    location_district: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price_max_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    rooms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    property_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="alerts")


class LeadAssignment(Base):
    """CRM: client lead assigned to an agent."""
    __tablename__ = "lead_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    property_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("properties.id"), nullable=True)
    status: Mapped[LeadStatus] = mapped_column(Enum(LeadStatus), default=LeadStatus.new)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    client: Mapped["User"] = relationship("User", back_populates="client_leads", foreign_keys=[client_user_id])
    agent: Mapped["User"] = relationship("User", back_populates="assigned_leads", foreign_keys=[agent_user_id])
    property: Mapped[Optional["Property"]] = relationship("Property", back_populates="lead_assignments")


class SearchRequest(Base):
    __tablename__ = "search_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    location_district: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price_min_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    price_max_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    rooms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    property_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
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
    platform: Mapped[PostPlatform] = mapped_column(Enum(PostPlatform), default=PostPlatform.telegram)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ScheduledPostStatus] = mapped_column(Enum(ScheduledPostStatus), default=ScheduledPostStatus.pending)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    property: Mapped["Property"] = relationship("Property", back_populates="scheduled_posts")

    __table_args__ = (
        Index("ix_scheduled_posts_status_at", "status", "scheduled_at"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), nullable=False)
    subscription_type: Mapped[SubscriptionType] = mapped_column(Enum(SubscriptionType), default=SubscriptionType.base)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    price_uzs: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus), default=SubscriptionStatus.pending_payment)
    payment_method: Mapped[Optional[PaymentMethod]] = mapped_column(Enum(PaymentMethod), nullable=True)
    payment_source: Mapped[Optional[PaymentSource]] = mapped_column(Enum(PaymentSource), nullable=True)
    payment_proof_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    auto_renewed: Mapped[bool] = mapped_column(Boolean, default=False)
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
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    related_subscription_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    related_property_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("properties.id"), nullable=True)
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="notifications")
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", back_populates="notifications")


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
