import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, JSON, Text, UniqueConstraint, CheckConstraint, Index
from .db import Base


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


class Role(Base):
    __tablename__ = "roles"
    name = Column(String(16), primary_key=True)


class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=uid)
    username = Column(String(64), nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    role = Column(String(16), ForeignKey("roles.name"), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class ManagerParent(Base):
    __tablename__ = "manager_parents"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    parent_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    __table_args__ = (CheckConstraint("user_id != parent_id", name="manager_parent_not_self"),)


class SNMPVisibilityDefault(Base):
    __tablename__ = 'snmp_visibility_default'
    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False)
    __table_args__ = (CheckConstraint('id = 1'),)


class UserSNMPVisibility(Base):
    __tablename__ = 'user_snmp_visibility'
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    enabled = Column(Boolean, nullable=False)


class DeviceLoginProfile(Base):
    __tablename__ = 'device_login_profiles'
    id = Column(String(36), primary_key=True, default=uid)
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    encrypted_config = Column(Text, nullable=False)
    __table_args__ = (UniqueConstraint('user_id', 'name'),)


class DeviceLoginProfileAccess(Base):
    __tablename__ = 'device_login_profile_access'
    profile_id = Column(String(36), ForeignKey('device_login_profiles.id', ondelete='CASCADE'), primary_key=True)
    manager_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True, index=True)


class UserSectionAccess(Base):
    __tablename__ = "user_section_access"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sections = Column(JSON, nullable=False)


class UserSectionEdits(Base):
    __tablename__ = "user_section_edits"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sections = Column(JSON, nullable=False)


class UserSectionDeletes(Base):
    __tablename__ = "user_section_deletes"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sections = Column(JSON, nullable=False)


class AccessRole(Base):
    __tablename__ = "access_roles"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(64), nullable=False, unique=True)
    sections = Column(JSON, nullable=False)
    editable_sections = Column(JSON, nullable=False)
    deletable_sections = Column(JSON, nullable=False)


class BuiltinAccessRole(Base):
    __tablename__ = "builtin_access_roles"
    id = Column(String(16), primary_key=True)
    name = Column(String(64), nullable=False)
    sections = Column(JSON, nullable=False)
    editable_sections = Column(JSON, nullable=False)
    deletable_sections = Column(JSON, nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)


class UserAccessRole(Base):
    __tablename__ = "user_access_roles"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    access_role_id = Column(String(36), ForeignKey("access_roles.id", ondelete="RESTRICT"), nullable=False)


class ManagerRole(Base):
    __tablename__ = "manager_roles"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(64), nullable=False, unique=True)
    access_role_id = Column(String(36), ForeignKey("access_roles.id", ondelete="RESTRICT"), nullable=False)


class UserManagerRole(Base):
    __tablename__ = "user_manager_roles"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(String(36), ForeignKey("manager_roles.id", ondelete="RESTRICT"), nullable=False)


class Initialization(Base):
    __tablename__ = "initialization"
    id = Column(Integer, primary_key=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    __table_args__ = (CheckConstraint("id = 1"),)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id = Column(String(36), primary_key=True, default=uid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    digest = Column(String(64), primary_key=True)
    session_id = Column(String(36), ForeignKey("login_sessions.id"), nullable=False)
    consumed = Column(Boolean, default=False, nullable=False)


class Tower(Base):
    __tablename__ = "towers"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(120), nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)
    location = Column(String(250), default="")
    management_ip = Column(String(45))
    manager_id = Column(String(36), ForeignKey("users.id"))


class Place(Base):
    __tablename__ = "places"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(120), nullable=False, unique=True)


class TowerPlace(Base):
    __tablename__ = "tower_places"
    tower_id = Column(String(36), ForeignKey("towers.id", ondelete="CASCADE"), primary_key=True)
    place_id = Column(String(36), ForeignKey("places.id", ondelete="RESTRICT"), nullable=False, index=True)


class ManagerPlace(Base):
    __tablename__ = "manager_places"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    place_id = Column(String(36), ForeignKey("places.id", ondelete="CASCADE"), primary_key=True)


class TowerAPISettings(Base):
    __tablename__ = "tower_api_settings"
    tower_id = Column(String(36), ForeignKey("towers.id", ondelete="CASCADE"), primary_key=True)
    encrypted_credentials = Column(Text, nullable=False)


class Sector(Base):
    __tablename__ = "sectors"
    id = Column(String(36), primary_key=True, default=uid)
    tower_id = Column(String(36), ForeignKey("towers.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    ssid = Column(String(120), default="")
    frequency_mhz = Column(Integer)
    channel_width_mhz = Column(Integer)
    model = Column(String(120), default="")
    ip_address = Column(String(45))


class SNMPProfile(Base):
    __tablename__ = "snmp_profiles"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(120), nullable=False)
    encrypted_credentials = Column(Text, nullable=False)


class Device(Base):
    __tablename__ = "devices"
    id = Column(String(36), primary_key=True, default=uid)
    tower_id = Column(String(36), ForeignKey("towers.id", ondelete="RESTRICT"), nullable=False, index=True)
    sector_id = Column(String(36), ForeignKey("sectors.id", ondelete="RESTRICT"))
    name = Column(String(120), nullable=False)
    ip_address = Column(String(45), nullable=False, unique=True)
    vendor = Column(String(30), nullable=False, default="generic")
    model = Column(String(120), default="")
    snmp_profile_id = Column(String(36), ForeignKey("snmp_profiles.id", ondelete="RESTRICT"))
    poll_interval = Column(Integer, default=60, nullable=False)
    retries = Column(Integer, default=2, nullable=False)
    failure_threshold = Column(Integer, default=3, nullable=False)
    cpu_threshold = Column(Float, default=90, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    status = Column(String(16), default="unknown", nullable=False)
    failures = Column(Integer, default=0, nullable=False)
    last_poll = Column(DateTime(timezone=True))
    last_success = Column(DateTime(timezone=True))


class DeviceAssignment(Base):
    __tablename__ = "device_assignments"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    device_id = Column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)


class Interface(Base):
    __tablename__ = "interfaces"
    id = Column(String(36), primary_key=True, default=uid)
    device_id = Column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    if_index = Column(Integer, nullable=False)
    name = Column(String(250), nullable=False)
    speed_mbps = Column(Float)
    oper_status = Column(Integer)
    __table_args__ = (UniqueConstraint("device_id", "if_index"),)


class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    collected_at = Column(DateTime(timezone=True), default=now, nullable=False)
    values = Column(JSON, nullable=False)
    __table_args__ = (Index("ix_metrics_device_time", "device_id", "collected_at"),)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(String(36), primary_key=True, default=uid)
    device_id = Column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(40), nullable=False)
    severity = Column(String(16), nullable=False)
    message = Column(String(500), nullable=False)
    opened_at = Column(DateTime(timezone=True), default=now, nullable=False)
    resolved_at = Column(DateTime(timezone=True))
    acknowledged_by = Column(String(36), ForeignKey("users.id"))


class NetworkLink(Base):
    __tablename__ = "network_links"
    id = Column(String(36), primary_key=True, default=uid)
    source_id = Column(String(36), ForeignKey("towers.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(String(36), ForeignKey("towers.id", ondelete="CASCADE"), nullable=False)
    evidence = Column(String(500), nullable=False)
    verified_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    verified_at = Column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (CheckConstraint("source_id <> target_id"), UniqueConstraint("source_id", "target_id"))


class UpdateHistory(Base):
    __tablename__ = "update_history"
    id = Column(String(36), primary_key=True, default=uid)
    version = Column(String(40), nullable=False)
    status = Column(String(30), nullable=False)
    detail = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id"))
    action = Column(String(120), nullable=False)
    target = Column(String(120))
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)


def audit(db, user, action, target=None):
    db.add(AuditLog(user_id=user.id if user else None, action=action, target=target))


class SAS4Connection(Base):
    __tablename__ = "sas4_connection"
    id = Column(Integer, primary_key=True)
    server_url = Column(String(500), nullable=False)
    username = Column(String(128), nullable=False)
    encrypted_password = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (CheckConstraint("id = 1"),)


class SAS4UserConnection(Base):
    __tablename__ = "sas4_user_connections"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    username = Column(String(128), nullable=False)
    encrypted_password = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now, nullable=False)


class CustomerProbeSettings(Base):
    __tablename__ = "customer_probe_settings"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    encrypted_settings = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now, nullable=False)


class PaymentGateway(Base):
    __tablename__ = 'payment_gateways'
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    provider = Column(String(16), primary_key=True)
    environment = Column(String(16), nullable=False, default='sandbox')
    encrypted_credentials = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now, nullable=False)


class RechargePayment(Base):
    __tablename__ = 'recharge_payments'
    __table_args__ = (UniqueConstraint('provider', 'environment', 'provider_id', name='uq_recharge_provider_payment'),)
    id = Column(String(32), primary_key=True)
    user_id = Column(String(36), ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    sas4_user_id = Column(Integer, nullable=False)
    sas4_username = Column(String(128), nullable=False)
    provider = Column(String(16), nullable=False)
    environment = Column(String(16), nullable=False)
    encrypted_credentials = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, index=True)
    amount = Column(String(40), nullable=False)
    currency = Column(String(8), nullable=False)
    provider_id = Column(String(128), nullable=True)
    quote = Column(JSON, nullable=False)
    checkout = Column(JSON, nullable=True)
    detail = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now, nullable=False)
