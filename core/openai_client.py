"""Shared OpenAI client singleton.

Replaces scattered _client globals across services.
Usage: from core.openai_client import get_openai_client
"""
from django.conf import settings
from openai import OpenAI

_client = None


def get_openai_client() -> OpenAI:
    """Return a shared OpenAI client instance."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client
