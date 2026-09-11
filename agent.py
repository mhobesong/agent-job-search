import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.runner import run_search, SearchConfig
from src.search import build_query
from src.resume import extract_resume_text

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
    p.add_argument("--captcha-wait", type=int, default=120, help="Seconds to wait for a human to solve a .")
    p.add_argument("--google-domain", default="google.com", help="Google domain, e.g. google.com / google.co.il")
    p.add_argument("--output", default="results.json", help="Output JSON path")
    p.add_argument("--list", action="store_true", help="Print the search query and exit")
    return p.parse_args()


def _cli_emit(event_type: str, data: dict):
    """CLI-compatible emitter that prints to stdout."""
    if event_type == "info":
        print(data.get("message", ""))
    elif event_type == "warning":
        print(f"\nWarning: {data.get('message', '')}")
    elif event_type == "error":
        print(f"\nError: {data.get('message', '')}")
    elif event_type == "phase":
        print(f"\n[Phase: {data.get('status')}] {data.pop('message', '')}")
    elif event_type == "candidate_start":
        print(f"[{data['idx']}/{data['total']}] {data['url']}")
    elif event_type == "candidate_step":
        print(f"      {data.get('detail', '')}")
    elif event_type == "candidate_result":
        status = data.get("status", "result")
        print(f"      Result: {status}")
    elif event_type == "candidates_total":
        print(f"Total candidates found: {data['total']}")
    elif event_type == "finish":
        print("\nSearch process finished.")

def main():
    args = parse_args()
    skills = [s.strip() for s in args.skills.split(",") if s.strip()]
    if not skills:
        sys.exit("Error: --skills must include at least one skill")

    min_match = args.min_skill_match
    if min_match == 0:
        min_match = max(2, (len(skills) + 1) // 2)

    query = build_query(skills, args.remote)
    
    if args.list:
        print(f"Search query: {query}")
        print(f"Skills ({len(skills)}): {', '.join(skills)}")
        print(f"Remote required: {args.remote}")
        print(f"Min skill match: {min_match}")
        return

    config = SearchConfig(
        resume_path=args.resume,
        skills=skills,
        remote=args.remote,
        max_pages=args.max_pages,
        min_skill_match=min_match,
        model=args.model,
        no_llm=args.no_llm,
        headless=args.headless,
        captcha_wait_s=args.captcha_wait,
        google_domain=args.google_domain,
        output_path=args.output
    )

    try:
        resume_text = extract_resume_text(config.resume_path)
    except Exception as e:
        sys.exit(f"Error reading resume: {e}")

    run_search(config, _cli_emit)

if __name__ == "__main__":
    main()

