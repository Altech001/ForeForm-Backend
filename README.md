# FormFore Backend (FastAPI API)

Welcome to the backend server for **FormFore**, a research-grade form builder and AI-powered data collection workspace. This FastAPI application handles user authentication, form definition management, response extraction, file storage, mixture-of-experts (MoE) agents, automated emails, and integrations with Google Drive & Google Sheets.

## 🚀 Key Features

- **Robust Form Builder API**: Supports sections, complex layouts, custom field validation, and quiz modes (automated scoring and grading).
- **MIxture of Experts (MoE) Agents**: Multi-agent sequential logic powered by NVIDIA models (Nemotron-49B as orchestrator and Llama-70B as subagents) for dynamic research-grade data extraction.
- **Gemini Live Integration**: Dynamic interactive filling and vocal analysis using the Gemini Live API.
- **Secure File Uploads**: Seamless integrations with Cloudinary for secure file storage and instant CDN access for images, videos, and documents.
- **Third-Party Integrations**:
  - **Google Sheets**: Auto-exporting response rows directly to sheets.
  - **Google Drive Explorer**: Navigating and attaching files from users' drives.
  - **Resend & SendGrid**: Instant automated email notifications for sharing invitations and response confirmations.
- **Secure JWT Authentication**: Role-based routing, hashed passwords, API key verification, and user session management.
- **Production-Ready DB Architecture**: Powered by SQLAlchemy with native support for both local SQLite development and high-concurrency cloud PostgreSQL databases (e.g., Neon).

---

## 🛠️ Technology Stack

* **Web Framework**: FastAPI (Uvicorn server)
* **ORM & Database**: SQLAlchemy (psycopg2-binary, SQLite)
* **AI & Agent Layer**: Google GenAI, OpenAI, Cerebras SDK, and NVIDIA Nemotron / Llama
* **Asset Storage**: Cloudinary SDK
* **Emails**: Resend / SendGrid
* **Authentication**: JWT (python-jose, bcrypt, passlib)

---

## 💻 Getting Started

### 1. Prerequisites
Make sure you have **Python 3.10** or higher installed on your machine.

### 2. Set Up Virtual Environment
Initialize and activate your virtual environment:
```bash
# Create the environment
python3 -m venv .venv

# Activate on Linux/macOS
source .venv/bin/activate

# Activate on Windows
.venv\Scripts\activate
```

### 3. Install Dependencies
Install all required libraries listed in `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.local` to `.env` and fill out your API credentials:
```bash
cp .env.local .env
```
Open `.env` and fill out the appropriate values:
- `DATABASE_URL`: PostgreSQL connection string (defaults to SQLite if left empty).
- `JWT_SECRET`: Random secure string for auth encryption.
- `RESEND_API_KEY`: API Key for transaction emails.
- `GEMINI_API_KEY`: Google Gemini API Key.
- `NVIDIA_API_KEY`: NVIDIA API Key for MoE orchestrator models.
- `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` / `CLOUDINARY_CLOUD_NAME`: Credentials for image and asset uploads.
- `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`: Client IDs for Google Integrations.

### 5. Running the Application
Launch the local Uvicorn development server:
```bash
uvicorn main:app --reload
```
The server will start at [http://127.0.0.1:8000](http://127.0.0.1:8000).

- **Interactive API docs (Swagger UI)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc documentation**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 📂 Project Structure

```
backend/
├── auth/                 # JWT validation and user dependencies
├── models/               # SQLAlchemy ORM declarations (User, Form, Task, etc.)
├── routers/              # FastAPI router modules (auth, upload, sheets, drive, ai)
├── schemas/              # Pydantic serialization models (request/response schemas)
├── services/             # Core service orchestrations (Resend, Nvidia, Quiz scoring)
├── uploads/              # Upload adapters (Cloudinary configuration and clients)
├── config.py             # Global application configuration settings (Settings class)
├── db.py                 # SQLAlchemy database session & engine initializer
├── migrations.py         # Incremental database column and structural upgrades
├── main.py               # Main application entry point & CORS configuration
├── requirements.txt      # Dependency manifest
└── .gitignore            # Files excluded from git tracking
```
