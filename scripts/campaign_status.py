"""Summarize model campaign status."""
import json
import subprocess
import sys

out = subprocess.run(
    [sys.executable, "-m", "value_genie", "model", "campaign", "status", "--json"],
    capture_output=True, text=True, encoding="utf-8",
)
raw = out.stdout
d = json.loads(raw[raw.find("{"):])
print("modeled:", d["modeled"], "/", d["queue_total"], "({}%)".format(d["modeled_pct"]))
for t in d["tiers"]:
    print("tier{} {}: modeled {}/{}, ready {}, pending {}".format(
        t["tier"], t["label"], t["modeled"], t["total"], t["ready"], t["pending"]))
print("next:", d.get("next"))
print("parked:", d.get("parked"))
