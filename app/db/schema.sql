-- Smart Trybe Compliance — schema (idempotent enum + table creation)

DO $$
BEGIN
    CREATE TYPE compliance_status AS ENUM (
        'NOT_STARTED',
        'PENDING',
        'COMPLETED',
        'EXPIRED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE compliance_type AS ENUM (
        'CAC',
        'FIRS',
        'ITF',
        'NSITF',
        'PENCOM',
        'GROUP_LIFE_INSURANCE',
        'ACCOUNT_AUDITING',
        'SCUML',
        'BPP_FEDERAL',
        'BPP_STATE'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE compliance_mode AS ENUM (
        'NEW',
        'RENEWAL',
        'PROCESS',
        'REGISTRATION'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE user_role AS ENUM (
        'CLIENT',
        'AGENT',
        'ADMIN'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TYPE compliance_status ADD VALUE IF NOT EXISTS 'IN_REVIEW';
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE oauth_provider AS ENUM (
        'google'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    full_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    role user_role NOT NULL DEFAULT 'CLIENT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

CREATE TABLE IF NOT EXISTS user_oauth_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    provider oauth_provider NOT NULL,
    provider_user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_oauth_accounts_user
    ON user_oauth_accounts (user_id);

CREATE INDEX IF NOT EXISTS idx_users_email_lower ON users (LOWER(email));

CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    rc_number TEXT,
    tin TEXT,
    address TEXT,
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compliance_registry (
    company_id UUID NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    compliance_type compliance_type NOT NULL,
    status compliance_status NOT NULL DEFAULT 'NOT_STARTED',
    expiry_date DATE,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (company_id, compliance_type)
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    compliance_type compliance_type NOT NULL,
    doc_type TEXT NOT NULL,
    s3_url TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_company_compliance
    ON documents (company_id, compliance_type);

CREATE INDEX IF NOT EXISTS idx_documents_company_compliance_doctype
    ON documents (company_id, compliance_type, doc_type);

CREATE TABLE IF NOT EXISTS compliance_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    compliance_type compliance_type NOT NULL,
    mode compliance_mode NOT NULL,
    status compliance_status NOT NULL DEFAULT 'NOT_STARTED',
    current_step INT NOT NULL DEFAULT 0,
    total_steps INT NOT NULL DEFAULT 1,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, compliance_type, mode)
);

CREATE INDEX IF NOT EXISTS idx_workflows_company_type_mode
    ON compliance_workflows (company_id, compliance_type, mode);

CREATE TABLE IF NOT EXISTS workflow_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    compliance_type compliance_type NOT NULL,
    mode compliance_mode NOT NULL,
    total_steps INT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (compliance_type, mode)
);

CREATE TABLE IF NOT EXISTS workflow_template_steps (
    template_id UUID NOT NULL REFERENCES workflow_templates (id) ON DELETE CASCADE,
    step_number INT NOT NULL,
    step_name TEXT NOT NULL,
    PRIMARY KEY (template_id, step_number)
);

CREATE INDEX IF NOT EXISTS idx_template_steps_template
    ON workflow_template_steps (template_id);

CREATE TABLE IF NOT EXISTS compliance_step_progress (
    workflow_id UUID NOT NULL REFERENCES compliance_workflows (id) ON DELETE CASCADE,
    step_number INT NOT NULL,
    step_name TEXT NOT NULL,
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMPTZ,
    step_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workflow_id, step_number)
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role user_role NOT NULL DEFAULT 'CLIENT';
UPDATE users SET role = 'ADMIN'::user_role, is_admin = TRUE WHERE is_admin = TRUE AND role = 'CLIENT'::user_role;

CREATE TABLE IF NOT EXISTS company_agent_assignments (
    company_id UUID NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    agent_user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    assigned_by UUID REFERENCES users (id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (company_id, agent_user_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_assignments_agent
    ON company_agent_assignments (agent_user_id);
ALTER TABLE compliance_step_progress ADD COLUMN IF NOT EXISTS step_data JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE compliance_step_progress ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS compliance_outputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL REFERENCES compliance_workflows (id) ON DELETE CASCADE,
    output_type TEXT NOT NULL,
    output_value TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outputs_workflow
    ON compliance_outputs (workflow_id);

DO $$
BEGIN
    CREATE TYPE company_registration_type AS ENUM (
        'EXISTING',
        'NEW'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE cart_status AS ENUM (
        'OPEN',
        'CHECKOUT',
        'PAID',
        'CANCELLED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE payment_status AS ENUM (
        'PENDING',
        'COMPLETED',
        'FAILED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE companies ADD COLUMN IF NOT EXISTS registration_type company_registration_type;

CREATE TABLE IF NOT EXISTS compliance_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    display_order INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compliance_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    compliance_type compliance_type NOT NULL,
    mode compliance_mode NOT NULL,
    category_id UUID NOT NULL REFERENCES compliance_categories (id) ON DELETE RESTRICT,
    display_name TEXT NOT NULL,
    description TEXT,
    icon_key TEXT,
    base_price_ngn NUMERIC(12, 2) NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (compliance_type, mode)
);

CREATE INDEX IF NOT EXISTS idx_catalog_category
    ON compliance_catalog (category_id);

CREATE TABLE IF NOT EXISTS compliance_carts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    status cart_status NOT NULL DEFAULT 'OPEN',
    shared_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE compliance_carts ADD COLUMN IF NOT EXISTS shared_data JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_cart_per_company
    ON compliance_carts (company_id)
    WHERE status = 'OPEN';

CREATE INDEX IF NOT EXISTS idx_carts_company
    ON compliance_carts (company_id);

CREATE TABLE IF NOT EXISTS compliance_cart_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id UUID NOT NULL REFERENCES compliance_carts (id) ON DELETE CASCADE,
    compliance_type compliance_type NOT NULL,
    mode compliance_mode NOT NULL,
    unit_price_ngn NUMERIC(12, 2) NOT NULL DEFAULT 0,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (cart_id, compliance_type, mode)
);

CREATE INDEX IF NOT EXISTS idx_cart_items_cart
    ON compliance_cart_items (cart_id);

CREATE TABLE IF NOT EXISTS compliance_payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id UUID NOT NULL REFERENCES compliance_carts (id) ON DELETE CASCADE,
    payment_reference TEXT,
    total_amount_ngn NUMERIC(12, 2) NOT NULL DEFAULT 0,
    status payment_status NOT NULL DEFAULT 'PENDING',
    breakdown JSONB NOT NULL DEFAULT '[]'::jsonb,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_cart
    ON compliance_payments (cart_id);

ALTER TABLE compliance_payments ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'manual';
ALTER TABLE compliance_payments ADD COLUMN IF NOT EXISTS provider_reference TEXT;
ALTER TABLE compliance_payments ADD COLUMN IF NOT EXISTS authorization_url TEXT;
ALTER TABLE compliance_payments ADD COLUMN IF NOT EXISTS provider_payload JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_reference
    ON compliance_payments (provider_reference)
    WHERE provider_reference IS NOT NULL;

CREATE TABLE IF NOT EXISTS compliance_entitlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    compliance_type compliance_type NOT NULL,
    mode compliance_mode NOT NULL,
    payment_id UUID NOT NULL REFERENCES compliance_payments (id) ON DELETE CASCADE,
    amount_ngn NUMERIC(12, 2) NOT NULL DEFAULT 0,
    paid_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at TIMESTAMPTZ,
    workflow_id UUID REFERENCES compliance_workflows (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_entitlements_company_type_mode
    ON compliance_entitlements (company_id, compliance_type, mode)
    WHERE consumed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_entitlements_payment
    ON compliance_entitlements (payment_id);

CREATE INDEX IF NOT EXISTS idx_registry_expiry
    ON compliance_registry (expiry_date)
    WHERE expiry_date IS NOT NULL;

CREATE TABLE IF NOT EXISTS company_data (
    company_id UUID NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    data_key TEXT NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (company_id, data_key)
);

CREATE INDEX IF NOT EXISTS idx_company_data_company
    ON company_data (company_id);

-- Compliance audit remediation: rejection/query workflow states (PI-1)
DO $$
BEGIN
    ALTER TYPE compliance_status ADD VALUE IF NOT EXISTS 'REJECTED';
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TYPE compliance_status ADD VALUE IF NOT EXISTS 'INFO_REQUIRED';
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE compliance_workflows ADD COLUMN IF NOT EXISTS status_reason TEXT;
ALTER TABLE compliance_workflows ADD COLUMN IF NOT EXISTS required_action TEXT;
ALTER TABLE compliance_workflows ADD COLUMN IF NOT EXISTS status_updated_by UUID REFERENCES users (id) ON DELETE SET NULL;

-- Compliance audit remediation: consent capture at registration (DP-1)
ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_accepted_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_version TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_ip TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_user_agent TEXT;

-- Compliance audit remediation: agent assignment rationale (PI-2)
ALTER TABLE company_agent_assignments ADD COLUMN IF NOT EXISTS assignment_reason TEXT;
