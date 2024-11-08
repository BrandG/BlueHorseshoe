# BlueHorseshoe Overview

This project intends to:

    1. Pick stocks that (absent news like earnings, market crashes, meme stocks, or wars) behave consistently and have a tendancy to have deltas (high - low) that are greater than 1%.

    2. For the best of that list, find price points to buy and sell for the following day.

    3. Generate a "Top 10" report, with the best ten stocks, and their given price points. Maybe other information like candlestick data, news, etc.


# Basic Outline

Note: all data files can be found here -> https://drive.google.com/drive/folders/14My1XapqqfbYN8uKK98oIsWSVb9YRuOy?usp=drive_link

(I've put expected testable constants in the list with asterisks)

    1.   Get latest data

        A. Get the list of all symbols.

        B. For each symbol (maybe batch of symbols)

            1. Open the data file and load into memory.

            2. Make net call

            3. Add all entries that are not already in memory (maybe just overwrite memory version?)

            4. Write out the data

    2.   Build new models. For each symbol:

        A. Load the data

        B. For each date:

            1. **Stability Score**

                a. Get the standard deviation (amount that it strays from its average midpoint (open-close)  during that day) *(daterange)

                b. Get a "stability score" by combining the size of the stdev and the ratio of midpoints that are within the stdev.

                c. (Maybe use other methods like ARIMA to determine stability)

            2. **Prediction Score**

                a. Rescaled Range Analysis. Get the Hurst exponent. Tells the general direction

                b. Validate RRA. Compare the next day's midpoint to the value created by the current day added to the Hurst exponent.

                c. Get the measurement of how close the next day's high and low are to the midpoint +-0.5%

        C. Combine the stability score and prediction score (possibly with multipliers), and get the mean value for all of the dates tested. Store that in a global record to choose the best symbols.

    3.   Create report

        A. Load the "best symbols" list.

        B. Find the top N entries, and load the recent data for them. For each of those entries:

            1. Get the RRA prediction for the midpoint and find the +-0.5% values.

            2. Get the "pain" and "profit" prices (where to drop out with a profit, possibly to exceed the 0.5%, and where to get out before losing too much money)

            3. Write out the graph of recent data, along with the predicted buy, sell, pain, and profit values. *(pain threshold, profit threshold)
