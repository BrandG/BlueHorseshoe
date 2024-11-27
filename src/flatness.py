import numpy as np
from scipy import stats

def analyze_midpoints(midpoints, weights=None, acceptable_ranges=None):
    """
    Analyzes a list of midpoints to calculate statistical metrics.

    Parameters:
        midpoints (list or array-like): A list of numerical midpoint values.

    Returns:
        dict: A dictionary containing calculated SD, CV, slope, and MAC values.
    """
    # Convert the list to a NumPy array for efficient numerical computations
    midpoints = np.array(midpoints)
    N = len(midpoints)

    # Calculate the Mean
    mean = np.mean(midpoints)

    # Calculate the Standard Deviation (SD)
    sd = np.std(midpoints, ddof=1)  # Use ddof=1 for sample standard deviation

    # Calculate the Coefficient of Variation (CV)
    cv = sd / mean if mean != 0 else np.nan  # Avoid division by zero

    # Calculate the Mean Absolute Change (MAC)
    mac = np.mean(np.abs(np.diff(midpoints)))

    # Prepare the time indices for linear regression (e.g., day numbers)
    x = np.arange(N)  # Creates an array [0, 1, 2, ..., N-1]

    # Perform Linear Regression to find the Slope
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, midpoints)

    # Compile the results into a dictionary
    results = {
        'mean': mean,
        'standard_deviation': sd,
        'coefficient_of_variation': cv,
        'mean_absolute_change': mac,
        'slope': slope
    }

    # Default weights
    if weights is None:
        weights = {
            'slope': 0.4,
            'standard_deviation': 0.3,
            'coefficient_of_variation': 0.2,
            'mean_absolute_change': 0.1
        }
    
    # Metrics to consider
    metrics = ['slope', 'standard_deviation', 'coefficient_of_variation', 'mean_absolute_change']
    
    # Default acceptable ranges for normalization (adjust based on your data)
    if acceptable_ranges is None:
        acceptable_ranges = {
            'slope': {'min': 0, 'max': 0.1},  # Adjust as per your acceptable slope range
            'standard_deviation': {'min': 0, 'max': 5},  # Adjust as per your data
            'coefficient_of_variation': {'min': 0, 'max': 0.1},  # Adjust as needed
            'mean_absolute_change': {'min': 0, 'max': 5}  # Adjust as per your data
        }
    
    # Prepare the data for normalization
    normalized_metrics = {}
    for metric in metrics:
        # Get the value for the metric
        if metric == 'slope':
            value = abs(results[metric])  # Use absolute value for slope
        else:
            value = results[metric]
        
        # Get acceptable min and max values
        min_val = acceptable_ranges[metric]['min']
        max_val = acceptable_ranges[metric]['max']
        
        # Normalize the metric
        if max_val - min_val == 0:
            normalized_value = 0
        else:
            normalized_value = (value - min_val) / (max_val - min_val)
            # Ensure the normalized value is between 0 and 1
            normalized_value = min(max(normalized_value, 0), 1)
        
        normalized_metrics[metric] = normalized_value
    
    # Compute the flatness score
    flatness_score = 0
    for metric in metrics:
        flatness_score += weights[metric] * normalized_metrics[metric]
    
    return flatness_score

