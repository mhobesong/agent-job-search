import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import llm as llm_mod
from src import report
from src.checker import check_page
from src.resume import extract_resume_text
from src.search import SearchSession, build_query


def parse_args():
    p = argparse.ArgumentParser(
        description="Search Google for career pages matching your skills, validate with an LLM, and rank resume fit."
    )
    p.add_argument("--resume", required=True, help="Path to resume (.pdf, .txt, .md)")
    p.add_argument("--skills", required=True, help='Comma-separated skills, e.g. "python,sql,aws"')
    p.add_argument("--remote", action="store_true", help="Require remote / work-from-home postings")
    p.add_argument("--max-pages", type=int, default=2, help="Number of Google listing pages to walk (default 2)")
    p.add_argument("--min-skill-match", type=int, default=0,
                   help="Min skills that must appear on a page (default: majority of listed skills)")
    p.add_argument("--model", default="llama3.2", help="Ollama model name (default llama3.2)")
    p.add_argument("--no-llm", action="store_true", help="Skip LLM steps 2 & 3; keep only deterministic match")
    p.add_argument("--headless", action="store_true", help="Run browser headless (disables captcha escalation)")
    p.add_argument("--captcha-wait", type=int, default=120, help="Seconds to wait for a human to solve a captcha (default 120)")
    p.add_argument("--google-domain", default="google.com", help="Google domain, e.g. google.com / google.co.il")
    p.add_argument("--output", default="results.json", help="Output JSON path")
    p.add_argument("--list", action="store_true", help="Print the search query and exit")
    return p.parse_args()


def main():
    args = parse_args()
    skills = [s.strip() for s in args.skills.split(",") if s.strip()]
    if not skills:
        sys.exit("Error: --skills must include at least one skill")

    min_match = args.min_skill_match
    if min_match == 0:
        min_match = max(2, (len(skills) + 1) // 2)

    query = build_query(skills, args.remote)
    print(f"Search query: {query}")
    print(f"Skills ({len(skills)}): {', '.join(skills)}")
    print(f"Remote required: {args.remote}")
    print(f"Min skill match: {min_match}")
    if args.list:
        return

    print("\nResume:")
    try:
        resume_text = extract_resume_text(args.resume)
    except Exception as e:
        sys.exit(f"Error reading resume: {e}")
    print(f"  extracted {len(resume_text)} chars from {args.resume}")

    use_llm = not args.no_llm
    if use_llm and not llm_mod.ollama_available():
        print("\nWarning: Ollama is not reachable at http://localhost:11434. Falling back to deterministic match only.")
        print("  (Start Ollama, or pass --no-llm to silence this.)")
        use_llm = False

    headless = args.headless
    if headless:
        print("\nWarning: --headless disables captcha escalation; the browser must be visible to hand off captchas to a human.")
        headless = False

    print("\nStarting browser and collecting Google results...\n")
    session = SearchSession(headless=headless, google_domain=args.google_domain, captcha_wait_s=args.captcha_wait)
    results = []
    try:
        hits = session.collect_results(query, max_pages=args.max_pages)
        print(f"\nTotal unique candidate URLs: {len(hits)}\n")

        for idx, item in enumerate(hits, 1):
            url = item["url"]
            print(f"[{idx}/{len(hits)}] {url}")

            fetched = session.fetch_page(url)
            if fetched is None:
                results.append({"url": url, "title": "", "status": "fetch-failed",
                                "matched": False, "skills_total": len(skills)})
                continue
            if fetched.get("status") == "captcha-timeout":
                print("      captcha unsolved within deadline; skipping URL")
                results.append({"url": url, "title": "", "status": "skipped:captcha",
                                "matched": False, "skills_total": len(skills)})
                continue
            page_text = fetched["text"]

            # Step 1: deterministic skill + remote matching
            check = check_page(url, page_text, skills, args.remote, min_match)
            print(f"      step1 skills {len(check.skills_matched)}/{len(skills)}, "
                  f"remote {'yes' if check.remote_found else 'no'} -> "
                  f"{'pass' if check.passed else 'FAIL'}")
            if not check.passed:
                results.append({
                    "url": url, "title": fetched["title"], "status": "rejected:match",
                    "matched": False,
                    "skills_matched": check.skills_matched, "skills_missing": check.skills_missing,
                    "skills_matched_count": len(check.skills_matched), "skills_total": len(skills),
                    "remote_found": check.remote_found, "remote_required": args.remote,
                })
                continue

            # Step 2 + 3: LLM validation and resume fit
            if use_llm:
                verdict = llm_mod.is_job_board(page_text, args.model)
                if verdict is None:
                    print("      step2 LLM unavailable; skipping job-board check")
                elif verdict.get("is_job_board"):
                    print(f"      step2 job-board: {verdict.get('reason', '')}")
                    results.append({
                        "url": url, "title": fetched["title"], "status": "rejected:job_board",
                        "matched": False,
                        "skills_matched": check.skills_matched,
                        "skills_matched_count": len(check.skills_matched), "skills_total": len(skills),
                        "remote_found": check.remote_found, "remote_required": args.remote,
                    })
                    continue

                fit = llm_mod.resume_fit(resume_text, page_text, args.model)
                if fit is None:
                    print("      step3 LLM unavailable; keeping deterministic match")
                    score, reason, matched = None, "", True
                else:
                    score, reason = fit.get("score"), fit.get("reason")
                    matched = bool(fit.get("match")) or (score is not None and score >= 60)
                    print(f"      step3 fit {score}: {reason}")
            else:
                score, reason, matched = None, "", True

            results.append({
                "url": url, "title": fetched["title"],
                "status": "match" if matched else "review",
                "matched": matched,
                "skills_matched": check.skills_matched, "skills_missing": check.skills_missing,
                "skills_matched_count": len(check.skills_matched), "skills_total": len(skills),
                "remote_found": check.remote_found, "remote_required": args.remote,
                "fit_score": score, "fit_reason": reason,
            })
    finally:
        session.close()

    print()
    report.print_report(results)
    report.write_json(results, query, path=args.output)


if __name__ == "__main__":
    main()
