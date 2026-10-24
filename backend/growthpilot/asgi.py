"""ASGI entry point: uvicorn growthpilot.asgi:app"""

from .api.app import create_app

app = create_app()
