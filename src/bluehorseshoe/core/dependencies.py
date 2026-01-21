"""
FastAPI dependency injection providers for BlueHorseshoe.
These functions provide injectable dependencies for API routes using FastAPI's Depends() system.
"""
from typing import Generator
from fastapi import Depends, Request
from pymongo.database import Database
from .container import AppContainer
from .config import Settings

def get_container(request: Request) -> AppContainer:
    """
    Get the AppContainer from FastAPI application state.

    The container is created during app lifespan startup and stored in app.state.
    This dependency provides access to the container for all routes.

    Args:
        request: FastAPI Request object

    Returns:
        AppContainer instance from app state

    Raises:
        AttributeError: If container is not initialized in app.state
    """
    return request.app.state.container

def get_database(container: AppContainer = Depends(get_container)) -> Database:
    """
    Get MongoDB database instance.

    This is an app-scoped dependency - the same database connection
    is reused across all requests for efficiency.

    Args:
        container: AppContainer (injected by FastAPI)

    Returns:
        MongoDB Database instance
    """
    return container.get_database()

def get_config(container: AppContainer = Depends(get_container)) -> Settings:
    """
    Get application settings/configuration.

    Args:
        container: AppContainer (injected by FastAPI)

    Returns:
        Settings instance with environment-based configuration
    """
    return container.settings

def get_invalid_symbols(container: AppContainer = Depends(get_container)) -> list:
    """
    Get list of invalid symbols to exclude from processing.

    Args:
        container: AppContainer (injected by FastAPI)

    Returns:
        List of invalid symbol strings
    """
    return container.get_invalid_symbols()
