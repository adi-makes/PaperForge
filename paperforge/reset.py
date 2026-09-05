import os
import shutil
from typing import Dict, Any

from paperforge.db.session import init_db
from paperforge.tracker import log_tracker


def reset_repository(
    config: Dict[str, Any],
    project_dir: str = ".",
    remove_sources: bool = True
) -> Dict[str, Any]:
    """
    Resets the PaperForge project workspace:
    - Removes .paperforge/ (SQLite DB, ChromaDB vector store)
    - Removes paper/ (generated LaTeX files, compiled PDF, Overleaf ZIP)
    - Removes assets/ generated outputs (figures, tables, references.bib)
    - Removes generated markdown reports (PAPER_PLAN.md, NEEDS_INPUT.md, REVIEW_REPORT.md, TRACKER.md)
    - Optionally removes all files in sources/ directory
    - Re-initializes clean folder structure and database
    """
    proj_abs = os.path.abspath(project_dir)
    sources_dir = os.path.join(proj_abs, config.get("paths", {}).get("sources_dir", "sources"))
    db_path = os.path.join(proj_abs, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    dot_paperforge = os.path.join(proj_abs, ".paperforge")
    paper_dir = os.path.join(proj_abs, config.get("paths", {}).get("paper_dir", "paper"))
    assets_dir = os.path.join(proj_abs, config.get("paths", {}).get("assets_dir", "assets"))

    cleaned_items = []

    # 1. Clean .paperforge directory
    if os.path.exists(dot_paperforge):
        shutil.rmtree(dot_paperforge, ignore_errors=True)
        cleaned_items.append(".paperforge/ (Database & ChromaDB vectors)")

    # 2. Clean paper directory
    if os.path.exists(paper_dir):
        shutil.rmtree(paper_dir, ignore_errors=True)
        cleaned_items.append("paper/ (Generated manuscript & compiled PDF)")

    # 3. Clean assets directory
    if os.path.exists(assets_dir):
        shutil.rmtree(assets_dir, ignore_errors=True)
        cleaned_items.append("assets/ (Generated figures, tables, bib)")

    # 4. Remove generated reports
    reports = ["PAPER_PLAN.md", "NEEDS_INPUT.md", "REVIEW_REPORT.md", "TRACKER.md"]
    for r in reports:
        r_path = os.path.join(proj_abs, r)
        if os.path.exists(r_path):
            try:
                os.remove(r_path)
                cleaned_items.append(f"{r}")
            except Exception:
                pass

    # 5. Clean sources/ folder if requested
    sources_cleaned_count = 0
    if remove_sources and os.path.exists(sources_dir):
        for item in os.listdir(sources_dir):
            item_path = os.path.join(sources_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
                sources_cleaned_count += 1
            elif os.path.isfile(item_path) or os.path.islink(item_path):
                os.remove(item_path)
                sources_cleaned_count += 1
        cleaned_items.append(f"sources/ ({sources_cleaned_count} source files/folders removed)")

    # Re-initialize clean workspace structure
    os.makedirs(sources_dir, exist_ok=True)
    os.makedirs(dot_paperforge, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)

    # Re-copy template into assets if available in package
    source_template = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "ieee_conference_template.tex"))
    target_template = os.path.abspath(os.path.join(assets_dir, "ieee_conference_template.tex"))
    if os.path.exists(source_template) and source_template != target_template:
        shutil.copy(source_template, target_template)

    init_db(db_path)

    tracker_file = os.path.join(proj_abs, "TRACKER.md")
    log_tracker(
        command="paperforge reset",
        summary="Reset PaperForge project workspace to clean state",
        reasoning=f"Removed database, vector store, paper output, reports, and {'source files' if remove_sources else 'retained sources'}",
        tracker_file=tracker_file,
        db_path=db_path
    )

    return {
        "status": "success",
        "cleaned_items": cleaned_items,
        "sources_removed": sources_cleaned_count if remove_sources else 0
    }
