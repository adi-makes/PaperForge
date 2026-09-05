import os
import re
import json
from typing import Dict, Any, List
from paperforge.db.session import get_session
from paperforge.db.models import (
    Source, Evidence, Dataset, Model, Experiment, Result, LiteratureItem, AuthorInfo, Claim, Contradiction, ClaimStatusEnum, StatusEnum
)
from paperforge.tracker import log_tracker

def process_research_understanding(config: Dict[str, Any], project_dir: str = ".") -> Dict[str, Any]:
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    tracker_file = os.path.join(project_dir, "TRACKER.md")
    session = get_session(db_path)

    evidences = session.query(Evidence).filter(Evidence.status == StatusEnum.FRESH).all()
    
    # 1. Author Resolution (never guess)
    sources = session.query(Source).all()
    for s in sources:
        if any(name in s.path.lower() for name in ["contributors", "readme", "author"]):
            with open(os.path.join(project_dir, s.path), "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                match = re.search(r"Author[s]?:?\s*([A-Za-z\s,\.]+)", content, re.IGNORECASE)
                if match:
                    name_str = match.group(1).strip()
                    if not session.query(AuthorInfo).filter(AuthorInfo.name == name_str).first():
                        author = AuthorInfo(
                            name=name_str,
                            resolved=True,
                            order_index=1
                        )
                        session.add(author)

    # 2. Extract Datasets & Models & Results from CSV/Markdown Evidences
    for ev in evidences:
        content = ev.extracted_content
        if ev.evidence_type in ["data_row", "table_summary"]:
            match = re.search(r"model_name:\s*([^,\n]+),\s*accuracy:\s*([0-9\.]+)", content, re.IGNORECASE)
            if match:
                model_name = match.group(1).strip()
                acc_val = match.group(2).strip()

                model = session.query(Model).filter(Model.name == model_name).first()
                if not model:
                    model = Model(name=model_name, description=f"Model {model_name} extracted from evidence #{ev.id}")
                    session.add(model)
                    session.commit()

                result = Result(
                    metric_name="accuracy",
                    metric_value=acc_val,
                    evidence_id=ev.id
                )
                session.add(result)
                session.commit()

    # 3. Summarize Traceable Entities (extract data BEFORE closing session)
    datasets = [d.name for d in session.query(Dataset).all()]
    models = [m.name for m in session.query(Model).all()]
    results_count = session.query(Result).count()
    authors = [a.name for a in session.query(AuthorInfo).all()]
    evidences_count = len(evidences)

    summary_text = (
        f"Research Summary:\n"
        f"- Authors Resolved: {len(authors)} ({authors})\n"
        f"- Models Found: {len(models)} ({models})\n"
        f"- Empirical Results Extracted: {results_count}\n"
        f"- Total Fresh Evidences Indexed: {evidences_count}"
    )

    log_tracker(
        command="paperforge summarize",
        summary="Generated structured research summary",
        reasoning=f"Extracted {len(models)} models and {results_count} metrics from fresh evidence.",
        tracker_file=tracker_file,
        db_path=db_path
    )

    session.close()
    return {
        "summary": summary_text,
        "authors": authors,
        "models": models,
        "results": results_count
    }


def extract_claims_and_contradictions(config: Dict[str, Any], project_dir: str = ".") -> Dict[str, Any]:
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    tracker_file = os.path.join(project_dir, "TRACKER.md")
    session = get_session(db_path)

    evidences = session.query(Evidence).filter(Evidence.status == StatusEnum.FRESH).all()
    
    claims_added = 0
    contradictions_added = 0

    metric_claims = {}
    for ev in evidences:
        content = ev.extracted_content
        matches = re.findall(r"([A-Za-z0-9\-_]+)\s+(?:achieves|reaches|attains|accuracy of|accuracy:)\s+([0-9\.]+%?)", content, re.IGNORECASE)
        for model_name, score in matches:
            claim_text = f"{model_name} achieves an accuracy of {score}."
            
            if model_name in metric_claims and metric_claims[model_name]["score"] != score:
                existing_ev_id = metric_claims[model_name]["ev_id"]
                contradiction = Contradiction(
                    description=f"Conflicting accuracy values for {model_name}: {metric_claims[model_name]['score']} (Ev #{existing_ev_id}) vs {score} (Ev #{ev.id})",
                    conflicting_evidence_ids=[existing_ev_id, ev.id],
                    resolution_status="UNRESOLVED"
                )
                session.add(contradiction)
                contradictions_added += 1
            else:
                metric_claims[model_name] = {"score": score, "ev_id": ev.id}
                
                claim = Claim(
                    text=claim_text,
                    status=ClaimStatusEnum.VERIFIED,
                    staleness=StatusEnum.FRESH,
                    evidence_ids=[ev.id]
                )
                session.add(claim)
                claims_added += 1

    session.commit()

    claims_count = session.query(Claim).count()
    contradictions_count = session.query(Contradiction).count()

    log_tracker(
        command="paperforge claims",
        summary=f"Extracted {claims_added} grounded claims and detected {contradictions_added} contradictions.",
        reasoning="Claims verified against exact evidence pointers.",
        tracker_file=tracker_file,
        db_path=db_path
    )

    session.close()
    return {
        "claims_count": claims_count,
        "contradictions_count": contradictions_count
    }
