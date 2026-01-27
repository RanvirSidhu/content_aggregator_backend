"""
Application configuration module.

This module handles all environment variables and application settings
using Pydantic's BaseSettings for validation and type safety.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Attributes:
        DATABASE_URL: PostgreSQL database connection string
        REDIS_HOST: Redis server hostname
        REDIS_PORT: Redis server port
        APP_NAME: Application name
        APP_VERSION: Application version
        DEBUG: Debug mode flag
        LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR)
        REFRESH_INTERVAL_MINUTES: Interval for periodic content refresh
        CORS_ORIGINS: Allowed CORS origins
    """

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # Application
    APP_NAME: str = "Content Aggregator API"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Scheduler
    REFRESH_INTERVAL_MINUTES: int = 15

    # CORS
    CORS_ORIGINS: list = ["*"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
