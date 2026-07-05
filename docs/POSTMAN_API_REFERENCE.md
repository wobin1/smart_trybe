# Postman — Smart Trybe Compliance API

## Base URL

| Environment | URL |
|-------------|-----|
| Local | `http://localhost:8000` |

Set Postman collection variables: `base_url`, `access_token`, `company_id`, `cart_id`, `payment_id`.

Import collections:
- **`postman/Smart_Trybe_Complete_Flow.postman_collection.json`** — **recommended** full E2E flow (client → cart → workflow → admin → agent). Run folders **0 → 8** in order.
- `postman/Smart_Trybe_Compliance.postman_collection.json` — endpoint reference + Smart Cart folder
- `postman/FIRS_Complete_Flow.postman_collection.json` — FIRS-only E2E flow

Set Postman collection variables: `base_url`, `admin_email`, `admin_password`. The complete flow auto-saves tokens, `company_id`, `payment_id`, `agent_user_id`.

## Authentication

All routes under `/api/v1/cac/...`, `/api/v1/bpp/...`, and `/api/v1/auth/me` require:

| Header | Value |
|--------|--------|
| `Authorization` | `Bearer <access_token>` |

Obtain `access_token` from **POST** `/api/v1/auth/register` or **POST** `/api/v1/auth/login`.

---

## Endpoints

### Health (no auth)

| Method | URI | Body |
|--------|-----|------|
| GET | `/health` | none |

---

### Auth

#### Register

| | |
|--|--|
| **Method** | POST |
| **URI** | `/api/v1/auth/register` |
| **Headers** | `Content-Type: application/json` |
| **JSON body** | `{ "email": "you@example.com", "password": "min8chars", "full_name": "Optional Name" }` |
| **Success** | `201` — `{ "access_token": "...", "token_type": "bearer" }` |

#### Login

| | |
|--|--|
| **Method** | POST |
| **URI** | `/api/v1/auth/login` |
| **Headers** | `Content-Type: application/json` |
| **JSON body** | `{ "email": "you@example.com", "password": "yourpassword" }` |
| **Success** | `200` — `{ "access_token": "...", "token_type": "bearer" }` |

#### Current user

| | |
|--|--|
| **Method** | GET |
| **URI** | `/api/v1/auth/me` |
| **Headers** | `Authorization: Bearer <access_token>` |
| **Success** | `200` — `{ "id", "email", "full_name", "created_at" }` |

---

### CAC (auth required)

#### Create company

| | |
|--|--|
| **Method** | POST |
| **URI** | `/api/v1/cac/companies` |
| **Headers** | `Authorization`, `Content-Type: application/json` |
| **JSON body** | `{ "name": "...", "rc_number": "...", "tin": "...", "address": "..." }` (optional fields except `name`) |
| **Success** | `201` — `{ "id": "<uuid>" }` |

#### List my companies

| | |
|--|--|
| **Method** | GET |
| **URI** | `/api/v1/cac/companies` |
| **Headers** | `Authorization` |

#### Get company

| | |
|--|--|
| **Method** | GET |
| **URI** | `/api/v1/cac/companies/{company_id}` |
| **Headers** | `Authorization` |

#### Update company

| | |
|--|--|
| **Method** | PATCH |
| **URI** | `/api/v1/cac/companies/{company_id}` |
| **Headers** | `Authorization`, `Content-Type: application/json` |
| **JSON body** | `{ "name": "...", "rc_number": "...", "tin": "...", "address": "..." }` (all optional) |

#### Get CAC registry row

| | |
|--|--|
| **Method** | GET |
| **URI** | `/api/v1/cac/companies/{company_id}/registry` |
| **Headers** | `Authorization` |

#### Upsert CAC registry (agent/admin only)

| | |
|--|--|
| **Method** | PUT |
| **URI** | `/api/v1/cac/companies/{company_id}/registry` |
| **Headers** | `Authorization` (AGENT or ADMIN), `Content-Type: application/json` |
| **JSON body** | `{ "status": "NOT_STARTED" \| "PENDING" \| "IN_REVIEW" \| "COMPLETED" \| "EXPIRED", "expiry_date": "YYYY-MM-DD" \| null }` |

#### Upload CAC document

| | |
|--|--|
| **Method** | POST |
| **URI** | `/api/v1/cac/companies/{company_id}/documents` |
| **Headers** | `Authorization` |
| **Body** | `multipart/form-data`: field `doc_type` (text), field `file` (file) |

---

### BPP Federal (auth required)

#### Get registry

| | |
|--|--|
| **Method** | GET |
| **URI** | `/api/v1/bpp/federal/companies/{company_id}/registry` |
| **Headers** | `Authorization` |

#### Upsert registry (agent/admin only)

| | |
|--|--|
| **Method** | PUT |
| **URI** | `/api/v1/bpp/federal/companies/{company_id}/registry` |
| **Headers** | `Authorization` (AGENT or ADMIN), `Content-Type: application/json` |
| **JSON body** | `{ "status": "...", "expiry_date": "YYYY-MM-DD" \| null }` |

**Preferred path:** use unified workflow routes (`/api/v1/workflow/BPP_FEDERAL/REGISTRATION/...`) for client step filling and submit. Legacy BPP registry routes remain for agent completion.

#### Upload document

| | |
|--|--|
| **Method** | POST |
| **URI** | `/api/v1/bpp/federal/companies/{company_id}/documents` |
| **Headers** | `Authorization` |
| **Body** | `multipart/form-data`: `doc_type`, `file` |

---

### BPP State (auth required)

Same shape as BPP Federal with base path `/api/v1/bpp/state/companies/{company_id}/...`.

---

### Catalog (auth required)

Browse compliance types grouped by category for the Smart Cart UI.

| Method | URI | Notes |
|--------|-----|-------|
| GET | `/api/v1/catalog/categories` | List category tabs |
| GET | `/api/v1/catalog/items?category=all` | All catalog items |
| GET | `/api/v1/catalog/items?category=tax_finance` | Filter by slug |
| GET | `/api/v1/catalog/items/{compliance_type}/{mode}` | Single item detail |

Category slugs: `corporate_registration`, `tax_finance`, `insurance_labour`, `data_regulatory`.

---

### Smart Cart (auth required)

| Method | URI | Body |
|--------|-----|------|
| GET | `/api/v1/cart/companies/{company_id}` | Open cart + line items |
| POST | `/api/v1/cart/companies/{company_id}/items` | `{ "compliance_type": "FIRS", "mode": "NEW" }` |
| DELETE | `/api/v1/cart/companies/{company_id}/items/{item_id}` | Remove line item |
| POST | `/api/v1/cart/companies/{company_id}/checkout` | Returns `payment_id` + breakdown |
| POST | `/api/v1/cart/companies/{company_id}/initialize-payment` | `{ "payment_id": "..." }` — returns Paystack `authorization_url` |
| POST | `/api/v1/cart/companies/{company_id}/pay` | Dev/manual only when `PAYMENT_DEV_MODE=true`: `{ "payment_id", "payment_reference", "start_workflows" }` |

**Production payment flow:** checkout → initialize-payment → redirect user to Paystack → Paystack webhook confirms payment and starts workflows.

| Method | URI | Auth | Notes |
|--------|-----|------|-------|
| POST | `/api/v1/webhooks/paystack` | Paystack signature | `x-paystack-signature` HMAC-SHA512 of raw body |

### Company data (auth required)

| Method | URI | Body |
|--------|-----|------|
| GET | `/api/v1/companies/{company_id}/data` | All canonical filled fields (for form prefill) |
| PUT | `/api/v1/companies/{company_id}/data` | `{ "data": { "company_address": "...", "rc_number": "...", "directors": [] } }` |

**Recommended Postman order:** use folder **Smart Cart — Full Test Flow** (requests 1–18).

Cross-compliance data reuse:
- **Read:** `GET /companies/{company_id}/data` — frontend compares returned keys with each form field and pre-fills matches.
- **Write:** `PUT /companies/{company_id}/data` or save workflow steps (both update `company_data`).
- **Workflow forms:** `GET .../steps/form?step_number=N` returns field schema + merged values + `missing_required`.
- **Workflow status:** `GET .../status` merges `company_data` into empty step fields automatically.

---

### Workflow (auth required)

| Method | URI | Body / params |
|--------|-----|---------------|
| GET | `/api/v1/workflow/templates/{compliance_type}/{mode}` | Template + step list |
| POST | `/api/v1/workflow/{type}/{mode}/companies/{company_id}/start` | Start workflow |
| GET | `/api/v1/workflow/{type}/{mode}/companies/{company_id}/steps/form?step_number=1` | Step form with prefill |
| GET | `/api/v1/workflow/{type}/{mode}/companies/{company_id}/status` | Full workflow + steps |
| PUT | `/api/v1/workflow/{type}/{mode}/companies/{company_id}/steps/{n}/draft` | `{ "data": { ... } }` |
| POST | `/api/v1/workflow/{type}/{mode}/companies/{company_id}/steps/{n}/complete` | `{ "step_name": "...", "data": { ... } }` |
| POST | `/api/v1/workflow/{type}/companies/{company_id}/documents` | multipart: `doc_type`, `file` |
| POST | `/api/v1/workflow/{type}/{mode}/companies/{company_id}/submit` | Client submit → `IN_REVIEW` (**requires paid cart entitlement**) |
| GET | `/api/v1/workflow/companies/{company_id}/progress` | All compliance progress |

Supported types: `CAC`, `FIRS`, `ITF`, `NSITF`, `PENCOM`, `GROUP_LIFE_INSURANCE`, `ACCOUNT_AUDITING`, `SCUML`, `BPP_FEDERAL`, `BPP_STATE`.

---

### Agent (AGENT or ADMIN)

| Method | URI | Notes |
|--------|-----|-------|
| GET | `/api/v1/agent/companies` | Assigned companies (admin: all) |
| GET | `/api/v1/agent/companies/{company_id}` | Full detail |
| GET | `/api/v1/agent/companies/{company_id}/progress` | Workflow progress |
| POST | `/api/v1/agent/companies/{id}/workflows/{type}/documents` | multipart upload |
| PATCH | `/api/v1/agent/companies/{id}/workflows/{type}/{mode}/status` | `{ "status", "current_step?" }` |
| POST | `/api/v1/agent/companies/{id}/workflows/{type}/{mode}/complete` | `{ "expiry_date?" }` |
| POST | `/api/v1/agent/companies/{id}/workflows/{type}/{mode}/outputs` | `{ "output_type", "output_value" }` |
| PUT | `/api/v1/agent/companies/{id}/registry/{compliance_type}` | Update registry |

---

### Admin (ADMIN only)

| Method | URI | Body |
|--------|-----|------|
| GET | `/api/v1/admin/catalog/items?category=all` | List catalog (incl. inactive) |
| GET | `/api/v1/admin/catalog/items/{type}/{mode}` | Single item |
| PATCH | `/api/v1/admin/catalog/items/{type}/{mode}` | `{ "base_price_ngn", "display_name", "is_active", ... }` |
| GET | `/api/v1/admin/users?role=AGENT` | List users |
| POST | `/api/v1/admin/users` | Create AGENT/ADMIN: `{ "email", "password", "role" }` |
| PATCH | `/api/v1/admin/users/{user_id}` | Update user |
| GET | `/api/v1/admin/companies` | All companies |
| GET | `/api/v1/admin/companies/{company_id}` | Company detail |
| GET | `/api/v1/admin/companies/{company_id}/workflow-progress` | Progress |
| GET | `/api/v1/admin/companies/{company_id}/assignments` | Agent assignments |
| POST | `/api/v1/admin/companies/{company_id}/assign-agent` | `{ "agent_user_id" }` |
| DELETE | `/api/v1/admin/companies/{company_id}/assign-agent/{agent_user_id}` | Unassign |

---

### Dashboard (auth required — role-aware)

| Method | URI | Role | Notes |
|--------|-----|------|-------|
| GET | `/api/v1/dashboard` | CLIENT / AGENT / ADMIN | Returns role-specific summary |
| GET | `/api/v1/dashboard/companies/{company_id}` | Any with access | Per-company stats |
| GET | `/api/v1/dashboard/renewals?days=90` | Any with access | Upcoming renewals |

---

## Environment variables (server)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | HS256 signing secret (use a long random value in production) |
| `JWT_ALGORITHM` | Default `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Default `1440` (24h) |
| `UPLOAD_DIR` | Local folder for uploaded files |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | File storage |
| `GOOGLE_CLIENT_ID` | Google OAuth |
| `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY` | Paystack payments |
| `PAYMENT_DEV_MODE` | `true` = allow manual `/pay`; `false` = webhook-only when Paystack configured |
| `PAYSTACK_CALLBACK_URL` | Frontend redirect after Paystack checkout |
| `ZOHO_FLOW_WEBHOOK_PAYMENT` | Zoho Flow URL — payment completed |
| `ZOHO_FLOW_WEBHOOK_WORKFLOW_SUBMITTED` | Zoho Flow URL — client submitted for review |
| `ZOHO_FLOW_WEBHOOK_AGENT_ASSIGNED` | Zoho Flow URL — agent assigned to company |
| `ZOHO_FLOW_WEBHOOK_WORKFLOW_COMPLETED` | Zoho Flow URL — agent marked compliance complete |
| `ZOHO_FLOW_WEBHOOK_SECRET` | Optional HMAC secret sent as `X-Webhook-Signature` |

### Zoho Flow event payloads

Each webhook receives: `{ "event": "<name>", "payload": { ... } }`

| Event | Trigger | Key payload fields |
|-------|---------|-------------------|
| `payment.completed` | Cart paid | `owner_email`, `company_name`, `breakdown`, `workflows_started` |
| `workflow.submitted` | Client submit | `compliance_type`, `mode`, `owner_email`, `company_name` |
| `agent.assigned` | Admin assigns agent | `agent_email`, `owner_email`, `company_name` |
| `workflow.completed` | Agent completes | `compliance_type`, `mode`, `owner_email`, `expiry_date` |

---

## Tests

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/test_security_unit.py -q
```

Integration tests (PostgreSQL required):

```bash
export TEST_DATABASE_URL='postgresql://USER:PASS@localhost:5432/DBNAME'
pytest tests/ -q
```
