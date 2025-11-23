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
import mplfinance as mpf #pylint: disable=import-error

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

@dataclass
class GraphData:
    """
    A class used to represent data for a graph.

    Attributes
    ----------
    labels : dict
        A dictionary to store labels for the x-axis, y-axis, and title.
    curves : list
        A list to store curve data (default is an empty list)
    lines : list
        A list to store line data (default is an empty list)
    points : list
        A list to store point data (default is an empty list)
    x_values : list
        A list to store x-axis values (default is an empty list)
    candles : list
        A list to store candlestick data (default is an empty list)
    """
    labels: dict = field(default_factory=lambda: {'x_label': 'x', 'y_label': 'y', 'title': 'title'})
    curves: list = field(default_factory=list)
    points: list = field(default_factory=list)
    x_values: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    candles: list = field(default_factory=list)


def graph(graph_data: GraphData) -> str:
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
    if graph_data.candles is None:
        graph_data.candles = []
    try:
        if graph_data.x_values is not None and len(graph_data.x_values) != 0:
            plt.xticks(ticks=range(len(graph_data.x_values)),
                       labels=graph_data.x_values, rotation=45)
        plt.xlabel(graph_data.labels['x_label'])
        plt.ylabel(graph_data.labels['y_label'])
        plt.title(graph_data.labels['title'])
        for candle in graph_data.candles:
            data = {
                'date': graph_data.x_values,
                'open': candle['open'],
                'high': candle['high'],
                'low': candle['low'],
                'close': candle['close'],
                'volume': candle['volume']
            }
            mpf.plot(data, type='candle', style='charles', title='Candlestick Chart', ylabel='Price', volume=True)
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
        current_time_ms = int(datetime.now().timestamp()) * 1000
        file_path = f'/workspaces/BlueHorseshoe/src/graphs/{graph_data.labels["title"]}_{current_time_ms}.png'
        plt.savefig(file_path)
        # plt.show()
        plt.gcf().canvas.draw_idle()
        plt.clf()
        return file_path
    except (ValueError, TypeError, KeyError) as e:
        logging.error("An error occurred while plotting the graph: %s", e)
        plt.gcf().canvas.draw_idle()
        plt.clf()
    return ""


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
                self.log_path = Path("/workspaces/BlueHorseshoe/src/logs/report.txt")
                self._initialize_file()
                self._initialized = True

    def _initialize_file(self) -> None:
        """Initialize the log file with proper directory creation and error handling."""
        try:
            # Ensure log directory exists
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

            # Open file with explicit newline handling
            self._file = open( # pylint: disable=consider-using-with
                self.log_path,
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
                    self._initialized = False

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
