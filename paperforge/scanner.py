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

    from paperforge.db.session import init_db
    init_db(db_path)
    session = get_session(db_path)
    embedding_provider = get_embedding_provider(config)
    hybrid_index = HybridIndex(chroma_dir=chroma_dir, embedding_provider=embedding_provider)

    os.makedirs(sources_path, exist_ok=True)

    new_files = []
    updated_files = []
    unchanged_files = []
    deleted_files = []
    stale_items_count = 0

    # 1. Gather all files currently present in sources/
    current_file_paths = []
    for root, _, files in os.walk(sources_path):
        for file in files:
            current_file_paths.append(os.path.join(root, file))

    current_rel_paths = {os.path.relpath(fp, project_dir): fp for fp in current_file_paths}
    total_files = len(current_rel_paths)

    if progress_callback:
        progress_callback(0, total_files, "", f"Discovered {total_files} files in {sources_path}")

    # 2. Check for DELETED files in database
    existing_db_sources = session.query(Source).all()
    db_source_map = {s.path: s for s in existing_db_sources}

    deleted_sources = [s for path, s in db_source_map.items() if path not in current_rel_paths]
    
    if deleted_sources:
        if progress_callback:
            progress_callback(0, total_files, "", f"Cleaning up {len(deleted_sources)} deleted sources...")

        # Pre-fetch claims, figures, tables for efficient staleness propagation
        claims = session.query(Claim).all()
        figs = session.query(Figure).all()
        tbls = session.query(Table).all()

        for d_source in deleted_sources:
            deleted_files.append(d_source.path)
            old_evidences = session.query(Evidence).filter(Evidence.source_id == d_source.id).all()
            old_ev_ids = {ev.id for ev in old_evidences}

            if old_ev_ids:
                # Remove vectors from ChromaDB
                hybrid_index.delete_evidences(list(old_ev_ids))

                # Mark dependent Claims, Figures, Tables STALE
                for c in claims:
                    if any(eid in (c.evidence_ids or []) for eid in old_ev_ids):
                        c.staleness = StatusEnum.STALE
                        stale_items_count += 1
                for f in figs:
                    if any(eid in (f.source_evidence_ids or []) for eid in old_ev_ids):
                        f.staleness = StatusEnum.STALE
                        stale_items_count += 1
                for t in tbls:
                    if any(eid in (t.source_evidence_ids or []) for eid in old_ev_ids):
                        t.staleness = StatusEnum.STALE
                        stale_items_count += 1

                # Delete old Evidences
                session.query(Evidence).filter(Evidence.source_id == d_source.id).delete(synchronize_session=False)

            # Delete Source row
            session.delete(d_source)
        session.commit()

    # Pre-fetch all dependent items once if any file update requires staleness propagation
    claims_cache = None
    figs_cache = None
    tbls_cache = None

    # 3. Process existing & new files
    for i, (rel_path, filepath) in enumerate(current_rel_paths.items(), 1):
        if progress_callback:
            progress_callback(i - 1, total_files, rel_path, f"Checking file hash & database record ({rel_path})...")

        current_hash = get_file_hash(filepath)
        ext = os.path.splitext(os.path.basename(filepath))[1].lower().strip(".") or "txt"
        existing_source = db_source_map.get(rel_path)

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
            session.flush()  # assign source.id without full commit
            new_files.append(rel_path)
            
            # Parse & extract evidence
            parser = get_parser(filepath)
            chunks = parser.parse(filepath)
            
            ev_objects = []
            for chunk in chunks:
                ev_objects.append(Evidence(
                    source_id=source.id,
                    source_content_hash=current_hash,
                    location_json=chunk["location_json"],
                    extracted_content=chunk["extracted_content"],
                    evidence_type=chunk["evidence_type"],
                    status=StatusEnum.FRESH
                ))
            
            if ev_objects:
                session.add_all(ev_objects)
                session.flush()

            session.commit()

            ev_to_index = [
                {
                    "id": ev.id,
                    "extracted_content": ev.extracted_content,
                    "location_json": ev.location_json,
                    "evidence_type": ev.evidence_type,
                    "source_id": source.id
                }
                for ev in ev_objects
            ]
            hybrid_index.add_evidences(ev_to_index)

        elif existing_source.content_hash != current_hash:
            # CHANGED file -> Staleness propagation & re-indexing
            if progress_callback:
                progress_callback(i - 1, total_files, rel_path, f"Propagating staleness & re-indexing ({rel_path})...")
            
            updated_files.append(rel_path)

            if claims_cache is None:
                claims_cache = session.query(Claim).all()
                figs_cache = session.query(Figure).all()
                tbls_cache = session.query(Table).all()

            # Mark old Evidences STALE & remove from ChromaDB
            old_evidences = session.query(Evidence).filter(Evidence.source_id == existing_source.id).all()
            old_ev_ids = {old_ev.id for old_ev in old_evidences}

            if old_ev_ids:
                hybrid_index.delete_evidences(list(old_ev_ids))

                for old_ev in old_evidences:
                    old_ev.status = StatusEnum.STALE
                    stale_items_count += 1

                for c in claims_cache:
                    if any(eid in (c.evidence_ids or []) for eid in old_ev_ids):
                        c.staleness = StatusEnum.STALE
                for f in figs_cache:
                    if any(eid in (f.source_evidence_ids or []) for eid in old_ev_ids):
                        f.staleness = StatusEnum.STALE
                for t in tbls_cache:
                    if any(eid in (t.source_evidence_ids or []) for eid in old_ev_ids):
                        t.staleness = StatusEnum.STALE

            # Update source record
            existing_source.content_hash = current_hash
            existing_source.status = StatusEnum.FRESH

            # Re-parse & extract new Evidences
            parser = get_parser(filepath)
            chunks = parser.parse(filepath)
            
            ev_objects = []
            for chunk in chunks:
                ev_objects.append(Evidence(
                    source_id=existing_source.id,
                    source_content_hash=current_hash,
                    location_json=chunk["location_json"],
                    extracted_content=chunk["extracted_content"],
                    evidence_type=chunk["evidence_type"],
                    status=StatusEnum.FRESH
                ))

            if ev_objects:
                session.add_all(ev_objects)
                session.flush()

            session.commit()

            ev_to_index = [
                {
                    "id": ev.id,
                    "extracted_content": ev.extracted_content,
                    "location_json": ev.location_json,
                    "evidence_type": ev.evidence_type,
                    "source_id": existing_source.id
                }
                for ev in ev_objects
            ]
            hybrid_index.add_evidences(ev_to_index)

        else:
            unchanged_files.append(rel_path)
            if progress_callback:
                progress_callback(i, total_files, rel_path, f"Source unchanged ({rel_path})")

        if progress_callback:
            progress_callback(i, total_files, rel_path, f"Processed {rel_path}")

    summary_msg = (
        f"Scanned {len(new_files) + len(updated_files) + len(unchanged_files) + len(deleted_files)} files: "
        f"{len(new_files)} new, {len(updated_files)} updated, {len(unchanged_files)} unchanged, {len(deleted_files)} deleted."
    )
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
        "deleted_files": deleted_files,
        "stale_items_count": stale_items_count
    }

