"""Vercel Python function entry point for the shared FastAPI application."""

from app.main import app

__all__ = ["app"]
