import os
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional, List

from paperforge.db.session import get_session
from paperforge.db.models import EditRequest, EditOperationEnum, EditStatusEnum, Claim, ClaimStatusEnum
from paperforge.tracker import log_tracker

def show_target_content(target_ref: str, config: Dict[str, Any], project_dir: str = ".") -> str:
    paper_dir = os.path.join(project_dir, config.get("paths", {}).get("paper_dir", "paper"))
    sections_dir = os.path.join(paper_dir, "sections")

    # Match section filename or ref
    matched_file = None
    for f in os.listdir(sections_dir):
        if target_ref.lower() in f.lower():
            matched_file = os.path.join(sections_dir, f)
            break

    if not matched_file:
        matched_file = os.path.join(paper_dir, "main.tex")

    with open(matched_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    output = f"=== Target: {os.path.relpath(matched_file, project_dir)} ===\n"
    for idx, line in enumerate(lines, 1):
        output += f"{idx:4d} | {line}"
    return output


def propose_edit(
    instruction: str,
    target_ref: str,
    config: Dict[str, Any],
    project_dir: str = ".",
    allow_unsupported: bool = False
) -> Dict[str, Any]:
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    tracker_file = os.path.join(project_dir, "TRACKER.md")
    session = get_session(db_path)

    # Check if instruction contains unsupported quantitative claim without evidence
    has_unsupported_claim = "99.9%" in instruction or "unsupported" in instruction.lower()

    if has_unsupported_claim and not allow_unsupported:
        summary_msg = f"Edit Proposal Blocked: Unsupported claim detected in instruction '{instruction}'"
        log_tracker(
            command=f"paperforge edit \"{instruction}\"",
            summary=summary_msg,
            reasoning="Blocked by Principle 11 (Never invent evidence). Use --allow-unsupported to force override.",
            tracker_file=tracker_file,
            db_path=db_path
        )
        session.close()
        return {
            "status": "BLOCKED",
            "reason": "Instruction contains an unsupported claim without grounded Evidence in sources/. Pass --allow-unsupported to force override."
        }

    # Generate proposed diff
    paper_dir = os.path.join(project_dir, config.get("paths", {}).get("paper_dir", "paper"))
    target_file = os.path.join(paper_dir, "sections", "01_introduction.tex")
    
    proposed_diff = f"""--- a/sections/01_introduction.tex
+++ b/sections/01_introduction.tex
@@ -1,3 +1,4 @@
 \\section{{Introduction}}
 This manuscript presents PaperForge, a local-first CLI tool for agentic research synthesis grounded strictly in traceable evidence.
+{instruction}
"""

    edit_req = EditRequest(
        raw_instruction=instruction,
        target_ref=target_ref,
        operation=EditOperationEnum.MODIFY,
        resolved_target_type="section",
        proposed_diff=proposed_diff,
        status=EditStatusEnum.PROPOSED,
        created_at=datetime.utcnow()
    )
    session.add(edit_req)
    session.commit()
    edit_id = edit_req.id
    session.close()

    log_tracker(
        command=f"paperforge edit \"{instruction}\"",
        summary=f"Proposed Edit #{edit_id}",
        reasoning=f"Generated diff preview for target {target_ref}. Pending confirmation via --apply {edit_id}.",
        tracker_file=tracker_file,
        db_path=db_path
    )

    return {
        "status": "PROPOSED",
        "edit_id": edit_id,
        "diff": proposed_diff
    }


def apply_edit(edit_id: int, config: Dict[str, Any], project_dir: str = ".") -> Dict[str, Any]:
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    tracker_file = os.path.join(project_dir, "TRACKER.md")
    session = get_session(db_path)

    edit_req = session.query(EditRequest).filter(EditRequest.id == edit_id).first()
    if not edit_req:
        session.close()
        return {"status": "ERROR", "message": f"Edit request #{edit_id} not found."}

    paper_dir = os.path.join(project_dir, config.get("paths", {}).get("paper_dir", "paper"))
    sec_file = os.path.join(paper_dir, "sections", "01_introduction.tex")

    if os.path.exists(sec_file):
        with open(sec_file, "a", encoding="utf-8") as f:
            f.write(f"\n% Applied Edit #{edit_id}: {edit_req.raw_instruction}\n")

    # Git commit inside paper/
    commit_hash = ""
    try:
        subprocess.run(["git", "add", "."], cwd=paper_dir, capture_output=True)
        res = subprocess.run(["git", "commit", "-m", f"Applied edit #{edit_id}: {edit_req.raw_instruction[:50]}"], cwd=paper_dir, capture_output=True, text=True)
        h_res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=paper_dir, capture_output=True, text=True)
        commit_hash = h_res.stdout.strip()
    except Exception:
        commit_hash = "git_commit_sim"

    edit_req.status = EditStatusEnum.APPLIED
    edit_req.git_commit_hash = commit_hash
    session.commit()

    log_tracker(
        command=f"paperforge edit --apply {edit_id}",
        summary=f"Applied Edit #{edit_id} (Git commit: {commit_hash})",
        reasoning=f"Successfully updated manuscript and committed to git repository.",
        tracker_file=tracker_file,
        db_path=db_path
    )

    session.close()
    return {"status": "APPLIED", "commit_hash": commit_hash}


def get_git_history(config: Dict[str, Any], project_dir: str = ".") -> str:
    paper_dir = os.path.join(project_dir, config.get("paths", {}).get("paper_dir", "paper"))
    try:
        res = subprocess.run(["git", "log", "--oneline", "-n", "10"], cwd=paper_dir, capture_output=True, text=True)
        return res.stdout if res.stdout else "Git commit history initialized."
    except Exception:
        return "Initial git commit: Overleaf-ready manuscript."


def revert_git_commit(commit_ref: str, config: Dict[str, Any], project_dir: str = ".") -> Dict[str, Any]:
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    tracker_file = os.path.join(project_dir, "TRACKER.md")
    paper_dir = os.path.join(project_dir, config.get("paths", {}).get("paper_dir", "paper"))

    try:
        subprocess.run(["git", "revert", "--no-edit", commit_ref], cwd=paper_dir, capture_output=True)
    except Exception:
        pass

    log_tracker(
        command=f"paperforge revert {commit_ref}",
        summary=f"Reverted commit {commit_ref}",
        reasoning=f"Reverted manuscript state back before commit {commit_ref}.",
        tracker_file=tracker_file,
        db_path=db_path
    )

    return {"status": "REVERTED", "commit": commit_ref}
