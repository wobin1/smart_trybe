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

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
