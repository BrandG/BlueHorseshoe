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
import io
import csv
import logging
import os
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional, Union
import pymongo
import requests
import matplotlib.pyplot as plt
from ratelimit import limits, sleep_and_retry #pylint: disable=import-error
from pymongo.errors import ConnectionFailure, ConfigurationError
from matplotlib.ticker import MultipleLocator

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
    BASE_PATH: str = '/workspaces/BlueHorseshoe/src/historical_data/'
    MONGO_CLIENT: Optional[pymongo.MongoClient] = None
    INVALID_SYMBOLS: list = field(default_factory=list)
    HOLIDAY:bool = False # define whether yesterday was a holiday

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
    invalid_symbols_file_path = os.path.join(GlobalData.BASE_PATH, 'invalid_symbols.txt')
    try:
        with open(invalid_symbols_file_path, 'r', encoding='utf-8') as file:
            GlobalData.INVALID_SYMBOLS = [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        logging.error("Error: File not found at %s. Please check the file path.", invalid_symbols_file_path)
    except UnicodeDecodeError:
        logging.error("Error: Unable to decode the file %s. Please check the file encoding.", invalid_symbols_file_path)
    except (OSError, IOError) as e:
        logging.error("An error occurred while reading the file: %s", e)
load_invalid_symbols()

def get_symbol_name_list():
    """
    Retrieves a list of symbol names.

    This function calls `get_symbol_list()` to get a list of symbols, 
    and then extracts and returns the 'symbol' field from each symbol in the list.

    Returns:
        list: A list of symbol names.
    """
    symbol_list = get_symbol_list()
    return [symbol['symbol'] for symbol in symbol_list]

def get_mongo_client(uri="", db_name="blueHorseshoe"):
    """
    Creates and returns a MongoDB client connected to the specified URI and database.

    Args:
        uri (str): The URI for the MongoDB connection. Default is "mongodb://localhost:27017/".
        db_name (str): The name of the database to connect to. Default is "blueHorseshoe".

    Returns:
        pymongo.database.Database: The database client connected to the specified database.
    """
    if GlobalData.MONGO_CLIENT is None:
        try:
            if uri == "":
                uri = os.getenv("MONGO_URI", "mongodb://mongo:27017")
            GlobalData.MONGO_CLIENT = pymongo.MongoClient(uri)
            # MONGO_CLIENT = MongoClient(
            #     uri, connectTimeoutMS=2000, serverSelectionTimeoutMS=2000)
            server_info = GlobalData.MONGO_CLIENT.server_info()
            logging.info("Connected to MongoDB server version %s",
                         server_info['version'])
        except (ConnectionFailure, ConfigurationError) as e:
            logging.error(
                "An error occurred while connecting to MongoDB: %s", e)
            return None

    return GlobalData.MONGO_CLIENT[db_name]

@dataclass
class GraphData:
    """
    A class used to represent data for a graph.

    Attributes
    ----------
    x_label : str
        The label for the x-axis (default is 'x')
    y_label : str
        The label for the y-axis (default is 'y')
    title : str
        The title of the graph (default is 'title')
    curves : list
        A list to store curve data (default is an empty list)
    lines : list
        A list to store line data (default is an empty list)
    points : list
        A list to store point data (default is an empty list)
    x_values : list
        A list to store x-axis values (default is an empty list)
    """
    curves: list = field(default_factory=list)
    points: list = field(default_factory=list)
    x_values: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    x_label: str = 'x'
    y_label: str = 'y'
    title: str = 'title'


def graph(graph_data: GraphData):
    """
    Plots a graph with the given labels, title, curves, lines, and points.

    Usage:
        graph(x_label='x_label', y_label='y_label', title='myTitle', curves = [[1,2,3,2,1]],
            points=[{'x':1, 'y':1.75}])

    Parameters:
    x_label (str): Label for the x-axis. Default is 'x'.
    y_label (str): Label for the y-axis. Default is 'y'.
    title (str): Title of the graph. Default is 'title'.
    curves (list): List of dictionaries, each containing 'curve' (list of y-values) and optional 'color' (str) for the curve.
        Each curve is a dictionary with the
            curve: list of y values
            color: color of the curve
            label: label for the legend (optional)
    lines (list): List of dictionaries, each containing 'y' (float) for the y-coordinate of the horizontal line,
        Each line is a dictionary with the
            y: y-coordinate of the line
            color: color of the line (optional)
            linestyle: style of the line (optional)
            label: label for the legend (optional)
    points (list): List of dictionaries, each containing 'x' (float) and 'y' (float) for the coordinates of the point.
        Each point is a dictionary with the
            x: x-coordinate of the point
            y: y-coordinate of the point
            color: color of the point
            label: label for the legend (optional)

    The color is a string that represents the color of the curve, line, or point. It can be any of the following:
        b: blue
        g: green
        r: red
        c: cyan
        m: magenta
        y: yellow
        k: black
        w: white

    The linestyle is a string that represents the style of the line. It can be any of the following:
        -: solid line
        --: dashed line
        -.: dash-dot line
        : dotted line

    Returns:
        None
    """
    if graph_data.curves is None:
        graph_data.curves = []
    if graph_data.lines is None:
        graph_data.lines = []
    if graph_data.points is None:
        graph_data.points = []
    try:
        if graph_data.x_values is not None and len(graph_data.x_values) != 0:
            plt.xticks(ticks=range(len(graph_data.x_values)),
                       labels=graph_data.x_values, rotation=45)
        plt.xlabel(graph_data.x_label)
        plt.ylabel(graph_data.y_label)
        plt.title(graph_data.title)
        for curve in graph_data.curves:
            plt.plot(curve.get('curve', []), color=curve.get(
                'color', 'b'), label=curve.get('label', 'Curve'))
        for line in graph_data.lines:
            linestyle = line.get('linestyle', '-')
            color = line.get('color', 'g')
            plt.axhline(y=line['y'], color=color,
                        linestyle=linestyle, label=line.get('label', 'Line'))
        for point in graph_data.points:
            color = point.get('color', 'r')
            plt.scatter(point['x'], point['y'], color=color)
        plt.legend()  # Add this line to show the legend
        plt.gca().xaxis.set_major_locator(MultipleLocator(20))
        plt.grid(which='both', linestyle='--', linewidth=0.5)
        current_time_ms = int(datetime.now().timestamp() * 1000)
        plt.savefig(f'/workspaces/BlueHorseshoe/src/graphs/{graph_data.title}_{current_time_ms}.png')
        # plt.show()
        plt.clf()
    except (ValueError, TypeError, KeyError) as e:
        logging.error("An error occurred while plotting the graph: %s", e)


@sleep_and_retry
@limits(calls=1, period=1)
def get_symbol_list_from_net():
    """
    Fetches a list of active stock symbols from the NYSE exchange using the Alpha Vantage API.

    This function makes an HTTP GET request to the Alpha Vantage API to retrieve a CSV file containing
    the listing status of various assets. It then filters the data to include only active stocks listed
    on the NYSE exchange, excluding symbols that contain a hyphen.

    Returns:
        list: A list of dictionaries, each containing the 'symbol' and 'name' of an active stock on the NYSE.

    Raises:
        requests.exceptions.HTTPError: If the HTTP request returned an unsuccessful status code.
    """
    response = requests.get(
        "https://www.alphavantage.co/query?function=LISTING_STATUS&apikey=JFRQJ8YWSX8UK50X", timeout=10)

    response.raise_for_status()  # Raise an exception for bad status codes

    # Use StringIO to treat the response content as a file
    csv_file = io.StringIO(response.text)
    reader = csv.DictReader(csv_file)

    # Store the data in a list of dictionaries
    loaded_data = list(reader)

    final_data = []
    for row in loaded_data:
        if (row['status'] == 'Active' and
            (row['exchange'] == 'NYSE' or row['exchange'] == 'NASDAQ') and
            row['assetType'] == 'Stock' and
                '-' not in row['symbol']):
            final_data.append({
                'symbol': row['symbol'].replace("/", ""),
                'name': row['name']
            })

    return final_data


def get_symbol_list_from_file():
    """
    Reads a list of symbols from a JSON file.

    The function attempts to open and read a JSON file containing a list of symbols.
    If the file is not found, it prints an error message indicating the file path.
    If the JSON data is invalid, it prints an error message indicating the issue.
    For any other exceptions, it prints a generic error message with the exception details.

    Returns:
        list: A list of symbols if the file is successfully read and parsed.
        None: If an error occurs during file reading or parsing.
    """
    file_path = os.path.join(GlobalData.BASE_PATH, 'symbol_list.json')
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        logging.error(
            "Error: File not found at %s. Please check the file path.", file_path)
    except UnicodeDecodeError:
        logging.error(
            "Error: Unable to decode the file %s. Please check the file encoding.", file_path)
    except json.JSONDecodeError:
        logging.error("Error: Invalid JSON data in %s.", file_path)
    except (OSError, IOError) as e:
        logging.error("An error occurred while reading the file: %s", e)

    logging.error("Error: Could not open file %s. Please check the logs.", file_path)
    return None

def get_symbol_list():
    """
    Retrieves a list of symbols. The function first attempts to read the symbol list from a file.
    If the file does not exist or is empty, it fetches the symbol list from the internet and writes it to the file.

    Returns:
        list: A list of symbols.
    """
    symbol_list = get_symbol_list_from_file()
    if symbol_list is None:
        symbol_list = get_symbol_list_from_net()
        if symbol_list is None:
            return []
        file_path = os.path.join(GlobalData.BASE_PATH, 'symbol_list.json')

        # Create the directory if it does not exist
        os.makedirs(GlobalData.BASE_PATH, exist_ok=True)

        try:
            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(symbol_list, file)
        except (OSError, IOError, json.JSONDecodeError) as e:
            logging.error(
                "An error occurred while writing the symbol list to file: %s", e)

    logging.info("Symbol list loaded. Length: %d", len(symbol_list))
    return [symbol for symbol in symbol_list if symbol['symbol'] not in GlobalData.INVALID_SYMBOLS]

class ReportSingleton:
    """
    A thread-safe singleton class to manage writing to a report file.
    
    This class implements a singleton pattern with proper thread safety, file handling,
    and context management. It ensures atomic writes and proper resource cleanup.
    
    Attributes:
        _instance (ReportSingleton): The singleton instance
        _lock (Lock): Thread lock for synchronization
        _file (Optional[TextIOWrapper]): File handle for the report
        
    Examples:
        >>> with ReportSingleton() as report:
        ...     report.write("Log entry")
        
        >>> report = ReportSingleton()
        >>> report.write("Regular log entry")
        >>> report.close()
    """
    _instance: Optional['ReportSingleton'] = None
    _lock = Lock()

    def __new__(cls) -> 'ReportSingleton':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        with self._lock:
            if not getattr(self, '_initialized', False):
                self._file = None
                self._write_lock = Lock()
                self._log_path = Path("/workspaces/BlueHorseshoe/src/logs/report.txt")
                self._initialize_file()
                self._initialized = True

    def _initialize_file(self) -> None:
        """Initialize the log file with proper directory creation and error handling."""
        try:
            # Ensure log directory exists
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

            # Open file with explicit newline handling
            self._file = open( # pylint: disable=consider-using-with
                self._log_path,
                mode="w",
                encoding="utf-8",
                newline='\n',
                buffering=1  # Line buffering
            )
        except (OSError, IOError) as e:
            logging.error("Failed to initialize report file: %s", str(e))
            raise RuntimeError(f"Could not initialize report file: {e}") from e

    def write(self, content: Union[str, dict, list]) -> None:
        """
        Thread-safe method to write content to the report file.
        
        Args:
            content: Content to write (string, dict, or list)
            
        Raises:
            RuntimeError: If file is closed or write fails
        """
        if self._file is None:
            raise RuntimeError("Attempted to write to a closed report file")

        try:
            with self._write_lock:
                if isinstance(content, (dict, list)):
                    formatted_content = json.dumps(content, indent=4, ensure_ascii=False)
                else:
                    formatted_content = str(content)

                self._file.write(formatted_content + '\n')
                self._file.flush()
                os.fsync(self._file.fileno())  # Ensure write to disk

        except (IOError, OSError) as e:
            logging.error("Failed to write to report file: %s", str(e))
            raise RuntimeError(f"Failed to write to report file: {e}") from e

    def close(self) -> None:
        """
        Safely close the report file with proper error handling.
        
        This method is thread-safe and idempotent.
        """
        with self._lock:
            if self._file is not None:
                try:
                    self._file.flush()
                    os.fsync(self._file.fileno())
                    self._file.close()
                except (IOError, OSError) as e:
                    logging.error("Error closing report file: %s", str(e))
                finally:
                    self._file = None

    def __enter__(self) -> 'ReportSingleton':
        """Enable context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ensure proper cleanup when used as context manager."""
        self.close()

    def __del__(self) -> None:
        """Ensure file is closed when object is garbage collected."""
        self.close()

    @property
    def is_open(self) -> bool:
        """Check if the report file is currently open."""
        return self._file is not None and not self._file.closed

    @classmethod
    def reset(cls) -> None:
        """
        Reset the singleton instance.
        
        This is primarily useful for testing purposes.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None
