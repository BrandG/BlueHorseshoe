import datetime

from bluehorseshoe.application import services


def test_update_market_data_builds_backfill_config(monkeypatch):
    captured = {}

    def fake_build_all_symbols_history(config, database=None, store=None):
        captured["config"] = config
        captured["database"] = database
        captured["store"] = store

    monkeypatch.setattr(services, "build_all_symbols_history", fake_build_all_symbols_history)

    result = services.update_market_data(
        database="db",
        store="store",
        recent=False,
        symbols=[{"symbol": "SPY", "name": ""}],
        deep=True,
        resume=True,
        limit=25,
    )

    assert result == "Data Updated"
    assert captured["database"] == "db"
    assert captured["store"] == "store"
    assert captured["config"].recent is False
    assert captured["config"].deep is True
    assert captured["config"].resume is False
    assert captured["config"].limit == 25


def test_run_prediction_resolves_date_and_adds_previous_performance(monkeypatch):
    class FakeTrader:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def swing_predict(self, **kwargs):
            assert kwargs["target_date"] == "2026-03-26"
            assert kwargs["aggregation"] == "sum"
            return {"regime": {"status": "ok"}, "candidates": []}

        def get_previous_performance(self, target_date):
            assert target_date == "2026-03-26"
            return {"date": "2026-03-25", "results": []}

    monkeypatch.setattr(services, "SwingTrader", FakeTrader)
    monkeypatch.setattr(services, "get_latest_market_date", lambda **kwargs: "2026-03-26")

    result = services.run_prediction(
        database="db",
        config="cfg",
        store="store",
        report_writer="writer",
    )

    assert result["date"] == "2026-03-26"
    assert result["previous_performance"] == {"date": "2026-03-25", "results": []}


def test_generate_reports_uses_flattened_regime_and_optional_arcade(monkeypatch):
    calls = {}

    class FakeReporter:
        def __init__(self, database=None):
            calls["database"] = database

        def generate_report(self, **kwargs):
            calls["generate_report"] = kwargs
            return "full-html"

        def generate_email_report(self, **kwargs):
            calls["generate_email_report"] = kwargs
            return "email-html"

        def save_both(self, html_content, email_html, basename):
            calls["save_both"] = (html_content, email_html, basename)
            return "/tmp/full.html", "/tmp/email.html"

        def generate_arcade_report(self, **kwargs):
            calls["generate_arcade_report"] = kwargs
            return "arcade-html"

        def save_arcade(self, html_content, filename):
            calls["save_arcade"] = (html_content, filename)
            return "/tmp/arcade.html"

    monkeypatch.setattr(services, "HTMLReporter", FakeReporter)

    report_data = {
        "date": "2026-03-26",
        "regime": {
            "details": {
                "SPY": {"close": 100, "ema50": 95, "ema200": 90},
                "VIX": {"close": 20, "fear_level": "neutral"},
            }
        },
        "candidates": [{"symbol": "SPY"}],
        "charts": [],
        "previous_performance": {"date": "2026-03-25", "results": []},
    }

    result = services.generate_reports(database="db", report_data=report_data, include_arcade=True)

    assert result["path"] == "/tmp/full.html"
    assert result["email_path"] == "/tmp/email.html"
    assert result["arcade_path"] == "/tmp/arcade.html"
    assert calls["generate_report"]["regime"]["spy_price"] == 100
    assert calls["generate_report"]["regime"]["vix_fear"] == "neutral"
    assert calls["save_both"] == ("full-html", "email-html", "report_2026-03-26")
