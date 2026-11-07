import json, random, csv, sys
import pandas as pd
from datetime import datetime, timedelta


cfg, rnd, N = json.load(open("cdr_config.json")), random.Random(42), int(sys.argv[1]) if len(sys.argv) > 1 else 10

num = lambda p: f"{rnd.choice(p['country_code'])}{rnd.choice(p['province_code'])}{rnd.randint(p['telcom_code']['min'], p['telcom_code']['max'])}{rnd.randint(0, 9999):04d}"

rng = lambda s: rnd.randint(s["min"], s["max"])

def cdr():
    c, b, t0 = cfg["called"], cfg["balance_change"], datetime.now()
    called = num(c["local"]) if rnd.random() < c["local_share"] else f"{rnd.choice(c['international']['country_code'])}{rnd.randint(10**7, 10**8 - 1)}"
    
    return {"caller": num(cfg["caller"]), "called": called, "start_time": (t0 + timedelta(seconds=rnd.randint(0, 1800))).strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": rng(cfg["duration_seconds"]), "balance_change": round(rnd.uniform(b["min_value"], b["max_value"]), b["right_digits"]), "cdr_type": cfg["cdr_type"],
            "total_currency_charge": rng(cfg["total_currency_charge"]), "total_non_currency_charge": rng(cfg["total_non_currency_charge"]),
            **{k: rnd.choice(cfg[k]) for k in ["cos_id", "application_subtype", "activity_direction", "discount_id", "cell_id", "cdr_call_type", "ocn_caller_id", "ocn_called_id"]}}
rows = [cdr() for _ in range(N)]
df = pd.DataFrame(rows)
df.to_csv('cdrs.csv', index=False)
