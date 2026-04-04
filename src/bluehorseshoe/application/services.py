"""
Application-level orchestration services.
"""
from __future__ import annotations

import datetime
import copy
from typing import Any, Optional

from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.service import get_latest_market_date
from bluehorseshoe.data.historical_data import BackfillConfig, build_all_symbols_history
from bluehorseshoe.reporting.html_reporter import HTMLReporter


def update_market_data(
    *,
    database,
    store,
    recent: bool,
    symbols=None,
    active_only: bool = False,
    deep: bool = False,
    resume: bool = False,
    limit: Optional[int] = None,
) -> str:
    """Run historical market data update/backfill."""
    backfill_config = BackfillConfig(
        recent=recent,
        symbols=symbols,
        active_only=active_only,
        deep=deep,
        resume=resume if not deep else False,
        limit=limit,
    )
    build_all_symbols_history(backfill_config, database=database, store=store)
    return "Data Updated"


def run_prediction(
    *,
    database,
    config,
    store,
    report_writer=None,
    target_date: Optional[str] = None,
    enabled_indicators: Optional[list[str]] = None,
    aggregation: str = "sum",
    symbols: Optional[list[str]] = None,
    progress_callback=None,
) -> dict[str, Any]:
    """Run the prediction workflow and attach related orchestration outputs."""
    resolved_date = target_date or get_latest_market_date(database=database, store=store)

    trader = SwingTrader(
        database=database,
        config=config,
        report_writer=report_writer,
        store=store,
    )
    report_data = trader.swing_predict(
        target_date=resolved_date,
        enabled_indicators=enabled_indicators,
        aggregation=aggregation,
        symbols=symbols,
        progress_callback=progress_callback,
    )

    if resolved_date and not report_data.get("date"):
        report_data["date"] = resolved_date
    elif not report_data.get("date"):
        report_data["date"] = str(datetime.date.today())

    return report_data


def flatten_regime_for_report(regime: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested regime details for HTML reporter compatibility."""
    flattened = copy.deepcopy(regime or {})

    spy_details = flattened.get("details", {}).get("SPY", {})
    flattened["spy_price"] = spy_details.get("close", "N/A")
    flattened["spy_ma50"] = spy_details.get("ema50", "N/A")
    flattened["spy_ma200"] = spy_details.get("ema200", "N/A")

    vix_details = flattened.get("details", {}).get("VIX", {})
    if vix_details:
        flattened["vix_close"] = vix_details.get("close", "N/A")
        flattened["vix_fear"] = vix_details.get("fear_level", "")

    aaii_details = flattened.get("details", {}).get("AAII", {})
    if aaii_details:
        flattened["aaii_spread"] = aaii_details.get("bull_bear_spread", "N/A")
        flattened["aaii_signal"] = aaii_details.get("signal", "")

    cnn_details = flattened.get("details", {}).get("CNN", {})
    if cnn_details:
        flattened["cnn_score"] = cnn_details.get("score", "N/A")
        flattened["cnn_rating"] = cnn_details.get("rating", "")

    return flattened


def generate_reports(
    *,
    database,
    report_data: dict[str, Any],
    include_arcade: bool = False,
) -> dict[str, Any]:
    """Generate HTML report artifacts from prediction output."""
    report_date = report_data.get("date", str(datetime.date.today()))
    regime = flatten_regime_for_report(report_data.get("regime", {}))
    candidates = report_data.get("candidates", [])
    charts = report_data.get("charts", [])

    reporter = HTMLReporter(database=database)
    html_content = reporter.generate_report(
        date=report_date,
        regime=regime,
        candidates=candidates,
        charts=charts,
    )
    email_html = reporter.generate_email_report(
        date=report_date,
        regime=regime,
        candidates=candidates,
    )
    full_path, email_path = reporter.save_both(html_content, email_html, f"report_{report_date}")

    result = {
        "status": "Report Generated",
        "path": full_path,
        "email_path": email_path,
    }
    if include_arcade:
        arcade_html = reporter.generate_arcade_report(
            date=report_date,
            regime=regime,
            candidates=candidates,
        )
        result["arcade_path"] = reporter.save_arcade(arcade_html, f"report_{report_date}_arcade.html")

    return result


def send_report_email(*, report_path: Optional[str]) -> str:
    """Send the generated report via email."""
    if not report_path:
        return "No Report Path"

    from bluehorseshoe.core.email_service import EmailService  # pylint: disable=import-outside-toplevel

    email_service = EmailService()
    return "Email Sent" if email_service.send_report(report_path) else "Email Failed"
