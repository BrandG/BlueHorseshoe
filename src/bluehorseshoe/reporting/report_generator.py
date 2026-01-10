import json
import logging
import os
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional, Union
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import mplfinance as mpf #pylint: disable=import-error

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
            self._file = open(
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
        Thread-safe method to write content to the report file and stdout.
        """
        if self._file is None:
            raise RuntimeError("Attempted to write to a closed report file")

        try:
            with self._write_lock:
                if isinstance(content, (dict, list)):
                    formatted_content = json.dumps(content, indent=4, ensure_ascii=False)
                else:
                    formatted_content = str(content)

                # Write to file
                self._file.write(formatted_content + '\n')
                self._file.flush()
                os.fsync(self._file.fileno())  # Ensure write to disk

                # Also print to console
                print(formatted_content)

        except (IOError, OSError) as e:
            logging.error("Failed to write to report file: %s", str(e))
            raise RuntimeError(f"Failed to write to report file: {e}") from e

    def close(self) -> None:
        """
        Safely close the report file with proper error handling.
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
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None
