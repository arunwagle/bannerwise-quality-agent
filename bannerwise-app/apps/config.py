"""Centralized configuration for the Bannerwise Quality Agent."""

import os


class Config:
    """Base configuration."""

    # --- Flask ---
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

    # --- Databricks Workspace ---
    DATABRICKS_HOST = os.environ.get('DATABRICKS_HOST', '')


class DevelopmentConfig(Config):
    """Development overrides."""
    DEBUG = True
    SECRET_KEY = 'dev-secret-key-local'


class ProductionConfig(Config):
    """Production overrides."""
    DEBUG = False


def get_config():
    """Return appropriate config based on FLASK_ENV."""
    env = os.environ.get('FLASK_ENV', 'development')
    if env == 'production':
        return ProductionConfig()
    return DevelopmentConfig()
