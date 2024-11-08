import os
import matplotlib.pyplot as plt
import json
import requests
import time
import io
import csv
from datetime import datetime, timedelta
from historicalData import load_historical_data_from_file


# Constants

# When calculating the stability score (2.B.1), set these to determine which is more important
# for finding a good stability value.
stdevMultiplier = 1.0   # The size of the stdev
ratioMultiplier = 2.0   # The ratio of midpoints that fall within the stdev

const_grab_recent_dates = True # When updating symbols, this tells whether to grab the whole range, or just recent data

const_date_range = 20 # The range of dates to use when testing the validity of a model

adjusted_rolling_close_open_modifier = 0.20 # default = 0.25
adjusted_weighted_price_stability_modifier = 0.15 # default = 0.20
adjusted_modified_atr_modifier = 0.15 # default = 0.20
stability_score_modifier = 0.50 # default = 0.35

combined_score_mul=[0.75,0.25]

base_path = '/workspaces/BlueHorseshoe/historical_data/'


# Functions

def graph(xLabel = 'x', yLabel = 'y', title = 'title', curves = None, lines = None, points = None):
    """
    Plots a graph with the given labels, title, curves, lines, and points.

    Usage:
        graph(xLabel='xlabel', yLabel='ylabel', title='myTitle', curves = [[1,2,3,2,1]],
            points=[{'x':1, 'y':1.75}])

    Parameters:
    xLabel (str): Label for the x-axis. Default is 'x'.
    yLabel (str): Label for the y-axis. Default is 'y'.
    title (str): Title of the graph. Default is 'title'.
    curves (list): List of dictionaries, each containing 'curve' (list of y-values) and optional 'color' (str) for the curve.
        Each curve is a dictionary with the
            curve: list of y values
            color: color of the curve
    lines (list): List of dictionaries, each containing 'y' (float) for the y-coordinate of the horizontal line, 
                    and optional 'color' (str) and 'linestyle' (str) for the line.
        Each line is a dictionary with the
            y: y value of the line
            color: color of the line
            linestyle: style of the line
    points (list): List of dictionaries, each containing 'x' (float) and 'y' (float) for the coordinates of the point, 
                    and optional 'color' (str) for the point.
        Each point is a dictionary with the
            x: x value of the point
            y: y value of the point
            color: color of the point

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
    if curves is None:
        curves = []
    if lines is None:
        lines = []
    if points is None:
        points = []
    try:
        plt.xlabel(xLabel)
        plt.ylabel(yLabel)
        plt.title(title)
        for curve in curves:
            plt.plot(curve.get('curve',[]), color=curve.get('color', 'b'))
        for line in lines:
            linestyle = line.get('linestyle', '-')
            color = line.get('color', 'g')
            plt.axhline(y=line['y'], color=color, linestyle=linestyle)
        for point in points:
            color = point.get('color', 'r')
            plt.scatter(point['x'], point['y'], color=color)
        plt.show()
    except Exception as e:
        print(f"An error occurred while plotting the graph: {e}")



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
    retval = []
    response = requests.get(f"https://www.alphavantage.co/query?function=LISTING_STATUS&apikey=JFRQJ8YWSX8UK50X")

    response.raise_for_status()  # Raise an exception for bad status codes

    # Use StringIO to treat the response content as a file
    csv_file = io.StringIO(response.text)
    reader = csv.DictReader(csv_file)

    # Store the data in a list of dictionaries
    loaded_data = list(reader)

    final_data = []
    for row in loaded_data:
        if row['status'] == 'Active' and row['exchange'] == 'NYSE' and row['assetType'] == 'Stock' and '-' not in row['symbol']:
            final_data.append({ 'symbol': row['symbol'].replace("/", ""), 'name': row['name']})

    # We shouldn't make more than one call per second. This certifies it.
    time.sleep(1)
    return final_data




def write_symbol_list_to_file(symbol_list):
    """
    Writes a list of symbols to a JSON file.

    Args:
        symbol_list (list): A list of symbols to be written to the file.

    The file is saved to the following path:
    '/content/drive/MyDrive/Projects/Programming/BlueHorseshoe/Historical Data/symbol_list.json'
    """
    file_name = '/content/drive/MyDrive/Projects/Programming/BlueHorseshoe/Historical Data/symbol_list.json'
    with open(file_name, 'w') as file:
        json.dump(symbol_list, file)




def read_symbol_list_from_file():
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
    file_name = '/content/drive/MyDrive/Projects/Programming/BlueHorseshoe/Historical Data/symbol_list.json'
    try:
        with open(file_name, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Error: File not found at {file_name}. Please check the file ID and path.")
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON data in {file_name}.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    return None



def get_symbol_list():
    """
    Retrieves a list of symbols. The function first attempts to read the symbol list from a file.
    If the file does not exist or is empty, it fetches the symbol list from the internet and writes it to the file.

    Returns:
        list: A list of symbols.
    """
    symbol_list = read_symbol_list_from_file()
    if symbol_list is None:
        symbol_list = get_symbol_list_from_net()
        write_symbol_list_to_file(symbol_list)
    return symbol_list



def get_symbol_sublist(listType, historical_data=None, symbol=''):
    """
    Generates a sublist of specific financial data from historical data.

    Args:
        listType (str): The type of data to extract. Valid options are 'high', 'low', 'open', 'close', 
                        'volume', 'midpoint', 'high_low_delta', 'open_close_delta', 
                        'high_low_delta_percentage', and 'close_open_delta_percentage'.
        historical_data (list, optional): A list of dictionaries containing historical data. 
                                            Each dictionary should have keys corresponding to the listType.
                                            If not provided, it will be loaded from a file based on the symbol.
        symbol (str, optional): The symbol for which to load historical data if historical_data is not provided.
                                Defaults to an empty string.

    Returns:
        list: A list of floats corresponding to the specified listType extracted from the historical data.

    Raises:
        ValueError: If the data in historical_data cannot be converted to float.
        TypeError: If the data in historical_data is not of the expected type.

    Usage:
        get_symbol_sublist('high', historical_data=historical_data)
        get_symbol_sublist('midpoint', symbol='QGEN')
        get_symbol_sublist('low', historical_data = load_historical_data_from_file('QGEN')['days'])

    Notes:
        - If both historical_data and symbol are not provided, the function will return an empty list.
        - If an invalid listType is provided, the function will print "Invalid listType" and continue.
    """
    if historical_data is None:
        if symbol == '':
            return retVal
        historical_data = load_historical_data_from_file(symbol)['days']

    retVal = []
    for day in historical_data:
        try:
            match listType:
                case 'high':
                    retVal.append(float(day['high']))
                case 'low':
                    retVal.append(float(day['low']))
                case 'open':
                    retVal.append(float(day['open']))
                case 'close':
                    retVal.append(float(day['close']))
                case 'volume':
                    retVal.append(float(day['volume']))
                case 'midpoint':
                    retVal.append(float(day['midpoint']))
                case 'high_low_delta':
                    retVal.append(float(day['high_low_delta']))
                case 'open_close_delta':
                    retVal.append(float(day['open_close_delta']))
                case 'high_low_delta_percentage':
                    retVal.append(float(day['high_low_delta_percentage']))
                case 'close_open_delta_percentage':
                    retVal.append(float(day['close_open_delta_percentage']))
                case _:
                    print("Invalid listType")
        except (ValueError, TypeError) as e:
            print(f"Invalid historical data. Making a list of {listType}, but the data was {e}")
            continue

    return retVal


def clip_data_to_dates(symbol='', price_data=None, end_date='', daterange=100):
    """
    Clips the given price data list to a specified date range ending at the given end date.

    Args:
        symbol (str, optional): The symbol for which to load historical data if price_data is not provided. Defaults to an empty string.
        price_data (list): A list of dictionaries containing price data with 'date' keys.
        end_date (str, optional): The end date for the date range in 'YYYY-MM-DD' format. Defaults to today's date.
        daterange (int, optional): The number of days before the end date to include in the results. Defaults to 100.

    Returns:
        list: A list of dictionaries containing price data within the specified date range.
    """
    results= []
    if end_date == '':
        end_date = datetime.today().strftime("%Y-%m-%d")
    end_date_dt = datetime.strptime(end_date, '%Y-%m-%d')
    if price_data is None:
        price_data = load_historical_data_from_file(symbol)['days']
    for day in price_data:
        current_date_dt = datetime.strptime(day['date'], '%Y-%m-%d')
        start_date_dt = end_date_dt - timedelta(days=daterange)
        if current_date_dt < end_date_dt and current_date_dt > start_date_dt:
            results.append(day)
    return results
