#!/usr/bin/env python3
"""
Visualize assumption tester results — charts for understanding BH performance.
Reads CSV output from assumption_tester.py and generates PNG charts.
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm

INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "research")
OUTPUT_DIR = os.path.join(INPUT_DIR, "charts")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_data():
    sweep = pd.read_csv(os.path.join(INPUT_DIR, "parameter_sweep.csv"))
    sims = pd.read_csv(os.path.join(INPUT_DIR, "trade_simulations.csv"))
    stop = pd.read_csv(os.path.join(INPUT_DIR, "stop_analysis.csv"))
    tiered = pd.read_csv(os.path.join(INPUT_DIR, "tiered_exit.csv"))
    scores = pd.read_csv(os.path.join(INPUT_DIR, "phase1_scores.csv"))
    return sweep, sims, stop, tiered, scores


# =========================================================================
# Chart 1: EV Heat Map — Target% vs Hold Days (at best stop, top 20)
# =========================================================================
def chart_ev_heatmap(sweep):
    top20 = sweep[sweep["top_n"] == 20]

    # For each (target, hold), find the stop with highest EV
    idx = top20.groupby(["target_pct", "hold_days"])["expected_value_pct"].idxmax()
    best = top20.loc[idx]

    pivot = best.pivot(index="target_pct", columns="hold_days", values="expected_value_pct")

    fig, ax = plt.subplots(figsize=(12, 8))
    vmax = max(abs(pivot.values.min()), abs(pivot.values.max()))
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    im = ax.imshow(pivot.values, cmap="RdYlGn", norm=norm, aspect="auto")

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{int(c)}d" for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{v:.1f}%" for v in pivot.index])
    ax.set_xlabel("Hold Days", fontsize=12)
    ax.set_ylabel("Target %", fontsize=12)
    ax.set_title("Expected Value per Trade (%) — Best Stop at Each Combo\n(Top 20 picks, 0% slippage)", fontsize=14)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            ax.text(j, i, f"{val:.3f}", ha="center", va="center",
                    fontsize=9, color="black" if abs(val) < vmax * 0.5 else "white")

    plt.colorbar(im, ax=ax, label="EV (%)")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "01_ev_heatmap.png"), dpi=150)
    plt.close()
    print("  01_ev_heatmap.png")


# =========================================================================
# Chart 2: Win Rate Heat Map — Target% vs Hold Days
# =========================================================================
def chart_winrate_heatmap(sweep):
    top20 = sweep[sweep["top_n"] == 20]
    idx = top20.groupby(["target_pct", "hold_days"])["expected_value_pct"].idxmax()
    best = top20.loc[idx]

    pivot = best.pivot(index="target_pct", columns="hold_days", values="win_rate")

    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(pivot.values * 100, cmap="YlGn", aspect="auto", vmin=0, vmax=100)

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{int(c)}d" for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{v:.1f}%" for v in pivot.index])
    ax.set_xlabel("Hold Days", fontsize=12)
    ax.set_ylabel("Target %", fontsize=12)
    ax.set_title("Win Rate (%) — at Best Stop for Each Combo\n(Top 20 picks, 0% slippage)", fontsize=14)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j] * 100
            ax.text(j, i, f"{val:.0f}%", ha="center", va="center",
                    fontsize=9, color="black" if val > 20 else "white")

    plt.colorbar(im, ax=ax, label="Win Rate (%)")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "02_winrate_heatmap.png"), dpi=150)
    plt.close()
    print("  02_winrate_heatmap.png")


# =========================================================================
# Chart 3: Stop Tradeoff Curve
# =========================================================================
def chart_stop_tradeoff(stop):
    s20 = stop[stop["top_n"] == 20].sort_values("stop_pct")

    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()

    x = s20["stop_pct"]
    ax1.plot(x, s20["winner_preservation_rate"] * 100, "g-o", linewidth=2, label="Winners Preserved (%)")
    ax2.plot(x, s20["loser_catch_rate"] * 100, "r-s", linewidth=2, label="Losers Caught (%)")

    ax1.set_xlabel("Stop Loss (%)", fontsize=12)
    ax1.set_ylabel("Winners Preserved (%)", fontsize=12, color="green")
    ax2.set_ylabel("Losers Caught (%)", fontsize=12, color="red")
    ax1.set_title("Stop Loss Tradeoff — Winners Preserved vs Losers Caught\n(2% target, 5-day hold, top 20)", fontsize=14)

    # Add crossover annotation
    for i in range(len(s20) - 1):
        row = s20.iloc[i]
        nxt = s20.iloc[i + 1]
        if row["winner_preservation_rate"] <= row["loser_catch_rate"] and \
           nxt["winner_preservation_rate"] >= nxt["loser_catch_rate"]:
            cross_stop = (row["stop_pct"] + nxt["stop_pct"]) / 2
            ax1.axvline(cross_stop, color="gray", linestyle="--", alpha=0.5)
            ax1.annotate(f"Balance ~{cross_stop:.1f}%", (cross_stop, 50),
                        fontsize=10, ha="center", color="gray")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="center right")
    ax1.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "03_stop_tradeoff.png"), dpi=150)
    plt.close()
    print("  03_stop_tradeoff.png")


# =========================================================================
# Chart 4: Forward Return Distribution (all top-20 picks)
# =========================================================================
def chart_return_distributions(sims):
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    days = [1, 2, 3, 5, 7, 10]

    for ax, d in zip(axes.flat, days):
        col = f"d{d}_close_pct"
        if col not in sims.columns:
            ax.set_visible(False)
            continue

        returns = sims[col].dropna() * 100
        color = "green" if returns.mean() > 0 else "red"

        ax.hist(returns, bins=50, color=color, alpha=0.7, edgecolor="black", linewidth=0.5)
        ax.axvline(0, color="black", linewidth=1)
        ax.axvline(returns.mean(), color="blue", linewidth=2, linestyle="--",
                   label=f"Mean: {returns.mean():.2f}%")
        ax.axvline(returns.median(), color="orange", linewidth=2, linestyle=":",
                   label=f"Median: {returns.median():.2f}%")

        pct_positive = (returns > 0).sum() / len(returns) * 100
        ax.set_title(f"Day {d} Returns ({pct_positive:.0f}% positive)", fontsize=11)
        ax.set_xlabel("Return (%)")
        ax.set_ylabel("Count")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.suptitle("Forward Return Distributions — Top 20 BH Picks\n(Buy at next-day open)", fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "04_return_distributions.png"), dpi=150)
    plt.close()
    print("  04_return_distributions.png")


# =========================================================================
# Chart 5: Per-Date Win Rate (time series — are some periods better?)
# =========================================================================
def chart_per_date_performance(sims):
    # For each date, count how many of the top 20 hit 2% in 5 days
    dates = sorted(sims["date"].unique())
    win_rates = []
    avg_returns = []

    for d in dates:
        subset = sims[sims["date"] == d]
        # Count how many hit +2% within 5 days (checking daily highs)
        wins = 0
        for _, row in subset.iterrows():
            for day in range(1, 6):
                hkey = f"d{day}_high_pct"
                if hkey in row and not pd.isna(row[hkey]) and row[hkey] >= 0.02:
                    wins += 1
                    break
        total = len(subset)
        win_rates.append(wins / total * 100 if total > 0 else 0)

        # Average day-5 return
        d5 = subset["d5_close_pct"].dropna() * 100
        avg_returns.append(d5.mean() if len(d5) > 0 else 0)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

    ax1.bar(range(len(dates)), win_rates, color=["green" if w > 50 else "red" for w in win_rates], alpha=0.7)
    ax1.axhline(np.mean(win_rates), color="blue", linestyle="--", label=f"Avg: {np.mean(win_rates):.1f}%")
    ax1.set_ylabel("Win Rate (%)")
    ax1.set_title("Per-Date: % of Top 20 Hitting 2% in 5 Days", fontsize=13)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    colors = ["green" if r > 0 else "red" for r in avg_returns]
    ax2.bar(range(len(dates)), avg_returns, color=colors, alpha=0.7)
    ax2.axhline(np.mean(avg_returns), color="blue", linestyle="--", label=f"Avg: {np.mean(avg_returns):.2f}%")
    ax2.set_ylabel("Avg Day-5 Return (%)")
    ax2.set_title("Per-Date: Average 5-Day Return for Top 20", fontsize=13)
    ax2.set_xlabel("Date Index")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # X-axis: show every 10th date
    step = max(1, len(dates) // 10)
    ax2.set_xticks(range(0, len(dates), step))
    ax2.set_xticklabels([dates[i][:10] for i in range(0, len(dates), step)], rotation=45)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "05_per_date_performance.png"), dpi=150)
    plt.close()
    print("  05_per_date_performance.png")


# =========================================================================
# Chart 6: Strategy Comparison (Baseline vs Mean Reversion)
# =========================================================================
def chart_strategy_comparison(sims):
    strategies = sims["strategy"].unique()
    if len(strategies) < 2:
        print("  06_strategy_comparison.png — SKIPPED (only one strategy)")
        return

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    for ax, days_label, days in zip(axes, ["Day 2", "Day 5", "Day 10"], [2, 5, 10]):
        col = f"d{days}_close_pct"
        if col not in sims.columns:
            continue
        for strat in sorted(strategies):
            sub = sims[sims["strategy"] == strat][col].dropna() * 100
            ax.hist(sub, bins=40, alpha=0.5, label=f"{strat} (n={len(sub)}, avg={sub.mean():.2f}%)")
        ax.axvline(0, color="black", linewidth=1)
        ax.set_title(f"{days_label} Returns by Strategy")
        ax.set_xlabel("Return (%)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.suptitle("Strategy Comparison — Baseline vs Mean Reversion", fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "06_strategy_comparison.png"), dpi=150)
    plt.close()
    print("  06_strategy_comparison.png")


# =========================================================================
# Chart 7: Max Adverse Excursion (MAE) — How deep do winners dip?
# =========================================================================
def chart_mae_analysis(sims):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Classify winners vs losers (2%/5d without stop)
    winners = []
    losers = []
    for _, row in sims.iterrows():
        hit = False
        for day in range(1, 6):
            hkey = f"d{day}_high_pct"
            if hkey in row and not pd.isna(row[hkey]) and row[hkey] >= 0.02:
                hit = True
                break
        mae = row.get("max_adverse_excursion", 0) * 100
        if hit:
            winners.append(mae)
        else:
            losers.append(mae)

    # MAE distributions
    bins = np.linspace(min(min(winners, default=0), min(losers, default=0)), 0, 40)
    ax1.hist(winners, bins=bins, alpha=0.6, color="green", label=f"Winners (n={len(winners)})", edgecolor="black", linewidth=0.3)
    ax1.hist(losers, bins=bins, alpha=0.6, color="red", label=f"Losers (n={len(losers)})", edgecolor="black", linewidth=0.3)
    ax1.set_xlabel("Max Adverse Excursion (%)")
    ax1.set_ylabel("Count")
    ax1.set_title("MAE Distribution — Winners vs Losers\n(2% target, 5-day hold)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Cumulative: what % of winners would survive each stop level?
    stop_levels = np.arange(0.5, 10.1, 0.25)
    pct_winners_surviving = []
    pct_losers_surviving = []
    for sl in stop_levels:
        w_survive = sum(1 for m in winners if m > -sl) / len(winners) * 100 if winners else 0
        l_survive = sum(1 for m in losers if m > -sl) / len(losers) * 100 if losers else 0
        pct_winners_surviving.append(w_survive)
        pct_losers_surviving.append(l_survive)

    ax2.plot(stop_levels, pct_winners_surviving, "g-", linewidth=2, label="Winners surviving")
    ax2.plot(stop_levels, pct_losers_surviving, "r-", linewidth=2, label="Losers surviving")
    ax2.fill_between(stop_levels, pct_winners_surviving, pct_losers_surviving,
                     alpha=0.1, color="blue")
    ax2.set_xlabel("Stop Loss Level (%)")
    ax2.set_ylabel("% of Trades Surviving")
    ax2.set_title("Cumulative MAE — Stop Level vs Survival Rate")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "07_mae_analysis.png"), dpi=150)
    plt.close()
    print("  07_mae_analysis.png")


# =========================================================================
# Chart 8: Score vs Forward Return (is higher score = better outcome?)
# =========================================================================
def chart_score_vs_return(sims):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    for ax, days, label in zip(axes, [2, 5, 10], ["Day 2", "Day 5", "Day 10"]):
        col = f"d{days}_close_pct"
        if col not in sims.columns:
            continue
        valid = sims[["score", col]].dropna()
        returns = valid[col] * 100
        scores = valid["score"]

        ax.scatter(scores, returns, alpha=0.15, s=10, c=returns.apply(lambda x: "green" if x > 0 else "red"))
        ax.axhline(0, color="black", linewidth=1)

        # Bin by score quintiles
        try:
            bins = pd.qcut(scores, 5, duplicates="drop")
            means = valid.groupby(bins)[col].mean() * 100
            mids = valid.groupby(bins)["score"].mean()
            ax.plot(mids, means, "b-o", linewidth=2, markersize=8, label="Quintile avg")
        except Exception:
            pass

        ax.set_xlabel("BH Score")
        ax.set_ylabel(f"{label} Return (%)")
        ax.set_title(f"Score vs {label} Return")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.suptitle("Does Higher BH Score = Better Returns?", fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "08_score_vs_return.png"), dpi=150)
    plt.close()
    print("  08_score_vs_return.png")


# =========================================================================
# Chart 9: Tiered Exit Analysis
# =========================================================================
def chart_tiered_exit(tiered):
    t20 = tiered[tiered["top_n"] == 20]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Full win rate heatmap
    pivot = t20.pivot(index="stop_pct", columns="hold_days", values="full_win_rate")
    im = axes[0].imshow(pivot.values * 100, cmap="YlGn", aspect="auto")
    axes[0].set_xticks(range(len(pivot.columns)))
    axes[0].set_xticklabels([f"{int(c)}d" for c in pivot.columns])
    axes[0].set_yticks(range(len(pivot.index)))
    axes[0].set_yticklabels([f"{v:.1f}%" for v in pivot.index])
    axes[0].set_xlabel("Hold Days")
    axes[0].set_ylabel("Stop %")
    axes[0].set_title("Full Win Rate (T1+T2)")
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            axes[0].text(j, i, f"{pivot.values[i,j]*100:.0f}%", ha="center", va="center", fontsize=7)
    plt.colorbar(im, ax=axes[0])

    # T1 hit rate heatmap
    pivot2 = t20.pivot(index="stop_pct", columns="hold_days", values="t1_hit_rate")
    im2 = axes[1].imshow(pivot2.values * 100, cmap="YlGn", aspect="auto")
    axes[1].set_xticks(range(len(pivot2.columns)))
    axes[1].set_xticklabels([f"{int(c)}d" for c in pivot2.columns])
    axes[1].set_yticks(range(len(pivot2.index)))
    axes[1].set_yticklabels([f"{v:.1f}%" for v in pivot2.index])
    axes[1].set_xlabel("Hold Days")
    axes[1].set_ylabel("Stop %")
    axes[1].set_title("T1 Hit Rate (1%)")
    for i in range(len(pivot2.index)):
        for j in range(len(pivot2.columns)):
            axes[1].text(j, i, f"{pivot2.values[i,j]*100:.0f}%", ha="center", va="center", fontsize=7)
    plt.colorbar(im2, ax=axes[1])

    # EV heatmap
    pivot3 = t20.pivot(index="stop_pct", columns="hold_days", values="expected_value_pct")
    vmax = max(abs(pivot3.values.min()), abs(pivot3.values.max()))
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax) if vmax > 0 else None
    im3 = axes[2].imshow(pivot3.values, cmap="RdYlGn", aspect="auto", norm=norm)
    axes[2].set_xticks(range(len(pivot3.columns)))
    axes[2].set_xticklabels([f"{int(c)}d" for c in pivot3.columns])
    axes[2].set_yticks(range(len(pivot3.index)))
    axes[2].set_yticklabels([f"{v:.1f}%" for v in pivot3.index])
    axes[2].set_xlabel("Hold Days")
    axes[2].set_ylabel("Stop %")
    axes[2].set_title("Expected Value (%)")
    for i in range(len(pivot3.index)):
        for j in range(len(pivot3.columns)):
            axes[2].text(j, i, f"{pivot3.values[i,j]:.2f}", ha="center", va="center", fontsize=7)
    plt.colorbar(im3, ax=axes[2])

    fig.suptitle("Tiered Exit Analysis (T1=1%, T2=2%) — Top 20", fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "09_tiered_exit.png"), dpi=150)
    plt.close()
    print("  09_tiered_exit.png")


# =========================================================================
# Chart 10: Rank Position Analysis — Do higher-ranked picks perform better?
# =========================================================================
def chart_rank_analysis(sims):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Group by rank, compute avg day-5 return
    rank_stats = sims.groupby("rank").agg({
        "d5_close_pct": ["mean", "std", "count"],
    }).reset_index()
    rank_stats.columns = ["rank", "mean_return", "std_return", "count"]
    rank_stats["mean_return"] *= 100
    rank_stats["std_return"] *= 100

    colors = ["green" if r > 0 else "red" for r in rank_stats["mean_return"]]
    ax1.bar(rank_stats["rank"], rank_stats["mean_return"], color=colors, alpha=0.7)
    ax1.axhline(0, color="black", linewidth=1)
    ax1.set_xlabel("Rank Position (1 = highest score)")
    ax1.set_ylabel("Avg Day-5 Return (%)")
    ax1.set_title("Average 5-Day Return by Rank Position")
    ax1.grid(True, alpha=0.3)

    # Win rate by rank (2% in 5 days)
    win_by_rank = {}
    for rank in sorted(sims["rank"].unique()):
        sub = sims[sims["rank"] == rank]
        wins = 0
        for _, row in sub.iterrows():
            for day in range(1, 6):
                hkey = f"d{day}_high_pct"
                if hkey in row and not pd.isna(row[hkey]) and row[hkey] >= 0.02:
                    wins += 1
                    break
        win_by_rank[rank] = wins / len(sub) * 100 if len(sub) > 0 else 0

    ranks = sorted(win_by_rank.keys())
    rates = [win_by_rank[r] for r in ranks]
    ax2.bar(ranks, rates, color="steelblue", alpha=0.7)
    ax2.axhline(np.mean(rates), color="red", linestyle="--", label=f"Avg: {np.mean(rates):.1f}%")
    ax2.set_xlabel("Rank Position (1 = highest score)")
    ax2.set_ylabel("Win Rate — 2% in 5 Days (%)")
    ax2.set_title("Win Rate by Rank Position")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "10_rank_analysis.png"), dpi=150)
    plt.close()
    print("  10_rank_analysis.png")


# =========================================================================
# Chart 11: Diagnostic — Score distribution of top 20
# =========================================================================
def chart_score_distribution(scores):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    ax1.hist(scores["score"], bins=50, color="steelblue", alpha=0.7, edgecolor="black", linewidth=0.3)
    ax1.axvline(scores["score"].mean(), color="red", linestyle="--",
                label=f"Mean: {scores['score'].mean():.1f}")
    ax1.axvline(scores["score"].median(), color="orange", linestyle=":",
                label=f"Median: {scores['score'].median():.1f}")
    ax1.set_xlabel("BH Score")
    ax1.set_ylabel("Count")
    ax1.set_title("Score Distribution of Top-20 Picks")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Strategy breakdown
    for strat in sorted(scores["strategy"].unique()):
        sub = scores[scores["strategy"] == strat]
        ax2.hist(sub["score"], bins=30, alpha=0.5, label=f"{strat} (n={len(sub)})")
    ax2.set_xlabel("BH Score")
    ax2.set_ylabel("Count")
    ax2.set_title("Score Distribution by Strategy")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "11_score_distribution.png"), dpi=150)
    plt.close()
    print("  11_score_distribution.png")


# =========================================================================
# Chart 12: Cumulative Return Over Time (equity curve)
# =========================================================================
def chart_equity_curve(sims):
    """Simulate equity curves for different parameter combos."""
    fig, ax = plt.subplots(figsize=(14, 7))

    dates = sorted(sims["date"].unique())
    date_idx = {d: i for i, d in enumerate(dates)}

    configs = [
        ("2% tgt / 2% stop / 5d", 0.02, 0.02, 5),
        ("2% tgt / 3% stop / 5d", 0.02, 0.03, 5),
        ("1% tgt / 1.5% stop / 3d", 0.01, 0.015, 3),
        ("1% tgt / 2% stop / 2d", 0.01, 0.02, 2),
    ]

    for label, target, stop, hold in configs:
        cumulative = [1.0]
        for d in dates:
            sub = sims[sims["date"] == d]
            date_pnl = 0
            n_trades = 0
            for _, row in sub.iterrows():
                for day in range(1, hold + 1):
                    lkey = f"d{day}_low_pct"
                    hkey = f"d{day}_high_pct"
                    if lkey not in row or pd.isna(row[lkey]):
                        break
                    if row[lkey] <= -stop:
                        date_pnl -= stop
                        n_trades += 1
                        break
                    if row[hkey] >= target:
                        date_pnl += target
                        n_trades += 1
                        break
                else:
                    # Timeout — use last available close
                    ckey = f"d{hold}_close_pct"
                    if ckey in row and not pd.isna(row[ckey]):
                        date_pnl += row[ckey]
                        n_trades += 1
            # Equal weight per trade
            if n_trades > 0:
                avg_pnl = date_pnl / n_trades
                cumulative.append(cumulative[-1] * (1 + avg_pnl))
            else:
                cumulative.append(cumulative[-1])

        ax.plot(range(len(cumulative)), cumulative, linewidth=1.5, label=label)

    ax.axhline(1.0, color="black", linewidth=1, linestyle=":")
    ax.set_xlabel("Date Index")
    ax.set_ylabel("Cumulative Return (starting at 1.0)")
    ax.set_title("Equity Curves — Various Parameter Combos\n(Equal-weight top 20 picks per date)", fontsize=14)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    step = max(1, len(dates) // 10)
    ax.set_xticks(range(0, len(dates) + 1, step))
    ax.set_xticklabels([dates[i][:10] if i < len(dates) else "" for i in range(0, len(dates) + 1, step)], rotation=45)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "12_equity_curves.png"), dpi=150)
    plt.close()
    print("  12_equity_curves.png")


# =========================================================================
# Main
# =========================================================================
def main():
    print("Loading data...")
    sweep, sims, stop, tiered, scores = load_data()
    print(f"  Simulations: {len(sims)} trades across {sims['date'].nunique()} dates")
    print(f"  Parameter sweep: {len(sweep)} combos")
    print(f"  Scores: {len(scores)} top-N entries")
    print()
    print("Generating charts...")

    chart_ev_heatmap(sweep)
    chart_winrate_heatmap(sweep)
    chart_stop_tradeoff(stop)
    chart_return_distributions(sims)
    chart_per_date_performance(sims)
    chart_strategy_comparison(sims)
    chart_mae_analysis(sims)
    chart_score_vs_return(sims)
    chart_tiered_exit(tiered)
    chart_rank_analysis(sims)
    chart_score_distribution(scores)
    chart_equity_curve(sims)

    print(f"\nAll charts saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
