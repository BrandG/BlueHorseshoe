"""
HTML Reporter module for BlueHorseshoe.
Generates a styled HTML report from trading signals and market data.
"""
import os
import io
import base64
import pandas as pd
import mplfinance as mpf
from datetime import datetime
from typing import List, Dict, Any
from bluehorseshoe.data.historical_data import load_historical_data

class HTMLReporter:
    """
    Generates HTML reports for BlueHorseshoe trading sessions.
    """
    # Number of top candidates to show per strategy in report
    TOP_CANDIDATES_PER_STRATEGY = 5
    # Number of candidates to show in main "Top Candidates" table
    TOP_CANDIDATES_TABLE_LIMIT = 10

    def __init__(self, output_dir: str = "src/logs", database=None):
        """
        Initialize HTMLReporter with optional dependency injection.

        Args:
            output_dir: Directory to save generated reports
            database: MongoDB database instance. If None, uses global singleton.
        """
        self.output_dir = output_dir
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
        
        # Format prices
        entry = c.get('close', 0)
        stop = c.get('stop_loss', 0)
        target = c.get('target', 0)
        
        price_info = f"E:<b>${entry:.2f}</b> S:<b style='color:var(--badge-bear)'>${stop:.2f}</b> T:<b style='color:var(--badge-bull)'>${target:.2f}</b>"
        
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
        baseline_top = sorted([c for c in candidates if c.get('strategy') == 'Baseline'],
                              key=lambda x: (x.get('score', 0), x.get('ml_prob', 0)),
                              reverse=True)[:top_n]
        meanrev_top = sorted([c for c in candidates if c.get('strategy') == 'MeanRev'],
                            key=lambda x: (x.get('score', 0), x.get('ml_prob', 0)),
                            reverse=True)[:top_n]

        # Generate Sparklines
        for c in baseline_top:
            c['chart_b64'] = self._generate_sparkline(c['symbol'])
            
        for c in meanrev_top:
            c['chart_b64'] = self._generate_sparkline(c['symbol'])

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
            "<tr><th>Status</th><th>SPY Price</th><th>SPY MA50</th><th>SPY MA200</th></tr>",
            f"<tr><td>{self._get_regime_badge(regime.get('status', 'Unknown'))}</td>",
            f"<td>{regime.get('spy_price', 'N/A')}</td>",
            f"<td>{regime.get('spy_ma50', 'N/A')}</td>",
            f"<td>{regime.get('spy_ma200', 'N/A')}</td></tr>",
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
        html.append("<tr><th>Symbol</th><th>Exchange</th><th>Strategy</th><th>Score</th><th>Close Price</th><th>Indicators</th></tr>")


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
        baseline_top = sorted([c for c in candidates if c.get('strategy') == 'Baseline'],
                              key=lambda x: (x.get('score', 0), x.get('ml_prob', 0)),
                              reverse=True)[:top_n]
        meanrev_top = sorted([c for c in candidates if c.get('strategy') == 'MeanRev'],
                            key=lambda x: (x.get('score', 0), x.get('ml_prob', 0)),
                            reverse=True)[:top_n]

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
        html.append("<tr><th>Status</th><th>SPY Price</th><th>SPY MA50</th><th>SPY MA200</th></tr>")

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
        html.append(f"<td>{regime.get('spy_ma200', 'N/A')}</td></tr>")
        html.append("</table>")

        # Top Baseline Candidates
        html.append("<div class='strategy-section'>")
        html.append(f"<h3>Top {top_n} Baseline (Trend Following)</h3>")

        if baseline_top:
            html.append("<table>")
            html.append("<tr><th>Symbol</th><th>Score</th><th>ML Confidence</th><th>Entry</th><th>Stop</th><th>Target</th></tr>")
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
                target = c.get('target', 0)

                html.append("<tr>")
                html.append(f"<td><a href='{url}' target='_blank'><strong>{symbol}</strong></a></td>")
                html.append(f"<td class='{score_cls}'>{score:.1f}</td>")
                html.append(f"<td>{ml_prob*100:.0f}%</td>")
                html.append(f"<td>${entry:.2f}</td>")
                html.append(f"<td style='color:#c0392b;font-weight:bold'>${stop:.2f}</td>")
                html.append(f"<td style='color:#27ae60;font-weight:bold'>${target:.2f}</td>")
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
            html.append("<tr><th>Symbol</th><th>Score</th><th>ML Confidence</th><th>Entry</th><th>Stop</th><th>Target</th></tr>")
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
                target = c.get('target', 0)

                html.append("<tr>")
                html.append(f"<td><a href='{url}' target='_blank'><strong>{symbol}</strong></a></td>")
                html.append(f"<td class='{score_cls}'>{score:.1f}</td>")
                html.append(f"<td>{ml_prob*100:.0f}%</td>")
                html.append(f"<td>${entry:.2f}</td>")
                html.append(f"<td style='color:#c0392b;font-weight:bold'>${stop:.2f}</td>")
                html.append(f"<td style='color:#27ae60;font-weight:bold'>${target:.2f}</td>")
                html.append("</tr>")
            html.append("</table>")
        else:
            html.append("<p>No candidates found for this strategy.</p>")

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
        html.append("<tr><th>Symbol</th><th>Strategy</th><th>Score</th><th>ML</th><th>Price</th><th>Top Indicators</th></tr>")

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
