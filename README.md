# 💬 Realtime Chat Server (FastAPI)

## 🎯 Project Goal

This project implements a high-performance, real-time chat server using the **FastAPI** framework, fulfilling all requirements outlined in the *Engineering Python Test* — including **Authentication**, **Realtime Chat**, **Persistence**, and **Group Management**.

The submission includes both:
- The backend server code, and  
- A minimal single-file HTML/JavaScript client for testing the complete functionality end-to-end.

### Live Demo:

[![Watch Demo Video](https://img.shields.io/badge/DEMO-WATCH_VIDEO_ON_DRIVE-red?style=for-the-badge&logo=googledrive)](https://drive.google.com/file/d/17uIrqAqoxhBu-SFXYkkOZhoGk3aQFZI-/view?usp=sharing)

---

## 🛠️ Tech Stack

| Component | Technology | Role |
|------------|-------------|------|
| **Backend Framework** | FastAPI | High-performance API and WebSocket handling |
| **Asynchronous** | ASGI (Uvicorn) | Server runtime for concurrent handling of HTTP and WS requests |
| **WebSockets** | FastAPI WebSockets | Realtime communication for chat and typing indicators |
| **Data Models & ORM** | SQLModel (Pydantic + SQLAlchemy) | Defines users, chats, and groups with automatic schema generation |
| **Authentication** | JWT (PyJWT) | Secure token-based access and refresh token management |
| **Minimal Frontend** | HTML/JavaScript | Single-file client to test all API and WS endpoints |

---

## ✨ Key Features Implemented

The server provides a robust, fully functional chat service covering all required specifications:

### 🔒 Authentication (JWT)
- **Sign-Up (`/auth/register`)** – User creation with hashed passwords.  
- **Login (`/auth/login`)** – Issuance of short-lived *Access Tokens* and long-lived *Refresh Tokens*.  
- **Token Refresh (`/auth/refresh`)** – Secure renewal of access tokens using refresh tokens.  
- **Protected Endpoints** – All sensitive endpoints (chat, history, groups) require valid bearer tokens.

---

### 💬 Realtime Chat (`/ws/chat`)
- **Centralized WebSocket Handler** – A single, secure WebSocket endpoint handles all real-time communication.  
- **One-to-One (1:1) Chat** – Private messages between two users.  
- **Group Chat** – Messages broadcast to all members of a specific group.  
- **Persistence** – All chat messages (1:1 and Group) are stored in the database for history retrieval.  
- **Realtime Notifications** – Users are instantly notified of new messages they receive.

---

### ⏳ Persistence and History
- **Message Storage** – Dedicated models for storing individual and group messages with timestamps.  
- **History Retrieval** – HTTP endpoints allow authenticated users to fetch past messages for both 1:1 and group chats.

---

### 👥 Group Management
- **Group Creation (`/groups`)** – Users can create new groups and define initial members.  
- **Membership Management** – Groups are securely linked to user accounts via a junction table.

---

### ⌨️ Typing Indicators
- **Realtime Typing Status** – WebSocket messages are used to transmit a user's `typing` or `stopped_typing` status to other participants in a 1:1 or group chat.

---

## 📁 Project Structure

<pre lang="markdown">
punch-fastapi-backend-test/
├── main.py                # FastAPI application entry point (uvicorn main:app)
├── app/                   # Root application module
│   ├── auth/              # Authentication routes (login, register, refresh)
│   │   └── router.py
│   ├── chat/              # Chat/Group routes and WebSocket handler
│   │   └── router.py
│   ├── core/              # Security and configuration utilities
│   │   └── security.py
│   ├── database/          # Database connection, model definitions
│   │   └── models.py
│   ├── schemas/           # Pydantic models for request/response validation
│   ├── services.py        # Shared services and business logic (e.g., token generation)
│   └── static/            # Static files
│       └── index.html     # Minimal HTML/JS Client (for submission)
├── .env.example
├── requirements.txt       # Dependencies
└── README.md              # This document
</pre>

## 🚀 Setup and Running
### 1️⃣ Backend Setup

**Clone the repository:** 
 ```bash
git clone [https://github.com/punchagency/punch-django-backend-test.git](https://github.com/punchagency/punch-django-backend-test.git)
cd punch-django-backend-test
git checkout kinghenrymorgan
 ```

**Create and configure environment file:**
```bash
cp .env.example .env
```

Make sure the values for SECRET_KEY, ALGORITHM, and DB_URL are correctly set in your .env file.

**Create a virtual environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Run the Server:**

Use Uvicorn to run the FastAPI service.

```bash
uvicorn app:app --reload
```

The server will start on http://localhost:8000.

### 2️⃣ Frontend Client Access

The minimal test client is located at:

```arduino
app/static/index.html
```

To test:

1: Ensure the backend server is running.

2: Open your web browser and navigate to:
👉 http://localhost:8000/static/index.html

3: The client provides an interface to:

- Register and log in two users (e.g., “Alice” and “Bob”).

- Connect two browser tabs to the WebSocket endpoint.

- Test 1:1 chat, Group chat, and Typing Indicators in real-time.

## 📢 Submission Note

The test instructions required placing:

- The backend code in this repository, and

- The minimal frontend client in a separate frontend repository (punch-frontend-test).

**Reason for Combined Submission**

During final testing, the designated frontend repository
(https://github.com/punchagency/punch-frontend-test
)
was inaccessible (returned a 404 error).

To ensure the full, working solution could be reviewed within the deadline,
the minimal HTML/JS client (app/static/index.html) has been included here.

✅ The included client successfully demonstrates all backend functionalities end-to-end.