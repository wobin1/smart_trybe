# Smart Trybe — System Overview for Frontend Developers

This document explains how the Smart Trybe backend works and what the frontend needs to support. Use it together with:

- **Postman collection (recommended):** `backend/postman/Smart_Trybe_Complete_Flow.postman_collection.json` — run folders **0 → 8** in order to see the full lifecycle
- **API reference:** `backend/docs/POSTMAN_API_REFERENCE.md` — endpoint-level details

---

## What the product does

Smart Trybe is a **Nigerian business compliance platform**. A client (business owner) registers, creates one or more companies, browses compliance services (FIRS, ITF, CAC, etc.), pays for them, fills out guided workflows, uploads documents, and submits for review. An **admin** oversees companies and assigns **agents** to process submissions. Agents complete the compliance work and record outputs (e.g. TIN).

The frontend is essentially three role-based apps sharing one API:

| Role | Who | Main job |
|------|-----|----------|
| `CLIENT` | Business owner | Register, manage companies, buy compliance, fill workflows, submit |
| `ADMIN` | Platform operator | View all companies, manage catalog, create agents, assign agents |
| `AGENT` | Compliance processor | Work assigned companies, update status, add outputs, mark complete |

---

## High-level architecture

```
┌─────────────┐     Bearer JWT      ┌──────────────────────────────────┐
│   Frontend  │ ◄─────────────────► │  FastAPI backend (localhost:8000) │
│  (3 roles)  │                     │  /api/v1/*                        │
└─────────────┘                     └──────────┬───────────────────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
              PostgreSQL                  Paystack                   Zoho Flow
           (companies, workflows,         (payments)              (email/SMS via
            carts, documents)                                    webhooks — backend only)
```

- **Auth:** JWT bearer token from `POST /api/v1/auth/register` or `POST /api/v1/auth/login`
- **Base URL:** `http://localhost:8000` (all routes under `/api/v1/`)
- **Role detection:** `GET /api/v1/auth/me` returns user info; `GET /api/v1/dashboard` returns role-specific data with a `role` field (`CLIENT`, `ADMIN`, `AGENT`)

---

## Core concepts the UI must understand

### 1. Company (the central entity)

Everything is scoped to a **company**. One client can own **multiple companies**.

A company has:

- Basic profile: name, RC number, TIN, address
- `registration_type`: `EXISTING` (already registered with CAC) or `NEW` (startup)
- **Company data** — a shared JSON store of canonical fields used to prefill forms across compliances
- **Compliance workflows** — one per compliance type + mode (e.g. FIRS/NEW, ITF/NEW)
- **Cart** — per company, for purchasing compliance services
- **Documents** — uploaded files tied to compliance types

**Key routes:**

- `POST /api/v1/cac/companies` — create
- `GET /api/v1/cac/companies` — list
- `GET/PATCH /api/v1/cac/companies/{id}` — detail / update
- `GET/PUT /api/v1/companies/{id}/data` — shared prefill data

### 2. Catalog (the “shop”)

Compliance services are listed in a catalog with categories and prices.

- `GET /api/v1/catalog/categories` — tabs like `tax_finance`, `corporate_registration`
- `GET /api/v1/catalog/items?category=all` — all items
- `GET /api/v1/catalog/items/{type}/{mode}` — single item (e.g. `FIRS/NEW`)

Each item has a `compliance_type` (FIRS, ITF, CAC, etc.) and `mode` (NEW, RENEWAL, REGISTRATION, PROCESS).

### 3. Cart & payment (how services are purchased)

Each company has its own cart. The flow:

```
Browse catalog → Add items to cart → Checkout → Pay → Entitlements created → Workflows can start
```

| Step | Endpoint | What happens |
|------|----------|--------------|
| View cart | `GET /cart/companies/{id}` | Open cart + line items + subtotal |
| Add item | `POST /cart/companies/{id}/items` | `{ "compliance_type": "FIRS", "mode": "NEW" }` |
| Remove item | `DELETE /cart/companies/{id}/items/{item_id}` | Remove line |
| Checkout | `POST /cart/companies/{id}/checkout` | Locks cart, creates pending payment, returns `payment_id` + price breakdown |
| Initialize Paystack | `POST /cart/companies/{id}/initialize-payment` | Returns `authorization_url` — redirect user here |
| Confirm (dev only) | `POST /cart/companies/{id}/pay` | Manual payment when `PAYMENT_DEV_MODE=true` |
| Pay from workflow step | `POST /workflow/{type}/{mode}/companies/{id}/checkout-payment` | Ensures item in cart, checkouts, returns same shape as initialize-payment |

**Production payment flow:**

1. Checkout → get `payment_id`
2. Initialize Paystack → redirect to `authorization_url`
3. User pays on Paystack
4. Paystack webhook hits backend → payment confirmed, entitlements created, workflows auto-started, **Make payment step auto-completed**
5. Frontend should poll workflow status or redirect to a “payment success” page

**Dev payment flow** (`PAYMENT_DEV_MODE=true`):

- Skip Paystack; call `/pay` directly with `{ payment_id, payment_reference, start_workflows: true }`

**Payment timing (all valid):**

- Pay **before** filling forms (cart checkout first)
- Pay **per compliance** from the last workflow step via `checkout-payment`
- Pay **once for the whole cart** after filling one or more workflows

**Important:** Payment creates **entitlements** — one per cart item. An entitlement is consumed when the client **submits** a workflow. Submit is blocked without a paid entitlement. Completing the “Make payment” step by typing a reference does **not** count as payment.

### 4. Workflows (the guided compliance forms)

A workflow is a multi-step form for one compliance type + mode on one company.

**Statuses:**

```
NOT_STARTED → PENDING → IN_REVIEW → COMPLETED
                              ↘ EXPIRED (renewals)
```

| Status | Meaning |
|--------|---------|
| `NOT_STARTED` | No workflow instance yet |
| `PENDING` | Started, client filling steps |
| `IN_REVIEW` | Client submitted; waiting for agent |
| `COMPLETED` | Agent finished |
| `EXPIRED` | Compliance expired (renewal needed) |

**Starting a workflow:**

- Automatically after payment (if `start_workflows: true`)
- Or manually: `POST /workflow/{type}/{mode}/companies/{id}/start`
- **You can start and fill steps before paying** — but **submit requires payment**

**Every workflow ends with “Make payment”.** That step is auto-completed when cart payment succeeds. Do not treat a typed `payment_reference` as proof of payment.

**Paid status (banner):**

`GET .../status` (and step form) include:

```json
"payment": {
  "is_paid": false,
  "payment_id": null,
  "paid_at": null,
  "consumed": false,
  "payment_reference": null
}
```

Use `payment.is_paid` for the “In your cart — not paid yet” vs “Paid” banner — not step completion alone.

**Step lifecycle (per step):**

```
GET steps/form?step_number=N  →  render dynamic form (with prefill)
         ↓
PUT steps/N/draft             →  save partial progress (optional)
         ↓
POST steps/N/complete         →  mark step done, persist data
```

For the last step, if unpaid: call `POST .../checkout-payment` (then Paystack or `/pay`). Completing Make payment while unpaid returns **402**.

**Form prefill (critical for UX):**

`GET .../steps/form?step_number=1` returns:

```json
{
  "fields": [
    {
      "key": "cac_rc_number",
      "label": "CAC RC number",
      "type": "text",
      "required": true,
      "shared": true,
      "canonical_key": "rc_number",
      "value": "RC-ST-2026-001",
      "filled": true
    }
  ],
  "missing_required": []
}
```

The backend merges three sources:

1. **Step schema** — field definitions per compliance/step
2. **Step data** — what the user already saved for this step
3. **Company data** — shared fields from other workflows (RC number, address, directors, etc.)

When a user completes a step, shared fields propagate into `company_data` so the next compliance (e.g. ITF after FIRS) is pre-filled.

**Frontend should:** Build forms dynamically from the `fields` array. Respect `type`, `required`, `options`, `filled`, and `shared` (show “reused from company profile” hints for shared fields).

**Submit (the gate):**

`POST /workflow/{type}/{mode}/companies/{id}/submit`

On success → status becomes `IN_REVIEW`.

On failure → **403** with:

```json
{
  "detail": {
    "message": "Workflow submission blocked by missing requirements",
    "missing": [
      "PAYMENT: compliance fee not paid",
      "STEPS: 3/5",
      "DOCUMENT:CAC_CERTIFICATE"
    ]
  }
}
```

The frontend must parse `detail.missing` and show actionable blockers (pay, complete steps, upload docs).

### 5. Documents

Uploaded via multipart form:

- `POST /workflow/{type}/companies/{id}/documents`
- Fields: `doc_type` (text), `file` (file)

Required doc types vary by compliance (e.g. FIRS needs `CAC_CERTIFICATE`, `CAC_STATUS_REPORT`, `DIRECTOR_DETAILS`).

**Document library:**

- `GET /companies/{id}/documents?compliance_type=FIRS` — list uploaded docs
- `POST /companies/{id}/documents/reuse` — attach an existing doc to another compliance

Documents can be reused across compliances when they represent the same underlying asset.

### 6. Admin flow

Admin does not go through the client cart/workflow UI. They:

1. Log in (`POST /auth/login` — admin email must be in server `ADMIN_EMAILS`)
2. View all companies (`GET /admin/companies`)
3. Inspect workflow progress (`GET /admin/companies/{id}/workflow-progress`)
4. Assign an agent (`POST /admin/companies/{id}/assign-agent` with `{ agent_user_id }`)
5. Manage catalog prices (`PATCH /admin/catalog/items/{type}/{mode}`)
6. Create agent users (`POST /admin/users` with `role: "AGENT"`)

### 7. Agent flow

Agents only see **assigned** companies:

1. Log in
2. `GET /agent/companies` — assigned list
3. `GET /agent/companies/{id}/progress` — workflow progress
4. Process submission:
   - `PATCH /agent/companies/{id}/workflows/{type}/{mode}/status` — update status/step
   - `POST .../outputs` — record deliverables (e.g. `{ "output_type": "TIN", "output_value": "12345678-0001" }`)
   - `POST .../complete` — mark workflow `COMPLETED` with optional `expiry_date`
   - `PUT /agent/companies/{id}/registry/{type}` — update compliance registry

After completion, the client sees `COMPLETED` status and outputs (e.g. TIN) on `GET .../status`.

---

## End-to-end client journey (what the Postman flow tests)

This is the happy path your frontend should support:

```
1. Register / Login
      ↓
2. Create company (can create multiple)
      ↓
3. Optionally save company data early (PUT /companies/{id}/data) for prefill
      ↓
4. Browse catalog → add FIRS/NEW + ITF/NEW to cart
      ↓
5. Checkout → initialize Paystack (or dev /pay)
      ↓
6. Payment completes → entitlements created → workflows auto-started
      ↓
7. Open FIRS/NEW workflow:
   - Fetch step form (prefilled)
   - Complete steps 1–5
   - Upload required documents
   - Submit → IN_REVIEW
      ↓
8. Client dashboard shows "in review"
      ↓
   [Admin assigns agent]
      ↓
9. Agent processes → adds TIN output → marks COMPLETED
      ↓
10. Client sees COMPLETED + TIN on status page
```

**Payment gate behavior** (tested in Postman folder `PG`):

- Workflow can be **started** and steps filled **without** payment
- **Submit** returns 403 with `PAYMENT` in `missing` if not paid
- After payment, `PAYMENT` is no longer in `missing` (but steps/docs may still block)
- After payment, `GET .../status` shows `payment.is_paid: true` and the Make payment step is completed

---

## Dashboards (role-aware)

`GET /api/v1/dashboard` returns different data per role:

**Client dashboard:**

- Summary: company count, active workflows, in review, completed, upcoming renewals
- `currently_working_on` — active workflow items with progress
- Company list

**Also:**

- `GET /dashboard/companies/{id}` — per-company stats
- `GET /dashboard/renewals?days=90` — compliances expiring soon

**Admin / Agent dashboards** return role-specific summaries (assigned companies, pending reviews, etc.).

Use the dashboard `role` field to route users after login:

- `CLIENT` → client home
- `ADMIN` → admin console
- `AGENT` → agent queue

---

## Notifications (backend-only — no frontend work)

The backend fires Zoho Flow webhooks on:

- `payment.completed`
- `workflow.submitted`
- `agent.assigned`
- `workflow.completed`

These drive email/SMS. The frontend does not call these — but you may want success toasts at the same trigger points.

---

## API conventions for the frontend

| Concern | Pattern |
|---------|---------|
| Auth header | `Authorization: Bearer <token>` |
| JSON bodies | `Content-Type: application/json` |
| File uploads | `multipart/form-data` with `doc_type` + `file` |
| Errors | FastAPI format: `{ "detail": "..." }` or `{ "detail": { "message": "...", "missing": [...] } }` |
| IDs | UUIDs everywhere (`company_id`, `payment_id`, `workflow_id`) |
| Money | Amounts in NGN (`subtotal_ngn`, `total_amount_ngn`, `base_price_ngn`) |
| Compliance path | `/workflow/{compliance_type}/{mode}/companies/{company_id}/...` |

**Company context:** Most client screens need a selected `company_id`. Support a company switcher when the user has multiple companies.

---

## Suggested frontend screen map

| Screen | Primary API calls |
|--------|-------------------|
| Login / Register | `/auth/login`, `/auth/register`, `/auth/me` |
| Client home | `/dashboard` |
| Companies list | `/cac/companies` |
| Company detail | `/cac/companies/{id}`, `/companies/{id}/data` |
| Catalog | `/catalog/categories`, `/catalog/items` |
| Cart | `/cart/companies/{id}`, add/remove items, checkout |
| Payment | initialize-payment → Paystack redirect; or dev `/pay` |
| Workflow hub | `/workflow/companies/{id}/progress` |
| Workflow step | `/steps/form`, `/steps/{n}/draft`, `/steps/{n}/complete` |
| Document upload | `/workflow/{type}/companies/{id}/documents` |
| Submit review | `/workflow/{type}/{mode}/companies/{id}/submit` |
| Admin companies | `/admin/companies`, workflow-progress, assign-agent |
| Agent queue | `/agent/companies`, progress, complete workflow |

---

## Key UX behaviors to implement

1. **Dynamic forms** — Do not hardcode FIRS fields. Render from `GET .../steps/form`.
2. **Prefill indicators** — Show when `filled: true` and `shared: true`.
3. **Submit blockers** — On 403, parse `detail.missing` into a checklist (payment, steps, documents).
4. **Payment before submit** — Allow browsing/filling workflows before pay; block submit until paid.
5. **Multi-compliance cart** — One checkout can buy FIRS + ITF; both workflows start after payment.
6. **Progress tracking** — Use `/workflow/companies/{id}/progress` or `/status` for step bars and badges.
7. **Role routing** — After login, branch on `role` from `/dashboard` or `/auth/me`.
8. **Paystack return** — Handle `PAYSTACK_CALLBACK_URL` redirect; poll payment/workflow status since confirmation is webhook-driven in production.

---

## Compliance types supported

`CAC`, `FIRS`, `ITF`, `NSITF`, `PENCOM`, `GROUP_LIFE_INSURANCE`, `ACCOUNT_AUDITING`, `SCUML`, `BPP_FEDERAL`, `BPP_STATE`

Each has different steps and required documents. The Postman collection exercises **FIRS/NEW** end-to-end; other types follow the same workflow pattern with different step schemas.

---

## Local dev setup

1. Backend at `http://localhost:8000`
2. Register admin with email in server `ADMIN_EMAILS`, restart server
3. Set `PAYMENT_DEV_MODE=true` to skip Paystack and use `POST /pay` directly
4. Import and run the Postman collection folders 0→8 to verify the API before building UI

---

## Summary

**Clients buy compliance services per company, fill guided multi-step workflows with smart prefill, upload documents, and submit for review — but only after payment; admins assign agents; agents complete the work and record outputs like TIN.**
