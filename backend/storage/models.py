"""Cloud schema. SQLite uses schema_translate_map for hermetic development tests."""
from sqlalchemy import (MetaData, Table, Column, String, Text, Integer, Float, Boolean,
                        LargeBinary, JSON, ForeignKey, ForeignKeyConstraint, UniqueConstraint, Index, CheckConstraint)

metadata = MetaData()
SCHEMAS = ("auth", "content", "learning", "runtime", "admin")

users = Table("users", metadata,
    Column("id", String(64), primary_key=True), Column("username", Text, nullable=False),
    Column("username_norm", Text, nullable=False, unique=True), Column("email", Text, unique=True),
    Column("password_hash", Text, nullable=False), Column("role", String(16), nullable=False),
    Column("api_key_encrypted", LargeBinary), Column("created_at", Float, nullable=False),
    Column("disabled", Integer, nullable=False, server_default="0"),
    CheckConstraint("role IN ('owner','user')", name="valid_user_role"),
    CheckConstraint("role <> 'owner' OR (id = 'studyadmin' AND username_norm = 'studyadmin')", name="reserved_owner"), schema="auth")
Index("single_owner", users.c.role, unique=True,
      postgresql_where=users.c.role == "owner", sqlite_where=users.c.role == "owner")
login_sessions = Table("login_sessions", metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", ForeignKey("auth.users.id"), nullable=False, index=True),
    Column("created_at", Float, nullable=False), Column("expires_at", Float, nullable=False), schema="auth")
email_challenges = Table("email_challenges", metadata,
    Column("email", Text, primary_key=True), Column("code_hash", Text, nullable=False),
    Column("expires_at", Float, nullable=False), Column("sent_at", Float, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("consumed", Integer, nullable=False, server_default="0"), schema="auth")
auth_rate_events = Table("auth_rate_events", metadata,
    Column("bucket", Text, nullable=False, index=True), Column("created_at", Float, nullable=False), schema="auth")
native_sessions = Table("native_sessions", metadata,
    Column("id", String(36), primary_key=True), Column("family_id", String(36), nullable=False, index=True),
    Column("user_id", ForeignKey("auth.users.id"), nullable=False, index=True),
    Column("device_name", String(128), nullable=False),
    Column("access_hash", String(64), nullable=False, unique=True),
    Column("refresh_hash", String(64), nullable=False, unique=True),
    Column("access_expires_at", Float, nullable=False), Column("refresh_expires_at", Float, nullable=False),
    Column("created_at", Float, nullable=False), Column("rotated", Boolean, nullable=False, default=False),
    Column("revoked", Boolean, nullable=False, default=False), schema="auth")

questions = Table("questions", metadata,
    Column("id", String(36), primary_key=True), Column("owner_user_id", ForeignKey("auth.users.id"), index=True),
    Column("content", Text, nullable=False), Column("data", JSON, nullable=False),
    Column("revision", Integer, nullable=False, default=1), Column("active", Boolean, nullable=False, default=True),
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False), schema="content")
question_versions = Table("question_versions", metadata,
    Column("question_id", ForeignKey("content.questions.id"), primary_key=True),
    Column("revision", Integer, primary_key=True), Column("data", JSON, nullable=False),
    Column("created_at", Float, nullable=False), schema="content")
assets = Table("assets", metadata,
    Column("id", String(36), primary_key=True), Column("owner_user_id", ForeignKey("auth.users.id"), index=True),
    Column("storage_key", Text, nullable=False, unique=True), Column("sha256", String(64), nullable=False),
    Column("filename", Text, nullable=False), Column("media_type", Text, nullable=False),
    Column("size", Integer, nullable=False), Column("created_at", Float, nullable=False), schema="content")
patterns = Table("patterns", metadata,
    Column("id", String(36), primary_key=True), Column("data", JSON, nullable=False),
    Column("active", Boolean, nullable=False, default=True), Column("revision", Integer, nullable=False, default=1), schema="content")

question_access = Table("question_access", metadata,
    Column("user_id", ForeignKey("auth.users.id"), primary_key=True),
    Column("question_id", ForeignKey("content.questions.id"), primary_key=True), schema="learning")
attempts = Table("attempts", metadata,
    Column("id", String(36), primary_key=True), Column("user_id", ForeignKey("auth.users.id"), nullable=False),
    Column("question_id", String(36), nullable=False), Column("question_revision", Integer, nullable=False),
    Column("request_id", String(128), nullable=False), Column("student_answer", Text, nullable=False),
    Column("result", JSON, nullable=False), Column("asset_ids", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
    ForeignKeyConstraint(["user_id", "question_id"], ["learning.question_access.user_id", "learning.question_access.question_id"]),
    ForeignKeyConstraint(["question_id", "question_revision"], ["content.question_versions.question_id", "content.question_versions.revision"]),
    UniqueConstraint("user_id", "request_id"), schema="learning")
teaching_sessions = Table("teaching_sessions", metadata,
    Column("session_id", String(36), primary_key=True), Column("user_id", ForeignKey("auth.users.id"), nullable=False),
    Column("state_json", JSON, nullable=False), Column("revision", Integer, nullable=False, default=0),
    Column("pending_job", String(36)), Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False), UniqueConstraint("user_id", "session_id"), schema="learning")
learning_records = Table("records", metadata,
    Column("id", String(36), primary_key=True), Column("user_id", ForeignKey("auth.users.id"), nullable=False, index=True),
    Column("kind", String(100), nullable=False), Column("data", JSON, nullable=False),
    Column("question_id", String(36)), Column("created_at", Float, nullable=False),
    ForeignKeyConstraint(["user_id", "question_id"], ["learning.question_access.user_id", "learning.question_access.question_id"]), schema="learning")
jobs = Table("jobs", metadata,
    Column("id", String(36), primary_key=True), Column("user_id", ForeignKey("auth.users.id"), nullable=False, index=True),
    Column("request_id", String(128), nullable=False), Column("kind", String(32), nullable=False),
    Column("fingerprint", String(64), nullable=False), Column("args", JSON, nullable=False),
    Column("status", String(20), nullable=False), Column("stage", Text, nullable=False),
    Column("progress", Integer, nullable=False, default=0), Column("result", JSON), Column("error", JSON),
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False),
    UniqueConstraint("user_id", "request_id"), schema="runtime")
aliases = Table("legacy_aliases", metadata,
    Column("user_id", ForeignKey("auth.users.id"), primary_key=True),
    Column("resource", String(100), primary_key=True), Column("legacy_id", Text, primary_key=True),
    Column("resource_id", String(36), nullable=False), schema="runtime")
admin_records = Table("records", metadata,
    Column("id", String(36), primary_key=True), Column("kind", String(100), nullable=False),
    Column("data", JSON, nullable=False), Column("created_at", Float, nullable=False), schema="admin")
migration_runs = Table("migration_runs", metadata,
    Column("id", String(36), primary_key=True), Column("manifest", JSON, nullable=False),
    Column("created_at", Float, nullable=False), schema="admin")
Index("records_owner_kind", learning_records.c.user_id, learning_records.c.kind)
Index("admin_records_kind", admin_records.c.kind)
