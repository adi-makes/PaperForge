import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from paperforge.db.session import get_session
from paperforge.db.models import Source, Evidence, Claim, Figure, Table, StatusEnum
from paperforge.parsers import get_parser, get_file_hash
from paperforge.index import HybridIndex
from paperforge.providers.embedding import get_embedding_provider
from paperforge.tracker import log_tracker

def scan_sources(
    config: Dict[str, Any], 
    project_dir: str = ".",
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None
) -> Dict[str, Any]:
    sources_path = os.path.join(project_dir, config.get("paths", {}).get("sources_dir", "sources"))
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    chroma_dir = os.path.join(project_dir, ".paperforge/chroma_db")
    tracker_file = os.path.join(project_dir, "TRACKER.md")

    if progress_callback:
        progress_callback(0, 0, "", "Initializing database & embedding provider...")

    session = get_session(db_path)
    embedding_provider = get_embedding_provider(config)
    hybrid_index = HybridIndex(chroma_dir=chroma_dir, embedding_provider=embedding_provider)

    os.makedirs(sources_path, exist_ok=True)

    new_files = []
    updated_files = []
    unchanged_files = []
    stale_items_count = 0

    all_file_paths = []
    for root, _, files in os.walk(sources_path):
        for file in files:
            all_file_paths.append(os.path.join(root, file))

    total_files = len(all_file_paths)

    if progress_callback:
        progress_callback(0, total_files, "", f"Discovered {total_files} files in {sources_path}")

    # 1. Walk sources/
    for i, filepath in enumerate(all_file_paths, 1):
        rel_path = os.path.relpath(filepath, project_dir)
        if progress_callback:
            progress_callback(i - 1, total_files, rel_path, f"Checking file hash & database record ({rel_path})...")

        current_hash = get_file_hash(filepath)
        ext = os.path.splitext(os.path.basename(filepath))[1].lower().strip(".") or "txt"

        existing_source = session.query(Source).filter(Source.path == rel_path).first()

        if existing_source is None:
            # NEW file
            if progress_callback:
                progress_callback(i - 1, total_files, rel_path, f"Parsing & indexing new source ({rel_path})...")
            
            source = Source(
                path=rel_path,
                file_type=ext,
                content_hash=current_hash,
                ingested_at=datetime.utcnow(),
                status=StatusEnum.FRESH
            )
            session.add(source)
            session.commit()
            new_files.append(rel_path)
            
            # Parse & extract evidence
            parser = get_parser(filepath)
            chunks = parser.parse(filepath)
            ev_to_index = []
            for chunk in chunks:
                ev = Evidence(
                    source_id=source.id,
                    source_content_hash=current_hash,
                    location_json=chunk["location_json"],
                    extracted_content=chunk["extracted_content"],
                    evidence_type=chunk["evidence_type"],
                    status=StatusEnum.FRESH
                )
                session.add(ev)
                session.commit()
                ev_to_index.append({
                    "id": ev.id,
                    "extracted_content": ev.extracted_content,
                    "location_json": ev.location_json,
                    "evidence_type": ev.evidence_type,
                    "source_id": source.id
                })
            hybrid_index.add_evidences(ev_to_index)

        elif existing_source.content_hash != current_hash:
            # CHANGED file -> Staleness propagation
            if progress_callback:
                progress_callback(i - 1, total_files, rel_path, f"Propagating staleness & re-indexing ({rel_path})...")
            
            updated_files.append(rel_path)
            
            # Mark old Evidences STALE
            old_evidences = session.query(Evidence).filter(Evidence.source_id == existing_source.id).all()
            for old_ev in old_evidences:
                old_ev.status = StatusEnum.STALE
                stale_items_count += 1
                
                # Mark dependent Claims STALE
                claims = session.query(Claim).all()
                for c in claims:
                    if old_ev.id in (c.evidence_ids or []):
                        c.staleness = StatusEnum.STALE

                # Mark dependent Figures STALE
                figs = session.query(Figure).all()
                for f in figs:
                    if old_ev.id in (f.source_evidence_ids or []):
                        f.staleness = StatusEnum.STALE

                # Mark dependent Tables STALE
                tbls = session.query(Table).all()
                for t in tbls:
                    if old_ev.id in (t.source_evidence_ids or []):
                        t.staleness = StatusEnum.STALE

            # Update source
            existing_source.content_hash = current_hash
            existing_source.status = StatusEnum.FRESH
            session.commit()

            # Re-parse & extract new Evidences
            parser = get_parser(filepath)
            chunks = parser.parse(filepath)
            ev_to_index = []
            for chunk in chunks:
                ev = Evidence(
                    source_id=existing_source.id,
                    source_content_hash=current_hash,
                    location_json=chunk["location_json"],
                    extracted_content=chunk["extracted_content"],
                    evidence_type=chunk["evidence_type"],
                    status=StatusEnum.FRESH
                )
                session.add(ev)
                session.commit()
                ev_to_index.append({
                    "id": ev.id,
                    "extracted_content": ev.extracted_content,
                    "location_json": ev.location_json,
                    "evidence_type": ev.evidence_type,
                    "source_id": existing_source.id
                })
            hybrid_index.add_evidences(ev_to_index)

        else:
            unchanged_files.append(rel_path)
            if progress_callback:
                progress_callback(i, total_files, rel_path, f"Source unchanged ({rel_path})")

        if progress_callback:
            progress_callback(i, total_files, rel_path, f"Processed {rel_path}")

    summary_msg = f"Scanned {len(new_files) + len(updated_files) + len(unchanged_files)} files: {len(new_files)} new, {len(updated_files)} updated, {len(unchanged_files)} unchanged."
    reasoning_msg = f"Staleness propagation marked {stale_items_count} old evidences and dependent claims/figures/tables as STALE."

    log_tracker(
        command="paperforge scan",
        summary=summary_msg,
        reasoning=reasoning_msg,
        tracker_file=tracker_file,
        db_path=db_path
    )

    session.close()
    return {
        "new_files": new_files,
        "updated_files": updated_files,
        "unchanged_files": unchanged_files,
        "stale_items_count": stale_items_count
    }
