"""Generate the symbol sample + parameter-grid slices for the 5-agent sweep."""
import json, os, numpy as np, duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")
N_SYMBOLS = 250
N_SLICES = 5
START = "2016-01-01"
TESTPAT = {"ZXZZT","ZVZZT","ZWZZT","ZAZZT","ZBZZT","ZCZZT","ZJZZT","CBO","CBX","IGZ","NTEST","CTEST"}

con = duckdb.connect(DB, read_only=True)
syms = con.execute("SELECT symbol,count(*) n FROM ohlcv WHERE date>=? GROUP BY symbol HAVING n>300",
                   [START]).df().symbol.tolist()
con.close()
syms = [s for s in syms if s not in TESTPAT and not (s.startswith("Z") and s.endswith("ZZT"))]
rng = np.random.default_rng(7)
sample = sorted(rng.choice(syms, N_SYMBOLS, replace=False).tolist())
with open(os.path.join(HERE, "symbols.txt"), "w") as f:
    f.write("\n".join(sample) + "\n")
print(f"{len(sample)} symbols -> symbols.txt")

# ---- core grid: width(4) x D(2) x M(2) x G(2) x invalidation(2) = 64 ----
WIDTHS = [
    {"width_mode": "atr", "width_atr": 0.15},
    {"width_mode": "atr", "width_atr": 0.30},
    {"width_mode": "pct", "width_pct": 0.0015},
    {"width_mode": "pct", "width_pct": 0.0030},
]
combos = []
for wd in WIDTHS:
    for D in (0.75, 1.5):
        for M in (2, 3):
            for G in (5, 10):
                for inv in (1, 2):
                    combos.append({**wd, "breakaway_depth_atr": D, "min_touches": M,
                                   "min_bars_between": G, "invalidation_confirm_bars": inv,
                                   "max_age_bars": 252})
# ---- volume-gate mini-slice (his "touches high vol" refinement) ----
for D in (0.75, 1.5):
    for tv in (1.0, 1.5):
        combos.append({"width_mode": "atr", "width_atr": 0.15, "breakaway_depth_atr": D,
                       "min_touches": 2, "min_bars_between": 5, "invalidation_confirm_bars": 1,
                       "max_age_bars": 252, "use_volume_gate": True, "touch_vol_min": tv})

print(f"{len(combos)} combos -> {N_SLICES} slices")
slices = [[] for _ in range(N_SLICES)]
for i, cmb in enumerate(combos):
    slices[i % N_SLICES].append(cmb)
for i, sl in enumerate(slices):
    with open(os.path.join(HERE, f"combos_slice_{i}.jsonl"), "w") as f:
        for cmb in sl:
            f.write(json.dumps(cmb) + "\n")
    print(f"  slice {i}: {len(sl)} combos")
