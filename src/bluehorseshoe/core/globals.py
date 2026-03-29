"""
Module: globals

This module provides global configurations and utility functions for the BlueHorseshoe project.
It includes functionalities for loading invalid symbols.

Note: MongoDB connections are now managed through the AppContainer class in container.py.
Use create_app_container() to get database instances instead of using global singletons.

Global Variables:
    - GlobalData.base_path (str): The base path for historical data files.
    - GlobalData.invalid_symbols (list): A list to store invalid stock symbols.

Functions:
    - load_invalid_symbols(): Loads invalid symbols from a file and stores them in GlobalData.

Classes:
    - GlobalData: Dataclass containing global configuration data.
"""

import logging
from dataclasses import dataclass, field

from bluehorseshoe.core.config import REPO_ROOT
from bluehorseshoe.core.invalid_symbols import load_invalid_symbols as load_invalid_symbols_file
from bluehorseshoe.core.invalid_symbols import resolve_invalid_symbols_path

@dataclass
class GlobalData:
    """
    A class used to represent global data for the BlueHorseshoe project.

    Attributes
    ----------
    BASE_PATH : str
        The base path for historical data files.
    INVALID_SYMBOLS : list
        A list to store invalid stock symbols.

    Note: MongoDB connections are now managed through AppContainer instead of global state.
    """
    base_path: str = f'{REPO_ROOT}/src/historical_data/'
    invalid_symbols: list = field(default_factory=list)

# MongoDB connections are now managed through the AppContainer class
# Use create_app_container() to get a database instance instead of this global function

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
    invalid_symbols_file_path = resolve_invalid_symbols_path(GlobalData.base_path)
    GlobalData.invalid_symbols = load_invalid_symbols_file(invalid_symbols_file_path)
    if not GlobalData.invalid_symbols:
        logging.error("Error: File not found at %s. Please check the file path.", invalid_symbols_file_path)
load_invalid_symbols()
