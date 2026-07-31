# Bannerwise Quality Agent — Solution Design

## Components

### 1. Flask Web Application
- Factory pattern (create_app())
- Blueprint-based route organization
- Gunicorn WSGI server for production

### 2. Quality Assessment Engine
- AI-powered analysis of banner creatives
- Scoring dimensions: composition, text readability, brand consistency

### 3. Deployment
- Declarative Automation Bundles (DABs)
- Dev/Prod targets
- Secrets management via Databricks secret scope
