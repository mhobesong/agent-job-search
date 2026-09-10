import json
from datetime import datetime, timezone
from typing import List

HEADERS = ["#", "URL", "Skills", "Remote", "Fit", "Status"]
WIDTHS = [3, 46, 8, 7, 6, 18]


def _fmt_row(cells, widths):
    clipped = [(c[: w - 1] + "…" if len(c) > w else c).ljust(w) for c, w in zip(cells, widths)]
    return "  ".join(clipped).rstrip()


def print_report(results: List[dict]):
    bar = "-" * (sum(WIDTHS) + 2 * (len(WIDTHS) - 1))
    print(bar)
    print(_fmt_row(HEADERS, WIDTHS))
    print(bar)
    for i, r in enumerate(results, 1):
        status = "MATCH" if r.get("matched") else r.get("status", "skipped")
        fit = str(r.get("fit_score", "-"))
        skills = f"{r.get('skills_matched_count', 0)}/{r.get('skills_total', 0)}"
        remote = "yes" if r.get("remote_found") else ("n/a" if not r.get("remote_required") else "no")
        print(_fmt_row([str(i), r["url"], skills, remote, fit, status[:17]], WIDTHS))
    print(bar)

    matches = [r for r in results if r.get("matched")]
    print(f"\nTotal candidates examined: {len(results)}")
    print(f"Matched job postings:      {len(matches)}")
    for m in matches:
        print(f"  - {m['url']}  (fit {m.get('fit_score')} — {m.get('fit_reason', '')})")


def write_json(results: List[dict], query: str, path: str = "results.json"):
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "total": len(results),
        "matches": [r["url"] for r in results if r.get("matched")],
        "results": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Results written to {path}")
