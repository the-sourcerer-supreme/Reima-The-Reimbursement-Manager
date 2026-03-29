from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Company(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(120), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    email_verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_verified_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('ADMIN', 'MANAGER', 'EMPLOYEE', 'FINANCE', 'DIRECTOR')", name="ck_app_user_role"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_app_user_status"),
        CheckConstraint("email_verified IN (0, 1)", name="ck_app_user_email_verified"),
    )

    company = relationship("Company")


class ApprovalFlow(Base):
    __tablename__ = "approval_flow"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalStep(Base):
    __tablename__ = "approval_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("approval_flow.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_mandatory: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("flow_id", "step_order", name="uq_approval_step_flow_step_order"),
        CheckConstraint("approver_role IN ('MANAGER', 'FINANCE', 'DIRECTOR')", name="ck_approval_step_role"),
        CheckConstraint("is_mandatory IN (0, 1)", name="ck_approval_step_is_mandatory"),
    )


class ApprovalRule(Base):
    __tablename__ = "approval_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("approval_flow.id", ondelete="CASCADE"), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold_percentage: Mapped[float | None] = mapped_column(Numeric(5, 2))
    specific_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))

    __table_args__ = (
        CheckConstraint("type IN ('PERCENTAGE', 'SPECIFIC', 'HYBRID')", name="ck_approval_rule_type"),
    )


class Expense(Base):
    __tablename__ = "expense"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    converted_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False)
    expense_date: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    receipt_name: Mapped[str | None] = mapped_column(String(255))
    receipt_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_expense_status"),
    )


class ExpenseApproval(Base):
    __tablename__ = "expense_approval"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expense.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_mandatory: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action_date: Mapped[str | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("expense_id", "approver_id", "step_order", name="uq_expense_approval_step"),
        CheckConstraint("approver_role IN ('MANAGER', 'FINANCE', 'DIRECTOR')", name="ck_expense_approval_role"),
        CheckConstraint("is_mandatory IN (0, 1)", name="ck_expense_approval_is_mandatory"),
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_expense_approval_status"),
    )


class UserSession(Base):
    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)


class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("is_read IN (0, 1)", name="ck_notification_is_read"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(120), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)


Index("idx_user_company_role", AppUser.company_id, AppUser.role)
Index("idx_expense_company_user", Expense.company_id, Expense.user_id)
Index("idx_approval_expense_step", ExpenseApproval.expense_id, ExpenseApproval.step_order)
Index("idx_notification_user", Notification.user_id, Notification.created_at)
Index("idx_audit_company", AuditLog.company_id, AuditLog.created_at)
Index("idx_email_verification_user", EmailVerificationToken.user_id, EmailVerificationToken.expires_at)
Index("idx_password_reset_user", PasswordResetToken.user_id, PasswordResetToken.expires_at)
