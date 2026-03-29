CREATE TABLE IF NOT EXISTS company (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  country VARCHAR(120) NOT NULL,
  base_currency VARCHAR(3) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS app_user (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  manager_id INTEGER REFERENCES app_user(id) ON DELETE SET NULL,
  name VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  email_verified INTEGER NOT NULL DEFAULT 0 CHECK (email_verified IN (0, 1)),
  email_verified_at TIMESTAMPTZ,
  role VARCHAR(20) NOT NULL CHECK (role IN ('ADMIN', 'MANAGER', 'EMPLOYEE', 'FINANCE', 'DIRECTOR')),
  department VARCHAR(120) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_flow (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL UNIQUE REFERENCES company(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_step (
  id SERIAL PRIMARY KEY,
  flow_id INTEGER NOT NULL REFERENCES approval_flow(id) ON DELETE CASCADE,
  step_order INTEGER NOT NULL,
  approver_role VARCHAR(20) NOT NULL CHECK (approver_role IN ('MANAGER', 'FINANCE', 'DIRECTOR')),
  is_mandatory INTEGER NOT NULL DEFAULT 1 CHECK (is_mandatory IN (0, 1)),
  UNIQUE (flow_id, step_order)
);

CREATE TABLE IF NOT EXISTS approval_rule (
  id SERIAL PRIMARY KEY,
  flow_id INTEGER NOT NULL UNIQUE REFERENCES approval_flow(id) ON DELETE CASCADE,
  type VARCHAR(20) NOT NULL CHECK (type IN ('PERCENTAGE', 'SPECIFIC', 'HYBRID')),
  threshold_percentage NUMERIC(5, 2),
  specific_user_id INTEGER REFERENCES app_user(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS expense (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
  currency VARCHAR(3) NOT NULL,
  converted_amount NUMERIC(12, 2) NOT NULL,
  category VARCHAR(120) NOT NULL,
  description TEXT NOT NULL,
  vendor VARCHAR(255) NOT NULL,
  expense_date VARCHAR(20) NOT NULL,
  status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
  receipt_name VARCHAR(255),
  receipt_data TEXT,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS expense_approval (
  id SERIAL PRIMARY KEY,
  expense_id INTEGER NOT NULL REFERENCES expense(id) ON DELETE CASCADE,
  approver_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  step_order INTEGER NOT NULL,
  approver_role VARCHAR(20) NOT NULL CHECK (approver_role IN ('MANAGER', 'FINANCE', 'DIRECTOR')),
  is_mandatory INTEGER NOT NULL DEFAULT 1 CHECK (is_mandatory IN (0, 1)),
  status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
  comment TEXT NOT NULL DEFAULT '',
  action_date TIMESTAMPTZ,
  UNIQUE (expense_id, approver_id, step_order)
);

CREATE TABLE IF NOT EXISTS user_session (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  token_hash VARCHAR(255) NOT NULL UNIQUE,
  csrf_token VARCHAR(255) NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS email_verification_token (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  token_hash VARCHAR(255) NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS password_reset_token (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  token_hash VARCHAR(255) NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS notification (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  message TEXT NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
  actor_id INTEGER REFERENCES app_user(id) ON DELETE SET NULL,
  action VARCHAR(120) NOT NULL,
  target_type VARCHAR(120) NOT NULL,
  target_id INTEGER,
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_company_role ON app_user(company_id, role);
CREATE INDEX IF NOT EXISTS idx_expense_company_user ON expense(company_id, user_id);
CREATE INDEX IF NOT EXISTS idx_approval_expense_step ON expense_approval(expense_id, step_order);
CREATE INDEX IF NOT EXISTS idx_notification_user ON notification(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_company ON audit_log(company_id, created_at);
CREATE INDEX IF NOT EXISTS idx_email_verification_user ON email_verification_token(user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_token(user_id, expires_at);
