"""Apply the voice tariff (Call_Tariff.json) to every CDR and add three columns:
  charged_amount    = amount computed from the tariff (rules below)
  charge_difference = charged_amount - total_currency_charge
  charge_category   = Overcharge  if charge_difference < 0 (billed more than the tariff)
                      Undercharge if charge_difference > 0 (billed less than the tariff)
                      Correct     if charge_difference = 0

Rating rules:
  * destination   = longest country-code prefix of `called` found in the tariff.
                    For a tariff entry that lists `province_code` (Canada), the 3 digits
                    after the country code must be one of them.
  * rate          = Off-PeakHours.ratePerSecond if off-peak hours are enabled and the call
                    STARTS in [off-peak start, off-peak end), otherwise ratePerSecond.
  * amount        = rate * duration_seconds, rounded half-up to 0.01.
CDRs that cannot be rated (unknown destination, call before effectiveDate, bad data) get all three
columns empty; a non-numeric total_currency_charge leaves charge_difference and charge_category
empty. Such CDRs are reported on stderr. All other columns are written back unchanged.
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
DIFF_COL = "charge_difference"
CATEGORY_COL = "charge_category"
CHARGED_COL = "total_currency_charge"
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


def categorize(diff):
    if diff is None:
        return None
    return "Overcharge" if diff < 0 else "Undercharge" if diff > 0 else "Correct"


def main():
    ap = argparse.ArgumentParser(description="Rate CDRs with the JSON tariff and add charged_amount, charge_difference and charge_category columns.")
    ap.add_argument("-i", "--input", type=Path, default=HERE / "cdrs.csv", help="CDR CSV to rate (default: %(default)s)")
    ap.add_argument("-t", "--tariff", type=Path, default=HERE / "Call_Tariff.json", help="tariff JSON (default: %(default)s)")
    ap.add_argument("-o", "--output", type=Path, default=HERE / "cdrs_rated.csv", help="rated CSV (default: %(default)s)")
    args = ap.parse_args()

    tariff, by_code = load_tariff(args.tariff)
    effective = date.fromisoformat(tariff["effectiveDate"])

    # Read everything as text so untouched columns are written back exactly as they came in.
    df = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    missing = {"called", "start_time", "duration_seconds", CHARGED_COL} - set(df.columns)
    if missing:
        raise SystemExit(f"{args.input} is missing column(s): {', '.join(sorted(missing))}")

    amounts, diffs, problems = [], [], []
    cols = zip(df["called"], df["start_time"], df["duration_seconds"], df[CHARGED_COL])
    for line, (called, st, dur, charged) in enumerate(cols, start=2):
        amount = diff = None
        try:
            amount = rate_one(called, st, dur, by_code, effective)
            charged = Decimal(charged.strip())
            if not charged.is_finite():  # Decimal accepts "NaN" / "Infinity"; those are not amounts
                raise ArithmeticError
            diff = (amount - charged).quantize(CENT, rounding=ROUND_HALF_UP)
            if diff == 0:
                diff = abs(diff)  # a tiny negative difference rounds to -0.00; write it as 0.00
        except Unrated as e:
            problems.append((line, called, f"not rated: {e}"))
        except ArithmeticError:  # decimal.InvalidOperation: total_currency_charge is not a number
            problems.append((line, called, f"{CHARGED_COL} is not a number ({DIFF_COL} and {CATEGORY_COL} left empty)"))
        amounts.append(amount)
        diffs.append(diff)

    df[AMOUNT_COL] = amounts  # re-running on an already rated file replaces these columns
    df[DIFF_COL] = diffs
    df[CATEGORY_COL] = [categorize(d) for d in diffs]
    df.to_csv(args.output, index=False)

    cur = tariff.get("currency", "")
    rated = sum(a is not None for a in amounts)
    total = sum((a for a in amounts if a is not None), Decimal(0))
    total_diff = sum((d for d in diffs if d is not None), Decimal(0))
    print(f"rated {rated}/{len(df)} CDRs, total {AMOUNT_COL} {total} {cur}, total {DIFF_COL} {total_diff} {cur} -> {args.output}")
    counts = Counter(df[CATEGORY_COL].dropna())
    print("  " + ", ".join(f"{c}: {counts[c]}" for c in ("Overcharge", "Undercharge", "Correct")))
    if problems:
        print(f"WARNING: {len(problems)} CDR(s) with empty result column(s):", file=sys.stderr)
        for reason, n in Counter(p[2] for p in problems).most_common():
            print(f"  {n:>6}  {reason}", file=sys.stderr)
        for line, called, reason in problems[:10]:
            print(f"  e.g. line {line}: called={called} -> {reason}", file=sys.stderr)


if __name__ == "__main__":
    main()