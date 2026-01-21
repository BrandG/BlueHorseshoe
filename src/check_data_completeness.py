"""
Deep Data Quality Audit Script
Scans MongoDB 'historical_prices' for:
1. Gaps in trading days (vs business days)
2. Logical inconsistencies (High < Low)
3. Zero/Null values
4. Extreme price spikes (>50% daily change)
"""
import logging
import sys
import os
import csv
import pandas as pd

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

# pylint: disable=wrong-import-position
from bluehorseshoe.core.container import create_app_container

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("src/logs/data_audit.log"),
        logging.StreamHandler()
    ]
)

def audit_symbol(df):
    """
    Runs checks on a single symbol's DataFrame.
    Returns a list of issue strings.
    """
    issues = []

    if df.empty:
        return ["NO_DATA"]

    # 1. Logical Integrity
    invalid_ohlc = df[
        (df['high'] < df['low']) |
        (df['high'] < df['open']) |
        (df['high'] < df['close']) |
        (df['low'] > df['open']) |
        (df['low'] > df['close'])
    ]
    if not invalid_ohlc.empty:
        issues.append(f"LOGICAL_ERR: {len(invalid_ohlc)} days with invalid OHLC")

    # 2. Zero Values
    zeros = df[
        (df['open'] == 0) |
        (df['high'] == 0) |
        (df['low'] == 0) |
        (df['close'] == 0)
    ]
    if not zeros.empty:
        issues.append(f"ZERO_PRICE: {len(zeros)} days with 0.0 price")

    # 3. Spikes (Returns > 50%)
    if len(df) > 1:
        # Avoid SettingWithCopyWarning by operating on copy or simple assignment
        returns = df['close'].pct_change().abs()
        spikes = returns[returns > 0.5]
        if not spikes.empty:
            issues.append(f"SPIKE: {len(spikes)} days with >50% move")

    # 4. Gaps
    df['date_dt'] = pd.to_datetime(df['date'])
    start_date = df['date_dt'].min()
    end_date = df['date_dt'].max()

    expected_days = pd.bdate_range(start=start_date, end=end_date)
    actual_days = set(df['date_dt'])

    missing_days = [d for d in expected_days if d not in actual_days]

    if len(missing_days) > 0:
        total_range = len(expected_days)
        missing_ratio = len(missing_days) / total_range if total_range > 0 else 0

        if missing_ratio > 0.10:
            issues.append(f"GAPS: Missing {len(missing_days)} business days ({missing_ratio:.1%} of range)")

    return issues

def check_completeness():
    """
    Main execution loop.
    """
    # pylint: disable=too-many-locals
    container = create_app_container()
    database = container.get_database()
    if database is None:
        logging.error("Could not connect to MongoDB")
        container.close()
        sys.exit(1)

    col = database['historical_prices']

    logging.info("Starting Deep Data Audit...")

    cursor = col.find({}, {"symbol": 1})
    symbols_to_check = [d['symbol'] for d in cursor]
    total_docs = len(symbols_to_check)

    logging.info("Found %d symbols to check.", total_docs)

    report_data = []
    issues_found = 0

    for i, symbol in enumerate(symbols_to_check):
        if i % 100 == 0:
            logging.info("Processed %d/%d symbols...", i, total_docs)

        doc = col.find_one({"symbol": symbol}, {"days": 1})
        if not doc:
            continue

        days = doc.get('days', [])

        if not days:
            report_data.append({"symbol": symbol, "issue": "NO_DATA"})
            issues_found += 1
            continue

        df = pd.DataFrame(days)

        required_cols = ['date', 'open', 'high', 'low', 'close']
        if not all(col_name in df.columns for col_name in required_cols):
            report_data.append({"symbol": symbol, "issue": "MISSING_COLUMNS"})
            issues_found += 1
            continue

        symbol_issues = audit_symbol(df)

        if symbol_issues:
            issues_found += 1
            for issue in symbol_issues:
                report_data.append({"symbol": symbol, "issue": issue})

    output_file = 'src/logs/audit_report.csv'
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "issue"])
        writer.writeheader()
        writer.writerows(report_data)

    logging.info("Audit Complete. Found issues in %d symbols.", issues_found)
    logging.info("Detailed report written to %s", output_file)

    container.close()

if __name__ == "__main__":
    check_completeness()
