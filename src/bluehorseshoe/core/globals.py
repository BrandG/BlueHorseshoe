"""
Module: globals

This module provides various global configurations, utility functions, and classes for the BlueHorseshoe project.
It includes functionalities for loading invalid symbols, managing a singleton report file, connecting to MongoDB,
plotting graphs, and fetching stock symbols from the internet or a file.

Imports:
    - json
    - io
    - csv
    - logging
    - os
    - datetime
    - dataclasses
    - pymongo
    - requests
    - matplotlib.pyplot
    - ratelimit
    - pymongo.errors
    - matplotlib.ticker

Global Variables:
    - BASE_PATH (str): The base path for historical data files.
    - MONGO_CLIENT (pymongo.MongoClient): The MongoDB client instance.
    - invalid_symbols (list): A list to store invalid stock symbols.

Functions:
    - load_invalid_symbols(): Loads invalid symbols from a file and stores them in the global variable `invalid_symbols`.
    - get_mongo_client(uri="", db_name="blueHorseshoe"): Creates and returns a MongoDB client connected to the specified URI and database.
    - graph(graph_data: GraphData): Plots a graph with the given labels, title, curves, lines, and points.
    - get_symbol_list_from_net(): Fetches a list of active stock symbols from the NYSE exchange using the Alpha Vantage API.
    - get_symbol_list_from_file(): Reads a list of symbols from a JSON file.
    - get_symbol_name_list(): Retrieves a list of symbol names.
    - get_symbol_list(): Retrieves a list of symbols from a file or the internet.

Classes:
    - ReportSingleton: A singleton class to manage writing to a report file.
    - GraphData: A class used to represent data for a graph.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional
import pymongo
from pymongo.errors import ConnectionFailure, ConfigurationError

@dataclass
class GlobalData:
    """
    A class used to represent global data for the BlueHorseshoe project.

    Attributes
    ----------
    BASE_PATH : str
        The base path for historical data files.
    MONGO_CLIENT : pymongo.MongoClient
        The MongoDB client instance.
    INVALID_SYMBOLS : list
        A list to store invalid stock symbols.
    """
    base_path: str = '/workspaces/BlueHorseshoe/src/historical_data/'
    mongo_client: Optional[pymongo.MongoClient] = None
    invalid_symbols: list = field(default_factory=list)
    holiday:bool = False # define whether yesterday was a holiday

def get_mongo_client(uri="", db_name="blueHorseshoe"):
    """
    Creates and returns a MongoDB client connected to the specified URI and database.

    Args:
        uri (str): The URI for the MongoDB connection. Default is "mongodb://localhost:27017/".
        db_name (str): The name of the database to connect to. Default is "blueHorseshoe".

    Returns:
        pymongo.database.Database: The database client connected to the specified database.
    """
    if GlobalData.mongo_client is None:
        try:
            if uri == "":
                uri = os.getenv("MONGO_URI", "mongodb://mongo:27017")
            GlobalData.mongo_client = pymongo.MongoClient(uri)
            # MONGO_CLIENT = MongoClient(
            #     uri, connectTimeoutMS=2000, serverSelectionTimeoutMS=2000)
            server_info = GlobalData.mongo_client.server_info()
            logging.info("Connected to MongoDB server version %s",
                         server_info['version'])
        except (ConnectionFailure, ConfigurationError) as e:
            logging.error(
                "An error occurred while connecting to MongoDB: %s", e)
            return None

    return GlobalData.mongo_client.get_database(db_name)

def load_invalid_symbols():
    """
    Loads invalid symbols from a file and stores them in the global variable `invalid_symbols`.

    The function attempts to read a file named 'invalid_symbols.txt' located in the directory specified by `BASE_PATH`.
    Each line in the file is expected to contain one invalid symbol. Empty lines are ignored.

    Raises:
        FileNotFoundError: If the file does not exist at the specified path.
        UnicodeDecodeError: If the file cannot be decoded using UTF-8 encoding.
        OSError, IOError: If an error occurs while reading the file.

    Logs:
        An error message if the file is not found, cannot be decoded, or if any other I/O error occurs.
    """
    GlobalData.invalid_symbols = []
    invalid_symbols_file_path = os.path.join(GlobalData.base_path, 'invalid_symbols.txt')
    try:
        with open(invalid_symbols_file_path, 'r', encoding='utf-8') as file:
            GlobalData.invalid_symbols = [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        logging.error("Error: File not found at %s. Please check the file path.", invalid_symbols_file_path)
    except UnicodeDecodeError:
        logging.error("Error: Unable to decode the file %s. Please check the file encoding.", invalid_symbols_file_path)
    except (OSError, IOError) as e:
        logging.error("An error occurred while reading the file: %s", e)
load_invalid_symbols()
