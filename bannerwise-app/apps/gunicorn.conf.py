"""Gunicorn configuration file for Databricks Apps deployment.

Reads the DATABRICKS_APP_PORT environment variable at runtime
to bind to the correct port assigned by the platform.
"""

import os

# Bind to the port assigned by Databricks Apps platform
bind = f"0.0.0.0:{os.environ.get('DATABRICKS_APP_PORT', '8000')}"
