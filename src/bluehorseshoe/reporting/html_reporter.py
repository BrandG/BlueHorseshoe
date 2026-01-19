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
    def __init__(self, output_dir: str = "src/logs"):
        self.output_dir = output_dir
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
            .top-list ul { list-style: none; padding: 0; margin: 0; }
            .top-list li { padding: 8px 0; border-bottom: 1px solid var(--border-color); font-family: 'Consolas', 'Monaco', monospace; font-size: 0.95em; }
            .top-list li:last-child { border-bottom: none; }
            .top-list-header { font-weight: bold; color: var(--secondary-text); font-size: 0.8em; text-transform: uppercase; border-bottom: 2px solid var(--border-color) !important; padding-bottom: 5px !important; margin-bottom: 5px; display: flex; justify-content: space-between; }
            .symbol-link { text-decoration: none; color: var(--link-color); transition: color 0.2s; }
            .symbol-link:hover { color: var(--link-hover); text-decoration: underline; }
            
            /* Toggle Button */
            .theme-toggle { position: fixed; top: 20px; right: 20px; padding: 10px 15px; background: var(--table-header-bg); color: var(--table-header-text); border: none; border-radius: 5px; cursor: pointer; font-weight: bold; box-shadow: 0 2px 5px rgba(0,0,0,0.2); z-index: 1000; }
            .theme-toggle:hover { opacity: 0.9; }

            /* Collapsible Styles */
            details { width: 100%; }
            summary { cursor: pointer; display: flex; justify-content: space-between; outline: none; list-style: none; }
            summary::-webkit-details-marker { display: none; }
            .summary-content { display: flex; justify-content: space-between; width: 100%; align-items: center; }
            .sparkline-container { text-align: center; padding: 10px; background: var(--bg-color); margin-top: 5px; border-radius: 4px; }
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
            data = load_historical_data(symbol)
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
        # Format: <<SYMBOL>>:<<EXCHANGE>> <<TECH SCORE>> <<ML ATTITUDE>> <<ENTRY PRICE>>
        # ML Attitude derived from probability
        prob = c.get('ml_prob', 0.0)
        attitude = f"ML:{prob*100:.0f}%"
        
        symbol = c['symbol']
        url = f"https://finance.yahoo.com/quote/{symbol}"
        
        summary_html = f"<div class='summary-content'><span><a href='{url}' target='_blank' class='symbol-link'><b>{symbol}</b></a>:<small>{c.get('exchange','UNK')}</small></span> <span><b>{c['score']:.1f}</b> <span style='color:#777'>{attitude}</span> <b>${c['close']:.2f}</b></span></div>"
        
        chart_html = ""
        if 'chart_b64' in c and c['chart_b64']:
            chart_html = f"<div class='sparkline-container'><img src='{c['chart_b64']}' alt='{symbol} chart' /></div>"
            
        return f"<details><summary>{summary_html}</summary>{chart_html}</details>"


    def generate_report(self, date: str, regime: Dict[str, Any], candidates: List[Dict[str, Any]], charts: List[str]) -> str:
        """
        Builds the complete HTML string.
        """
        # Filter Top 5 for each strategy
        baseline_top5 = sorted([c for c in candidates if c.get('strategy') == 'Baseline'], key=lambda x: x.get('score', 0), reverse=True)[:5]
        meanrev_top5 = sorted([c for c in candidates if c.get('strategy') == 'MeanRev'], key=lambda x: x.get('score', 0), reverse=True)[:5]

        # Generate Sparklines
        for c in baseline_top5:
            c['chart_b64'] = self._generate_sparkline(c['symbol'])
            
        for c in meanrev_top5:
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

            # Top 5 Lists (Side-by-Side)
            "<div class='top-lists-wrapper'>",
            
            # Baseline Column
            "<div class='top-list'>",
            "<h3>Top 5 Baseline (Trend)</h3>",
            "<ul>",
            "<li class='top-list-header'><span>Symbol</span> <span>Score / ML / Entry</span></li>"
        ]
        
        if baseline_top5:
            for c in baseline_top5:
                html.append(f"<li>{self._format_top_list_item(c)}</li>")
        else:
            html.append("<li>No candidates found.</li>")
        
        html.append("</ul></div>")

        # Mean Rev Column
        html.append("<div class='top-list'>")
        html.append("<h3>Top 5 Mean Reversion</h3>")
        html.append("<ul>")
        html.append("<li class='top-list-header'><span>Symbol</span> <span>Score / ML / Entry</span></li>")

        if meanrev_top5:
            for c in meanrev_top5:
                html.append(f"<li>{self._format_top_list_item(c)}</li>")
        else:
            html.append("<li>No candidates found.</li>")

        html.append("</ul></div></div>")

        # Candidates Section
        html.append(f"<h2>Top Candidates ({len(candidates)})</h2>")
        html.append("<table>")
        html.append("<tr><th>Symbol</th><th>Exchange</th><th>Strategy</th><th>Score</th><th>Close Price</th><th>Indicators</th></tr>")


        for cand in candidates:
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

    def save(self, html_content: str, filename: str = "latest_report.html"):
        """Saves the HTML content to a file."""
        path = os.path.join(self.output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return path
