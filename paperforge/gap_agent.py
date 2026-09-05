import os
from typing import Dict, Any, List
from paperforge.db.session import get_session
from paperforge.db.models import AuthorInfo, Claim, ClaimStatusEnum, Contradiction, MissingEvidence, ResolutionTierEnum, StatusEnum
from paperforge.tracker import log_tracker

def analyze_gaps_and_update_needs_input(config: Dict[str, Any], project_dir: str = ".") -> Dict[str, Any]:
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    tracker_file = os.path.join(project_dir, "TRACKER.md")
    needs_input_file = os.path.join(project_dir, "NEEDS_INPUT.md")
    session = get_session(db_path)

    gaps = []

    # 1. AuthorInfo gap check
    resolved_authors = session.query(AuthorInfo).filter(AuthorInfo.resolved == True).all()
    if not resolved_authors:
        gap = MissingEvidence(
            description="Author names and affiliations could not be extracted from sources/.",
            resolution_tier=ResolutionTierEnum.D_NEEDS_CLARIFICATION,
            blocking=False,  # Unresolved author info generates marked TODOs in manuscript per spec
            suggested_action="Add a CONTRIBUTORS.md or README.md in sources/ listing author names, affiliations, and emails."
        )
        session.add(gap)
        gaps.append(gap)

    # 2. Check for UNSUPPORTED claims or missing ablation studies
    unsupported_claims = session.query(Claim).filter(Claim.status == ClaimStatusEnum.UNSUPPORTED).all()
    for c in unsupported_claims:
        gap = MissingEvidence(
            description=f"Claim lacks grounded evidence: '{c.text}'",
            resolution_tier=ResolutionTierEnum.E_NEEDS_NEW_EXPERIMENT,
            blocking=True,
            suggested_action="Provide experimental log, CSV result, or evaluation paper in sources/ backing this claim."
        )
        session.add(gap)
        gaps.append(gap)

    # 3. Check unresolved Contradictions
    unresolved_contradictions = session.query(Contradiction).filter(Contradiction.resolution_status == "UNRESOLVED").all()
    for con in unresolved_contradictions:
        gap = MissingEvidence(
            description=f"Unresolved data contradiction: {con.description}",
            resolution_tier=ResolutionTierEnum.D_NEEDS_CLARIFICATION,
            blocking=True,
            suggested_action="Provide clarifying note or updated dataset in sources/ to resolve conflict."
        )
        session.add(gap)
        gaps.append(gap)

    session.commit()

    # 4. Generate NEEDS_INPUT.md if blocking gaps exist
    blocking_gaps = [g for g in gaps if g.blocking]
    if blocking_gaps:
        with open(needs_input_file, "w", encoding="utf-8") as f:
            f.write("# PaperForge NEEDS_INPUT.md — Required Evidence & Clarifications\n\n")
            f.write("The following evidence gaps are currently blocking paper planning and build generation.\n")
            f.write("Please resolve them by dropping the required file(s) into `sources/` and running `paperforge resume`.\n\n")
            for idx, g in enumerate(blocking_gaps, 1):
                f.write(f"### Gap #{idx}: [{g.resolution_tier.value}]\n")
                f.write(f"- **Description**: {g.description}\n")
                f.write(f"- **Required Action**: {g.suggested_action}\n\n")
    else:
        if os.path.exists(needs_input_file):
            os.remove(needs_input_file)

    summary_msg = f"Gap Analysis: {len(gaps)} total gaps identified ({len(blocking_gaps)} blocking)."
    reasoning_msg = f"Updated NEEDS_INPUT.md with {len(blocking_gaps)} blocking gaps." if blocking_gaps else "No blocking gaps remaining."

    log_tracker(
        command="paperforge gap-analysis",
        summary=summary_msg,
        reasoning=reasoning_msg,
        needs_input_ref="NEEDS_INPUT.md" if blocking_gaps else None,
        tracker_file=tracker_file,
        db_path=db_path
    )

    session.close()
    return {
        "total_gaps": len(gaps),
        "blocking_gaps": len(blocking_gaps)
    }


def get_project_status(config: Dict[str, Any], project_dir: str = ".") -> Dict[str, Any]:
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    session = get_session(db_path)

    stale_evidences = session.query(Claim).filter(Claim.staleness == StatusEnum.STALE).count()
    unverified_claims = session.query(Claim).filter(Claim.status != ClaimStatusEnum.VERIFIED).count()
    verified_claims = session.query(Claim).filter(Claim.status == ClaimStatusEnum.VERIFIED).count()
    authors_resolved = session.query(AuthorInfo).filter(AuthorInfo.resolved == True).count()
    blocking_gaps = session.query(MissingEvidence).filter(MissingEvidence.blocking == True).count()

    session.close()
    return {
        "verified_claims": verified_claims,
        "unverified_claims": unverified_claims,
        "stale_items": stale_evidences,
        "authors_resolved": authors_resolved > 0,
        "blocking_gaps": blocking_gaps,
        "ready_for_plan": (blocking_gaps == 0)
    }
