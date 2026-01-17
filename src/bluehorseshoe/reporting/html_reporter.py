"""
HTML Reporter module for BlueHorseshoe.
Generates a styled HTML report from trading signals and market data.
"""
import os
from datetime import datetime
from typing import List, Dict, Any

class HTMLReporter:
    """
    Generates HTML reports for BlueHorseshoe trading sessions.
    """
    def __init__(self, output_dir: str = "src/logs"):
        self.output_dir = output_dir
        self.css = """
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; background: #fff; padding: 20px; box-shadow: 0 0 10px rgba(0,0,0,0.1); border-radius: 8px; }
            h1, h2, h3 { color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 10px; }
            table { width: 100%; border-collapse: collapse; margin: 20px 0; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #34495e; color: #fff; }
            tr:hover { background-color: #f5f5f5; }
            .badge { padding: 5px 10px; border-radius: 4px; color: #fff; font-weight: bold; font-size: 0.9em; }
            .badge-bull { background-color: #27ae60; }
            .badge-bear { background-color: #c0392b; }
            .badge-neutral { background-color: #f39c12; }
            .score-high { color: #27ae60; font-weight: bold; }
            .score-med { color: #f39c12; font-weight: bold; }
            .score-low { color: #c0392b; font-weight: bold; }
            .footer { margin-top: 40px; font-size: 0.8em; color: #777; text-align: center; }
            .chart-container { display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; }
            .chart-box { border: 1px solid #ddd; padding: 10px; border-radius: 4px; background: #fff; }
            img { max-width: 100%; height: auto; }
        </style>
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

    def generate_report(self, date: str, regime: Dict[str, Any], candidates: List[Dict[str, Any]], charts: List[str]) -> str:
        """
        Builds the complete HTML string.
        """
        html = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            f"<title>BlueHorseshoe Report - {date}</title>",
            self.css,
            "</head>",
            "<body>",
            "<div class='container'>",
            f"<h1>BlueHorseshoe Daily Report <small style='font-size:0.5em; color:#777'>{date}</small></h1>",

            # Market Regime Section
            "<details>",
            f"<summary style='cursor:pointer'><h2>Market Regime: {self._get_regime_badge(regime.get('status', 'Unknown'))}</h2></summary>",
            "<table>",
            "<tr><th>Status</th><th>SPY Price</th><th>SPY MA50</th><th>SPY MA200</th></tr>",
            f"<tr><td>{self._get_regime_badge(regime.get('status', 'Unknown'))}</td>",
            f"<td>{regime.get('spy_price', 'N/A')}</td>",
            f"<td>{regime.get('spy_ma50', 'N/A')}</td>",
            f"<td>{regime.get('spy_ma200', 'N/A')}</td></tr>",
            "</table>",
            f"<p><strong>Commentary:</strong> {regime.get('commentary', 'No commentary available.')}</p>",
            "</details>",

            # Candidates Section
            f"<h2>Top Candidates ({len(candidates)})</h2>",
            "<table>",
            "<tr><th>Symbol</th><th>Exchange</th><th>Strategy</th><th>Score</th><th>Close Price</th><th>Indicators</th></tr>"
        ]

        for cand in candidates:
            score = cand.get('score', 0)
            score_cls = self._get_score_class(score)
            indicators = ", ".join(cand.get('reasons', []))

            html.append(f"<tr>")
            html.append(f"<td><strong>{cand['symbol']}</strong></td>")
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
