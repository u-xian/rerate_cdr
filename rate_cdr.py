"""Apply the voice tariff (Call_Tariff.json) to every CDR and add a `charged_amount` column.

Rating rules:
  * destination   = longest country-code prefix of `called` found in the tariff.
                    For a tariff entry that lists `province_code` (Canada), the 3 digits
                    after the country code must be one of them.
  * rate          = Off-PeakHours.ratePerSecond if off-peak hours are enabled and the call
                    STARTS in [off-peak start, off-peak end), otherwise ratePerSecond.
  * amount        = rate * duration_seconds, rounded half-up to 0.01.
CDRs that cannot be rated (unknown destination, call before effectiveDate, bad data) get an
empty `charged_amount` and are reported on stderr. All other columns are written back unchanged.
"""
import argparse, json, sys
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
TIME_FMT = "%Y-%m-%d %H:%M:%S"
CENT = Decimal("0.01")
AMOUNT_COL = "charged_amount"
OFF_PEAK = "Off-PeakHours"


class Unrated(Exception):
    """The CDR cannot be rated; the message says why."""


def load_tariff(path):
    t = json.load(open(path))
    if t.get("billingUnit") != "per_second":
        print(f"WARNING: {path.name} says billingUnit={t.get('billingUnit')!r}; rates are applied per second "
              f"(ratePerSecond) regardless", file=sys.stderr)
    by_code = {}
    for e in t["tariffs"]:
        code = str(e["countryCode"])  # accept 44 or "44"
        if code in by_code:
            raise SystemExit(f"countryCode {code} appears twice in {path}")
        off = e.get(OFF_PEAK)
        if "ratePerSecond" not in e or (off and off.get("enabled") and "ratePerSecond" not in off):
            raise SystemExit(f"tariff for countryCode {code} ({e.get('countryName')}) has no ratePerSecond")
        by_code[code] = e
    return t, by_code


def in_window(window, t):
    if not window or not window.get("enabled"):
        return False
    start, end = time.fromisoformat(window["start"]), time.fromisoformat(window["end"])
    return start <= t < end if start <= end else (t >= start or t < end)  # also handles overnight windows


def rate_one(called, start_time, duration, by_code, effective):
    called = called.strip()
    if not called.isdigit():
        raise Unrated("called number is not numeric")
    code = next((called[:n] for n in (3, 2, 1) if called[:n] in by_code), None)
    if code is None:
        raise Unrated("no tariff for destination")
    entry = by_code[code]
    if "province_code" in entry and int(called[len(code):len(code) + 3] or -1) not in entry["province_code"]:
        raise Unrated("province code not in tariff")

    try:
        start = datetime.strptime(start_time.strip(), TIME_FMT)
        seconds = int(duration)
    except ValueError:
        raise Unrated("bad start_time or duration_seconds")
    if seconds < 0:
        raise Unrated("negative duration")
    if start.date() < effective:
        raise Unrated("call before tariff effectiveDate")

    off_peak = entry.get(OFF_PEAK)
    rate = off_peak["ratePerSecond"] if in_window(off_peak, start.time()) else entry["ratePerSecond"]
    amount = Decimal(str(rate)) * seconds  # charged_amount = ratePerSecond * duration_seconds
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def main():
    ap = argparse.ArgumentParser(description="Rate CDRs with the JSON tariff and add a charged_amount column.")
    ap.add_argument("-i", "--input", type=Path, default=HERE / "cdrs.csv", help="CDR CSV to rate (default: %(default)s)")
    ap.add_argument("-t", "--tariff", type=Path, default=HERE / "Call_Tariff.json", help="tariff JSON (default: %(default)s)")
    ap.add_argument("-o", "--output", type=Path, default=HERE / "cdrs_rated.csv", help="rated CSV (default: %(default)s)")
    args = ap.parse_args()

    tariff, by_code = load_tariff(args.tariff)
    effective = date.fromisoformat(tariff["effectiveDate"])

    # Read everything as text so untouched columns are written back exactly as they came in.
    df = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    missing = {"called", "start_time", "duration_seconds"} - set(df.columns)
    if missing:
        raise SystemExit(f"{args.input} is missing column(s): {', '.join(sorted(missing))}")

    amounts, problems = [], []
    for line, (called, st, dur) in enumerate(zip(df["called"], df["start_time"], df["duration_seconds"]), start=2):
        try:
            amounts.append(rate_one(called, st, dur, by_code, effective))
        except Unrated as e:
            amounts.append(None)
            problems.append((line, called, str(e)))

    df[AMOUNT_COL] = amounts  # re-running on an already rated file replaces the column
    df.to_csv(args.output, index=False)

    rated = len(df) - len(problems)
    total = sum((a for a in amounts if a is not None), Decimal(0))
    print(f"rated {rated}/{len(df)} CDRs, total {total} {tariff.get('currency', '')} -> {args.output}")
    if problems:
        print(f"WARNING: {len(problems)} CDR(s) not rated ({AMOUNT_COL} left empty):", file=sys.stderr)
        for reason, n in Counter(p[2] for p in problems).most_common():
            print(f"  {n:>6}  {reason}", file=sys.stderr)
        for line, called, reason in problems[:10]:
            print(f"  e.g. line {line}: called={called} -> {reason}", file=sys.stderr)


if __name__ == "__main__":
    main()