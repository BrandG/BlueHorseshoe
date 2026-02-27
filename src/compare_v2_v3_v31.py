"""Compare V2 vs V3 vs V3.1 range backtest results."""
import csv

TARGET_DATES = {
    '2025-10-01', '2025-10-08', '2025-10-15', '2025-10-22', '2025-10-29',
    '2025-11-05', '2025-11-12', '2025-11-19', '2025-11-26',
    '2025-12-03', '2025-12-10', '2025-12-17', '2025-12-24', '2025-12-31',
    '2026-01-07', '2026-01-14', '2026-01-21', '2026-01-28',
}


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


def overlap_report(label_a, trades_a, label_b, trades_b):
    picks_a = {(t['date'], t['symbol']) for t in trades_a}
    picks_b = {(t['date'], t['symbol']) for t in trades_b}
    shared = picks_a & picks_b
    union = picks_a | picks_b
    pct = len(shared) / max(len(union), 1) * 100
    print(f'{label_a} vs {label_b}: {len(shared)} shared picks ({pct:.1f}% of union)')
    return shared


# --- Load data ---
# V2: extract from pre-V3 backup (old format, filter to target dates)
v2_all = load_rows('src/logs/backtest_log_pre_v3_range.csv')
v2_rows = [r for r in v2_all if r['date'] in TARGET_DATES]

v3_rows = load_rows('src/logs/backtest_log_v3_range.csv')
v31_rows = load_rows('src/logs/backtest_log_v31_range.csv')

print(f'Loaded: V2={len(v2_rows)} rows, V3={len(v3_rows)} rows, V3.1={len(v31_rows)} rows')
print()

# --- Analyze each ---
v2_trades = analyze(v2_rows, 'V2 (original baseline weights)')
v3_trades = analyze(v3_rows, 'V3 (data-driven weights, 11 zeroed)')
v31_trades = analyze(v31_rows, 'V3.1 (V3 + top 6 indicators restored)')

# --- Summary comparison ---
print('=' * 70)
print('SIDE-BY-SIDE COMPARISON')
print('=' * 70)

for label, trades in [('V2', v2_trades), ('V3', v3_trades), ('V3.1', v31_trades)]:
    pnls = [float(t['profit_loss']) for t in trades]
    wins = [t for t in trades if t['outcome'] == 'WIN']
    total = sum(pnls)
    avg = total / len(pnls) if pnls else 0
    wr = len(wins) / len(trades) * 100 if trades else 0
    print(f'{label:<6}  Trades: {len(trades):>3}  WinRate: {wr:>5.1f}%  AvgPnL: {avg:>6.2f}%  TotalPnL: {total:>8.2f}%')

print()

# --- Overlap ---
print('=== Pick Overlap ===')
overlap_report('V2', v2_trades, 'V3', v3_trades)
overlap_report('V2', v2_trades, 'V3.1', v31_trades)
overlap_report('V3', v3_trades, 'V3.1', v31_trades)
