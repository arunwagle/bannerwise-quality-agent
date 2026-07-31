"""Centralized configuration for the Bannerwise Quality Agent.

All API endpoints and thresholds are configured here.
When swapping mocks for real services, update these values.
"""

import os


class Config:
    """Base configuration."""

    # --- Flask ---
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')

    # --- Confidence Gate ---
    CONFIDENCE_THRESHOLD = float(os.environ.get('CONFIDENCE_THRESHOLD', '0.85'))

    # --- Model Serving Endpoint (Router Agent) ---
    SERVING_ENDPOINT_URL = os.environ.get(
        'SERVING_ENDPOINT_URL',
        'https://fevm-aw-serverless-stable.cloud.databricks.com/serving-endpoints/bannerwise-quality-router/invocations'
    )

    # --- Vector Search ---
    VS_ENDPOINT = os.environ.get('VS_ENDPOINT', 'bannerwise-vs-endpoint')
    VS_INDEX = os.environ.get('VS_INDEX', 'catalog.schema.certified_qa_index')

    # --- Genie Space (Analytical Lane) ---
    GENIE_SPACE_ID = os.environ.get('GENIE_SPACE_ID', 'genie-space-mock-001')

    # --- SQL Warehouse ---
    SQL_WAREHOUSE_ID = os.environ.get('SQL_WAREHOUSE_ID', '2d8e531640ffa469')

    # --- Databricks Workspace ---
    DATABRICKS_HOST = os.environ.get('DATABRICKS_HOST', '')

    # --- Admin ---
    ADMIN_USERS = [
        e.strip() for e in
        os.environ.get('ADMIN_USERS', 'arun.wagle@databricks.com').split(',')
    ]

    # --- API Mode ---
    # Set to "mock" for development, "live" for production
    API_MODE = os.environ.get('API_MODE', 'mock')


class DevelopmentConfig(Config):
    """Development overrides."""
    DEBUG = True
    SECRET_KEY = 'dev-secret-key-local'
    API_MODE = 'mock'


class ProductionConfig(Config):
    """Production overrides."""
    DEBUG = False
    API_MODE = 'live'


def get_config():
    """Return appropriate config based on FLASK_ENV."""
    env = os.environ.get('FLASK_ENV', 'development')
    if env == 'production':
        return ProductionConfig()
    return DevelopmentConfig()
