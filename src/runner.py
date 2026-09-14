import os
import dataclasses
from typing import List, Callable, Optional, Any

@dataclasses.dataclass
class SearchConfig:
    resume_path: str
    skills: List[str]
    remote: bool
    max_pages: int
    min_skill_match: int
    model: str
    no_llm: bool
    headless: bool
    captcha_wait_s: int
    google_domain: str
    output_path: str
    custom_query: Optional[str] = None

def run_search(config: SearchConfig, 
               emit: Callable[[str, dict], None], 
               cancel_check: Callable[[], bool] = lambda: False) -> Any:
    """
    Executes the job search pipeline.
    
    :param config: SearchConfig containing all parameters.
    :param emit: Function to emit events. Signature: emit(event_type, data_dict).
    :param cancel_check: Function to check if the search should be cancelled.
    :return: The list of results found during the search.
    """
    from src import llm as llm_mod
    from src import report
    from src.checker import check_page
    from src.resume import extract_resume_text
    from src.search import SearchSession, build_query

    skills = config.skills
    if not skills:
        return []

    min_match = config.min_skill_match
    if min_match == 0:
        min_match = max(2, (len(skills) + 1) // 2)

    query = config.custom_query if config.custom_query else build_query(skills, config.remote)
    
    # Initial info
    emit("info", {"message": f"Search query: {query}"})
    emit("info", {"message": f"Skills ({len(skills)}): {', '.join(skills)}"})
    emit("info", {"message": f"Remote required: {config.remote}"})
    emit("info", {"message": f"Min skill match: {min_match}"})

    if config.no_llm:
        # Pre-check for --list style short-circuit is handled in agent.py
        pass

    print(f"Search query: {query}") # Still print for CLI compatibility
    print(f"Skills ({len(skills)}): {', '.join(skills)}")
    print(f"Remote required: {config.remote}")
    print(f"Min skill match: {min_match}")

    # Resume extraction
    emit("info", {"message": "Reading resume..."})
    try:
        resume_text = extract_resume_text(config.resume_path)
        emit("info", {"message": f"  extracted {len(resume_text)} chars from {config.resume_path}"})
    except Exception as e:
        emit("error", {"message": f"Error reading resume: {e}"})
        raise e

    use_llm = not config.no_llm
    if use_llm and not llm_mod.ollama_available():
        msg = "\nWarning: Ollama is not reachable at http://localhost:11434. Falling back to deterministic match only."
        emit("warning", {"message": msg})
        print(msg)
        use_llm = False

    headless = config.headless
    if headless:
        msg = "\nWarning: --headless disables captcha escalation; the browser must be visible to hand off captchas to a human."
        emit("warning", {"message": msg})
        print(msg)
        headless = False

    emit("phase", {"status": "collecting", "message": "Starting browser and collecting Google results..."})
    print("\nStarting browser and collecting Google results...\n")

    session = SearchSession(
        headless=headless, 
        google_domain=config.google_domain, 
        captcha_wait_s=config.captcha_wait_s
    )
    results = []

    try:
        hits = session.collect_results(query, max_pages=config.max_pages)
        emit("info", {"message": f"\nTotal unique candidate URLs: {len(hits)}\n"})
        print(f"\nTotal unique candidate URLs: {len(hits)}\n")
        
        emit("candidates_total", {"total": len(hits)})

        for idx, item in enumerate(hits, 1):
            if cancel_check():
                emit("info", {"message": "Search cancelled by user."})
                break

            url = item["url"]
            emit("candidate_start", {"idx": idx, "total": len(hits), "url": url})
            print(f"[{idx}/{len(hits)}] {url}")

            emit("candidate_step", {"stage": "fetch", "ok": True, "detail": "Fetching page content..."})
            fetched = session.fetch_page(url)
            
            if fetched is None:
                results.append({"url": url, "title": "", "status": "fetch-failed",
                                "matched": False, "skills_total": len(skills)})
                continue
            
            if fetched.get("status") == "captcha-timeout":
                emit("candidate_step", {"stage": "fetch", "ok": False, "detail": "Captcha timeout"})
                emit("captcha", {"url": url, "state": "timeout"})
                print("      captcha unsolved within deadline; skipping URL")
                results.append({"url": url, "title": "", "status": "skipped:captcha",
                                "matched": False, "skills_total": len(skills)})
                continue

            page_text = fetched["text"]

            # Step 1: deterministic skill + remote matching
            emit("candidate_step", {"stage": "step1", "ok": True, "detail": "Running deterministic match..."})
            check = check_page(url, page_text, skills, config.remote, min_match)
            print(f"      step1 skills {len(check.skills_matched)}/{len(skills)}, "
                  f"remote {'yes' if check.remote_found else 'no'} -> "
                  f"{'pass' if check.passed else 'FAIL'}")
            if not check.passed:
                results.append({
                    "url": url, "title": fetched["title"], "status": "rejected:match",
                    "matched": False,
                    "skills_matched": check.skills_matched, "skills_missing": check.skills_missing,
                    "skills_matched_count": len(check.skills_matched), "skills_total": len(skills),
                    "remote_found": check.remote_found, "remote_required": config.remote,
                })
                emit("candidate_result", {"status": "rejected:match"})
                continue


            # Step 2 + 3: LLM validation and resume fit
            if use_llm:
                emit("candidate_step", {"stage": "step2", "ok": True, "detail": "Running job-board check (LLM)..."})
                verdict = llm_mod.is_job_board(page_text, config.model)
                if verdict is None:
                    emit("candidate_step", {"stage": "step2", "ok": False, "detail": "LLM unavailable"})
                    print("      step2 LLM unavailable; skipping job-board check")
                elif verdict.get("is_job_board"):
                    print(f"      step2 job-board: {verdict.get('reason', '')}")
                    emit("candidate_step", {"stage": "step2", "ok": False, "detail": verdict.get('reason', 'job-board detected')})
                    results.append({
                        "url": url, "title": fetched["title"], "status": "rejected:job_board",
                        "matched": False,
                        "skills_matched": check.skills_matched,
                        "skills_matched_int": len(check.skills_matched), "skills_total": len(skills),
                        "remote_found": check.remote_found, "remote_required": config.remote,
                    })
                    emit("candidate_result", {"status": "rejected:job_board"})
                    continue

                emit("candidate_step", {"stage": "step3", "ok": True, "detail": "Running resume fit check (LLM)..."})
                fit = llm_mod.resume_fit(resume_text, page_text, config.model)
                if fit is None:
                    emit("candidate_step", {"stage": "step3", "ok": False, "detail": "LLM unavailable"})
                    print("      step3 LLM unavailable; keeping deterministic match")
                    score, reason, matched = None, "", True
                else:
                    score, reason = fit.get("score"), fit.get("reason")
                    matched = bool(fit.get("match")) or (score is not None and score >= 60)
                    print(f"      step3 fit {score}: {reason}")
                
                emit("candidate_step", {"stage": "step3", "ok": True, "detail": f"Fit score: {score}"})
            else:
                score, reason, matched = None, "", True

            result_entry = {
                "url": url, "title": fetched["title"],
                "status": "match" if matched else "review",
                "matched": matched,
                "skills_matched": check.skills_matched, "skills_missing": check.skills_missing,
                "skills_matched_count": len(check.skills_matched), "skills_total": len(skills),
                "remote_found": check.remote_found, "remote_required": config.remote,
                "fit_score": score, "fit_reason": reason,
            }
            results.append(result_entry)
            emit("candidate_result", {"row": result_entry})

        emit("phase", {"status": "done", "message": "Search completed."})
        emit("finish", {"results": results, "matches": [r["url"] for r in results if r["status"] == "match"]})
    except Exception as e:
        emit("error", {"message": str(e)})
        print(f"Error during search: {e}")
        raise e
    finally:
        session.close()
        report.print_report(results)
        report.write_json(results, query, path=config.output_path)
        emit("info", {"message": "Results written to " + config.output_path})

    return results
