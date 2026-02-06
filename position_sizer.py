#!/usr/bin/env python3
"""
BlueHorseshoe Position Sizing Calculator

Usage:
    python position_sizer.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43
    python position_sizer.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43 --target 80.45
"""

import argparse
import sys

def calculate_position_size(account_size, risk_percent, entry_price, stop_price, target_price=None, fractional=True):
    """Calculate position size based on risk management."""

    # Calculate risk per share
    risk_per_share = entry_price - stop_price

    if risk_per_share <= 0:
        print("❌ ERROR: Stop loss must be below entry price!")
        return None

    # Calculate account risk in dollars
    account_risk = account_size * (risk_percent / 100)

    # Calculate number of shares
    shares = account_risk / risk_per_share

    # Use fractional shares or round down
    if fractional:
        shares_to_buy = round(shares, 3)  # Round to 3 decimal places (standard for fractional)
    else:
        shares_to_buy = int(shares)  # Round down for whole shares only

    # Calculate actual position cost
    position_cost = shares_to_buy * entry_price
    position_percent = (position_cost / account_size) * 100

    # Calculate actual risk with calculated shares
    actual_risk = shares_to_buy * risk_per_share
    actual_risk_percent = (actual_risk / account_size) * 100

    # Calculate potential outcomes
    if target_price:
        gain_per_share = target_price - entry_price
        potential_gain = shares_to_buy * gain_per_share
        potential_gain_percent = (potential_gain / account_size) * 100
        risk_reward_ratio = gain_per_share / risk_per_share if risk_per_share > 0 else 0
    else:
        potential_gain = None
        potential_gain_percent = None
        risk_reward_ratio = None

    return {
        'shares': shares_to_buy,
        'fractional': fractional,
        'position_cost': position_cost,
        'position_percent': position_percent,
        'risk_per_share': risk_per_share,
        'actual_risk': actual_risk,
        'actual_risk_percent': actual_risk_percent,
        'potential_gain': potential_gain,
        'potential_gain_percent': potential_gain_percent,
        'risk_reward_ratio': risk_reward_ratio
    }


def print_position_summary(symbol, account_size, risk_percent, entry, stop, target, result, open_positions_risk=0):
    """Print a formatted position sizing summary."""

    print("\n" + "="*70)
    print(f"POSITION SIZE CALCULATOR - {symbol if symbol else 'Trade'}")
    print("="*70)

    print(f"\n📊 ACCOUNT INFO:")
    print(f"   Total Capital:        ${account_size:,.2f}")
    print(f"   Risk per Trade:       {risk_percent}%")
    print(f"   Max Risk ($):         ${account_size * (risk_percent/100):,.2f}")

    print(f"\n💰 TRADE DETAILS:")
    print(f"   Entry Price:          ${entry:.2f}")
    print(f"   Stop Loss:            ${stop:.2f}")
    if target:
        print(f"   Target Price:         ${target:.2f}")

    print(f"\n📈 POSITION SIZING:")
    print(f"   Risk per Share:       ${result['risk_per_share']:.2f}")
    if result.get('fractional', True):
        print(f"   Shares to Buy:        {result['shares']:.3f} shares (fractional)")
    else:
        print(f"   Shares to Buy:        {result['shares']} shares (whole)")
    print(f"   Position Cost:        ${result['position_cost']:,.2f} ({result['position_percent']:.1f}% of capital)")

    print(f"\n⚠️  RISK ANALYSIS:")
    print(f"   Risk if Stopped:      ${result['actual_risk']:.2f} ({result['actual_risk_percent']:.2f}%)")

    if open_positions_risk > 0:
        total_risk = result['actual_risk'] + open_positions_risk
        total_risk_percent = (total_risk / account_size) * 100
        print(f"   Other Positions Risk: ${open_positions_risk:.2f}")
        print(f"   TOTAL PORTFOLIO RISK: ${total_risk:.2f} ({total_risk_percent:.2f}%)")

        if total_risk_percent > 10:
            print(f"   ⚠️  WARNING: Total risk exceeds 10%!")

    if result['potential_gain'] is not None:
        print(f"\n🎯 PROFIT POTENTIAL:")
        print(f"   Gain if Target Hit:   ${result['potential_gain']:.2f} ({result['potential_gain_percent']:.2f}%)")
        print(f"   Risk/Reward Ratio:    1:{result['risk_reward_ratio']:.2f}")

        if result['risk_reward_ratio'] < 1.0:
            print(f"   ⚠️  WARNING: R/R ratio below 1:1")

    if result.get('fractional', True):
        print(f"\n✅ POSITION SIZE: BUY {result['shares']:.3f} SHARES @ ${entry:.2f}")
    else:
        print(f"\n✅ POSITION SIZE: BUY {result['shares']} SHARES @ ${entry:.2f}")
    print("="*70 + "\n")


def interactive_mode():
    """Run calculator in interactive mode."""
    print("\n" + "="*70)
    print("BLUEHORSESHOE POSITION SIZING CALCULATOR")
    print("="*70)

    # Get account info
    account_size = float(input("\n💼 Account size ($): "))
    risk_percent = float(input("⚠️  Risk per trade (%): "))

    while True:
        print("\n" + "-"*70)
        symbol = input("\n📊 Symbol (or 'q' to quit): ").strip().upper()

        if symbol.lower() == 'q':
            break

        try:
            entry = float(input(f"💰 Entry price for {symbol}: $"))
            stop = float(input(f"🛑 Stop loss for {symbol}: $"))
            target_input = input(f"🎯 Target price for {symbol} (or press Enter to skip): $")
            target = float(target_input) if target_input.strip() else None

            open_risk_input = input(f"📊 Total risk from other open positions ($): $")
            open_positions_risk = float(open_risk_input) if open_risk_input.strip() else 0

            result = calculate_position_size(account_size, risk_percent, entry, stop, target)

            if result:
                print_position_summary(symbol, account_size, risk_percent, entry, stop, target, result, open_positions_risk)

        except ValueError as e:
            print(f"\n❌ Invalid input: {e}")
            continue
        except Exception as e:
            print(f"\n❌ Error: {e}")
            continue


def main():
    parser = argparse.ArgumentParser(
        description='BlueHorseshoe Position Sizing Calculator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Calculate position size
  python position_sizer.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43

  # Include target price for R/R calculation
  python position_sizer.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43 --target 80.45

  # Account for existing positions
  python position_sizer.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43 --open-risk 50

  # Interactive mode
  python position_sizer.py --interactive
        """
    )

    parser.add_argument('--account', type=float, help='Total account size in dollars')
    parser.add_argument('--risk', type=float, help='Risk per trade as percentage (e.g., 1.0 for 1%%)')
    parser.add_argument('--entry', type=float, help='Entry price')
    parser.add_argument('--stop', type=float, help='Stop loss price')
    parser.add_argument('--target', type=float, help='Target price (optional)')
    parser.add_argument('--symbol', type=str, help='Stock symbol (optional)')
    parser.add_argument('--open-risk', type=float, default=0, help='Total risk from other open positions')
    parser.add_argument('--whole-shares', action='store_true', help='Use whole shares only (no fractional)')
    parser.add_argument('--interactive', action='store_true', help='Run in interactive mode')

    args = parser.parse_args()

    # Interactive mode
    if args.interactive or len(sys.argv) == 1:
        interactive_mode()
        return

    # Command-line mode
    if not all([args.account, args.risk, args.entry, args.stop]):
        parser.print_help()
        return

    result = calculate_position_size(args.account, args.risk, args.entry, args.stop, args.target, fractional=not args.whole_shares)

    if result:
        print_position_summary(args.symbol, args.account, args.risk, args.entry, args.stop, args.target, result, args.open_risk)


if __name__ == '__main__':
    main()
