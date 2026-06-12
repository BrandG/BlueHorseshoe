# FTMO Commodities v2 Sweep Verdict

Run date: 2026-06-12 UTC.

## Data And Cost Gate

Backfill completed for `XAU_USD`, `XAG_USD`, `WTICO_USD`, `BCO_USD`, `NATGAS_USD`, and `XCU_USD` across H4 and H1, 2016-01-01 through 2026-06-12. The OANDA candle endpoints accepted these symbols even though `client.list_instruments()` did not list them.

Stored validation using the existing FX-grid validator reported data gaps on every commodity, especially H1. This appears to be a session-calendar mismatch for commodity CFDs, not a raw OHLC/spread invariant failure. Treat the sweep as research-grade, not production-grade, until commodity-specific expected-session validation is added.

OANDA financing is missing for every commodity because the symbols are absent from `client.list_instruments()`. The sweep therefore applies observed bid/ask spread costs and flags financing as unavailable; it does not silently assume commodity swap is zero.

Median H4 spread cost in R under the standard 0.5% stop geometry:

- Gold: `0.040R`
- Silver: `0.180R`
- WTI: `0.101R`
- Brent: `0.100R`
- Natgas: `0.469R`
- Copper: `0.098R`

Natgas is close to half an R in spread alone and should be excluded or separately parameterized unless a much wider bracket is justified.

## Book-Level Results

All book-level Newey-West CIs are below zero after spread costs:

- MR under limit, H4 limit: mean `-0.107R`, CI `[-0.114, -0.100]`
- MR under limit, H4 market: mean `-0.320R`, CI `[-0.326, -0.313]`
- Trend, H4 limit: mean `-0.048R`, CI `[-0.055, -0.042]`
- Trend, H4 market: mean `-0.273R`, CI `[-0.279, -0.268]`
- Trend, D1 limit: mean `-0.315R`, CI `[-0.327, -0.302]`
- Trend, D1 market: mean `-0.470R`, CI `[-0.482, -0.459]`

The only relatively less-bad book is H4 trend with limit entries, but it still fails the NW gate.

## Answers

1. MR-under-limit does not port to commodities at the book level after spread costs. Some individual limit cells are near flat or positive before book aggregation, but the book-level CI is decisively negative.
2. Trend does not wake up enough to clear costs. H4 trend limit is the closest, but still negative at book level; D1 trend is worse.
3. Gold, WTI, Brent, and copper have plausible spread costs for research. Silver is expensive. Natgas is likely untradeable under this bracket geometry on spread alone. Commodity swap remains unknown and would only worsen long-hold books if materially negative.
4. Recommended next conditioner: inventory-event proximity for oil and natgas only after commodity financing/session validation is fixed. COT and real-yield conditioners are premature because the unconditioned books do not clear the cost gate.

## FTMO Ticker Notes

The config uses:

- `XAUUSD.sim`
- `XAGUSD.sim`
- `USOIL.sim`
- `UKOIL.sim`
- `NATGAS.sim`
- `XCUUSD.sim`

`XAUUSD.sim`, `USOIL.sim`, `UKOIL.sim`, and `NATGAS.sim` came from the task text. `XAGUSD.sim` and `XCUUSD.sim` follow the same convention but should be verified against FTMO's symbol specification before live or paper wiring. No live wiring was changed.
