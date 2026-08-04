"""Services package — API-driven data access layer.

Services:
  - live_router_service  → Model Serving endpoint + Genie Space
  - demo_router_service  → Offline demo mode (no endpoints)
  - corpus_service       → Certified QA corpus (Delta table)
  - history_service      → Query history (Delta table)
  - genie_service        → Genie Space API for analytical queries
  - certified_lane_service → Execute certified SQL with LLM formatting
"""
