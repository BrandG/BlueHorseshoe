"""Compare V2 vs V3 range backtest results (properly separated)."""
import csv


def load_rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def analyze(rows, label):
    trades = [r for r in rows if r['status'] != 'no_entry']
    wins = [r for r in trades if r['outcome'] == 'WIN']
    losses = [r for r in trades if r['outcome'] == 'LOSS']
    no_entry = [r for r in rows if r['status'] == 'no_entry']

    pnls = [float(r['profit_loss']) for r in trades]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls) if pnls else 0
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    best = max(trades, key=lambda r: float(r['profit_loss'])) if pnls else None
    worst = min(trades, key=lambda r: float(r['profit_loss'])) if pnls else None

    dates = sorted(set(r['date'] for r in rows))

    print(f'=== {label} ===')
    print(f'Total rows: {len(rows)}  |  Trades: {len(trades)}  |  No-entry: {len(no_entry)}')
    print(f'Wins: {len(wins)}  |  Losses: {len(losses)}')
    print(f'Win Rate: {win_rate:.1f}%')
    print(f'Avg P&L per trade: {avg_pnl:.2f}%')
    print(f'Total P&L: {total_pnl:.2f}%')
    print(f'Dates covered: {len(dates)}')
    if best:
        print(f'Best trade:  {best["symbol"]} on {best["date"]} = +{float(best["profit_loss"]):.2f}%')
    if worst:
        print(f'Worst trade: {worst["symbol"]} on {worst["date"]} = {float(worst["profit_loss"]):.2f}%')
    print()

    print(f'{"Date":<12} {"Trades":>6} {"Wins":>5} {"WinRate":>8} {"AvgPnL":>8} {"TotalPnL":>9}')
    print('-' * 50)
    for d in dates:
        dt = [r for r in trades if r['date'] == d]
        dw = [r for r in dt if r['outcome'] == 'WIN']
        dp = [float(r['profit_loss']) for r in dt]
        wr = len(dw) / len(dt) * 100 if dt else 0
        ap = sum(dp) / len(dp) if dp else 0
        tp = sum(dp)
        print(f'{d:<12} {len(dt):>6} {len(dw):>5} {wr:>7.1f}% {ap:>7.2f}% {tp:>8.2f}%')
    print()
    return trades


# --- Load and separate ---
v3_rows = load_rows('src/logs/backtest_log_v3_range.csv')
combined_rows = load_rows('src/logs/backtest_log.csv')

# Build V3 key set to subtract from combined log
v3_keys = set()
for r in v3_rows:
    v3_keys.add((r['date'], r['symbol'], r['score']))

v2_rows = [r for r in combined_rows if (r['date'], r['symbol'], r['score']) not in v3_keys]

print(f'Separated: V2={len(v2_rows)} rows, V3={len(v3_rows)} rows')
print()

# --- Analyze ---
v2_trades = analyze(v2_rows, 'V2 (baseline weights, top_n=10)')
v3_trades = analyze(v3_rows, 'V3 (data-driven weights, top_n=10)')

# --- Overlap ---
v2_picks = {(t['date'], t['symbol']) for t in v2_trades}
v3_picks = {(t['date'], t['symbol']) for t in v3_trades}
overlap = v2_picks & v3_picks

print(f'=== Pick Overlap ===')
print(f'V2 unique picks: {len(v2_picks)}')
print(f'V3 unique picks: {len(v3_picks)}')
print(f'Overlap: {len(overlap)} ({len(overlap) / max(len(v2_picks | v3_picks), 1) * 100:.1f}% of union)')
if overlap:
    print('Shared picks:')
    for d, s in sorted(overlap):
        print(f'  {d} {s}')
