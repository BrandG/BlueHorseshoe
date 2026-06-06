"""Tests for the Signal Track Record aggregation."""

from bluehorseshoe.reporting import track_record as tr


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs
        self.last_query = None

    def find(self, query, projection=None):
        self.last_query = query
        rank_lte = query.get("rank", {}).get("$lte", 10**9)
        start = query["batch_date"]["$gte"]
        end = query["batch_date"]["$lte"]
        return [
            d for d in self._docs
            if (d.get("rank", 0) <= rank_lte) and (start <= d["batch_date"] <= end)
        ]


class _FakeDB:
    def __init__(self, docs):
        self._coll = _FakeCollection(docs)

    def __getitem__(self, name):
        assert name == "journal_hypothetical_trades"
        return self._coll


def _doc(batch, strat, rank, outcome, pnl, alpha=0.0, days=3, sym="AAA"):
    return {
        "batch_date": batch, "symbol": sym, "strategy": strat, "rank": rank,
        "outcome": outcome, "pnl_pct": pnl, "alpha_pct": alpha, "days_held": days,
    }


def test_none_database_returns_none():
    assert tr.compute_track_record(None, "2026-05-20") is None


def test_empty_window_returns_none():
    db = _FakeDB([_doc("2020-01-01", "baseline", 1, "WIN", 0.05)])
    # Lookback window won't reach back to 2020.
    assert tr.compute_track_record(db, "2026-05-20", lookback_days=60) is None


def test_query_failure_returns_none():
    class _Boom:
        def __getitem__(self, name):
            raise RuntimeError("mongo down")
    assert tr.compute_track_record(_Boom(), "2026-05-20") is None


def test_metrics_math():
    docs = [
        _doc("2026-05-18", "baseline", 1, "WIN", 0.04, alpha=0.02),
        _doc("2026-05-18", "baseline", 2, "LOSS", -0.02, alpha=-0.03),
        _doc("2026-05-18", "baseline", 3, "TIMEOUT", 0.01, alpha=0.0),
        _doc("2026-05-18", "baseline", 4, "NOT_ENTERED", 0.0),
        _doc("2026-05-18", "mean_reversion", 1, "WIN", 0.06, alpha=0.05),
    ]
    out = tr.compute_track_record(_FakeDB(docs), "2026-05-20", tiers=(10,))
    m = out["tiers"][10]["overall"]
    assert m["total"] == 5
    assert m["entered"] == 4           # NOT_ENTERED excluded
    assert m["not_entered"] == 1
    assert m["wins"] == 3              # pnl > 0 (incl. the +0.01 TIMEOUT)
    assert m["win_rate"] == 0.75
    assert m["target_hits"] == 2 and m["stops"] == 1 and m["timeouts"] == 1
    # avg pnl over entered = (4 + -2 + 1 + 6)/4 = 2.25%
    assert round(m["avg_pnl_pct"], 4) == 2.25
    # profit factor = gross_win(0.11) / |gross_loss|(0.02) = 5.5
    assert round(m["profit_factor"], 2) == 5.5
    assert out["tiers"][10]["mean_reversion"]["entered"] == 1


def test_by_strategy_split_is_registry_driven():
    """Every strategy that fired in-window gets its own split — incl. the HA sleeve."""
    docs = [
        _doc("2026-05-18", "baseline", 1, "WIN", 0.04),
        _doc("2026-05-18", "mean_reversion", 2, "LOSS", -0.02),
        _doc("2026-05-18", "deep_oversold", 3, "WIN", 0.06),
        _doc("2026-05-18", "deep_oversold_ha", 4, "WIN", 0.09),
    ]
    out = tr.compute_track_record(_FakeDB(docs), "2026-05-20", tiers=(10,))
    by_strat = out["tiers"][10]["by_strategy"]
    assert set(by_strat) == {"baseline", "mean_reversion", "deep_oversold", "deep_oversold_ha"}
    assert by_strat["deep_oversold_ha"]["display"] == "DeepOS+HA"
    assert by_strat["deep_oversold_ha"]["metrics"]["entered"] == 1
    # strategy_labels lets the renderers map name -> display (movers, JS).
    assert out["strategy_labels"]["deep_oversold_ha"] == "DeepOS+HA"
    # Strategies with no in-window signals are omitted (no empty columns).
    out2 = tr.compute_track_record(
        _FakeDB([_doc("2026-05-18", "baseline", 1, "WIN", 0.01)]), "2026-05-20", tiers=(10,))
    assert set(out2["tiers"][10]["by_strategy"]) == {"baseline"}


def test_profit_factor_infinite_when_no_losers():
    docs = [_doc("2026-05-18", "baseline", 1, "WIN", 0.03)]
    out = tr.compute_track_record(_FakeDB(docs), "2026-05-20", tiers=(10,))
    assert out["tiers"][10]["overall"]["profit_factor"] is None  # rendered as ∞


def test_rank_tiers_partition():
    docs = [_doc("2026-05-18", "baseline", r, "WIN", 0.01) for r in (1, 5, 25, 40)]
    out = tr.compute_track_record(_FakeDB(docs), "2026-05-20", tiers=(10, 50))
    assert out["tiers"][10]["overall"]["total"] == 2   # ranks 1,5
    assert out["tiers"][50]["overall"]["total"] == 4   # ranks 1,5,25,40


def test_top_movers_from_tight_tier():
    docs = [
        _doc("2026-05-18", "baseline", 1, "WIN", 0.10, sym="BIG"),
        _doc("2026-05-18", "baseline", 2, "LOSS", -0.08, sym="BAD"),
        _doc("2026-05-18", "baseline", 30, "WIN", 0.99, sym="DEEP"),  # outside tight tier
    ]
    out = tr.compute_track_record(_FakeDB(docs), "2026-05-20", tiers=(10, 50))
    assert out["top_winners"][0]["symbol"] == "BIG"   # DEEP excluded (rank 30 > 10)
    assert out["top_losers"][0]["symbol"] == "BAD"
