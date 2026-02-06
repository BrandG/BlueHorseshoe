#!/usr/bin/env python3
"""
Quick Position Sizer - BlueHorseshoe Edition

Just paste the signal from your report and get your position size!

Usage:
    python quick_size.py

Then enter:
    - Your account size
    - Your risk %
    - Paste the BlueHorseshoe signal line

Example signal:
    GEF - Entry: 75.34 | Stop: 70.43 | Target: 80.45 | Score: 38.25 | ML Win%: 60.7%
"""

import re
import sys


def parse_signal(signal_line):
    """Parse a BlueHorseshoe signal line."""

    # Extract symbol
    symbol_match = re.match(r'^(\w+)', signal_line.strip())
    symbol = symbol_match.group(1) if symbol_match else "UNKNOWN"

    # Extract entry price
    entry_match = re.search(r'Entry:\s*\$?([\d.]+)', signal_line)
    entry = float(entry_match.group(1)) if entry_match else None

    # Extract stop loss
    stop_match = re.search(r'Stop:\s*\$?([\d.]+)', signal_line)
    stop = float(stop_match.group(1)) if stop_match else None

    # Extract target
    target_match = re.search(r'(?:Target|Exit):\s*\$?([\d.]+)', signal_line)
    target = float(target_match.group(1)) if target_match else None

    # Extract ML probability if present
    ml_match = re.search(r'ML.*?(\d+\.?\d*)%', signal_line)
    ml_prob = float(ml_match.group(1)) if ml_match else None

    # Extract score if present
    score_match = re.search(r'Score:\s*([\d.]+)', signal_line)
    score = float(score_match.group(1)) if score_match else None

    return {
        'symbol': symbol,
        'entry': entry,
        'stop': stop,
        'target': target,
        'ml_prob': ml_prob,
        'score': score
    }


def calculate_position(account_size, risk_percent, entry, stop, fractional=True):
    """Calculate position size."""

    if entry <= stop:
        return None, "Error: Stop must be below entry!"

    risk_per_share = entry - stop
    account_risk = account_size * (risk_percent / 100)
    shares_exact = account_risk / risk_per_share

    # Use fractional shares or round down
    if fractional:
        shares = round(shares_exact, 3)  # Round to 3 decimals
    else:
        shares = int(shares_exact)

    if shares == 0:
        return None, "Error: Position too small (stop too wide or account too small)"

    actual_risk = shares * risk_per_share
    position_cost = shares * entry

    return {
        'shares': shares,
        'position_cost': position_cost,
        'actual_risk': actual_risk,
        'risk_per_share': risk_per_share,
        'fractional': fractional
    }, None


def print_result(signal, account_size, risk_percent, position):
    """Print formatted position size result."""

    print("\n" + "="*60)
    print(f"  📊 {signal['symbol']} - POSITION SIZE")
    print("="*60)

    print(f"\n💰 TRADE SETUP:")
    print(f"   Entry:    ${signal['entry']:.2f}")
    print(f"   Stop:     ${signal['stop']:.2f}")
    if signal['target']:
        print(f"   Target:   ${signal['target']:.2f}")
    if signal['score']:
        print(f"   Score:    {signal['score']:.1f}")
    if signal['ml_prob']:
        print(f"   ML Win%:  {signal['ml_prob']:.1f}%")

    print(f"\n📈 YOUR POSITION:")
    print(f"   Account:  ${account_size:,.0f}")
    print(f"   Risk:     {risk_percent}%")
    print(f"   Max Risk: ${account_size * (risk_percent/100):,.0f}")

    if position.get('fractional', True):
        print(f"\n✅ BUY {position['shares']:.3f} SHARES @ ${signal['entry']:.2f}")
    else:
        print(f"\n✅ BUY {position['shares']} SHARES @ ${signal['entry']:.2f}")
    print(f"   Cost:     ${position['position_cost']:,.2f}")
    print(f"   Risk:     ${position['actual_risk']:.2f}")

    if signal['target']:
        gain_per_share = signal['target'] - signal['entry']
        potential_gain = position['shares'] * gain_per_share
        print(f"   If Win:   +${potential_gain:.2f}")

    print("="*60 + "\n")


def main():
    print("\n" + "="*60)
    print("  BLUEHORSESHOE QUICK POSITION SIZER")
    print("="*60)

    try:
        # Get account info
        account_size = float(input("\n💼 Your account size ($): "))
        risk_percent = float(input("⚠️  Risk per trade (%): "))

        print("\n📋 Paste BlueHorseshoe signal line:")
        print("   (Example: GEF - Entry: 75.34 | Stop: 70.43 | Target: 80.45)")

        while True:
            signal_line = input("\n> ").strip()

            if not signal_line or signal_line.lower() in ['q', 'quit', 'exit']:
                print("\n👋 Goodbye!")
                break

            # Parse the signal
            signal = parse_signal(signal_line)

            if not signal['entry'] or not signal['stop']:
                print("\n❌ Could not parse signal. Please check format.")
                print("   Expected: SYMBOL - Entry: XX.XX | Stop: XX.XX | Target: XX.XX")
                continue

            # Calculate position
            position, error = calculate_position(account_size, risk_percent, signal['entry'], signal['stop'])

            if error:
                print(f"\n❌ {error}")
                continue

            # Print result
            print_result(signal, account_size, risk_percent, position)

            # Ask for another
            print("Paste another signal, or press Enter to quit...")

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except ValueError as e:
        print(f"\n❌ Invalid input: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
