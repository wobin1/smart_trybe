# Postman — Smart Trybe Compliance API

## Base URL

| Environment | URL |
|-------------|-----|
| Local | `http://localhost:8000` |

Set Postman collection variables: `base_url`, `access_token`, `company_id`.

Import: `postman/Smart_Trybe_Compliance.postman_collection.json` (login/register scripts save the token; create company saves `company_id`).

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

#### Upsert CAC registry

| | |
|--|--|
| **Method** | PUT |
| **URI** | `/api/v1/cac/companies/{company_id}/registry` |
| **Headers** | `Authorization`, `Content-Type: application/json` |
| **JSON body** | `{ "status": "NOT_STARTED" \| "PENDING" \| "COMPLETED" \| "EXPIRED", "expiry_date": "YYYY-MM-DD" \| null }` |

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

#### Upsert registry

| | |
|--|--|
| **Method** | PUT |
| **URI** | `/api/v1/bpp/federal/companies/{company_id}/registry` |
| **Headers** | `Authorization`, `Content-Type: application/json` |
| **JSON body** | `{ "status": "...", "expiry_date": "YYYY-MM-DD" \| null }` |

Setting `status` to `COMPLETED` returns **403** if prerequisites (FIRS active TCC, PENCOM, ITF, NSITF) are missing.

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

## Environment variables (server)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | HS256 signing secret (use a long random value in production) |
| `JWT_ALGORITHM` | Default `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Default `1440` (24h) |
| `UPLOAD_DIR` | Local folder for uploaded files |

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
pytest tests/test_api_integration.py -q
```
