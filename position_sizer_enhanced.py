#!/usr/bin/env python3
"""
BlueHorseshoe Position Sizing Calculator - Enhanced Version

Supports both manual and auto-calculation modes:
1. Manual mode: Provide entry, stop, target manually
2. Auto mode: Provide symbol and strategy, calculates using BlueHorseshoe logic

Usage:
    # Manual mode (original)
    python position_sizer_enhanced.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43 --target 80.45

    # Auto mode (NEW)
    python position_sizer_enhanced.py --account 2000 --risk 1.0 --symbol GEF --strategy baseline
    python position_sizer_enhanced.py --account 2000 --risk 1.0 --symbol AAPL --strategy mean_reversion

    # Run inside Docker
    docker exec bluehorseshoe python /workspaces/BlueHorseshoe/position_sizer_enhanced.py --account 2000 --risk 1.0 --symbol GEF --strategy baseline
"""

import argparse
import sys
import os
import pandas as pd
from ta.volatility import AverageTrueRange

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

try:
    from bluehorseshoe.core.container import create_app_container
    from bluehorseshoe.data.historical_data import load_historical_data
    CAN_AUTO_CALCULATE = True
except ImportError:
    CAN_AUTO_CALCULATE = False
    print("⚠️  Warning: Cannot import BlueHorseshoe modules. Auto-calculation disabled.")
    print("   Run inside Docker for auto-calculation: docker exec bluehorseshoe python ...")


def calculate_atr(df: pd.DataFrame, window: int = 14) -> float:
    """Calculate ATR from DataFrame."""
    if 'ATR' in df.columns:
        atr = df.iloc[-1]['ATR']
    else:
        atr_indicator = AverageTrueRange(
            high=df['high'],
            low=df['low'],
            close=df['close'],
            window=window
        )
        df['ATR'] = atr_indicator.average_true_range()
        atr = df.iloc[-1]['ATR']

    if pd.isna(atr):
        # Fallback to 2% of close price
        atr = df.iloc[-1]['close'] * 0.02

    return atr


def calculate_baseline_levels(df: pd.DataFrame, atr: float) -> dict:
    """
    Calculate entry, stop, and target for Baseline (Trend) strategy.

    Logic from strategy.py:
    - Entry: Close - (0.20 * ATR) [default discount]
    - Stop: Entry - (2.0 * ATR) OR swing_low_5 * 0.985 (safer one)
    - Target: Max of (swing_high_20, entry + 3.0 * ATR)
    """
    last_row = df.iloc[-1]
    last_close = last_row['close']

    # Entry (using default 0.20 discount)
    entry_price = last_close - (0.20 * atr)

    # Stop loss candidates
    swing_low_5 = df['low'].rolling(window=5).min().iloc[-1]
    atr_stop = entry_price - (2.0 * atr)
    swing_stop = swing_low_5 * 0.985

    # Use the safer (wider) stop
    stop_loss = min(swing_stop, atr_stop)

    # Target
    swing_high_20 = df['high'].rolling(window=20).max().iloc[-1]
    take_profit = max(swing_high_20, entry_price + (3.0 * atr))

    return {
        'entry_price': float(entry_price),
        'stop_loss': float(stop_loss),
        'take_profit': float(take_profit),
        'atr': float(atr),
        'last_close': float(last_close)
    }


def calculate_mean_reversion_levels(df: pd.DataFrame, atr: float) -> dict:
    """
    Calculate entry, stop, and target for Mean Reversion strategy.

    Logic from strategy.py:
    - Entry: Current close (buying weakness)
    - Stop: Entry - (1.5 * ATR)
    - Target: Max of (EMA20, entry + 2.0 * ATR)
    """
    last_row = df.iloc[-1]
    last_close = last_row['close']

    # Entry is current close
    entry_price = last_close

    # Stop loss
    stop_loss = entry_price - (1.5 * atr)

    # Target (EMA20 or 2.0 * ATR above entry)
    ema20 = df['close'].ewm(span=20).mean().iloc[-1]
    take_profit = max(ema20, entry_price + (2.0 * atr))

    return {
        'entry_price': float(entry_price),
        'stop_loss': float(stop_loss),
        'take_profit': float(take_profit),
        'atr': float(atr),
        'last_close': float(last_close)
    }


def get_auto_levels(symbol: str, strategy: str) -> dict:
    """
    Auto-calculate entry, stop, and target using BlueHorseshoe logic.

    Args:
        symbol: Stock symbol
        strategy: 'baseline' or 'mean_reversion'

    Returns:
        Dict with entry_price, stop_loss, take_profit
    """
    if not CAN_AUTO_CALCULATE:
        print("❌ ERROR: Auto-calculation not available. Run inside Docker container:")
        print("   docker exec bluehorseshoe python position_sizer_enhanced.py ...")
        return None

    # Create container for database access
    container = create_app_container()

    try:
        # Load historical data
        price_data = load_historical_data(symbol, database=container.get_database())

        if not price_data or not price_data.get('days'):
            print(f"❌ ERROR: No historical data found for {symbol}")
            return None

        df = pd.DataFrame(price_data['days'])

        if len(df) < 30:
            print(f"❌ ERROR: Insufficient data for {symbol} ({len(df)} days, need 30+)")
            return None

        # Calculate ATR
        atr = calculate_atr(df)

        # Calculate levels based on strategy
        if strategy.lower() == 'baseline':
            levels = calculate_baseline_levels(df, atr)
        elif strategy.lower() in ['mean_reversion', 'mr']:
            levels = calculate_mean_reversion_levels(df, atr)
        else:
            print(f"❌ ERROR: Invalid strategy '{strategy}'. Use 'baseline' or 'mean_reversion'")
            return None

        return levels

    finally:
        container.close()


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


def print_position_summary(symbol, account_size, risk_percent, entry, stop, target, result,
                          open_positions_risk=0, strategy=None, last_close=None, atr=None):
    """Print a formatted position sizing summary."""

    print("\n" + "="*70)
    print(f"POSITION SIZE CALCULATOR - {symbol if symbol else 'Trade'}")
    if strategy:
        strategy_name = "Baseline (Trend)" if strategy == "baseline" else "Mean Reversion"
        print(f"Strategy: {strategy_name}")
    print("="*70)

    print(f"\n📊 ACCOUNT INFO:")
    print(f"   Total Capital:        ${account_size:,.2f}")
    print(f"   Risk per Trade:       {risk_percent}%")
    print(f"   Max Risk ($):         ${account_size * (risk_percent/100):,.2f}")

    if last_close:
        print(f"\n📈 MARKET DATA:")
        print(f"   Current Close:        ${last_close:.2f}")
        if atr:
            print(f"   ATR (14-day):         ${atr:.2f}")

    print(f"\n💰 TRADE DETAILS:")
    print(f"   Entry Price:          ${entry:.2f}")
    if last_close:
        entry_discount_pct = ((last_close - entry) / last_close) * 100
        print(f"                         ({entry_discount_pct:.2f}% below current close)")
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
    print("BLUEHORSESHOE POSITION SIZING CALCULATOR - ENHANCED")
    print("="*70)

    if not CAN_AUTO_CALCULATE:
        print("\n⚠️  Auto-calculation disabled (not running in Docker)")
        print("   Only manual mode available\n")

    # Get account info
    account_size = float(input("\n💼 Account size ($): "))
    risk_percent = float(input("⚠️  Risk per trade (%): "))

    while True:
        print("\n" + "-"*70)
        if CAN_AUTO_CALCULATE:
            print("\nMode: (1) Auto-calculate from symbol, (2) Manual entry, (q) Quit")
        else:
            print("\nMode: (2) Manual entry, (q) Quit")
        mode = input("Select mode: ").strip()

        if mode.lower() == 'q':
            break

        try:
            if mode == '1' and CAN_AUTO_CALCULATE:
                # Auto mode
                symbol = input("\n📊 Symbol: ").strip().upper()
                print("\nStrategy: (1) Baseline (Trend), (2) Mean Reversion")
                strategy_choice = input("Select strategy: ").strip()

                strategy = 'baseline' if strategy_choice == '1' else 'mean_reversion'

                print(f"\n🔄 Calculating levels for {symbol} using {strategy} strategy...")
                levels = get_auto_levels(symbol, strategy)

                if not levels:
                    continue

                entry = levels['entry_price']
                stop = levels['stop_loss']
                target = levels['take_profit']
                last_close = levels['last_close']
                atr = levels['atr']

                print(f"\n✅ Auto-calculated levels:")
                print(f"   Entry:  ${entry:.2f}")
                print(f"   Stop:   ${stop:.2f}")
                print(f"   Target: ${target:.2f}")

            else:
                # Manual mode
                symbol = input("\n📊 Symbol (or press Enter to skip): ").strip().upper()
                if not symbol:
                    symbol = None

                entry = float(input(f"💰 Entry price: $"))
                stop = float(input(f"🛑 Stop loss: $"))
                target_input = input(f"🎯 Target price (or press Enter to skip): $")
                target = float(target_input) if target_input.strip() else None

                strategy = None
                last_close = None
                atr = None

            # Common for both modes
            open_risk_input = input(f"\n📊 Total risk from other open positions ($, or press Enter for 0): $")
            open_positions_risk = float(open_risk_input) if open_risk_input.strip() else 0

            result = calculate_position_size(account_size, risk_percent, entry, stop, target)

            if result:
                print_position_summary(symbol, account_size, risk_percent, entry, stop, target,
                                     result, open_positions_risk, strategy, last_close, atr)

        except ValueError as e:
            print(f"\n❌ Invalid input: {e}")
            continue
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            continue


def main():
    parser = argparse.ArgumentParser(
        description='BlueHorseshoe Position Sizing Calculator - Enhanced Version',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # AUTO MODE - Calculate levels from BlueHorseshoe logic (run in Docker)
  docker exec bluehorseshoe python position_sizer_enhanced.py --account 2000 --risk 1.0 --symbol GEF --strategy baseline
  docker exec bluehorseshoe python position_sizer_enhanced.py --account 2000 --risk 1.0 --symbol AAPL --strategy mean_reversion

  # MANUAL MODE - Provide your own levels (original behavior)
  python position_sizer_enhanced.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43 --target 80.45

  # Interactive mode
  docker exec bluehorseshoe python position_sizer_enhanced.py --interactive
        """
    )

    # Account settings
    parser.add_argument('--account', type=float, help='Total account size in dollars')
    parser.add_argument('--risk', type=float, help='Risk per trade as percentage (e.g., 1.0 for 1%%)')

    # Auto mode (NEW)
    parser.add_argument('--symbol', type=str, help='Stock symbol (for auto mode)')
    parser.add_argument('--strategy', type=str, choices=['baseline', 'mean_reversion', 'mr'],
                       help='Strategy: baseline (trend) or mean_reversion')

    # Manual mode (original)
    parser.add_argument('--entry', type=float, help='Entry price (manual mode)')
    parser.add_argument('--stop', type=float, help='Stop loss price (manual mode)')
    parser.add_argument('--target', type=float, help='Target price (optional, manual mode)')

    # Other options
    parser.add_argument('--open-risk', type=float, default=0, help='Total risk from other open positions')
    parser.add_argument('--whole-shares', action='store_true', help='Use whole shares only (no fractional)')
    parser.add_argument('--interactive', action='store_true', help='Run in interactive mode')

    args = parser.parse_args()

    # Interactive mode
    if args.interactive or len(sys.argv) == 1:
        interactive_mode()
        return

    # Validate required args
    if not args.account or not args.risk:
        print("❌ ERROR: --account and --risk are required")
        parser.print_help()
        return

    # Auto mode
    if args.symbol and args.strategy:
        if not CAN_AUTO_CALCULATE:
            print("❌ ERROR: Auto-calculation not available. Run inside Docker container:")
            print("   docker exec bluehorseshoe python position_sizer_enhanced.py ...")
            return

        print(f"\n🔄 Calculating levels for {args.symbol} using {args.strategy} strategy...")
        levels = get_auto_levels(args.symbol, args.strategy)

        if not levels:
            return

        entry = levels['entry_price']
        stop = levels['stop_loss']
        target = levels['take_profit']
        last_close = levels['last_close']
        atr = levels['atr']

        print(f"\n✅ Auto-calculated levels:")
        print(f"   Entry:  ${entry:.2f}")
        print(f"   Stop:   ${stop:.2f}")
        print(f"   Target: ${target:.2f}")

        result = calculate_position_size(args.account, args.risk, entry, stop, target,
                                        fractional=not args.whole_shares)

        if result:
            print_position_summary(args.symbol, args.account, args.risk, entry, stop, target,
                                 result, args.open_risk, args.strategy, last_close, atr)

    # Manual mode
    elif args.entry and args.stop:
        result = calculate_position_size(args.account, args.risk, args.entry, args.stop, args.target,
                                        fractional=not args.whole_shares)

        if result:
            print_position_summary(args.symbol, args.account, args.risk, args.entry, args.stop,
                                 args.target, result, args.open_risk)

    else:
        print("❌ ERROR: Either provide (--symbol --strategy) for auto mode OR (--entry --stop) for manual mode")
        parser.print_help()


if __name__ == '__main__':
    main()
