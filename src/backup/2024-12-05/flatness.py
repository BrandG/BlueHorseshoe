"""
Module: flatness

This module provides functionality to analyze a list of midpoints and calculate statistical metrics such as mean,
standard deviation, coefficient of variation, mean absolute change, and slope. It also computes a flatness score
based on these metrics.

Functions:
    analyze_midpoints(midpoints, weights=None, acceptable_ranges=None):
        Analyzes a list of midpoints to calculate statistical metrics and compute a flatness score.

            weights (dict, optional): A dictionary specifying the weights for each metric in the flatness score calculation.
            acceptable_ranges (dict, optional): A dictionary specifying the acceptable ranges for normalization of each metric.

            float: The computed flatness score.
"""
# import numpy as np
# from scipy import stats

# def analyze_midpoints(midpoints, weights=None, acceptable_ranges=None):
#     """
#     Analyzes a list of midpoints to calculate statistical metrics.

#     Parameters:
#         midpoints (list or array-like): A list of numerical midpoint values.

#     Returns:
#         float: The computed flatness score.
#     """
#     # Convert the list to a NumPy array for efficient numerical computations
#     midpoints = np.array(midpoints)

#     # Calculate the Mean
#     mean = np.mean(midpoints)

#     # Calculate the Standard Deviation (SD)
#     sd = np.std(midpoints, ddof=1)  # Use ddof=1 for sample standard deviation

#     # Calculate the Coefficient of Variation (CV)
#     cv = sd / mean if mean != 0 else np.nan  # Avoid division by zero

#     # Calculate the Mean Absolute Change (MAC)
#     mac = np.mean(np.abs(np.diff(midpoints)))

#     # Perform Linear Regression to find the Slope
#     slope, _, _, _, _ = stats.linregress(np.arange(len(midpoints)), midpoints)

#     # Default weights
#     weights = weights or {
#         'slope': 0.4,
#         'standard_deviation': 0.3,
#         'coefficient_of_variation': 0.2,
#         'mean_absolute_change': 0.1
#     }

#     # Default acceptable ranges for normalization (adjust based on your data)
#     acceptable_ranges = acceptable_ranges or {
#         'slope': {'min': 0, 'max': 0.1},  # Adjust as per your acceptable slope range
#         'standard_deviation': {'min': 0, 'max': 5},  # Adjust as per your data
#         'coefficient_of_variation': {'min': 0, 'max': 0.1},  # Adjust as needed
#         'mean_absolute_change': {'min': 0, 'max': 5}  # Adjust as per your data
#     }

#     # Prepare the results and normalize them
#     results = {
#         'slope': abs(slope),
#         'standard_deviation': sd,
#         'coefficient_of_variation': cv,
#         'mean_absolute_change': mac
#     }

#     normalized_metrics = {
#         metric: min(max((results[metric] - acceptable_ranges[metric]['min']) /
#                         (acceptable_ranges[metric]['max'] - acceptable_ranges[metric]['min']), 0), 1)
#         for metric in results.items()
#     }

#     # Compute the flatness score
#     flatness_score = sum(weights[metric] * normalized_metrics[metric] for metric in results)

#     return flatness_score
