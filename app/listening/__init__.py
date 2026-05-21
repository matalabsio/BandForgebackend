"""BandForge Listening module — modular monolith.

Exposes a FastAPI router for the IELTS Listening pipeline:
start, questions (R2 signed audio), autosave, submit (sync scoring),
score-report.
"""

from app.listening.router import router

__all__ = ["router"]
