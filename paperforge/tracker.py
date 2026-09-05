import os
from datetime import datetime
from typing import Optional
from paperforge.db.session import get_session
from paperforge.db.models import TrackerEntry

def log_tracker(
    command: str,
    summary: str,
    reasoning: Optional[str] = None,
    user_input: Optional[str] = None,
    needs_input_ref: Optional[str] = None,
    tracker_file: str = "TRACKER.md",
    db_path: str = ".paperforge/paperforge.db"
):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # 1. DB log
    try:
        session = get_session(db_path)
        entry = TrackerEntry(
            timestamp=datetime.utcnow(),
            command=command,
            summary=summary,
            reasoning=reasoning,
            user_input=user_input,
            needs_input_ref=needs_input_ref
        )
        session.add(entry)
        session.commit()
        session.close()
    except Exception:
        pass # Ignore DB failure if init hasn't completed yet

    # 2. TRACKER.md log
    markdown_entry = f"\n### [{timestamp}] Command: `{command}`\n"
    markdown_entry += f"- **Summary**: {summary}\n"
    if reasoning:
        markdown_entry += f"- **Reasoning/Agent Decision**: {reasoning}\n"
    if user_input:
        markdown_entry += f"- **User Input**: {user_input}\n"
    if needs_input_ref:
        markdown_entry += f"- **NEEDS_INPUT Ref**: {needs_input_ref}\n"

    if not os.path.exists(tracker_file):
        with open(tracker_file, "w", encoding="utf-8") as f:
            f.write("# PaperForge System Audit & Decision Tracker\n\n")
            f.write("This file tracks all state changes, agent decisions, and user interactions.\n")

    with open(tracker_file, "a", encoding="utf-8") as f:
        f.write(markdown_entry)
