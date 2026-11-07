import argparse, json, random, re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent  # files are found next to this script, wherever it is run from
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def positive_int(s):
    n = int(s)
    if n < 1:
        raise argparse.ArgumentTypeError(f"number of CDRs must be >= 1, got {n}")
    return n


ap = argparse.ArgumentParser(description="Generate fake CDRs into a CSV file.")
ap.add_argument("n", nargs="?", type=positive_int, default=10, help="number of CDRs to generate (default: 10)")
ap.add_argument("-c", "--config", type=Path, default=HERE / "cdr_config.json", help="generator config (default: %(default)s)")
ap.add_argument("-o", "--output", type=Path, default=HERE / "cdrs.csv", help="output CSV (default: %(default)s)")
args = ap.parse_args()

cfg, rnd, N = json.load(open(args.config)), random.Random(42), args.n


def time_window(spec):
    """start_time config -> (window start, window length in seconds).
    start: "now" or a fixed "YYYY-MM-DD HH:MM:SS" (fixed = identical output on every run).
    end:   offset from start, e.g. "+30min", "+2h", "+900s"."""
    start = datetime.now().replace(microsecond=0) if spec["start"] == "now" else datetime.strptime(spec["start"], TIME_FMT)
    m = re.fullmatch(r"\+(\d+)(s|min|h)", spec["end"].strip())
    if not m:
        raise SystemExit(f'start_time.end must look like "+30min", "+2h" or "+900s", got {spec["end"]!r}')
    return start, int(m[1]) * {"s": 1, "min": 60, "h": 3600}[m[2]]


t0, window = time_window(cfg["start_time"])  # computed once, so every CDR shares the same reference time

num = lambda p: f"{rnd.choice(p['country_code'])}{rnd.choice(p['province_code'])}{rnd.randint(p['telcom_code']['min'], p['telcom_code']['max'])}{rnd.randint(0, 9999):04d}"

rng = lambda s: rnd.randint(s["min"], s["max"])

def cdr():
    c, b = cfg["called"], cfg["balance_change"]
    called = num(c["local"]) if rnd.random() < c["local_share"] else f"{rnd.choice(c['international']['country_code'])}{rnd.randint(10**7, 10**8 - 1)}"

    return {"caller": num(cfg["caller"]), "called": called, "start_time": (t0 + timedelta(seconds=rnd.randint(0, window))).strftime(TIME_FMT),
            "duration_seconds": rng(cfg["duration_seconds"]), "balance_change": round(rnd.uniform(b["min_value"], b["max_value"]), b["right_digits"]), "cdr_type": cfg["cdr_type"],
            "total_currency_charge": rng(cfg["total_currency_charge"]), "total_non_currency_charge": rng(cfg["total_non_currency_charge"]),
            **{k: rnd.choice(cfg[k]) for k in ["cos_id", "application_subtype", "activity_direction", "discount_id", "cell_id", "cdr_call_type", "ocn_caller_id", "ocn_called_id"]}}
rows = [cdr() for _ in range(N)]
df = pd.DataFrame(rows)
df.to_csv(args.output, index=False)
print(f"wrote {len(df)} CDRs to {args.output}")
