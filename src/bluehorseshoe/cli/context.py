"""
CLI Context Manager for BlueHorseshoe command-line scripts.
Provides dependency injection for CLI mode with proper resource lifecycle management.
"""
from contextlib import contextmanager
from typing import Generator
from bluehorseshoe.core.container import create_app_container, AppContainer
from bluehorseshoe.core.config import Settings
from bluehorseshoe.reporting.report_generator import ReportWriter
from pymongo.database import Database


class CLIContext:
    """
    Context object containing all dependencies needed for CLI operations.
    This provides a clean interface for accessing injected dependencies.
    """

    def __init__(self, container: AppContainer, report_writer: ReportWriter):
        """
        Initialize CLI context with container and report writer.

        Args:
            container: AppContainer with app-scoped resources
            report_writer: ReportWriter for CLI output
        """
        self._container = container
        self._report_writer = report_writer

    @property
    def container(self) -> AppContainer:
        """Access to the full container if needed."""
        return self._container

    @property
    def config(self) -> Settings:
        """Access to application settings."""
        return self._container.settings

    @property
    def db(self) -> Database:
        """Access to MongoDB database."""
        return self._container.get_database()

    @property
    def report_writer(self) -> ReportWriter:
        """Access to report writer for logging."""
        return self._report_writer

    @property
    def invalid_symbols(self) -> list:
        """Access to list of invalid symbols."""
        return self._container.get_invalid_symbols()


@contextmanager
def create_cli_context() -> Generator[CLIContext, None, None]:
    """
    Create a CLI context manager with proper resource lifecycle.

    This context manager:
    - Creates an AppContainer for app-scoped resources
    - Creates a ReportWriter for CLI output
    - Provides clean access to all dependencies
    - Ensures proper cleanup on exit

    Usage:
        with create_cli_context() as ctx:
            trader = SwingTrader(
                database=ctx.db,
                config=ctx.config,
                report_writer=ctx.report_writer
            )
            # Use trader...

    Yields:
        CLIContext with all injected dependencies
    """
    # Create container
    container = create_app_container()

    # Create report writer for CLI output
    report_path = f"{container.settings.logs_path}/report.txt"
    report_writer = ReportWriter(log_path=report_path)

    # Create context object
    ctx = CLIContext(container=container, report_writer=report_writer)

    try:
        yield ctx
    finally:
        # Cleanup resources
        report_writer.close()
        container.close()
