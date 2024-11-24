import os
import matplotlib.pyplot as plt
import json
import requests
import io
import csv
from datetime import datetime, timedelta
from ratelimit import limits, sleep_and_retry
import logging
from pymongo import MongoClient


# When calculating the stability score (2.B.1), set these to determine which is more important
# for finding a good stability value.
stdevMultiplier = 1.0   # The size of the stdev
ratioMultiplier = 1.0   # The ratio of midpoints that fall within the stdev

const_grab_recent_dates = True # When updating symbols, this tells whether to grab the whole range, or just recent data

const_date_range = 20 # The range of dates to use when testing the validity of a model

adjusted_rolling_close_open_modifier = 0.20 # default = 0.25
adjusted_weighted_price_stability_modifier = 0.15 # default = 0.20
adjusted_modified_atr_modifier = 0.15 # default = 0.20
stability_score_modifier = 0.50 # default = 0.35

combined_score_mul=[0.75,0.25]

base_path = '/workspaces/BlueHorseshoe/historical_data/'

invalid_symbols = ['AJXA','APGB','AQNA','ARGO','BBLN','BCPA','BCPB', 'BFX','BMAC','BOAC','BODY','CBX','CCV',
                   'CPTK','CSTA','CTEST','ECG','EOCW','FSNB','GCTSW','HT','HYLN','INGM','ISG','JHAA','LHC','OSG','PNSTWS',
                   'PRMB','ROSS','SCU','SIX','TMAC','USX','VMW','MTEST','NTEST','ASGI','CMSA', 'RBCP', 'GFR', 'GOOS', 
                   'HBI', 'HOMB', 'QTWO', 'ZBH', 'INST','RCFA','SAVE', 'DLY', 'AEVA', 'GFL', 'CARR', 'OTIS', 'RFM', 'BIPC', 
                   'MPLN', 'SPHR', 'RSI', 'SKLZ', 'APG', 'ADCT', 'SLQT', 'DNMR', 'AFGD', 'FOUR', 'SBBA', 'AZEK', 'ETWO', 
                   'HAFN', 'MP', 'ACI', 'FTHY', 'SII', 'DNB', 'LMND', 'BFLY', 'ALIT', 'MEG', 'BEPC', 'RKT', 'SST', 'BEKE', 
                   'NTST', 'ML', 'QS', 'NYC', 'UZD', 'MIR', 'NUVB', 'NDMO', 'XPEV', 'GB', 'PFH', 'RBOT', 'SNOW', 'AMWL', 'U', 
                   'GETY', 'SOJE', 'BCAT', 'VNT', 'MGRB', 'ASAN', 'BQ', 'PLTR', 'YALA', 'ATIP', 'DTB', 'MKFG', 'STEM', 'IH', 
                   'OUST', 'PSFE', 'MNSO', 'TIMB', 'BNH', 'GHLD', 'CRC', 'GATO', 'MAX', 'PTA', 'LU', 'SPIR', 'OWLT', 'GRNT', 
                   'JOBY', 'UP', 'LICY', 'BKKT', 'YSG', 'OPFI', 'GBTG', 'AIZN', 'SDHY', 'NRDY', 'NOTE', 'AI', 'SMR', 'OPAD', 
                   'OWL', 'UZE', 'ACHR', 'BARK', 'GWH', 'IONQ', 'EVEX', 'KUKE', 'GRND', 'DFH', 'MYTE', 'RLX', 'ZIM', 'AMPS', 
                   'FRGE', 'ONTF', 'TIXT', 'SMRT', 'LDI', 'TFSA', 'PKST', 'RCC', 'BWSN', 'RFMZ', 'PERF', 'SES', 'OSCR', 'UWMC', 
                   'ASAI', 'CSAN', 'RBLX', 'CPNG', 'HAYW', 'LANV', 'OLO', 'NAPA', 'TUYA', 'BNL', 'DOCN', 'KIND', 'SEMR', 
                   'VZIO', 'BIGZ', 'ZH', 'ECCW', 'NXU', 'COUR', 'COMP', 'HTFB', 'AGL', 'BEPH', 'DNA', 'LOCL', 'DV', 'GENI', 
                   'KKRS', 'PATH', 'BOWL', 'PL', 'EDR', 'NPCT', 'BRCC', 'BRW', 'LEV', 'WDH', 'SMWB', 'GROV', 'OGN', 'GPOR', 
                   'PCOR', 'BIPH', 'NBXG', 'PAY', 'UZF', 'ZIP', 'FCRX', 'FIGS', 'HGTY', 'NE', 'ZETA', 'ECCC', 'TPTA', 'AOMR', 
                   'RERE', 'YMM', 'CXM', 'DOCS', 'NEUE', 'MCW', 'WDI', 'BNT', 'DDL', 'S', 'YOU', 'CURV', 'DTM', 'PSQH', 'FREY', 
                   'OKLO', 'SHCO', 'BLND', 'BRDG', 'STVN', 'FLYX', 'NABL', 'LAW', 'VSCO', 'VTEX', 'CNM', 'GXO', 'RYAN', 'ZVIA', 
                   'MGRD', 'XPOF', 'MLNK', 'COOK', 'RSKD', 'DOLE', 'ECVT', 'HIPO', 'AMBP', 'MIO', 'NPWR', 'JXN', 'RDW', 'BROS', 
                   'ONON', 'MTAL', 'AKA', 'TOST', 'SLVM', 'CWAN', 'ECAT', 'WRBY', 'BHIL', 'TFPM', 'KORE', 'VLN', 'WBX', 'CION', 
                   'LTH', 'IHS', 'FNA', 'EICA', 'FBRT', 'ENFN', 'PX', 'ARIS', 'KD', 'INFA', 'MEGI', 'BXSL', 'DTC', 'CBL', 'CMTG', 
                   'CDRE', 'NXDT', 'PRM', 'CINT', 'WEAV', 'ONL', 'SG', 'NMAI', 'GUG', 'DTG', 'CTV', 'CRGY', 'NU', 'BEPI', 'EVTL', 
                   'IOT', 'NPFD', 'BBAI', 'BWNB', 'ZGN', 'DOUG', 'DMA', 'MNTN', 'WEL', 'SOAR', 'BIPI', 'ECCV', 'PAXS', 'SGHC', 
                   'BFAC', 'MDV', 'RMMZ', 'NRGV', 'RLTY', 'BBUC', 'PNST', 'KMPB', 'PGRU', 'ESAB', 'STEW', 'EE', 'SAT', 'BLCO', 
                   'HTFC', 'EHAB', 'HKD', 'HLN', 'QBTS', 'HLLY', 'AMPX', 'CRBG', 'XPER', 'BHVN', 'LVWR', 'RZC', 'SDRL', 'HSHP', 
                   'BMN', 'RXO', 'NXG', 'SAJ', 'FSCO', 'BKDT', 'FG', 'BAM', 'MBC', 'SAY', 'VTS', 'TXO', 'ASBA', 'AESI', 'CLCO', 
                   'CR', 'MSGE', 'SAZ', 'KVUE', 'ATMU', 'KNF', 'AACT', 'CAVA', 'PHIN', 'FIHL', 'KGS', 'SVV', 'VTMX', 'LZM', 'SRFM', 
                   'EICB', 'SN', 'ALUR', 'ECO', 'EXTO', 'BETR', 'APOS', 'TKO', 'HYAC', 'KVYO', 'KLG', 'PMTU', 'LAC', 'LAAC', 'VLTO', 
                   'VSTS', 'BIRK', 'MNR', 'CCIA', 'NLOP', 'HG', 'WS', 'FGN', 'ZKH', 'DEC', 'CDLR', 'IROHU', 'ELPC', 'ALTM', 'CLBR', 
                   'SDHC', 'PSBD', 'MFAN', 'MSDL', 'NCDL', 'OBDE', 'AS', 'ANRO', 'RWTN', 'MITN', 'AHR', 'TBBB', 'SOC', 'BODI', 'ATHS', 
                   'CTOS', 'RDDT', 'AUNA', 'DXYZ', 'SOLV', 'BEPJ', 'GCTS', 'GEV', 'MGRE', 'WNS', 'PACS', 'ULS', 'CTRI', 'IBTA', 
                   'MFAO', 'LOAR', 'RBRK', 'VIK', 'ZK', 'MITP', 'KBDC', 'BOW', 'CIMN', 'BIPJ', 'SPMC', 'RWTO', 'TBN', 'LB', 'SW', 
                   'ARDT', 'PDCC', 'CON', 'AOMN', 'SMC', 'CIMO', 'AAM', 'AMTM', 'BKV', 'CURB', 'GRDN', 'EQV', 'FVR', 'SARO', 'CBNA', 
                   'SBXD', 'CICB', 'KLC']
MyMongoClient = None

def get_mongo_client(uri="mongodb://localhost:27017/", db_name="blueHorseshoe"):
    """
    Creates and returns a MongoDB client connected to the specified URI and database.

    Args:
        uri (str): The URI for the MongoDB connection. Default is "mongodb://localhost:27017/".
        db_name (str): The name of the database to connect to. Default is "blueHorseshoe".

    Returns:
        pymongo.database.Database: The database client connected to the specified database.
    """
    global MyMongoClient
    if MyMongoClient is None:
        try:
            MyMongoClient = MongoClient(uri, connectTimeoutMS=1000, serverSelectionTimeoutMS=1000)
            server_info = MyMongoClient.server_info()
            logging.info(f"Connected to MongoDB server version {server_info['version']}")
        except Exception as e:
            logging.error(f"An error occurred while connecting to MongoDB: {e}")
            return None

    return MyMongoClient[db_name]

def graph(xLabel = 'x', yLabel = 'y', title = 'title', curves = None, lines = None, points = None, x_values = None):
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
        if x_values is not None and len(x_values) != 0:
            plt.xticks(ticks=range(len(x_values)), labels=x_values, rotation=45)
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
        current_time_ms = int(datetime.now().timestamp() * 1000)
        plt.savefig(f'graphs/{title}_{current_time_ms}.png')
        # plt.show()
        plt.clf()
    except Exception as e:
        logging.error(f"An error occurred while plotting the graph: {e}")



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
    response = requests.get("https://www.alphavantage.co/query?function=LISTING_STATUS&apikey=JFRQJ8YWSX8UK50X")

    response.raise_for_status()  # Raise an exception for bad status codes

    # Use StringIO to treat the response content as a file
    csv_file = io.StringIO(response.text)
    reader = csv.DictReader(csv_file)

    # Store the data in a list of dictionaries
    loaded_data = list(reader)

    final_data = []
    for row in loaded_data:
        if (row['status'] == 'Active' and 
            row['exchange'] == 'NYSE' and 
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
    file_path = os.path.join(base_path, 'symbol_list.json')
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        logging.error(f"Error: File not found at {file_path}. Please check the file path.")
    except UnicodeDecodeError:
        logging.error(f"Error: Unable to decode the file {file_path}. Please check the file encoding.")
    except json.JSONDecodeError:
        logging.error(f"Error: Invalid JSON data in {file_path}.")
    except Exception as e:
        logging.error(f"An unexpected error of type {type(e).__name__} occurred: {e}")
        
    print(f"Error: Could not open file {file_path}. Please check the logs.")
    return None

def get_symbol_name_list():
    symbol_list = get_symbol_list()
    return [symbol['symbol'] for symbol in symbol_list]

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
        file_path = os.path.join(base_path, 'symbol_list.json')

        # Create the directory if it does not exist
        os.makedirs(base_path, exist_ok=True)

        try:
            with open(file_path, 'w') as file:
                json.dump(symbol_list, file)
        except Exception as e:
            logging.error(f"An error occurred while writing the symbol list to file: {e}")
    symbol_list = [symbol for symbol in symbol_list if symbol['symbol'] not in invalid_symbols]
    return symbol_list



def get_symbol_sublist(listType, historical_data=None):
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
        get_symbol_sublist('low', historical_data = load_historical_data('QGEN')['days'])

    Notes:
        - If both historical_data and symbol are not provided, the function will return an empty list.
        - If an invalid listType is provided, the function will write a warning to the log and return an empty list.
    """
    if historical_data is None:
        logging.warning("No historical data provided. Please provide historical data or a symbol.")
        return []

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
                    logging.warning("Invalid listType")
        except (ValueError, TypeError) as e:
            logging.warning(f"Invalid historical data. Making a list of {listType}, but the data was {e}")
            continue

    return retVal


# def clip_data_to_dates(price_data=None, end_date='', daterange=100):
#     """
#     Clips the given price data list to a specified date range ending at the given end date.

#     Args:
#         symbol (str, optional): The symbol for which to load historical data if price_data is not provided. Defaults to an empty string.
#         price_data (list): A list of dictionaries containing price data with 'date' keys.
#         end_date (str, optional): The end date for the date range in 'YYYY-MM-DD' format. Defaults to today's date.
#         daterange (int, optional): The number of days before the end date to include in the results. Defaults to 100.

#     Returns:
#         list: A list of dictionaries containing price data within the specified date range.
#     """
#     results= []
#     if end_date == '':
#         end_date = datetime.today().strftime("%Y-%m-%d")
#     end_date_dt = datetime.strptime(end_date, '%Y-%m-%d')
#     if price_data is None:
#         return results
#     for day in price_data:
#         current_date_dt = datetime.strptime(day['date'], '%Y-%m-%d')
#         start_date_dt = end_date_dt - timedelta(days=daterange)
#         if current_date_dt <= end_date_dt and current_date_dt > start_date_dt:
#             results.append(day)
#     return results


# def calculate_ewma_delta(price_data, period=20):
#     """
#     Calculates the Exponentially Weighted Moving Average (EWMA) of daily deltas for the given price data.

#     Args:
#         price_data (list): A list of dictionaries containing 'high' and 'low' price data.
#         period (int): The period for calculating the EWMA. Default is 20.

#     Returns:
#         float: The EWMA of daily deltas. Returns 0 if there is insufficient data.
#     """
#     if not isinstance(price_data, list) or not all(isinstance(item, dict) for item in price_data) or len(price_data) == 0:
#         raise ValueError("price_data must be a non-empty list of dictionaries")

#     daily_deltas = []
#     for price_obj in price_data:
#         try:
#             high = float(price_obj.get('high', 0))
#             low = float(price_obj.get('low', 0))
#         except (ValueError, TypeError):
#             logging.warning("Invalid price data. Skipping entry.")
#             continue  # Skip this entry if conversion fails
#         if high == 0 and low == 0:
#             logging.warning("Both high and low prices are zero. Skipping entry.")
#             continue  # Skip if both high and low are zero
#         average_price = (high + low) / 2  # Optionally use close price as the baseline
#         daily_delta = ((high - low) / average_price)  # Convert to percentage
#         daily_deltas.append(daily_delta)

#     if len(daily_deltas) == 0:
#         return 0

#     # Set smoothing factor
#     alpha = 2 / (period + 1)

#     # Initialize EWMA with the first delta value
#     ewma = daily_deltas[0]

#     # Apply EWMA formula for each subsequent delta
#     for delta in daily_deltas[1:]:
#         ewma = (delta * alpha) + (ewma * (1 - alpha))

#     return ewma

def open_report_file():
    """
    Opens a file to write reports.

    Returns:
        None
    """
    global reportFile
    reportFile = open('report.txt', 'w')

def close_report_file():
    """
    Closes the report file.

    Returns:
        None
    """
    global reportFile
    reportFile.close()

def report(newLine = ''):
    """
    Prints a report to the console.

    Args:
        newLine (str): The text to print. Defaults to an empty string.

    Returns:
        None
    """
    global reportFile
    reportFile.write(newLine + '\n')
    reportFile.flush()
