"""
HTML Reporter module for BlueHorseshoe.
Generates a styled HTML report from trading signals and market data.
"""
import os
import io
import json
import base64
import pandas as pd
import mplfinance as mpf
from datetime import datetime
from typing import List, Dict, Any
from bluehorseshoe.analysis.strategy_registry import get_all_strategies
from bluehorseshoe.data.historical_data import load_historical_data

class HTMLReporter:
    """
    Generates HTML reports for BlueHorseshoe trading sessions.
    """
    # Number of top candidates to show per strategy in report
    TOP_CANDIDATES_PER_STRATEGY = 5
    # Number of candidates to show in main "Top Candidates" table
    TOP_CANDIDATES_TABLE_LIMIT = 10

    def __init__(self, output_dir: str = "src/logs", graphs_dir: str = "src/graphs", database=None):
        """
        Initialize HTMLReporter with optional dependency injection.

        Args:
            output_dir: Directory to save generated reports
            graphs_dir: Directory to save arcade-style reports
            database: MongoDB database instance. If None, uses global singleton.
        """
        self.output_dir = output_dir
        self.graphs_dir = graphs_dir
        self.database = database
        self.css = """
        <style>
            :root {
                --bg-color: #f4f4f9;
                --container-bg: #fff;
                --text-color: #333;
                --heading-color: #2c3e50;
                --border-color: #eee;
                --table-header-bg: #34495e;
                --table-header-text: #fff;
                --table-row-hover: #f5f5f5;
                --table-border: #ddd;
                --card-shadow: rgba(0,0,0,0.1);
                --badge-bull: #27ae60;
                --badge-bear: #c0392b;
                --badge-neutral: #f39c12;
                --link-color: #2c3e50;
                --link-hover: #3498db;
                --secondary-text: #777;
            }
            [data-theme="dark"] {
                --bg-color: #1a1a1a;
                --container-bg: #2d2d2d;
                --text-color: #e0e0e0;
                --heading-color: #ecf0f1;
                --border-color: #444;
                --table-header-bg: #2c3e50;
                --table-header-text: #ecf0f1;
                --table-row-hover: #3d3d3d;
                --table-border: #444;
                --card-shadow: rgba(0,0,0,0.5);
                --badge-bull: #2ecc71;
                --badge-bear: #e74c3c;
                --badge-neutral: #f1c40f;
                --link-color: #bdc3c7;
                --link-hover: #3498db;
                --secondary-text: #aaa;
            }

            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: var(--bg-color); color: var(--text-color); margin: 0; padding: 20px; transition: background-color 0.3s, color 0.3s; }
            .container { max-width: 1200px; margin: 0 auto; background: var(--container-bg); padding: 20px; box-shadow: 0 0 10px var(--card-shadow); border-radius: 8px; transition: background-color 0.3s; }
            h1, h2, h3 { color: var(--heading-color); border-bottom: 2px solid var(--border-color); padding-bottom: 10px; }
            table { width: 100%; border-collapse: collapse; margin: 20px 0; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid var(--table-border); }
            th { background-color: var(--table-header-bg); color: var(--table-header-text); }
            tr:hover { background-color: var(--table-row-hover); }
            .badge { padding: 5px 10px; border-radius: 4px; color: #fff; font-weight: bold; font-size: 0.9em; }
            .badge-bull { background-color: var(--badge-bull); }
            .badge-bear { background-color: var(--badge-bear); }
            .badge-neutral { background-color: var(--badge-neutral); }
            .score-high { color: var(--badge-bull); font-weight: bold; }
            .score-med { color: var(--badge-neutral); font-weight: bold; }
            .score-low { color: var(--badge-bear); font-weight: bold; }
            .sentiment-bullish { color: #22c55e; font-weight: bold; }
            .sentiment-neutral { color: #a3a3a3; }
            .sentiment-bearish { color: #ef4444; font-weight: bold; }
            .footer { margin-top: 40px; font-size: 0.8em; color: var(--secondary-text); text-align: center; }
            .chart-container { display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; }
            .chart-box { border: 1px solid var(--border-color); padding: 10px; border-radius: 4px; background: var(--container-bg); }
            img { max-width: 100%; height: auto; }
            .top-lists-wrapper { display: flex; gap: 20px; margin: 20px 0; }
            .top-list { flex: 1; background: var(--container-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 15px; box-shadow: 0 2px 4px var(--card-shadow); }
            .top-list h3 { border-bottom: 2px solid var(--border-color); margin-top: 0; padding-bottom: 10px; color: var(--heading-color); font-size: 1.2em; }
            
            .top-list-row { 
                display: grid; 
                grid-template-columns: 120px 80px 100px 1fr; 
                align-items: center; 
                padding: 10px 0; 
                border-bottom: 1px solid var(--border-color);
                width: 100%;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 0.95em;
            }
            .top-list-row:hover { background-color: var(--table-row-hover); }
            .top-list-row:last-child { border-bottom: none; }
            
            .top-list-header-grid { 
                display: grid; 
                grid-template-columns: 120px 80px 100px 1fr; 
                font-weight: bold; 
                color: var(--secondary-text); 
                font-size: 0.8em; 
                text-transform: uppercase; 
                border-bottom: 2px solid var(--border-color); 
                padding-bottom: 8px; 
                margin-bottom: 5px; 
            }
            
            .symbol-link { text-decoration: none; color: var(--link-color); transition: color 0.2s; }
            .symbol-link:hover { color: var(--link-hover); text-decoration: underline; }
            
            /* Toggle Button */
            .theme-toggle { position: fixed; top: 20px; right: 20px; padding: 10px 15px; background: var(--table-header-bg); color: var(--table-header-text); border: none; border-radius: 5px; cursor: pointer; font-weight: bold; box-shadow: 0 2px 5px rgba(0,0,0,0.2); z-index: 1000; }
            .theme-toggle:hover { opacity: 0.9; }

            /* Collapsible Styles */
            details { width: 100%; }
            summary { cursor: pointer; outline: none; list-style: none; }
            summary::-webkit-details-marker { display: none; }
            .sparkline-container { text-align: center; padding: 10px; background: var(--bg-color); margin-top: 5px; border-radius: 4px; }

            /* Share Calculator Styles */
            .calculator-widget {
                background: var(--container-bg);
                padding: 10px 0;
            }
            .calc-inputs {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 15px;
                margin-bottom: 15px;
            }
            .calc-input-group {
                display: flex;
                flex-direction: column;
            }
            .calc-input-group label {
                font-weight: bold;
                margin-bottom: 5px;
                color: var(--text-color);
            }
            .calc-input-group input {
                padding: 10px;
                border: 1px solid var(--border-color);
                border-radius: 4px;
                font-size: 1em;
                background: var(--bg-color);
                color: var(--text-color);
            }
            .calc-result {
                background: var(--bg-color);
                padding: 15px;
                border-radius: 4px;
                margin-top: 15px;
            }
            .calc-result-row {
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                border-bottom: 1px solid var(--border-color);
            }
            .calc-result-row:last-child {
                border-bottom: none;
            }
            .calc-result-label {
                color: var(--secondary-text);
            }
            .calc-result-value {
                font-weight: bold;
                color: var(--heading-color);
            }
        </style>
        <script>
            function toggleTheme() {
                const body = document.body;
                const currentTheme = body.getAttribute('data-theme');
                const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
                body.setAttribute('data-theme', newTheme);
                localStorage.setItem('theme', newTheme);
            }

            // Apply saved theme on load
            window.onload = function() {
                const savedTheme = localStorage.getItem('theme');
                if (savedTheme) {
                    document.body.setAttribute('data-theme', savedTheme);
                }
            }

            // Share Calculator
            function calculateShares() {
                const amount = parseFloat(document.getElementById('calc-amount').value);
                const price = parseFloat(document.getElementById('calc-price').value);

                if (isNaN(amount) || isNaN(price) || price <= 0) {
                    document.getElementById('calc-result').innerHTML = '<div class="calc-result-row"><span style="color: var(--badge-bear);">Please enter valid amounts</span></div>';
                    return;
                }

                const fractionalShares = amount / price;
                const wholeShares = Math.floor(fractionalShares);
                const costWhole = wholeShares * price;
                const costFractional = fractionalShares * price;
                const leftover = amount - costWhole;

                document.getElementById('calc-result').innerHTML = `
                    <div class="calc-result-row">
                        <span class="calc-result-label">Fractional Shares:</span>
                        <span class="calc-result-value">${fractionalShares.toFixed(3)} shares</span>
                    </div>
                    <div class="calc-result-row">
                        <span class="calc-result-label">Whole Shares:</span>
                        <span class="calc-result-value">${wholeShares} shares</span>
                    </div>
                    <div class="calc-result-row">
                        <span class="calc-result-label">Cost (Fractional):</span>
                        <span class="calc-result-value">$${costFractional.toFixed(2)}</span>
                    </div>
                    <div class="calc-result-row">
                        <span class="calc-result-label">Cost (Whole):</span>
                        <span class="calc-result-value">$${costWhole.toFixed(2)}</span>
                    </div>
                    <div class="calc-result-row">
                        <span class="calc-result-label">Leftover (Whole):</span>
                        <span class="calc-result-value">$${leftover.toFixed(2)}</span>
                    </div>
                `;
            }

            // Auto-calculate on input
            document.addEventListener('DOMContentLoaded', function() {
                const amountInput = document.getElementById('calc-amount');
                const priceInput = document.getElementById('calc-price');

                if (amountInput && priceInput) {
                    amountInput.addEventListener('input', calculateShares);
                    priceInput.addEventListener('input', calculateShares);
                }
            });
        </script>
        """

    def _get_regime_badge(self, status: str) -> str:
        status_lower = status.lower()
        if "bull" in status_lower:
            return f'<span class="badge badge-bull">{status}</span>'
        if "bear" in status_lower:
            return f'<span class="badge badge-bear">{status}</span>'
        return f'<span class="badge badge-neutral">{status}</span>'

    def _get_score_class(self, score: float) -> str:
        if score >= 80:
            return "score-high"
        if score >= 50:
            return "score-med"
        return "score-low"

    @staticmethod
    def _get_sentiment_display(score: float) -> str:
        """Return an HTML snippet showing sentiment as a colored indicator."""
        if score == 0.0:
            return "<span class='sentiment-neutral'>N/A</span>"
        if score > 0.15:
            return f"<span class='sentiment-bullish'>&#9650; {score:+.2f}</span>"
        if score < -0.15:
            return f"<span class='sentiment-bearish'>&#9660; {score:+.2f}</span>"
        return f"<span class='sentiment-neutral'>&#9644; {score:+.2f}</span>"

    def _generate_sparkline(self, symbol: str) -> str:
        """
        Generates a base64 encoded candlestick chart for the last 10 trading days.
        """
        try:
            data = load_historical_data(symbol, database=self.database)
            if not data or 'days' not in data:
                return ""
            
            df = pd.DataFrame(data['days'])
            if df.empty:
                return ""
                
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df = df.tail(10) # Last 10 days
            
            # Create buffer
            buf = io.BytesIO()
            
            # Plot
            # Minimalist style
            s = mpf.make_mpf_style(base_mpf_style='charles', rc={'font.size': 8})
            
            mpf.plot(df, type='candle', style=s, volume=False, 
                     savefig=dict(fname=buf, dpi=72, bbox_inches='tight', pad_inches=0.1),
                     figsize=(4, 2), axisoff=True)
            
            buf.seek(0)
            img_str = base64.b64encode(buf.read()).decode('utf-8')
            return f"data:image/png;base64,{img_str}"
        except Exception as e:
            print(f"Error generating chart for {symbol}: {e}")
            return ""

    def _format_top_list_item(self, c: Dict[str, Any]) -> str:
        # Format: <<SYMBOL>>:<<EXCHANGE>> <<TECH SCORE>> <<ML ATTITUDE>> <<ENTRY>> <<STOP>> <<TARGET>>
        # ML Attitude derived from probability
        prob = c.get('ml_prob', 0.0)
        attitude = f"ML:{prob*100:.0f}%"
        
        symbol = c['symbol']
        url = f"https://finance.yahoo.com/quote/{symbol}"
        
        # Format prices with percentage from entry
        entry = c.get('close', 0)
        stop = c.get('stop_loss', 0)
        target = c.get('target', 0)

        stop_pct = ((stop - entry) / entry * 100) if entry else 0
        target_pct = ((target - entry) / entry * 100) if entry else 0

        price_info = (f"E:<b>${entry:.2f}</b> "
                      f"S:<b style='color:var(--badge-bear)'>${stop:.2f}</b><small style='color:var(--badge-bear)'> ({stop_pct:.1f}%)</small> "
                      f"T:<b style='color:var(--badge-bull)'>${target:.2f}</b><small style='color:var(--badge-bull)'> (+{target_pct:.1f}%)</small>")
        
        summary_html = f"""
            <div class='top-list-row'>
                <span><a href='{url}' target='_blank' class='symbol-link'><b>{symbol}</b></a>:<small>{c.get('exchange','UNK')}</small></span>
                <span><b>{c['score']:.1f}</b></span>
                <span style='color:#777'>{attitude}</span>
                <span>{price_info}</span>
            </div>
        """
        
        chart_html = ""
        if 'chart_b64' in c and c['chart_b64']:
            chart_html = f"<div class='sparkline-container'><img src='{c['chart_b64']}' alt='{symbol} chart' /></div>"
            
        return f"<details><summary>{summary_html}</summary>{chart_html}</details>"


    def generate_report(self, date: str, regime: Dict[str, Any], candidates: List[Dict[str, Any]], charts: List[str], previous_performance: Dict[str, Any] = None) -> str:
        """
        Builds the complete HTML string.
        """
        # Filter top candidates for each strategy (sort by score, then ML confidence)
        top_n = self.TOP_CANDIDATES_PER_STRATEGY
        strategy_tops = {}
        for strat in get_all_strategies():
            tops = sorted(
                [c for c in candidates if c.get('strategy') == strat.display_name],
                key=lambda x: (x.get('score', 0), x.get('ml_prob', 0)),
                reverse=True,
            )[:top_n]
            for c in tops:
                c['chart_b64'] = self._generate_sparkline(c['symbol'])
            strategy_tops[strat.display_name] = tops

        # Keep backward-compatible aliases for rendering sections
        baseline_top = strategy_tops.get('Baseline', [])
        meanrev_top = strategy_tops.get('MeanRev', [])

        html = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            f"<title>BlueHorseshoe Report - {date}</title>",
            self.css,
            "</head>",
            "<body>",
            "<button class='theme-toggle' onclick='toggleTheme()'>Toggle Dark Mode</button>",
            "<div class='container'>",
            f"<h1>BlueHorseshoe Daily Report <small style='font-size:0.5em; color:#777'>{date}</small></h1>",

            # Market Regime Section
            "<details>",
            f"<summary style='cursor:pointer; font-size: 1.5em; font-weight: bold; color: var(--heading-color); padding-bottom: 10px;'>Market Regime: {self._get_regime_badge(regime.get('status', 'Unknown'))}</summary>",
            "<hr style='border: 0; border-bottom: 2px solid var(--border-color); margin: 0 0 20px 0;'>",
            "<table>",
            "<tr><th>Status</th><th>SPY Price</th><th>SPY MA50</th><th>SPY MA200</th><th>VIX</th><th>AAII</th><th>CNN F&G</th></tr>",
            f"<tr><td>{self._get_regime_badge(regime.get('status', 'Unknown'))}</td>",
            f"<td>{regime.get('spy_price', 'N/A')}</td>",
            f"<td>{regime.get('spy_ma50', 'N/A')}</td>",
            f"<td>{regime.get('spy_ma200', 'N/A')}</td>",
            f"<td>{regime.get('vix_close', 'N/A')}{(' (' + regime.get('vix_fear', '') + ')') if regime.get('vix_fear') else ''}</td>",
            f"<td>{regime.get('aaii_spread', 'N/A')}{(' (' + regime.get('aaii_signal', '') + ')') if regime.get('aaii_signal') else ''}</td>",
            f"<td>{regime.get('cnn_score', 'N/A')}{(' (' + regime.get('cnn_rating', '') + ')') if regime.get('cnn_rating') else ''}</td></tr>",
            "</table>",
            f"<p><strong>Commentary:</strong> {regime.get('commentary', 'No commentary available.')}</p>",
            "</details>",

            # Share Calculator Widget (Collapsible)
            "<details>",
            "<summary style='cursor:pointer; font-size: 1.5em; font-weight: bold; color: var(--heading-color); padding-bottom: 10px;'>💰 Quick Share Calculator</summary>",
            "<hr style='border: 0; border-bottom: 2px solid var(--border-color); margin: 0 0 20px 0;'>",
            "<div class='calculator-widget'>",
            "<div class='calc-inputs'>",
            "<div class='calc-input-group'>",
            "<label for='calc-amount'>Investment Amount ($)</label>",
            "<input type='number' id='calc-amount' placeholder='200' step='0.01' min='0'>",
            "</div>",
            "<div class='calc-input-group'>",
            "<label for='calc-price'>Entry Price ($)</label>",
            "<input type='number' id='calc-price' placeholder='75.34' step='0.01' min='0.01'>",
            "</div>",
            "</div>",
            "<div id='calc-result' class='calc-result'>",
            "<div class='calc-result-row'><span class='calc-result-label'>Enter amounts above to calculate shares</span></div>",
            "</div>",
            "</div>",
            "</details>",

            # Top 5 Lists (Side-by-Side)
            "<div class='top-lists-wrapper'>",
            
            # Baseline Column
            "<div class='top-list'>",
            f"<h3>Top {top_n} Baseline (Trend)</h3>",
            "<div class='top-list-header-grid'><span>Symbol</span> <span>Score</span> <span>ML</span> <span>Levels</span></div>"
        ]

        if baseline_top:
            for c in baseline_top:
                html.append(self._format_top_list_item(c))
        else:
            html.append("<div class='top-list-row'>No candidates found.</div>")

        html.append("</div>")

        # Mean Rev Column
        html.append("<div class='top-list'>")
        html.append(f"<h3>Top {top_n} Mean Reversion</h3>")
        html.append("<div class='top-list-header-grid'><span>Symbol</span> <span>Score</span> <span>ML</span> <span>Levels</span></div>")

        if meanrev_top:
            for c in meanrev_top:
                html.append(self._format_top_list_item(c))
        else:
            html.append("<div class='top-list-row'>No candidates found.</div>")

        html.append("</div></div>")

        # Connors RSI(2) Setups Section
        connors_top = [c for c in candidates if c.get('strategy') == 'Connors']
        html.append("<h2>Connors RSI(2) Setups</h2>")
        if connors_top:
            html.append("<table>")
            html.append("<tr><th>Symbol</th><th>RSI(2)</th><th>Price vs SMA200</th><th>Entry</th><th>Stop</th><th>Target</th><th>Score</th></tr>")
            for c in connors_top:
                symbol = c['symbol']
                url = f"https://finance.yahoo.com/quote/{symbol}"
                rsi2 = c.get('connors_rsi2', 0) or 0
                sma200 = c.get('connors_sma200', 0) or 0
                entry = c.get('close', 0)
                stop = c.get('stop_loss', 0)
                target = c.get('target', 0)
                score = c.get('score', 0)
                pct_above = ((entry - sma200) / sma200 * 100) if sma200 else 0
                stop_pct = ((stop - entry) / entry * 100) if entry else 0
                target_pct = ((target - entry) / entry * 100) if entry else 0

                html.append("<tr>")
                html.append(f"<td><a href='{url}' target='_blank' class='symbol-link'><strong>{symbol}</strong></a></td>")
                html.append(f"<td style='color:#c0392b;font-weight:bold'>{rsi2:.1f}</td>")
                html.append(f"<td>{pct_above:+.1f}% above</td>")
                html.append(f"<td>${entry:.2f}</td>")
                html.append(f"<td style='color:#c0392b'>${stop:.2f} <small>({stop_pct:.1f}%)</small></td>")
                html.append(f"<td style='color:#27ae60'>${target:.2f} <small>(+{target_pct:.1f}%)</small></td>")
                html.append(f"<td>{score:.1f}</td>")
                html.append("</tr>")
            html.append("</table>")
        else:
            html.append("<p style='color:#777'>No Connors RSI(2) setups today.</p>")

        # Previous Performance Section
        if previous_performance and previous_performance.get('results'):
            prev_date = previous_performance.get('date', 'Unknown')
            results = previous_performance.get('results', [])
            
            html.append(f"<h2>Previous Day Performance <small style='font-size:0.6em; color:#777'>(Suggestions from {prev_date})</small></h2>")
            html.append("<table>")
            html.append("<tr><th>Symbol</th><th>Strategy</th><th>Setup (E/S/T)</th><th>Outcome</th><th>PnL</th></tr>")
            
            for r in results:
                symbol = r['symbol']
                url = f"https://finance.yahoo.com/quote/{symbol}"
                outcome = r['outcome']
                pnl = r['pnl']
                
                outcome_style = "background-color: #95a5a6;" # Gray (No Entry)
                if outcome == "Active":
                    outcome_style = "background-color: #3498db;" # Blue
                elif outcome == "Target Hit":
                    outcome_style = "background-color: #27ae60;" # Green
                elif outcome == "Stopped Out":
                    outcome_style = "background-color: #c0392b;" # Red
                
                pnl_color = "color: #27ae60;" if pnl > 0 else ("color: #c0392b;" if pnl < 0 else "color: #777;")
                pnl_str = f"{pnl*100:.2f}%" if outcome != "No Entry" else "-"
                
                setup_str = f"E:${r['entry']:.2f} S:${r['stop']:.2f} T:${r['target']:.2f}"
                
                html.append("<tr>")
                html.append(f"<td><a href='{url}' target='_blank' class='symbol-link'><b>{symbol}</b></a></td>")
                html.append(f"<td>{r['strategy']}</td>")
                html.append(f"<td><small>{setup_str}</small></td>")
                html.append(f"<td><span class='badge' style='{outcome_style}'>{outcome}</span></td>")
                html.append(f"<td style='font-weight:bold; {pnl_color}'>{pnl_str}</td>")
                html.append("</tr>")
                
            html.append("</table>")

        # Candidates Section - limit to top N by score (primary), then ML confidence (secondary)
        top_candidates = sorted(candidates,
                               key=lambda x: (x.get('score', 0), x.get('ml_prob', 0)),
                               reverse=True)[:self.TOP_CANDIDATES_TABLE_LIMIT]
        html.append(f"<h2>Top Candidates ({len(top_candidates)})</h2>")
        html.append("<table>")
        html.append("<tr><th>Symbol</th><th>Exchange</th><th>Strategy</th><th>Score</th><th title='AlphaVantage NEWS_SENTIMENT API'>Sentiment (AV)</th><th title='Tiingo News API &mdash; headlines scored with VADER'>Sentiment (Tiingo)</th><th title='StockTwits &mdash; bull/bear tag ratio from public messages'>Sentiment (ST)</th><th title='Finviz &mdash; news headlines scored with VADER'>Sentiment (FV)</th><th title='Z-score normalized composite'>Sent (C)</th><th>Close Price</th><th>Indicators</th></tr>")


        for cand in top_candidates:
            score = cand.get('score', 0)
            score_cls = self._get_score_class(score)
            indicators = ", ".join(cand.get('reasons', []))
            
            symbol = cand['symbol']
            url = f"https://finance.yahoo.com/quote/{symbol}"

            html.append(f"<tr>")
            html.append(f"<td><a href='{url}' target='_blank' class='symbol-link'><strong>{symbol}</strong></a></td>")
            html.append(f"<td><small>{cand.get('exchange', 'Unknown')}</small></td>")
            html.append(f"<td>{cand.get('strategy', 'N/A')}</td>")
            html.append(f"<td class='{score_cls}'>{score:.2f}</td>")
            html.append(f"<td>{self._get_sentiment_display(cand.get('sentiment', 0.0))}</td>")
            html.append(f"<td>{self._get_sentiment_display(cand.get('sentiment_tiingo', 0.0))}</td>")
            html.append(f"<td>{self._get_sentiment_display(cand.get('sentiment_stocktwits', 0.0))}</td>")
            html.append(f"<td>{self._get_sentiment_display(cand.get('sentiment_finviz', 0.0))}</td>")
            html.append(f"<td><strong>{self._get_sentiment_display(cand.get('sentiment_composite', 0.0))}</strong></td>")
            html.append(f"<td>{cand.get('close', 'N/A')}</td>")
            html.append(f"<td><small>{indicators}</small></td>")
            html.append("</tr>")

        html.append("</table>")

        # Charts Section
        if charts:
            html.append("<h2>Charts</h2>")
            html.append("<div class='chart-container'>")
            for chart_path in charts:
                # We assume charts are in src/graphs and report is viewed relative to that or served via static server
                # For local file viewing, we use the absolute path or relative if in same folder
                filename = os.path.basename(chart_path)
                # In a real webserver, this would be /graphs/filename. For CLI file:// usage, relative path is safer if moved.
                # We'll link to the graphs folder relative to logs
                rel_path = f"../graphs/{filename}"
                html.append(f"<div class='chart-box'><img src='{rel_path}' alt='Chart' width='600'></div>")
            html.append("</div>")

        # Footer
        html.append(f"<div class='footer'>Generated by BlueHorseshoe v2.1 on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>")
        html.append("</div></body></html>")

        return "\n".join(html)

    def generate_email_report(self, date: str, regime: Dict[str, Any], candidates: List[Dict[str, Any]], previous_performance: Dict[str, Any] = None) -> str:
        """
        Generates a simplified, email-friendly HTML report without JavaScript or interactive elements.

        Args:
            date: Report date
            regime: Market regime data
            candidates: Trading candidates
            previous_performance: Optional previous day performance data

        Returns:
            Email-friendly HTML string
        """
        # Filter top candidates for each strategy (sort by score, then ML confidence)
        top_n = self.TOP_CANDIDATES_PER_STRATEGY
        strategy_tops = {}
        for strat in get_all_strategies():
            strategy_tops[strat.display_name] = sorted(
                [c for c in candidates if c.get('strategy') == strat.display_name],
                key=lambda x: (x.get('score', 0), x.get('ml_prob', 0)),
                reverse=True,
            )[:top_n]
        baseline_top = strategy_tops.get('Baseline', [])
        meanrev_top = strategy_tops.get('MeanRev', [])

        # Inline CSS optimized for email clients
        email_css = """
        <style>
            body { font-family: Arial, Helvetica, sans-serif; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
            .container { max-width: 700px; margin: 0 auto; background: #fff; padding: 20px; }
            h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; margin-top: 0; }
            h2 { color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 8px; margin-top: 30px; }
            h3 { color: #34495e; margin-bottom: 10px; }
            table { width: 100%; border-collapse: collapse; margin: 15px 0; }
            th, td { padding: 10px; text-align: left; border: 1px solid #ddd; }
            th { background-color: #34495e; color: #fff; font-weight: bold; }
            tr:nth-child(even) { background-color: #f9f9f9; }
            .badge { padding: 4px 8px; border-radius: 3px; color: #fff; font-weight: bold; font-size: 0.85em; display: inline-block; }
            .badge-bull { background-color: #27ae60; }
            .badge-bear { background-color: #c0392b; }
            .badge-neutral { background-color: #f39c12; }
            .score-high { color: #27ae60; font-weight: bold; }
            .score-med { color: #f39c12; font-weight: bold; }
            .score-low { color: #c0392b; font-weight: bold; }
            .sentiment-bullish { color: #22c55e; font-weight: bold; }
            .sentiment-neutral { color: #a3a3a3; }
            .sentiment-bearish { color: #ef4444; font-weight: bold; }
            .strategy-section { margin: 25px 0; padding: 15px; background-color: #f8f9fa; border-left: 4px solid #3498db; }
            .footer { margin-top: 30px; font-size: 0.85em; color: #777; text-align: center; padding-top: 15px; border-top: 1px solid #ddd; }
            a { color: #2c3e50; text-decoration: none; }
            a:hover { color: #3498db; text-decoration: underline; }
            .small-text { font-size: 0.85em; color: #777; }
        </style>
        """

        html = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "<meta charset='UTF-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
            f"<title>BlueHorseshoe Report - {date}</title>",
            email_css,
            "</head>",
            "<body>",
            "<div class='container'>",
            f"<h1>BlueHorseshoe Daily Report</h1>",
            f"<p class='small-text'>Report Date: <strong>{date}</strong></p>",
        ]

        # Market Regime Section (simplified, no collapsible)
        html.append("<h2>Market Regime</h2>")
        html.append("<table>")
        html.append("<tr><th>Status</th><th>SPY Price</th><th>SPY MA50</th><th>SPY MA200</th><th>VIX</th><th>AAII</th><th>CNN F&G</th></tr>")

        # Simple badge without the helper method
        status = regime.get('status', 'Unknown')
        status_lower = status.lower()
        if "bull" in status_lower:
            status_badge = f'<span class="badge badge-bull">{status}</span>'
        elif "bear" in status_lower:
            status_badge = f'<span class="badge badge-bear">{status}</span>'
        else:
            status_badge = f'<span class="badge badge-neutral">{status}</span>'

        html.append(f"<tr><td>{status_badge}</td>")
        html.append(f"<td>{regime.get('spy_price', 'N/A')}</td>")
        html.append(f"<td>{regime.get('spy_ma50', 'N/A')}</td>")
        html.append(f"<td>{regime.get('spy_ma200', 'N/A')}</td>")
        vix_cell = regime.get('vix_close', 'N/A')
        if regime.get('vix_fear'):
            vix_cell = f"{vix_cell} ({regime['vix_fear']})"
        html.append(f"<td>{vix_cell}</td>")
        aaii_cell = regime.get('aaii_spread', 'N/A')
        if regime.get('aaii_signal'):
            aaii_cell = f"{aaii_cell} ({regime['aaii_signal']})"
        html.append(f"<td>{aaii_cell}</td>")
        cnn_cell = regime.get('cnn_score', 'N/A')
        if regime.get('cnn_rating'):
            cnn_cell = f"{cnn_cell} ({regime['cnn_rating']})"
        html.append(f"<td>{cnn_cell}</td></tr>")
        html.append("</table>")

        # Top Baseline Candidates
        html.append("<div class='strategy-section'>")
        html.append(f"<h3>Top {top_n} Baseline (Trend Following)</h3>")

        if baseline_top:
            html.append("<table>")
            html.append("<tr><th>Symbol</th><th>Score</th><th title='AlphaVantage NEWS_SENTIMENT API'>Sent (AV)</th><th title='Tiingo News API &mdash; headlines scored with VADER'>Sent (TI)</th><th title='StockTwits &mdash; bull/bear tag ratio from public messages'>Sent (ST)</th><th title='Finviz &mdash; news headlines scored with VADER'>Sent (FV)</th><th title='Z-score normalized composite'>Sent (C)</th><th>ML Confidence</th><th>Entry</th><th>Stop</th><th>T1 (+2%)</th><th>T2 Target</th></tr>")
            for c in baseline_top:
                symbol = c['symbol']
                url = f"https://finance.yahoo.com/quote/{symbol}"
                score = c.get('score', 0)

                # Score class
                if score >= 80:
                    score_cls = "score-high"
                elif score >= 50:
                    score_cls = "score-med"
                else:
                    score_cls = "score-low"

                ml_prob = c.get('ml_prob', 0.0)
                entry = c.get('close', 0)
                stop = c.get('stop_loss', 0)
                t1 = c.get('t1_target', entry * 1.02 if entry else 0)
                target = c.get('target', 0)
                stop_pct = ((stop - entry) / entry * 100) if entry else 0
                target_pct = ((target - entry) / entry * 100) if entry else 0

                html.append("<tr>")
                html.append(f"<td><a href='{url}' target='_blank'><strong>{symbol}</strong></a></td>")
                html.append(f"<td class='{score_cls}'>{score:.1f}</td>")
                html.append(f"<td>{self._get_sentiment_display(c.get('sentiment', 0.0))}</td>")
                html.append(f"<td>{self._get_sentiment_display(c.get('sentiment_tiingo', 0.0))}</td>")
                html.append(f"<td>{self._get_sentiment_display(c.get('sentiment_stocktwits', 0.0))}</td>")
                html.append(f"<td>{self._get_sentiment_display(c.get('sentiment_finviz', 0.0))}</td>")
                html.append(f"<td><strong>{self._get_sentiment_display(c.get('sentiment_composite', 0.0))}</strong></td>")
                html.append(f"<td>{ml_prob*100:.0f}%</td>")
                html.append(f"<td>${entry:.2f}</td>")
                html.append(f"<td style='color:#c0392b;font-weight:bold'>${stop:.2f} <span style='font-size:0.85em'>({stop_pct:.1f}%)</span></td>")
                html.append(f"<td style='color:#e67e22;font-weight:bold'>${t1:.2f} <span style='font-size:0.85em'>(+2.0%)</span></td>")
                html.append(f"<td style='color:#27ae60;font-weight:bold'>${target:.2f} <span style='font-size:0.85em'>(+{target_pct:.1f}%)</span></td>")
                html.append("</tr>")
            html.append("</table>")
        else:
            html.append("<p>No candidates found for this strategy.</p>")

        html.append("</div>")

        # Top Mean Reversion Candidates
        html.append("<div class='strategy-section'>")
        html.append(f"<h3>Top {top_n} Mean Reversion</h3>")

        if meanrev_top:
            html.append("<table>")
            html.append("<tr><th>Symbol</th><th>Score</th><th title='AlphaVantage NEWS_SENTIMENT API'>Sent (AV)</th><th title='Tiingo News API &mdash; headlines scored with VADER'>Sent (TI)</th><th title='StockTwits &mdash; bull/bear tag ratio from public messages'>Sent (ST)</th><th title='Finviz &mdash; news headlines scored with VADER'>Sent (FV)</th><th title='Z-score normalized composite'>Sent (C)</th><th>ML Confidence</th><th>Entry</th><th>Stop</th><th>T1 (+2%)</th><th>T2 Target</th></tr>")
            for c in meanrev_top:
                symbol = c['symbol']
                url = f"https://finance.yahoo.com/quote/{symbol}"
                score = c.get('score', 0)

                # Score class
                if score >= 80:
                    score_cls = "score-high"
                elif score >= 50:
                    score_cls = "score-med"
                else:
                    score_cls = "score-low"

                ml_prob = c.get('ml_prob', 0.0)
                entry = c.get('close', 0)
                stop = c.get('stop_loss', 0)
                t1 = c.get('t1_target', entry * 1.02 if entry else 0)
                target = c.get('target', 0)
                stop_pct = ((stop - entry) / entry * 100) if entry else 0
                target_pct = ((target - entry) / entry * 100) if entry else 0

                html.append("<tr>")
                html.append(f"<td><a href='{url}' target='_blank'><strong>{symbol}</strong></a></td>")
                html.append(f"<td class='{score_cls}'>{score:.1f}</td>")
                html.append(f"<td>{self._get_sentiment_display(c.get('sentiment', 0.0))}</td>")
                html.append(f"<td>{self._get_sentiment_display(c.get('sentiment_tiingo', 0.0))}</td>")
                html.append(f"<td>{self._get_sentiment_display(c.get('sentiment_stocktwits', 0.0))}</td>")
                html.append(f"<td>{self._get_sentiment_display(c.get('sentiment_finviz', 0.0))}</td>")
                html.append(f"<td><strong>{self._get_sentiment_display(c.get('sentiment_composite', 0.0))}</strong></td>")
                html.append(f"<td>{ml_prob*100:.0f}%</td>")
                html.append(f"<td>${entry:.2f}</td>")
                html.append(f"<td style='color:#c0392b;font-weight:bold'>${stop:.2f} <span style='font-size:0.85em'>({stop_pct:.1f}%)</span></td>")
                html.append(f"<td style='color:#e67e22;font-weight:bold'>${t1:.2f} <span style='font-size:0.85em'>(+2.0%)</span></td>")
                html.append(f"<td style='color:#27ae60;font-weight:bold'>${target:.2f} <span style='font-size:0.85em'>(+{target_pct:.1f}%)</span></td>")
                html.append("</tr>")
            html.append("</table>")
        else:
            html.append("<p>No candidates found for this strategy.</p>")

        html.append("</div>")

        # Connors RSI(2) Setups Section
        connors_top = [c for c in candidates if c.get('strategy') == 'Connors']
        html.append("<div class='strategy-section'>")
        html.append("<h3>Connors RSI(2) Setups</h3>")
        if connors_top:
            html.append("<table>")
            html.append("<tr><th>Symbol</th><th>RSI(2)</th><th>Price vs SMA200</th><th>Entry</th><th>Stop</th><th>Target</th><th>Score</th></tr>")
            for c in connors_top:
                symbol = c['symbol']
                url = f"https://finance.yahoo.com/quote/{symbol}"
                rsi2 = c.get('connors_rsi2', 0) or 0
                sma200 = c.get('connors_sma200', 0) or 0
                entry = c.get('close', 0)
                stop = c.get('stop_loss', 0)
                target = c.get('target', 0)
                score = c.get('score', 0)
                pct_above = ((entry - sma200) / sma200 * 100) if sma200 else 0
                stop_pct = ((stop - entry) / entry * 100) if entry else 0
                target_pct = ((target - entry) / entry * 100) if entry else 0

                html.append("<tr>")
                html.append(f"<td><a href='{url}' target='_blank'><strong>{symbol}</strong></a></td>")
                html.append(f"<td style='color:#c0392b;font-weight:bold'>{rsi2:.1f}</td>")
                html.append(f"<td>{pct_above:+.1f}% above</td>")
                html.append(f"<td>${entry:.2f}</td>")
                html.append(f"<td style='color:#c0392b'>${stop:.2f} <small>({stop_pct:.1f}%)</small></td>")
                html.append(f"<td style='color:#27ae60'>${target:.2f} <small>(+{target_pct:.1f}%)</small></td>")
                html.append(f"<td>{score:.1f}</td>")
                html.append("</tr>")
            html.append("</table>")
        else:
            html.append("<p>No Connors RSI(2) setups today.</p>")
        html.append("</div>")

        # Previous Performance Section
        if previous_performance and previous_performance.get('results'):
            prev_date = previous_performance.get('date', 'Unknown')
            results = previous_performance.get('results', [])

            html.append(f"<h2>Previous Day Performance</h2>")
            html.append(f"<p class='small-text'>Suggestions from: <strong>{prev_date}</strong></p>")
            html.append("<table>")
            html.append("<tr><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Stop</th><th>Target</th><th>Outcome</th><th>PnL</th></tr>")

            for r in results:
                symbol = r['symbol']
                url = f"https://finance.yahoo.com/quote/{symbol}"
                outcome = r['outcome']
                pnl = r['pnl']

                # Outcome badge
                if outcome == "Active":
                    outcome_badge = '<span class="badge" style="background-color:#3498db">Active</span>'
                elif outcome == "Target Hit":
                    outcome_badge = '<span class="badge badge-bull">Target Hit</span>'
                elif outcome == "Stopped Out":
                    outcome_badge = '<span class="badge badge-bear">Stopped Out</span>'
                else:
                    outcome_badge = '<span class="badge" style="background-color:#95a5a6">No Entry</span>'

                pnl_style = ""
                if pnl > 0:
                    pnl_style = "color:#27ae60;font-weight:bold"
                elif pnl < 0:
                    pnl_style = "color:#c0392b;font-weight:bold"
                else:
                    pnl_style = "color:#777"

                pnl_str = f"{pnl*100:.2f}%" if outcome != "No Entry" else "-"

                html.append("<tr>")
                html.append(f"<td><a href='{url}' target='_blank'><strong>{symbol}</strong></a></td>")
                html.append(f"<td>{r['strategy']}</td>")
                html.append(f"<td>${r['entry']:.2f}</td>")
                html.append(f"<td>${r['stop']:.2f}</td>")
                html.append(f"<td>${r['target']:.2f}</td>")
                html.append(f"<td>{outcome_badge}</td>")
                html.append(f"<td style='{pnl_style}'>{pnl_str}</td>")
                html.append("</tr>")

            html.append("</table>")

        # Top Candidates Table - simplified
        top_candidates = sorted(candidates,
                               key=lambda x: (x.get('score', 0), x.get('ml_prob', 0)),
                               reverse=True)[:self.TOP_CANDIDATES_TABLE_LIMIT]

        html.append(f"<h2>All Top Candidates ({len(top_candidates)})</h2>")
        html.append("<table>")
        html.append("<tr><th>Symbol</th><th>Strategy</th><th>Score</th><th title='AlphaVantage NEWS_SENTIMENT API'>Sent (AV)</th><th title='Tiingo News API &mdash; headlines scored with VADER'>Sent (TI)</th><th title='StockTwits &mdash; bull/bear tag ratio from public messages'>Sent (ST)</th><th title='Finviz &mdash; news headlines scored with VADER'>Sent (FV)</th><th title='Z-score normalized composite'>Sent (C)</th><th>ML</th><th>Price</th><th>Top Indicators</th></tr>")

        for cand in top_candidates:
            score = cand.get('score', 0)

            # Score class
            if score >= 80:
                score_cls = "score-high"
            elif score >= 50:
                score_cls = "score-med"
            else:
                score_cls = "score-low"

            # Show only top 3 indicators to keep email concise
            all_indicators = cand.get('reasons', [])
            top_indicators = ", ".join(all_indicators[:3])
            if len(all_indicators) > 3:
                top_indicators += f" (+{len(all_indicators)-3} more)"

            symbol = cand['symbol']
            url = f"https://finance.yahoo.com/quote/{symbol}"
            ml_prob = cand.get('ml_prob', 0.0)

            html.append("<tr>")
            html.append(f"<td><a href='{url}' target='_blank'><strong>{symbol}</strong></a></td>")
            html.append(f"<td>{cand.get('strategy', 'N/A')}</td>")
            html.append(f"<td class='{score_cls}'>{score:.1f}</td>")
            html.append(f"<td>{self._get_sentiment_display(cand.get('sentiment', 0.0))}</td>")
            html.append(f"<td>{self._get_sentiment_display(cand.get('sentiment_tiingo', 0.0))}</td>")
            html.append(f"<td>{self._get_sentiment_display(cand.get('sentiment_stocktwits', 0.0))}</td>")
            html.append(f"<td>{self._get_sentiment_display(cand.get('sentiment_finviz', 0.0))}</td>")
            html.append(f"<td><strong>{self._get_sentiment_display(cand.get('sentiment_composite', 0.0))}</strong></td>")
            html.append(f"<td>{ml_prob*100:.0f}%</td>")
            html.append(f"<td>${cand.get('close', 0):.2f}</td>")
            html.append(f"<td class='small-text'>{top_indicators}</td>")
            html.append("</tr>")

        html.append("</table>")

        # Footer
        html.append(f"<div class='footer'>Generated by BlueHorseshoe v2.1 on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>")
        html.append("Full interactive report attached.</div>")
        html.append("</div></body></html>")

        return "\n".join(html)

    def save(self, html_content: str, filename: str = "latest_report.html"):
        """Saves the HTML content to a file."""
        path = os.path.join(self.output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return path

    def save_both(self, full_html: str, email_html: str, base_filename: str = "report") -> tuple:
        """
        Saves both full interactive and email-friendly versions of the report.

        Args:
            full_html: Full interactive HTML report
            email_html: Email-friendly simplified HTML
            base_filename: Base name for files (without extension)

        Returns:
            Tuple of (full_report_path, email_report_path)
        """
        # Extract date from filename if present, otherwise use base
        if base_filename.endswith('.html'):
            base_filename = base_filename[:-5]

        full_path = self.save(full_html, f"{base_filename}.html")
        email_path = self.save(email_html, f"{base_filename}_email.html")

        return full_path, email_path

    def save_arcade(self, html_content: str, filename: str) -> str:
        """Saves arcade HTML report to the output (logs) directory."""
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return path

    def _build_arcade_prev_perf(self, previous_performance: Dict[str, Any] = None) -> str:
        """Build the previous performance HTML section for the arcade report."""
        if not previous_performance or not previous_performance.get('results'):
            return ''

        prev_date = previous_performance.get('date', 'Unknown')
        results = previous_performance['results'][:10]

        rows = []
        for r in results:
            symbol = r['symbol']
            strategy = r.get('strategy', '')
            outcome = r['outcome']
            pnl = r['pnl']

            if outcome == "Target Hit":
                badge_cls = "win"
                badge_text = "TARGET HIT"
            elif outcome == "Stopped Out":
                badge_cls = "loss"
                badge_text = "STOPPED"
            elif outcome == "Active":
                badge_cls = "active"
                badge_text = "ACTIVE"
            else:
                badge_cls = "noentry"
                badge_text = "NO ENTRY"

            if outcome != "No Entry":
                pnl_pct = f"{pnl*100:+.2f}%"
                pnl_color = "var(--neon-green)" if pnl > 0 else ("var(--neon-red)" if pnl < 0 else "var(--pixel-gray)")
            else:
                pnl_pct = "---"
                pnl_color = "var(--pixel-gray)"

            setup = f"E:${r['entry']:.2f} S:${r['stop']:.2f} T:${r['target']:.2f}"

            rows.append(
                f'<div class="prev-perf-row">'
                f'<span><a href="https://finance.yahoo.com/quote/{symbol}" target="_blank" '
                f'style="color:var(--neon-blue);text-decoration:none;text-shadow:0 0 4px var(--neon-blue)">{symbol}</a></span>'
                f'<span style="color:var(--pixel-gray)">{strategy}</span>'
                f'<span style="color:var(--pixel-white);font-size:0.7rem">{setup}</span>'
                f'<span><span class="outcome-badge {badge_cls}">{badge_text}</span></span>'
                f'<span style="color:{pnl_color}">{pnl_pct}</span>'
                f'</div>'
            )

        return (
            f'<div class="prev-perf-section">'
            f'<div class="prev-perf-title">YESTERDAY\'S RESULTS &mdash; {prev_date}</div>'
            f'<div class="prev-perf-header">'
            f'<span>SYMBOL</span><span>STRAT</span><span>SETUP</span><span>OUTCOME</span><span>PnL</span>'
            f'</div>'
            + '\n'.join(rows) +
            f'</div>'
        )

    def generate_arcade_report(self, date: str, regime: Dict[str, Any],
                               candidates: List[Dict[str, Any]],
                               previous_performance: Dict[str, Any] = None) -> str:
        """
        Generates a standalone arcade-themed HTML report with all data embedded.

        Args:
            date: Report date string
            regime: Market regime data dict
            candidates: List of trading candidate dicts
            previous_performance: Optional previous day performance data

        Returns:
            Complete HTML string for the arcade report
        """
        # Prepare candidates for JSON serialization
        report_candidates = []
        for c in candidates:
            rc = {
                'symbol': c.get('symbol', '???'),
                'exchange': c.get('exchange', ''),
                'strategy': c.get('strategy', 'Baseline'),
                'score': float(c.get('score', 0)),
                'close': float(c.get('close', 0)),
                'stop_loss': float(c.get('stop_loss', 0)),
                't1_target': float(c.get('t1_target', 0)),
                'target': float(c.get('target', 0)),
                'ml_prob': float(c.get('ml_prob', 0)),
                'sentiment': float(c.get('sentiment', 0)),
                'sentiment_tiingo': float(c.get('sentiment_tiingo', 0)),
                'sentiment_stocktwits': float(c.get('sentiment_stocktwits', 0)),
                'sentiment_finviz': float(c.get('sentiment_finviz', 0)),
                'sentiment_composite': float(c.get('sentiment_composite', 0)),
                'reasons': c.get('reasons', []),
                'components': {},
            }
            if c.get('connors_rsi2') is not None:
                rc['connors_rsi2'] = float(c['connors_rsi2'])
            if c.get('connors_sma200') is not None:
                rc['connors_sma200'] = float(c['connors_sma200'])
            report_candidates.append(rc)
        report_candidates.sort(key=lambda x: x['score'], reverse=True)

        # Prepare regime data
        report_regime = {
            'status': str(regime.get('status', 'NEUTRAL')),
            'details': {}
        }
        if 'details' in regime:
            for key in ['SPY', 'QQQ']:
                if key in regime['details']:
                    d = regime['details'][key]
                    report_regime['details'][key] = {
                        'close': float(d['close']) if d.get('close') else None,
                        'ema50': float(d['ema50']) if d.get('ema50') else None,
                        'ema200': float(d['ema200']) if d.get('ema200') else None,
                    }
            if 'VIX' in regime['details']:
                report_regime['details']['VIX'] = regime['details']['VIX']
            if 'AAII' in regime['details']:
                report_regime['details']['AAII'] = regime['details']['AAII']

        report_data = {
            'date': date,
            'regime': report_regime,
            'candidates': report_candidates,
        }

        data_json = json.dumps(report_data,
                               default=lambda o: float(o) if hasattr(o, '__float__') else str(o))
        # Escape </script> in JSON to prevent premature tag closing
        data_json = data_json.replace('</script>', '<\\/script>')

        prev_perf_html = self._build_arcade_prev_perf(previous_performance)
        gen_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Embed banner image as base64 if available
        banner_b64 = ''
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')
        banner_path = os.path.join(base_dir, 'BlueHorseshoeBanner.png')
        try:
            with open(banner_path, 'rb') as bf:
                banner_b64 = base64.b64encode(bf.read()).decode('utf-8')
        except (FileNotFoundError, OSError):
            pass

        # Embed favicon SVG as base64 if available
        favicon_b64 = ''
        favicon_path = os.path.join(base_dir, 'BlueHorseshoe.svg')
        try:
            with open(favicon_path, 'rb') as ff:
                favicon_b64 = base64.b64encode(ff.read()).decode('utf-8')
        except (FileNotFoundError, OSError):
            pass

        # ── CSS ──────────────────────────────────────────────────
        arcade_css = """<style>
:root {
  --crt-bg: #0a0a12;
  --crt-border: #1a1a2e;
  --neon-green: #39ff14;
  --neon-green-dim: #1a7a0a;
  --neon-pink: #ff2d7b;
  --neon-pink-dim: #7a1540;
  --neon-blue: #00d4ff;
  --neon-blue-dim: #006680;
  --neon-amber: #ffaa00;
  --neon-amber-dim: #7a5200;
  --neon-purple: #bf40ff;
  --neon-red: #ff3333;
  --neon-red-dim: #7a1a1a;
  --pixel-white: #e0e0e0;
  --pixel-gray: #555570;
  --pixel-dark: #16162a;
  --scanline-opacity: 0.06;
  --font-pixel: 'Press Start 2P', monospace;
  --glow-green: 0 0 10px #39ff14, 0 0 20px #39ff1466, 0 0 40px #39ff1433;
  --glow-pink: 0 0 10px #ff2d7b, 0 0 20px #ff2d7b66, 0 0 40px #ff2d7b33;
  --glow-blue: 0 0 10px #00d4ff, 0 0 20px #00d4ff66, 0 0 40px #00d4ff33;
  --glow-amber: 0 0 10px #ffaa00, 0 0 20px #ffaa0066, 0 0 40px #ffaa0033;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 14px; background: #050508; overflow-x: hidden; }
body {
  font-family: var(--font-pixel);
  background: var(--crt-bg);
  color: var(--pixel-white);
  min-height: 100vh;
  position: relative;
  image-rendering: pixelated;
}
body::before {
  content: '';
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: repeating-linear-gradient(0deg, transparent, transparent 2px,
    rgba(0,0,0,var(--scanline-opacity)) 2px, rgba(0,0,0,var(--scanline-opacity)) 4px);
  pointer-events: none; z-index: 9999;
}
body::after {
  content: '';
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,0.4) 100%);
  pointer-events: none; z-index: 9998;
}
@keyframes flicker {
  0%, 100% { opacity: 1; } 92% { opacity: 1; } 93% { opacity: 0.8; }
  94% { opacity: 1; } 96% { opacity: 0.9; } 97% { opacity: 1; }
}
.crt-screen { animation: flicker 8s infinite; }
.arcade-cabinet { max-width: 1280px; margin: 0 auto; padding: 12px; position: relative; }
.marquee-sign {
  text-align: center; padding: 24px 16px; margin-bottom: 8px; position: relative;
  border: 3px solid var(--neon-amber);
  background: linear-gradient(180deg, #1a1020 0%, #0d0815 100%);
  box-shadow: var(--glow-amber), inset 0 0 30px rgba(255,170,0,0.05);
}
.marquee-sign::before {
  content: ''; position: absolute; top: -1px; left: -1px; right: -1px; bottom: -1px;
  border: 1px dashed var(--neon-amber); opacity: 0.4;
}
.marquee-title {
  font-size: 1.6rem; color: var(--neon-amber); text-shadow: var(--glow-amber);
  letter-spacing: 4px; line-height: 1.8;
}
.marquee-banner {
  max-width: 100%; height: auto; max-height: 120px;
  image-rendering: auto; display: block; margin: 0 auto;
}
.marquee-subtitle {
  font-size: 0.55rem; color: var(--neon-blue); text-shadow: var(--glow-blue);
  margin-top: 8px; letter-spacing: 2px;
}
.marquee-date {
  font-size: 0.45rem; color: var(--neon-green); text-shadow: var(--glow-green);
  margin-top: 6px; letter-spacing: 1px;
}
.pixel-corner {
  position: absolute; width: 8px; height: 8px;
  background: var(--neon-amber); box-shadow: var(--glow-amber);
}
.pixel-corner.tl { top: 6px; left: 6px; }
.pixel-corner.tr { top: 6px; right: 6px; }
.pixel-corner.bl { bottom: 6px; left: 6px; }
.pixel-corner.br { bottom: 6px; right: 6px; }
.ticker-bar {
  background: var(--pixel-dark); border: 2px solid var(--neon-green-dim);
  padding: 8px 0; overflow: hidden; margin-bottom: 12px; position: relative;
}
.ticker-bar::before, .ticker-bar::after {
  content: ''; position: absolute; top: 0; bottom: 0; width: 40px; z-index: 2;
}
.ticker-bar::before { left: 0; background: linear-gradient(90deg, var(--pixel-dark), transparent); }
.ticker-bar::after { right: 0; background: linear-gradient(-90deg, var(--pixel-dark), transparent); }
@keyframes ticker-scroll { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }
.ticker-content {
  display: flex; gap: 40px; white-space: nowrap;
  animation: ticker-scroll 30s linear infinite;
  font-size: 0.55rem; color: var(--neon-green); text-shadow: 0 0 6px var(--neon-green);
}
.ticker-item { display: flex; align-items: center; gap: 8px; }
.ticker-sep { color: var(--pixel-gray); }
.arcade-btn {
  font-family: var(--font-pixel); font-size: 0.5rem; padding: 8px 16px;
  border: 2px solid; cursor: pointer; position: relative;
  text-transform: uppercase; letter-spacing: 1px; transition: all 0.1s; background: transparent;
}
.arcade-btn:active { transform: scale(0.96); }
.arcade-btn.btn-green { border-color: var(--neon-green); color: var(--neon-green); text-shadow: 0 0 6px var(--neon-green); box-shadow: 0 0 6px var(--neon-green-dim); }
.arcade-btn.btn-green:hover { background: rgba(57,255,20,0.1); box-shadow: var(--glow-green); }
.arcade-btn.btn-pink { border-color: var(--neon-pink); color: var(--neon-pink); text-shadow: 0 0 6px var(--neon-pink); box-shadow: 0 0 6px var(--neon-pink-dim); }
.arcade-btn.btn-pink:hover { background: rgba(255,45,123,0.1); box-shadow: var(--glow-pink); }
.arcade-btn.btn-blue { border-color: var(--neon-blue); color: var(--neon-blue); text-shadow: 0 0 6px var(--neon-blue); box-shadow: 0 0 6px var(--neon-blue-dim); }
.arcade-btn.btn-blue:hover { background: rgba(0,212,255,0.1); box-shadow: var(--glow-blue); }
.arcade-btn.btn-amber { border-color: var(--neon-amber); color: var(--neon-amber); text-shadow: 0 0 6px var(--neon-amber); box-shadow: 0 0 6px var(--neon-amber-dim); }
.arcade-btn.btn-amber:hover { background: rgba(255,170,0,0.1); box-shadow: var(--glow-amber); }
.status-bar { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-bottom: 12px; }
.status-panel {
  background: var(--pixel-dark); border: 2px solid var(--pixel-gray);
  padding: 12px; text-align: center;
}
.status-panel .label { font-size: 0.4rem; color: var(--pixel-gray); margin-bottom: 6px; letter-spacing: 1px; }
.status-panel .value { font-size: 0.65rem; letter-spacing: 1px; }
.status-panel .value.bullish { color: var(--neon-green); text-shadow: var(--glow-green); }
.status-panel .value.bearish { color: var(--neon-red); text-shadow: 0 0 10px var(--neon-red); }
.status-panel .value.neutral { color: var(--neon-amber); text-shadow: var(--glow-amber); }
.strategy-tabs { display: flex; gap: 4px; margin-bottom: 0; }
.strategy-tab {
  font-family: var(--font-pixel); font-size: 0.5rem; padding: 10px 20px;
  border: 2px solid var(--pixel-gray); border-bottom: none;
  background: var(--pixel-dark); color: var(--pixel-gray);
  cursor: pointer; transition: all 0.15s; letter-spacing: 1px;
}
.strategy-tab:hover { color: var(--pixel-white); border-color: var(--pixel-white); }
.strategy-tab.active {
  color: var(--neon-amber); border-color: var(--neon-amber);
  background: var(--crt-bg); text-shadow: 0 0 6px var(--neon-amber);
}
.leaderboard {
  border: 2px solid var(--neon-amber); background: var(--crt-bg);
  box-shadow: 0 0 15px rgba(255,170,0,0.1); margin-bottom: 16px;
}
.leaderboard-header {
  display: grid; grid-template-columns: 28px 40px 90px 1fr 60px 100px 100px 80px 80px 110px 80px;
  padding: 10px 12px; border-bottom: 2px solid var(--neon-amber);
  font-size: 0.8rem; color: var(--neon-amber); text-shadow: 0 0 4px var(--neon-amber);
  letter-spacing: 1px; background: rgba(255,170,0,0.05);
}
.leaderboard-body {
  max-height: 65vh; overflow-y: auto; scrollbar-width: thin;
  scrollbar-color: var(--neon-amber-dim) var(--pixel-dark);
}
.leaderboard-body::-webkit-scrollbar { width: 6px; }
.leaderboard-body::-webkit-scrollbar-track { background: var(--pixel-dark); }
.leaderboard-body::-webkit-scrollbar-thumb { background: var(--neon-amber-dim); border: 1px solid var(--neon-amber); }
@keyframes row-enter { from { opacity: 0; transform: translateX(-20px); } to { opacity: 1; transform: translateX(0); } }
.leaderboard-row {
  display: grid; grid-template-columns: 28px 40px 90px 1fr 60px 100px 100px 80px 80px 110px 80px;
  padding: 10px 12px; border-bottom: 1px solid rgba(85,85,112,0.3);
  font-size: 0.9rem; cursor: pointer; transition: background 0.1s;
  animation: row-enter 0.3s ease-out both;
}
.leaderboard-row:hover { background: rgba(255,170,0,0.06); }
.leaderboard-row:nth-child(even) { background: rgba(22,22,42,0.4); }
.leaderboard-row:nth-child(even):hover { background: rgba(255,170,0,0.08); }
.col-rank { color: var(--pixel-gray); display: flex; align-items: center; }
.rank-num { color: var(--neon-amber); }
.rank-1 .rank-num { color: #ffd700; text-shadow: 0 0 8px #ffd700; font-size: 1.1rem; }
.rank-2 .rank-num { color: #c0c0c0; text-shadow: 0 0 6px #c0c0c0; }
.rank-3 .rank-num { color: #cd7f32; text-shadow: 0 0 6px #cd7f32; }
.col-symbol { display: flex; align-items: center; gap: 6px; }
.symbol-name { color: var(--neon-blue); text-shadow: 0 0 6px var(--neon-blue); letter-spacing: 1px; font-size: 1.1rem; }
.strategy-badge { font-size: 0.6rem; padding: 2px 4px; border: 1px solid; letter-spacing: 0; }
.strategy-badge.baseline { color: var(--neon-green); border-color: var(--neon-green-dim); background: rgba(57,255,20,0.08); }
.strategy-badge.meanrev { color: var(--neon-purple); border-color: rgba(191,64,255,0.4); background: rgba(191,64,255,0.08); }
.strategy-badge.connors { color: var(--neon-amber); border-color: var(--neon-amber-dim); background: rgba(255,170,0,0.08); }
.col-score { display: flex; align-items: center; gap: 6px; }
.health-bar { width: 60px; height: 12px; background: var(--pixel-dark); border: 1px solid var(--pixel-gray); position: relative; overflow: hidden; }
.health-bar-fill { height: 100%; transition: width 0.5s ease-out; image-rendering: pixelated; }
.health-bar-fill.high { background: var(--neon-green); box-shadow: inset 0 0 4px rgba(57,255,20,0.5); }
.health-bar-fill.mid { background: var(--neon-amber); box-shadow: inset 0 0 4px rgba(255,170,0,0.5); }
.health-bar-fill.low { background: var(--neon-red); box-shadow: inset 0 0 4px rgba(255,51,51,0.5); }
.score-value { min-width: 28px; text-align: right; }
.score-high { color: var(--neon-green); text-shadow: 0 0 4px var(--neon-green); }
.score-mid { color: var(--neon-amber); text-shadow: 0 0 4px var(--neon-amber); }
.score-low { color: var(--neon-red); text-shadow: 0 0 4px var(--neon-red); }
.col-sent { display: flex; align-items: center; font-size: 0.8rem; font-weight: bold; }
.col-sent.sent-bull { color: var(--neon-green); text-shadow: 0 0 4px rgba(57,255,20,0.5); }
.col-sent.sent-bear { color: var(--neon-red); text-shadow: 0 0 4px rgba(255,51,51,0.5); }
.col-sent.sent-neutral { color: var(--pixel-gray); }
.col-price { display: flex; align-items: center; color: var(--pixel-white); }
.col-stop { display: flex; align-items: center; color: var(--neon-red); text-shadow: 0 0 4px rgba(255,51,51,0.5); }
.col-target { display: flex; align-items: center; color: var(--neon-green); text-shadow: 0 0 4px rgba(57,255,20,0.5); }
.col-ml { display: flex; align-items: center; gap: 4px; }
.ml-meter { display: flex; gap: 1px; }
.ml-pip { width: 6px; height: 14px; background: var(--pixel-dark); border: 1px solid rgba(85,85,112,0.3); transition: all 0.3s; }
.ml-pip.filled.green { background: var(--neon-green); box-shadow: 0 0 3px var(--neon-green); border-color: var(--neon-green); }
.ml-pip.filled.amber { background: var(--neon-amber); box-shadow: 0 0 3px var(--neon-amber); border-color: var(--neon-amber); }
.ml-pip.filled.red { background: var(--neon-red); box-shadow: 0 0 3px var(--neon-red); border-color: var(--neon-red); }
.ml-pct { font-size: 0.8rem; min-width: 30px; text-align: right; }
.col-rr { display: flex; align-items: center; font-size: 0.8rem; color: var(--neon-blue); text-shadow: 0 0 4px rgba(0,212,255,0.4); }
.col-check { display: flex; align-items: center; justify-content: center; }
.portfolio-check { -webkit-appearance: none; appearance: none; width: 16px; height: 16px; border: 2px solid var(--pixel-gray); background: var(--pixel-dark); cursor: pointer; position: relative; transition: all 0.15s; }
.portfolio-check:checked { border-color: var(--neon-pink); background: rgba(255,45,123,0.2); box-shadow: 0 0 6px var(--neon-pink); }
.portfolio-check:checked::after { content: ''; position: absolute; top: 2px; left: 2px; width: 8px; height: 8px; background: var(--neon-pink); }
.portfolio-badge { background: var(--neon-pink); color: var(--crt-bg); font-size: 0.45rem; padding: 1px 5px; margin-left: 6px; min-width: 14px; text-align: center; display: none; }
.detail-panel { display: none; grid-column: 1 / -1; padding: 16px 12px; border-bottom: 2px solid var(--neon-amber-dim); background: rgba(26,26,46,0.6); }
.detail-panel.open { display: block; animation: row-enter 0.2s ease-out; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
.detail-section { border: 1px solid var(--pixel-gray); padding: 12px; }
.detail-section-title { font-size: 0.8rem; color: var(--neon-amber); margin-bottom: 10px; letter-spacing: 1px; text-shadow: 0 0 4px var(--neon-amber); }
.rr-diagram { position: relative; height: 40px; margin: 8px 0; background: var(--pixel-dark); border: 1px solid var(--pixel-gray); overflow: hidden; }
.rr-zone-risk { position: absolute; left: 0; top: 0; bottom: 0; background: repeating-linear-gradient(45deg, transparent, transparent 3px, rgba(255,51,51,0.15) 3px, rgba(255,51,51,0.15) 6px); border-right: 2px solid var(--neon-red); }
.rr-zone-reward { position: absolute; right: 0; top: 0; bottom: 0; background: repeating-linear-gradient(45deg, transparent, transparent 3px, rgba(57,255,20,0.08) 3px, rgba(57,255,20,0.08) 6px); border-left: 2px solid var(--neon-green); }
.rr-entry-marker { position: absolute; top: 0; bottom: 0; width: 3px; background: var(--neon-amber); box-shadow: var(--glow-amber); z-index: 1; }
.rr-label { position: absolute; bottom: 2px; font-size: 0.6rem; letter-spacing: 0; }
.rr-label.stop { left: 4px; color: var(--neon-red); }
.rr-label.entry { color: var(--neon-amber); }
.rr-label.target { right: 4px; color: var(--neon-green); }
.rr-t1-marker { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--neon-amber); box-shadow: 0 0 6px var(--neon-amber); z-index: 1; opacity: 0.8; }
.rr-label.t1 { color: var(--neon-amber); top: 2px; bottom: auto; font-size: 0.55rem; }
.indicator-bar-row { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; font-size: 0.7rem; }
.indicator-name { width: 70px; color: var(--pixel-gray); text-align: right; text-transform: uppercase; }
.indicator-bar { flex: 1; height: 6px; background: var(--pixel-dark); border: 1px solid rgba(85,85,112,0.3); position: relative; overflow: hidden; }
.indicator-bar-fill { height: 100%; transition: width 0.4s ease-out; }
.indicator-bar-fill.positive { background: var(--neon-green); }
.indicator-bar-fill.negative { background: var(--neon-red); float: right; }
.indicator-val { width: 36px; text-align: left; font-size: 0.6rem; }
.indicator-val.pos { color: var(--neon-green); }
.indicator-val.neg { color: var(--neon-red); }
.sent-bar-row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; font-size: 0.7rem; }
.sent-bar-label { width: 50px; color: var(--pixel-gray); text-align: right; text-transform: uppercase; font-size: 0.6rem; }
.sent-bar-label.comp-label { color: var(--neon-amber); text-shadow: 0 0 4px var(--neon-amber); font-weight: bold; }
.sent-bar { flex: 1; height: 8px; background: var(--pixel-dark); border: 1px solid rgba(85,85,112,0.3); position: relative; overflow: hidden; }
.sent-bar-center { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--pixel-gray); opacity: 0.5; z-index: 1; }
.sent-bar-fill { position: absolute; top: 0; bottom: 0; transition: width 0.4s ease-out; }
.sent-bar-fill.positive { background: var(--neon-green); box-shadow: 0 0 4px rgba(57,255,20,0.3); left: 50%; }
.sent-bar-fill.negative { background: var(--neon-red); box-shadow: 0 0 4px rgba(255,51,51,0.3); right: 50%; }
.sent-bar-val { width: 50px; text-align: left; font-size: 0.65rem; }
.sent-bar-val.pos { color: var(--neon-green); }
.sent-bar-val.neg { color: var(--neon-red); }
.sent-bar-val.na { color: var(--pixel-gray); }
.empty-state { text-align: center; padding: 60px 20px; color: var(--pixel-gray); font-size: 0.5rem; line-height: 2.5; }
.arcade-footer { text-align: center; padding: 20px; font-size: 0.35rem; color: var(--pixel-gray); letter-spacing: 1px; line-height: 2.2; }
.footer-pixel-art { margin-bottom: 12px; font-size: 0.4rem; color: var(--neon-blue-dim); line-height: 1; letter-spacing: 0; white-space: pre; }
.pixel-divider { height: 2px; background: repeating-linear-gradient(90deg, var(--neon-amber-dim), var(--neon-amber-dim) 4px, transparent 4px, transparent 8px); margin: 12px 0; }
.stat-row { display: flex; justify-content: center; gap: 32px; margin-bottom: 12px; }
.stat-item { text-align: center; }
.stat-num { font-size: 0.7rem; color: var(--neon-green); text-shadow: var(--glow-green); }
.stat-label { font-size: 0.35rem; color: var(--pixel-gray); margin-top: 4px; letter-spacing: 1px; }
.modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(5,5,8,0.85); z-index: 5000; justify-content: center; align-items: center; }
.modal-overlay.open { display: flex; }
.modal-box { border: 3px solid var(--neon-pink); background: var(--crt-bg); padding: 32px; max-width: 700px; width: 90%; box-shadow: var(--glow-pink); position: relative; }
.modal-close { position: absolute; top: 8px; right: 12px; font-family: var(--font-pixel); font-size: 1.5rem; background: none; border: none; color: var(--neon-pink); cursor: pointer; text-shadow: 0 0 4px var(--neon-pink); }
.modal-title { font-size: 1.65rem; color: var(--neon-pink); text-shadow: var(--glow-pink); margin-bottom: 16px; letter-spacing: 1px; }
.calc-row { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.calc-label { font-size: 1.2rem; color: var(--pixel-gray); width: 180px; }
.calc-value { font-size: 1.35rem; color: var(--neon-green); text-shadow: 0 0 4px var(--neon-green); min-width: 180px; }
.calc-input { font-family: var(--font-pixel); font-size: 1.35rem; background: var(--pixel-dark); border: 2px solid var(--pixel-gray); color: var(--neon-pink); padding: 8px 12px; outline: none; width: 200px; text-shadow: 0 0 4px var(--neon-pink); }
.calc-input:focus { border-color: var(--neon-pink); }
.calc-divider { height: 1px; background: var(--pixel-gray); margin: 12px 0; opacity: 0.3; }
/* Portfolio Allocator */
.modal-box.portfolio-modal { max-width: 1250px; width: 95%; max-height: 90vh; overflow-y: auto; }
.portfolio-controls { display: flex; gap: 16px; align-items: flex-end; margin-bottom: 16px; flex-wrap: wrap; }
.portfolio-control-group { display: flex; flex-direction: column; gap: 4px; }
.portfolio-control-label { font-size: 0.5rem; color: var(--pixel-gray); letter-spacing: 1px; }
.portfolio-slider { -webkit-appearance: none; appearance: none; width: 200px; height: 8px; background: var(--pixel-dark); border: 1px solid var(--pixel-gray); outline: none; cursor: pointer; }
.portfolio-slider::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 16px; height: 16px; background: var(--neon-pink); border: 2px solid var(--neon-pink); cursor: pointer; box-shadow: 0 0 6px var(--neon-pink); }
.portfolio-slider::-moz-range-thumb { width: 16px; height: 16px; background: var(--neon-pink); border: 2px solid var(--neon-pink); cursor: pointer; box-shadow: 0 0 6px var(--neon-pink); border-radius: 0; }
.portfolio-slider-value { font-size: 0.7rem; color: var(--neon-pink); text-shadow: 0 0 4px var(--neon-pink); min-width: 30px; text-align: center; }
.portfolio-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 16px; }
.portfolio-summary-item { background: var(--pixel-dark); border: 1px solid var(--pixel-gray); padding: 10px; text-align: center; }
.portfolio-summary-label { font-size: 0.4rem; color: var(--pixel-gray); letter-spacing: 1px; margin-bottom: 4px; }
.portfolio-summary-value { font-size: 0.7rem; color: var(--neon-green); text-shadow: 0 0 4px var(--neon-green); }
.portfolio-summary-value.risk { color: var(--neon-red); text-shadow: 0 0 4px var(--neon-red); }
.portfolio-summary-value.rr { color: var(--neon-blue); text-shadow: 0 0 4px var(--neon-blue); }
.portfolio-table-header { display: grid; grid-template-columns: 50px 130px 110px 120px 120px 100px 120px 110px 110px; gap: 0 14px; padding: 8px 6px; border-bottom: 2px solid var(--neon-amber); font-size: 0.9rem; color: var(--neon-amber); text-shadow: 0 0 4px var(--neon-amber); letter-spacing: 1px; }
.portfolio-table-body { max-height: 50vh; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--neon-pink-dim) var(--pixel-dark); }
.portfolio-table-body::-webkit-scrollbar { width: 6px; }
.portfolio-table-body::-webkit-scrollbar-track { background: var(--pixel-dark); }
.portfolio-table-body::-webkit-scrollbar-thumb { background: var(--neon-pink-dim); border: 1px solid var(--neon-pink); }
.portfolio-table-row { display: grid; grid-template-columns: 50px 130px 110px 120px 120px 100px 120px 110px 110px; gap: 0 14px; padding: 8px 6px; border-bottom: 1px solid rgba(85,85,112,0.3); font-size: 1.2rem; align-items: center; }
.portfolio-table-row:nth-child(even) { background: rgba(22,22,42,0.4); }
.portfolio-col-rank { color: var(--neon-amber); }
.portfolio-col-symbol { color: var(--neon-blue); text-shadow: 0 0 4px var(--neon-blue); }
.portfolio-col-stop { color: var(--neon-red); text-shadow: 0 0 4px var(--neon-red); text-align: right; }
.portfolio-col-alloc { color: var(--neon-green); text-shadow: 0 0 4px var(--neon-green); }
.portfolio-col-pct { color: var(--pixel-white); }
.portfolio-col-shares { color: var(--neon-pink); text-shadow: 0 0 4px var(--neon-pink); text-align: right; }
.portfolio-col-price { color: var(--pixel-white); text-align: right; }
.portfolio-col-t1 { text-align: right; }
.portfolio-col-risk { color: var(--neon-red); text-align: right; }
.portfolio-col-reward { color: var(--neon-green); text-align: right; }
.portfolio-col-target { color: var(--neon-green); text-shadow: 0 0 4px var(--neon-green); text-align: right; }
.portfolio-table-header div:nth-child(3),
.portfolio-table-header div:nth-child(4),
.portfolio-table-header div:nth-child(5),
.portfolio-table-header div:nth-child(6),
.portfolio-table-header div:nth-child(7),
.portfolio-table-header div:nth-child(8),
.portfolio-table-header div:nth-child(9) { text-align: right; }
/* Previous Performance */
.prev-perf-section { border: 2px solid var(--neon-blue-dim); background: var(--pixel-dark); padding: 12px; margin-bottom: 12px; }
.prev-perf-title { font-size: 1.0rem; color: var(--neon-blue); text-shadow: 0 0 4px var(--neon-blue); margin-bottom: 10px; letter-spacing: 1px; }
.prev-perf-header, .prev-perf-row { display: grid; grid-template-columns: 90px 70px 1fr 100px 80px; padding: 8px 8px; font-size: 0.8rem; align-items: center; }
.prev-perf-header { color: var(--neon-amber); text-shadow: 0 0 4px var(--neon-amber); border-bottom: 1px solid var(--neon-amber-dim); letter-spacing: 1px; }
.prev-perf-row { border-bottom: 1px solid rgba(85,85,112,0.2); }
.prev-perf-row:nth-child(even) { background: rgba(22,22,42,0.3); }
.outcome-badge { font-size: 0.6rem; padding: 2px 6px; border: 1px solid; display: inline-block; }
.outcome-badge.win { color: var(--neon-green); border-color: var(--neon-green-dim); background: rgba(57,255,20,0.1); }
.outcome-badge.loss { color: var(--neon-red); border-color: var(--neon-red-dim); background: rgba(255,51,51,0.1); }
.outcome-badge.active { color: var(--neon-blue); border-color: var(--neon-blue-dim); background: rgba(0,212,255,0.1); }
.outcome-badge.noentry { color: var(--pixel-gray); border-color: rgba(85,85,112,0.3); background: rgba(85,85,112,0.1); }
/* Calc button in toolbar */
.toolbar { display: flex; gap: 8px; margin-bottom: 12px; justify-content: flex-end; }
@media (max-width: 900px) {
  .leaderboard-header, .leaderboard-row { grid-template-columns: 24px 30px 70px 1fr 50px 80px 80px 60px 60px 90px 60px; font-size: 0.7rem; padding: 8px 6px; }
  .marquee-title { font-size: 1rem; }
  .detail-grid { grid-template-columns: 1fr; }
  .status-bar { grid-template-columns: 1fr; }
  .health-bar { width: 40px; }
  .prev-perf-header, .prev-perf-row { grid-template-columns: 70px 50px 1fr 80px 60px; font-size: 0.7rem; }
  .portfolio-table-header, .portfolio-table-row { grid-template-columns: 30px 70px 65px 70px 70px 60px 60px; }
  .portfolio-col-risk, .portfolio-col-reward { display: none; }
  .portfolio-summary { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .leaderboard-header, .leaderboard-row { grid-template-columns: 24px 30px 1fr 70px 70px; }
  .col-stop, .col-t1, .col-target, .col-rr, .col-ml, .col-sent { display: none; }
  .marquee-title { font-size: 0.7rem; letter-spacing: 2px; }
  .prev-perf-header, .prev-perf-row { grid-template-columns: 60px 1fr 70px 60px; }
  .prev-perf-header span:nth-child(2), .prev-perf-row span:nth-child(2) { display: none; }
  .portfolio-table-header, .portfolio-table-row { grid-template-columns: 30px 1fr 60px 60px 60px 60px; }
  .portfolio-col-stop, .portfolio-col-t1, .portfolio-col-target { display: none; }
}
</style>"""

        # ── JS ──────────────────────────────────────────────────
        arcade_js = r"""
const state = {
  candidates: [],
  filtered: [],
  regime: null,
  currentDate: null,
  currentFilter: 'all',
  calcCandidate: null,
  selected: {},
};

function normalizeStrategy(s) {
  if (!s) return 'Baseline';
  const lower = s.toLowerCase();
  if (lower.includes('mean') || lower.includes('reversion') || lower === 'meanrev') return 'MeanRev';
  if (lower === 'connors') return 'Connors';
  return 'Baseline';
}

function renderAll() {
  renderStatusBar();
  renderLeaderboard();
  renderStats();
  renderTicker();
  document.getElementById('stratTabs').style.display = 'flex';
  document.querySelectorAll('.strategy-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.filter === state.currentFilter);
  });
}

function renderStatusBar() {
  const bar = document.getElementById('statusBar');
  bar.style.display = 'grid';
  const regime = state.regime;
  const regimeEl = document.getElementById('regimeStatus');
  if (regime) {
    const status = regime.status || 'NEUTRAL';
    regimeEl.textContent = status.toUpperCase();
    regimeEl.className = 'value ' + status.toLowerCase();
    if (regime.details && regime.details.SPY) {
      const spy = regime.details.SPY;
      document.getElementById('spyValue').textContent = spy.close ? '$' + spy.close.toFixed(2) : '---';
    }
    if (regime.details && regime.details.QQQ) {
      const qqq = regime.details.QQQ;
      document.getElementById('qqqValue').textContent = qqq.close ? '$' + qqq.close.toFixed(2) : '---';
    }
    if (regime.details && regime.details.VIX) {
      const vix = regime.details.VIX;
      const vixEl = document.getElementById('vixValue');
      vixEl.textContent = vix.close.toFixed(1);
      vixEl.className = 'value ' + (vix.close <= 20 ? 'bullish' : vix.close > 30 ? 'bearish' : 'neutral');
    }
    if (regime.details && regime.details.AAII) {
      const aaii = regime.details.AAII;
      const aaiiEl = document.getElementById('aaiiValue');
      const spread = aaii.bull_bear_spread;
      aaiiEl.textContent = spread.toFixed(1) + ' (' + aaii.signal + ')';
      aaiiEl.className = 'value ' + (spread <= -10 ? 'bullish' : spread >= 20 ? 'bearish' : 'neutral');
    }
    if (regime.details && regime.details.CNN) {
      const cnn = regime.details.CNN;
      const cnnEl = document.getElementById('cnnValue');
      cnnEl.textContent = cnn.score.toFixed(0) + ' (' + cnn.rating + ')';
      cnnEl.className = 'value ' + (cnn.score <= 40 ? 'bullish' : cnn.score >= 75 ? 'bearish' : 'neutral');
    }
  } else {
    regimeEl.textContent = 'N/A';
    regimeEl.className = 'value neutral';
    document.getElementById('spyValue').textContent = '---';
    document.getElementById('qqqValue').textContent = '---';
    document.getElementById('vixValue').textContent = '---';
    document.getElementById('aaiiValue').textContent = '---';
    document.getElementById('cnnValue').textContent = '---';
  }
}

function renderLeaderboard() {
  const lb = document.getElementById('leaderboard');
  const body = document.getElementById('leaderboardBody');
  lb.style.display = 'block';
  body.innerHTML = '';
  if (state.filtered.length === 0) {
    body.innerHTML = '<div class="empty-state">NO CANDIDATES FOUND</div>';
    return;
  }
  state.filtered.forEach((c, i) => {
    const rank = i + 1;
    const score = c.score;
    const mlPct = Math.round((c.ml_prob || 0) * 100);
    const rr = c.stop_loss > 0 ? ((c.target - c.close) / (c.close - c.stop_loss)).toFixed(1) : '---';
    const scoreClass = score >= 50 ? 'high' : score >= 30 ? 'mid' : 'low';
    const scoreTextClass = score >= 50 ? 'score-high' : score >= 30 ? 'score-mid' : 'score-low';
    const mlColor = mlPct >= 70 ? 'green' : mlPct >= 50 ? 'amber' : 'red';
    const mlTextClass = mlPct >= 70 ? 'score-high' : mlPct >= 50 ? 'score-mid' : 'score-low';
    const rankClass = rank <= 3 ? 'rank-' + rank : '';
    const stratClass = c.strategy === 'Connors' ? 'connors' : c.strategy === 'MeanRev' ? 'meanrev' : 'baseline';
    const stratLabel = c.strategy === 'Connors' ? 'CR' : c.strategy === 'MeanRev' ? 'MR' : 'BL';
    const sent = c.sentiment_composite || 0;
    const sentClass = sent === 0 ? 'sent-neutral' : sent > 0.15 ? 'sent-bull' : sent < -0.15 ? 'sent-bear' : 'sent-neutral';
    const sentLabel = sent === 0 ? 'N/A' : (sent > 0 ? '\u25B2' : '\u25BC') + sent.toFixed(2);
    const scoreWidth = Math.min(100, (score / 80) * 100);
    const mlPips = Math.round(mlPct / 10);
    const detailId = 'detail-' + i;
    const row = document.createElement('div');
    row.className = 'leaderboard-row ' + rankClass;
    row.style.animationDelay = (i * 0.04) + 's';
    row.onclick = function() { toggleDetail(i); };
    let pipsHtml = '';
    for (let j = 0; j < 10; j++) {
      pipsHtml += '<div class="ml-pip ' + (j < mlPips ? 'filled ' + mlColor : '') + '"></div>';
    }
    var selKey = c.symbol + '|' + c.strategy;
    row.innerHTML =
      '<div class="col-check"><input type="checkbox" class="portfolio-check"' + (state.selected[selKey] ? ' checked' : '') + ' onclick="toggleSelection(\'' + selKey + '\', event)"></div>' +
      '<div class="col-rank"><span class="rank-num">' + String(rank).padStart(2, '0') + '</span></div>' +
      '<div class="col-symbol"><span class="symbol-name">' + c.symbol + '</span><span class="strategy-badge ' + stratClass + '">' + stratLabel + '</span></div>' +
      '<div class="col-score"><div class="health-bar"><div class="health-bar-fill ' + scoreClass + '" style="width:' + scoreWidth + '%"></div></div><span class="score-value ' + scoreTextClass + '">' + score.toFixed(1) + '</span></div>' +
      '<div class="col-sent ' + sentClass + '">' + sentLabel + '</div>' +
      '<div class="col-price">$' + c.close.toFixed(2) + '</div>' +
      '<div class="col-stop">$' + c.stop_loss.toFixed(2) + '</div>' +
      '<div class="col-t1" style="color:var(--neon-amber);text-shadow:0 0 4px var(--neon-amber)">$' + (c.t1_target ? c.t1_target.toFixed(2) : '---') + '</div>' +
      '<div class="col-target" style="color:var(--neon-green)">$' + c.target.toFixed(2) + '</div>' +
      '<div class="col-ml"><div class="ml-meter">' + pipsHtml + '</div><span class="ml-pct ' + mlTextClass + '">' + mlPct + '%</span></div>' +
      '<div class="col-rr">' + rr + 'x</div>';
    body.appendChild(row);
    const detail = document.createElement('div');
    detail.className = 'detail-panel';
    detail.id = detailId;
    detail.innerHTML = buildDetailHTML(c);
    body.appendChild(detail);
  });
}

function buildSentimentBar(label, value, isComposite) {
  var labelCls = isComposite ? 'sent-bar-label comp-label' : 'sent-bar-label';
  if (value === 0) {
    return '<div class="sent-bar-row"><span class="' + labelCls + '">' + label + '</span>' +
      '<div class="sent-bar"><div class="sent-bar-center"></div></div>' +
      '<span class="sent-bar-val na">N/A</span></div>';
  }
  var pct = Math.abs(value) * 50;
  var cls = value >= 0 ? 'positive' : 'negative';
  var valCls = value >= 0 ? 'pos' : 'neg';
  var arrow = value >= 0 ? '\u25B2' : '\u25BC';
  return '<div class="sent-bar-row"><span class="' + labelCls + '">' + label + '</span>' +
    '<div class="sent-bar"><div class="sent-bar-center"></div>' +
    '<div class="sent-bar-fill ' + cls + '" style="width:' + pct + '%"></div></div>' +
    '<span class="sent-bar-val ' + valCls + '">' + arrow + value.toFixed(2) + '</span></div>';
}

function buildSentimentHTML(c) {
  return '<div class="detail-section"><div class="detail-section-title">SENTIMENT ANALYSIS</div>' +
    buildSentimentBar('AV', c.sentiment || 0, false) +
    buildSentimentBar('TI', c.sentiment_tiingo || 0, false) +
    buildSentimentBar('ST', c.sentiment_stocktwits || 0, false) +
    buildSentimentBar('FV', c.sentiment_finviz || 0, false) +
    '<div style="height:1px;background:var(--pixel-gray);opacity:0.3;margin:6px 0"></div>' +
    buildSentimentBar('COMP', c.sentiment_composite || 0, true) +
    '</div>';
}

function buildDetailHTML(c) {
  const riskPct = c.close > 0 ? (((c.close - c.stop_loss) / c.close) * 100).toFixed(2) : 0;
  const rewardPct = c.close > 0 ? (((c.target - c.close) / c.close) * 100).toFixed(2) : 0;
  const totalRange = c.target - c.stop_loss;
  const riskWidth = totalRange > 0 ? ((c.close - c.stop_loss) / totalRange * 100) : 30;
  const rewardWidth = totalRange > 0 ? ((c.target - c.close) / totalRange * 100) : 70;
  const t1Pos = (c.t1_target && totalRange > 0) ? ((c.t1_target - c.stop_loss) / totalRange * 100) : 0;
  let components = c.components || {};
  if (c.reasons && c.reasons.length && Object.keys(components).length === 0) {
    c.reasons.forEach(function(r) {
      const parts = r.split('=');
      if (parts[0] && parts[1]) components[parts[0]] = parseFloat(parts[1]);
    });
  }
  const maxAbsComponent = Math.max(1, ...Object.values(components).map(Math.abs));
  const indicatorBars = Object.entries(components).map(function(entry) {
    const name = entry[0], val = entry[1];
    const pct = Math.abs(val) / maxAbsComponent * 100;
    const cls = val >= 0 ? 'positive' : 'negative';
    const valCls = val >= 0 ? 'pos' : 'neg';
    const sign = val >= 0 ? '+' : '';
    return '<div class="indicator-bar-row"><span class="indicator-name">' + name + '</span>' +
      '<div class="indicator-bar"><div class="indicator-bar-fill ' + cls + '" style="width:' + pct + '%"></div></div>' +
      '<span class="indicator-val ' + valCls + '">' + sign + val.toFixed(1) + '</span></div>';
  }).join('');
  var t1Html = (c.t1_target && t1Pos > 0) ?
    '<div class="rr-t1-marker" style="left:' + t1Pos + '%"></div>' +
    '<span class="rr-label t1" style="left:' + t1Pos + '%">T1 $' + c.t1_target.toFixed(2) + ' (+2%)</span>' : '';
  return '<div class="detail-grid">' +
    '<div class="detail-section"><div class="detail-section-title">RISK / REWARD MAP</div>' +
    '<div class="rr-diagram"><div class="rr-zone-risk" style="width:' + riskWidth + '%"></div>' +
    '<div class="rr-zone-reward" style="width:' + rewardWidth + '%;left:' + riskWidth + '%"></div>' +
    '<div class="rr-entry-marker" style="left:' + riskWidth + '%"></div>' +
    t1Html +
    '<span class="rr-label stop">STOP $' + c.stop_loss.toFixed(2) + '</span>' +
    '<span class="rr-label entry" style="left:' + riskWidth + '%">ENTRY $' + c.close.toFixed(2) + '</span>' +
    '<span class="rr-label target">T2 $' + c.target.toFixed(2) + '</span></div>' +
    '<div style="display:flex;gap:20px;margin-top:10px;font-size:0.7rem;">' +
    '<span style="color:var(--neon-red)">RISK: ' + riskPct + '%</span>' +
    '<span style="color:var(--neon-amber)">T1: +2.0%</span>' +
    '<span style="color:var(--neon-green)">T2: ' + rewardPct + '%</span>' +
    '<span style="color:var(--neon-blue)">R:R ' + (parseFloat(rewardPct) / Math.max(0.01, parseFloat(riskPct))).toFixed(2) + 'x</span></div>' +
    '<div style="margin-top:14px">' +
    '<button class="arcade-btn btn-pink" style="font-size:0.7rem;padding:5px 10px" onclick="event.stopPropagation();openCalcForSymbol(\'' + c.symbol + '\',' + c.close + ',' + c.stop_loss + ',' + c.target + ')">CALC SHARES</button>' +
    '<a href="https://finance.yahoo.com/quote/' + c.symbol + '" target="_blank" rel="noopener" class="arcade-btn btn-blue" style="font-size:0.7rem;padding:5px 10px;text-decoration:none;display:inline-block;margin-left:4px">YAHOO</a></div></div>' +
    buildSentimentHTML(c) +
    '<div class="detail-section"><div class="detail-section-title">POWER LEVELS</div>' +
    (c.strategy === 'Connors' && c.connors_rsi2 !== undefined ?
      '<div style="display:flex;gap:20px;margin-bottom:10px;font-size:0.7rem;">' +
      '<span style="color:var(--neon-amber)">RSI(2): ' + c.connors_rsi2.toFixed(1) + '</span>' +
      (c.connors_sma200 ? '<span style="color:var(--neon-blue)">SMA200: $' + c.connors_sma200.toFixed(2) + '</span>' +
      '<span style="color:var(--neon-green)">' + ((c.close - c.connors_sma200) / c.connors_sma200 * 100).toFixed(1) + '% above</span>' : '') +
      '</div>' : '') +
    (indicatorBars || '<div style="font-size:0.7rem;color:var(--pixel-gray)">No component data available</div>') +
    '</div></div>';
}

function toggleDetail(index) {
  const detail = document.getElementById('detail-' + index);
  if (!detail) return;
  const isOpen = detail.classList.contains('open');
  document.querySelectorAll('.detail-panel.open').forEach(function(d) { d.classList.remove('open'); });
  if (!isOpen) detail.classList.add('open');
}

function renderStats() {
  document.getElementById('statsRow').style.display = 'flex';
  const total = state.filtered.length;
  const avgScore = total > 0 ? (state.filtered.reduce(function(s, c) { return s + c.score; }, 0) / total).toFixed(1) : 0;
  const avgML = total > 0 ? Math.round(state.filtered.reduce(function(s, c) { return s + (c.ml_prob || 0); }, 0) / total * 100) : 0;
  const best = total > 0 ? state.filtered[0].symbol : '---';
  document.getElementById('statTotal').textContent = total;
  document.getElementById('statAvgScore').textContent = avgScore;
  document.getElementById('statAvgML').textContent = avgML + '%';
  document.getElementById('statBest').textContent = best;
}

function renderTicker() {
  const tc = document.getElementById('tickerContent');
  if (state.filtered.length === 0) {
    tc.innerHTML = '<span class="ticker-item">NO DATA LOADED</span>';
    return;
  }
  const items = state.filtered.slice(0, 20).map(function(c) {
    const mlPct = Math.round((c.ml_prob || 0) * 100);
    const color = mlPct >= 70 ? 'var(--neon-green)' : mlPct >= 50 ? 'var(--neon-amber)' : 'var(--neon-red)';
    return '<span class="ticker-item" style="color:' + color + '">' + c.symbol + ' $' + c.close.toFixed(2) + ' [' + c.score.toFixed(1) + ']</span>';
  }).join('<span class="ticker-sep">|</span>');
  tc.innerHTML = items + '<span class="ticker-sep">&bull;</span>' + items;
}

function filterStrategy(filter, btn) {
  state.currentFilter = filter;
  document.querySelectorAll('.strategy-tab').forEach(function(t) {
    t.classList.toggle('active', t.dataset.filter === filter);
  });
  if (filter === 'all') {
    state.filtered = state.candidates.slice();
  } else {
    state.filtered = state.candidates.filter(function(c) { return c.strategy === filter; });
  }
  renderLeaderboard();
  renderStats();
  renderTicker();
}

function openCalcModal() { document.getElementById('calcModal').classList.add('open'); }
function closeCalcModal() { document.getElementById('calcModal').classList.remove('open'); }
function openCalcForSymbol(symbol, entry, stop, target) {
  state.calcCandidate = { symbol: symbol, entry: entry, stop: stop, target: target };
  document.getElementById('calcSymbol').textContent = symbol;
  document.getElementById('calcEntry').textContent = '$' + entry.toFixed(2);
  document.getElementById('calcStop').textContent = '$' + stop.toFixed(2);
  document.getElementById('calcTarget').textContent = '$' + target.toFixed(2);
  updateCalc();
  openCalcModal();
}
function updateCalc() {
  const c = state.calcCandidate;
  if (!c) return;
  const invest = parseFloat(document.getElementById('calcInvest').value) || 0;
  const fractional = invest / c.entry;
  const costFrac = (fractional * c.entry).toFixed(2);
  const riskFrac = (fractional * (c.entry - c.stop)).toFixed(2);
  const rewardFrac = (fractional * (c.target - c.entry)).toFixed(2);
  document.getElementById('calcSharesFrac').textContent = fractional.toFixed(3);
  document.getElementById('calcCostFrac').textContent = '$' + costFrac;
  document.getElementById('calcRiskFrac').textContent = '-$' + riskFrac;
  document.getElementById('calcRewardFrac').textContent = '+$' + rewardFrac;
}
// Portfolio Allocator
function normalizeScore(score) {
  return Math.max(0, Math.min(1, score / 50));
}
function normalizeMlProb(ml) {
  return Math.max(0, Math.min(1, ml));
}
function normalizeRR(entry, stop, target) {
  if (entry <= 0 || stop >= entry || target <= entry) return 0;
  var rr = (target - entry) / (entry - stop);
  return Math.min(1, Math.log(1 + rr) / Math.log(1 + 5));
}
function compositeWeight(c) {
  return 0.40 * normalizeScore(c.score) + 0.35 * normalizeMlProb(c.ml_prob || 0) + 0.25 * normalizeRR(c.close, c.stop_loss, c.target);
}
function toggleSelection(key, event) {
  event.stopPropagation();
  if (state.selected[key]) delete state.selected[key];
  else state.selected[key] = true;
  updatePortfolioBadge();
}
function updatePortfolioBadge() {
  var count = Object.keys(state.selected).length;
  var badge = document.getElementById('portfolioBadge');
  if (badge) { badge.textContent = count; badge.style.display = count > 0 ? 'inline-block' : 'none'; }
  var countEl = document.getElementById('portfolioSelectedCount');
  if (countEl) countEl.textContent = count;
}
function selectAllSymbols() {
  state.candidates.forEach(function(c) {
    if (c.close > 0 && c.stop_loss < c.close && c.target > c.close) {
      state.selected[c.symbol + '|' + c.strategy] = true;
    }
  });
  updatePortfolioBadge();
  renderLeaderboard();
  updatePortfolio();
}
function clearAllSymbols() {
  state.selected = {};
  updatePortfolioBadge();
  renderLeaderboard();
  updatePortfolio();
}
function getAutoThreshold(candidates) {
  if (candidates.length === 0) return 3;
  var q = Math.ceil(candidates.length / 4);
  return Math.max(3, Math.min(15, q));
}
function getValidPortfolioCandidates() {
  var selectedKeys = Object.keys(state.selected);
  return state.candidates.filter(function(c) {
    var key = c.symbol + '|' + c.strategy;
    return selectedKeys.indexOf(key) >= 0 && c.close > 0 && c.stop_loss < c.close && c.target > c.close;
  }).map(function(c) {
    var copy = {};
    for (var k in c) copy[k] = c[k];
    copy.composite = compositeWeight(c);
    return copy;
  }).sort(function(a, b) { return b.composite - a.composite; });
}
function allocatePortfolio(candidates, totalInvest, topN) {
  var selected = candidates.slice(0, topN);
  if (selected.length === 0) return [];
  var totalWeight = selected.reduce(function(s, c) { return s + c.composite; }, 0);
  if (totalWeight === 0) return [];
  return selected.map(function(c) {
    var pct = c.composite / totalWeight;
    var alloc = totalInvest * pct;
    var shares = alloc / c.close;
    var wholeShares = Math.floor(shares);
    var risk = shares * (c.close - c.stop_loss);
    var t1Gain = c.t1_target ? (c.t1_target - c.close) : 0;
    var t2Gain = c.target - c.close;
    var blendedRewardPerShare = 0.5 * t1Gain + 0.5 * t2Gain;
    var reward = shares * blendedRewardPerShare;
    var rr = risk > 0 ? reward / risk : 0;
    return { symbol: c.symbol, strategy: c.strategy, close: c.close, stop_loss: c.stop_loss, t1_target: c.t1_target || 0, target: c.target, alloc: alloc, pct: pct, shares: shares, risk: risk, reward: reward };
  });
}
function openPortfolioModal() {
  document.getElementById('portfolioModal').classList.add('open');
  updatePortfolioBadge();
  updatePortfolio();
}
function closePortfolioModal() {
  document.getElementById('portfolioModal').classList.remove('open');
}
function updatePortfolio() {
  var candidates = getValidPortfolioCandidates();
  var totalInvest = parseFloat(document.getElementById('portfolioInvest').value) || 0;
  var results = allocatePortfolio(candidates, totalInvest, candidates.length);
  renderPortfolioSummary(results);
  renderPortfolioTable(results);
}
function renderPortfolioSummary(results) {
  var totalAlloc = results.reduce(function(s, r) { return s + r.alloc; }, 0);
  var totalRisk = results.reduce(function(s, r) { return s + r.risk; }, 0);
  var totalReward = results.reduce(function(s, r) { return s + r.reward; }, 0);
  var portfolioRR = totalRisk > 0 ? (totalReward / totalRisk).toFixed(2) : '---';
  document.getElementById('portfolioTotalAlloc').textContent = '$' + totalAlloc.toFixed(2);
  document.getElementById('portfolioTotalRisk').textContent = '-$' + totalRisk.toFixed(2);
  document.getElementById('portfolioTotalReward').textContent = '+$' + totalReward.toFixed(2);
  document.getElementById('portfolioRR').textContent = portfolioRR + 'x';
}
function renderPortfolioTable(results) {
  var body = document.getElementById('portfolioTableBody');
  if (results.length === 0) {
    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--pixel-gray);font-size:0.5rem">NO VALID CANDIDATES</div>';
    return;
  }
  body.innerHTML = results.map(function(r, i) {
    var stratClass = r.strategy === 'Connors' ? 'connors' : r.strategy === 'MeanRev' ? 'meanrev' : 'baseline';
    var stratLabel = r.strategy === 'Connors' ? 'CR' : r.strategy === 'MeanRev' ? 'MR' : 'BL';
    var t1Val = r.t1_target ? '$' + r.t1_target.toFixed(2) : '---';
    return '<div class="portfolio-table-row">' +
      '<div class="portfolio-col-rank">' + String(i + 1).padStart(2, '0') + '</div>' +
      '<div class="portfolio-col-symbol">' + r.symbol + '</div>' +
      '<div class="portfolio-col-shares">' + (r.shares / 2).toFixed(2) + '</div>' +
      '<div class="portfolio-col-price">$' + r.close.toFixed(2) + '</div>' +
      '<div class="portfolio-col-stop">$' + r.stop_loss.toFixed(2) + '</div>' +
      '<div class="portfolio-col-t1" style="color:var(--neon-amber);text-shadow:0 0 4px var(--neon-amber)">' + t1Val + '</div>' +
      '<div class="portfolio-col-target" style="color:var(--neon-green)">$' + r.target.toFixed(2) + '</div>' +
      '<div class="portfolio-col-risk">-$' + r.risk.toFixed(0) + '</div>' +
      '<div class="portfolio-col-reward">+$' + r.reward.toFixed(0) + '</div></div>';
  }).join('');
}

document.getElementById('calcModal').addEventListener('click', function(e) { if (e.target === this) closeCalcModal(); });
document.getElementById('portfolioModal').addEventListener('click', function(e) { if (e.target === this) closePortfolioModal(); });
document.addEventListener('keydown', function(e) { if (e.key === 'Escape') { closeCalcModal(); closePortfolioModal(); } });

// Initialize from embedded data
document.addEventListener('DOMContentLoaded', function() {
  state.candidates = REPORT_DATA.candidates.map(function(c) {
    return {
      symbol: c.symbol || '???',
      exchange: c.exchange || '',
      strategy: normalizeStrategy(c.strategy),
      score: c.score || 0,
      close: c.close || 0,
      stop_loss: c.stop_loss || 0,
      t1_target: c.t1_target || 0,
      target: c.target || 0,
      ml_prob: c.ml_prob || 0,
      sentiment: c.sentiment || 0,
      sentiment_tiingo: c.sentiment_tiingo || 0,
      sentiment_stocktwits: c.sentiment_stocktwits || 0,
      sentiment_finviz: c.sentiment_finviz || 0,
      sentiment_composite: c.sentiment_composite || 0,
      reasons: c.reasons || [],
      components: c.components || {}
    };
  });
  state.candidates.sort(function(a, b) { return b.score - a.score; });
  state.regime = REPORT_DATA.regime || null;
  state.currentDate = REPORT_DATA.date;
  state.currentFilter = 'all';
  state.filtered = state.candidates.slice();
  renderAll();
});
"""

        # ── Build HTML ──────────────────────────────────────────
        html = [
            '<!DOCTYPE html>',
            '<html lang="en">',
            '<head>',
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f'<title>BLUE HORSESHOE &mdash; {date}</title>',
            f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{favicon_b64}">' if favicon_b64 else '',
            '<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">',
            arcade_css,
            '</head>',
            '<body class="crt-screen">',
            '<div class="arcade-cabinet">',

            # Marquee header
            '<div class="marquee-sign">',
            '<div class="pixel-corner tl"></div><div class="pixel-corner tr"></div>',
            '<div class="pixel-corner bl"></div><div class="pixel-corner br"></div>',
            f'<img src="data:image/png;base64,{banner_b64}" alt="Blue Horseshoe" class="marquee-banner">' if banner_b64 else '<div class="marquee-title">BLUE HORSESHOE</div>',
            '<div class="marquee-subtitle">SWING TRADING ARCADE &bull; EST. 2026</div>',
            f'<div class="marquee-date">REPORT: {date}</div>',
            '</div>',

            # Ticker
            '<div class="ticker-bar">',
            '<div class="ticker-content" id="tickerContent">',
            '<span class="ticker-item">LOADING...</span>',
            '</div></div>',

            # Toolbar (calc button only)
            '<div class="toolbar">',
            '<button class="arcade-btn btn-pink" onclick="openPortfolioModal()">PORTFOLIO<span class="portfolio-badge" id="portfolioBadge">0</span></button>',
            '<button class="arcade-btn btn-blue" onclick="openCalcModal()">CALC</button>',
            '</div>',

            # Status bar
            '<div class="status-bar" id="statusBar" style="display:none">',
            '<div class="status-panel"><div class="label">MARKET REGIME</div><div class="value" id="regimeStatus">---</div></div>',
            '<div class="status-panel"><div class="label">SPY</div><div class="value" id="spyValue" style="color:var(--pixel-white)">---</div></div>',
            '<div class="status-panel"><div class="label">QQQ</div><div class="value" id="qqqValue" style="color:var(--pixel-white)">---</div></div>',
            '<div class="status-panel"><div class="label">VIX</div><div class="value" id="vixValue" style="color:var(--pixel-white)">---</div></div>',
            '<div class="status-panel"><div class="label">AAII SENTIMENT</div><div class="value" id="aaiiValue" style="color:var(--pixel-white)">---</div></div>',
            '<div class="status-panel"><div class="label">CNN FEAR/GREED</div><div class="value" id="cnnValue" style="color:var(--pixel-white)">---</div></div>',
            '</div>',

            # Strategy tabs
            '<div class="strategy-tabs" id="stratTabs" style="display:none">',
            '<button class="strategy-tab active" data-filter="all" onclick="filterStrategy(\'all\', this)">ALL</button>',
            '<button class="strategy-tab" data-filter="Baseline" onclick="filterStrategy(\'Baseline\', this)">BASELINE</button>',
            '<button class="strategy-tab" data-filter="MeanRev" onclick="filterStrategy(\'MeanRev\', this)">MEAN REV</button>',
            '<button class="strategy-tab" data-filter="Connors" onclick="filterStrategy(\'Connors\', this)">CONNORS</button>',
            '</div>',

            # Leaderboard
            '<div class="leaderboard" id="leaderboard" style="display:none">',
            '<div class="leaderboard-header">',
            '<div></div><div>#</div><div>SYMBOL</div><div>SCORE</div><div title="Z-score normalized composite sentiment">SENT</div><div>ENTRY</div><div>STOP</div><div>T1</div><div>T2</div><div>ML PROB</div><div>R:R</div>',
            '</div>',
            '<div class="leaderboard-body" id="leaderboardBody"></div>',
            '</div>',

            # Previous performance
            prev_perf_html,

            # Stats row
            '<div class="stat-row" id="statsRow" style="display:none">',
            '<div class="stat-item"><div class="stat-num" id="statTotal">0</div><div class="stat-label">CANDIDATES</div></div>',
            '<div class="stat-item"><div class="stat-num" id="statAvgScore">0</div><div class="stat-label">AVG SCORE</div></div>',
            '<div class="stat-item"><div class="stat-num" id="statAvgML">0%</div><div class="stat-label">AVG ML PROB</div></div>',
            '<div class="stat-item"><div class="stat-num" id="statBest">---</div><div class="stat-label">TOP PICK</div></div>',
            '</div>',

            # Divider + Footer
            '<div class="pixel-divider"></div>',
            '<div class="arcade-footer">',
            '<div class="footer-pixel-art" aria-hidden="true">',
            '   ___  _    _   _ ___   _  _  ___  ___  ___ ___ ___ _  _  ___  ___',
            '  | _ )| |  | | | | __| | || |/ _ \\| _ \\/ __| __/ __| || |/ _ \\| __|',
            '  | _ \\| |__| |_| | _|  | __ | (_) |   /\\__ \\ _|\\__ \\ __ | (_) | _|',
            '  |___/|____|\\___/|___| |_||_|\\___/|_|_\\|___/___|___/_||_|\\___/|___|</div>',
            '<div>POWERED BY QUANTITATIVE ANALYSIS AND MACHINE LEARNING</div>',
            f'<div style="margin-top:4px;color:var(--neon-amber-dim)">GENERATED {gen_timestamp}</div>',
            '</div>',

            '</div>',  # end arcade-cabinet

            # Calc modal
            '<div class="modal-overlay" id="calcModal">',
            '<div class="modal-box">',
            '<button class="modal-close" onclick="closeCalcModal()">X</button>',
            '<div class="modal-title">SHARE CALCULATOR</div>',
            '<div class="calc-row"><span class="calc-label">SYMBOL:</span><span class="calc-value" id="calcSymbol">---</span></div>',
            '<div class="calc-row"><span class="calc-label">ENTRY:</span><span class="calc-value" id="calcEntry">---</span></div>',
            '<div class="calc-row"><span class="calc-label">STOP:</span><span class="calc-value" style="color:var(--neon-red);text-shadow:0 0 4px var(--neon-red)" id="calcStop">---</span></div>',
            '<div class="calc-row"><span class="calc-label">TARGET:</span><span class="calc-value" id="calcTarget">---</span></div>',
            '<div class="calc-divider"></div>',
            '<div class="calc-row"><span class="calc-label">INVEST $:</span><input type="number" class="calc-input" id="calcInvest" value="10000" oninput="updateCalc()"></div>',
            '<div class="calc-divider"></div>',
            '<div class="calc-row"><span class="calc-label">SHARES:</span><span class="calc-value" id="calcSharesFrac">---</span></div>',
            '<div class="calc-row"><span class="calc-label">COST:</span><span class="calc-value" id="calcCostFrac">---</span></div>',
            '<div class="calc-row"><span class="calc-label">RISK $:</span><span class="calc-value" style="color:var(--neon-red);text-shadow:0 0 4px var(--neon-red)" id="calcRiskFrac">---</span></div>',
            '<div class="calc-row"><span class="calc-label">REWARD $:</span><span class="calc-value" id="calcRewardFrac">---</span></div>',
            '</div></div>',

            # Portfolio modal
            '<div class="modal-overlay" id="portfolioModal">',
            '<div class="modal-box portfolio-modal">',
            '<button class="modal-close" onclick="closePortfolioModal()">X</button>',
            '<div class="modal-title">PORTFOLIO ALLOCATOR</div>',
            '<div class="portfolio-controls">',
            '<div class="portfolio-control-group">',
            '<span class="portfolio-control-label">INVEST $</span>',
            '<input type="number" class="calc-input" id="portfolioInvest" value="10000" oninput="updatePortfolio()">',
            '</div>',
            '<div class="portfolio-control-group">',
            '<span class="portfolio-control-label">SELECTED</span>',
            '<span class="portfolio-slider-value" id="portfolioSelectedCount">0</span>',
            '</div>',
            '<div class="portfolio-control-group" style="flex-direction:row;gap:6px;align-items:flex-end">',
            '<button class="arcade-btn btn-green" style="font-size:0.4rem;padding:5px 8px" onclick="selectAllSymbols()">ALL</button>',
            '<button class="arcade-btn btn-amber" style="font-size:0.4rem;padding:5px 8px" onclick="clearAllSymbols()">CLEAR</button>',
            '</div></div>',
            '<div class="portfolio-summary">',
            '<div class="portfolio-summary-item"><div class="portfolio-summary-label">ALLOCATED</div><div class="portfolio-summary-value" id="portfolioTotalAlloc">$0</div></div>',
            '<div class="portfolio-summary-item"><div class="portfolio-summary-label">TOTAL RISK</div><div class="portfolio-summary-value risk" id="portfolioTotalRisk">-$0</div></div>',
            '<div class="portfolio-summary-item"><div class="portfolio-summary-label">TOTAL REWARD</div><div class="portfolio-summary-value" id="portfolioTotalReward">+$0</div></div>',
            '<div class="portfolio-summary-item"><div class="portfolio-summary-label">PORTFOLIO R:R</div><div class="portfolio-summary-value rr" id="portfolioRR">---</div></div>',
            '</div>',
            '<div class="portfolio-table-header">',
            '<div>#</div><div>SYM</div><div>QTY/2</div><div>PRICE</div><div class="portfolio-col-stop">STOP</div><div class="portfolio-col-t1">T1</div><div class="portfolio-col-target">T2</div><div class="portfolio-col-risk">RISK</div><div class="portfolio-col-reward">RWD</div>',
            '</div>',
            '<div class="portfolio-table-body" id="portfolioTableBody"></div>',
            '</div></div>',

            # Script block
            '<script>',
            f'const REPORT_DATA = {data_json};',
            arcade_js,
            '</script>',
            '</body>',
            '</html>',
        ]

        return '\n'.join(html)
