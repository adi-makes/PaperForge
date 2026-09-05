import os
import tempfile
import pytest
from paperforge.scanner import scan_sources
from paperforge.db.session import get_session
from paperforge.db.models import Source, Evidence, Claim, StatusEnum

@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory() as tmp_dir:
        sources_dir = os.path.join(tmp_dir, "sources")
        os.makedirs(sources_dir, exist_ok=True)
        db_path = os.path.join(tmp_dir, ".paperforge/paperforge.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        session = get_session(db_path)
        session.close()
        config = {
            "paths": {
                "sources_dir": "sources",
                "db_path": ".paperforge/paperforge.db"
            }
        }
        yield tmp_dir, sources_dir, config, db_path

def test_scan_sources_incremental_lifecycle(temp_project):
    tmp_dir, sources_dir, config, db_path = temp_project

    # 1. Add file1.txt
    file1_path = os.path.join(sources_dir, "file1.txt")
    with open(file1_path, "w") as f:
        f.write("Line 1 content for file 1.\nLine 2 content for file 1.")

    res1 = scan_sources(config, project_dir=tmp_dir)
    assert len(res1["new_files"]) == 1
    assert len(res1["updated_files"]) == 0
    assert len(res1["unchanged_files"]) == 0
    assert len(res1["deleted_files"]) == 0

    session = get_session(db_path)
    sources = session.query(Source).all()
    assert len(sources) == 1
    evidences_count1 = session.query(Evidence).count()
    assert evidences_count1 > 0
    session.close()

    # 2. Rescan without changes -> 0 new, 0 updated, 1 unchanged
    res2 = scan_sources(config, project_dir=tmp_dir)
    assert len(res2["new_files"]) == 0
    assert len(res2["updated_files"]) == 0
    assert len(res2["unchanged_files"]) == 1
    assert len(res2["deleted_files"]) == 0

    # 3. Modify file1.txt -> 0 new, 1 updated, 0 unchanged
    with open(file1_path, "w") as f:
        f.write("Updated line 1 content for file 1.\nUpdated line 2 content.")

    res3 = scan_sources(config, project_dir=tmp_dir)
    assert len(res3["new_files"]) == 0
    assert len(res3["updated_files"]) == 1
    assert len(res3["unchanged_files"]) == 0
    assert len(res3["deleted_files"]) == 0

    session = get_session(db_path)
    stale_evs = session.query(Evidence).filter(Evidence.status == StatusEnum.STALE).count()
    assert stale_evs > 0
    session.close()

    # 4. Delete file1.txt -> 1 deleted
    os.remove(file1_path)
    res4 = scan_sources(config, project_dir=tmp_dir)
    assert len(res4["deleted_files"]) == 1
    assert len(res4["new_files"]) == 0
    assert len(res4["updated_files"]) == 0
    assert len(res4["unchanged_files"]) == 0

    session = get_session(db_path)
    sources_after_del = session.query(Source).all()
    assert len(sources_after_del) == 0
    evidences_after_del = session.query(Evidence).count()
    assert evidences_after_del == 0
    session.close()
