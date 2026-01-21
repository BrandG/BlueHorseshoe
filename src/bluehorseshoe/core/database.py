"""
Database connection and configuration module.

DEPRECATED: This module is deprecated in favor of dependency injection via AppContainer.
New code should use:
    from bluehorseshoe.core.container import create_app_container
    container = create_app_container()
    db = container.get_database()

This module is maintained for backward compatibility only.
"""
import os
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017")
DB_NAME = os.environ.get("MONGO_DB", "bluehorseshoe")

class Database:
    """
    Singleton wrapper for MongoDB client connection.

    DEPRECATED: Use dependency injection via AppContainer instead.
    """
    client: MongoClient = None
    db = None

    def connect(self):
        """Establish connection to MongoDB."""
        self.client = MongoClient(MONGO_URI)
        self.db = self.client[DB_NAME]

    def get_db(self):
        """Return the database instance, connecting if necessary."""
        if self.db is None:
            self.connect()
        return self.db

# Global instance (DEPRECATED - for backward compatibility only)
# New code should use AppContainer for dependency injection
db = Database()
