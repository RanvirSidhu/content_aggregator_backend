# Content Aggregator API

A Multi-source content aggregation API built with FastAPI that fetches, normalizes, and serves articles from tech platforms including Dev.to, Reddit, and Lobsters.

## Features

Fetches content from Dev.to, Reddit (/r/programming), and Lobsters
Stores articles in PostgreSQL with SQLAlchemy ORM
Automatic content updates every 15 minutes using APScheduler
Asynchronous task execution with Dramatiq and Redis
Structured logging with file and console output
Filter articles by source
Trigger content updates on-demand via API
Proper error handling, validation, and configuration management

## Project Structure

```
content-aggregator/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py           # API endpoint definitions
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # Configuration management
│   │   └── logging.py          # Logging setup
│   ├── db/
│   │   ├── __init__.py
│   │   └── session.py          # Database connection & session
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLAlchemy ORM models
│   │   └── schemas.py          # Schemas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── fetcher.py          # Content fetching logic
│   │   └── scheduler.py        # Background task scheduling
│   └── utils/
│       ├── __init__.py
│       └── article_parser.py   # Article normalization utilities
├── logs/                       # Application logs (auto-created)
├── .env                        # Environment variables (create from .env.example)
├── .env.example                # Example environment configuration
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

## Prerequisites

- Python 3.11 or higher
- PostgreSQL 13 or higher
- Redis 6 or higher

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd content-aggregator
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Setup PostgreSQL database
Setup PostegreSQL DB.

### 5. Setup Redis
Setup and start redis-server.

### 6. Configure environment variables

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your configuration
nano .env  # or use your preferred editor
```

Update the following required variables in `.env`:
```env
DATABASE_URL=postgresql+asyncpg://your_user:your_password@localhost:5432/content_aggregator
REDIS_HOST=localhost
REDIS_PORT=6379
```

## Running the Application

### Start the API server

```bash
# Development mode with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

```

### Start the Dramatiq worker

Open a new terminal and run:

```bash
# Start worker
dramatiq app.services.scheduler
```

The API will be available at: http://localhost:8000

## API Documentation

Interactive API documentation is available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Available Endpoints

#### Health Check
```http
GET /
```
Returns API status and version information.

#### Get Articles
```http
GET /api/articles?source={source}&limit={limit}&offset={offset}
```

**Query Parameters:**
- `source` (optional): Filter by source (Dev.to, Reddit, Lobsters)

**Example:**
```bash
curl http://localhost:8000/api/articles?source=Dev.to
```

#### Trigger Manual Refresh
```http
POST /api/refresh/trigger
```
Manually trigger content refresh in background.

**Example:**
```bash
curl -X POST http://localhost:8000/api/refresh/trigger
```

#### Disable Periodic Refresh
```http
POST /api/refresh/disable
```
Pause automatic content refresh.

#### Enable Periodic Refresh
```http
POST /api/refresh/enable
```
Resume automatic content refresh.

### Logging

Logs are written to both console and `logs/app.log` file with the following format:
```
2024-01-27 10:30:45 - app.services.fetcher - INFO - fetch_source:123 - Starting fetch from Dev.to
```

Log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

## Architecture

### Data Flow
1. **Startup**: Application initializes database and checks for existing data
2. **Initial Fetch**: If database is empty, fetches articles from all sources
3. **Scheduled Refresh**: APScheduler triggers refresh every 15 minutes
4. **Background Processing**: Dramatiq worker processes fetch tasks asynchronously
5. **Database Storage**: New articles are saved to PostgreSQL
6. **API Serving**: FastAPI serves articles via REST endpoints

### Components

- **FastAPI**: Web framework for API endpoints
- **SQLAlchemy**: ORM for database operations
- **APScheduler**: Cron-like task scheduler
- **Dramatiq**: Distributed task queue
- **Redis**: Message broker for Dramatiq
- **PostgreSQL**: Data persistence
