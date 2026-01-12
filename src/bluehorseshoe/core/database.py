"""
Database connection and configuration module.
"""
import os
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017")
DB_NAME = os.environ.get("MONGO_DB", "bluehorseshoe")

class Database:
    """
    Singleton wrapper for MongoDB client connection.
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

# Global instance
db = Database()
