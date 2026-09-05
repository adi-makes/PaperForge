import os
import tempfile
import pytest
from paperforge.reset import reset_repository
from paperforge.db.session import get_session
from paperforge.db.models import Source

def test_reset_repository_full():
    with tempfile.TemporaryDirectory() as tmp_dir:
        sources_dir = os.path.join(tmp_dir, "sources")
        dot_pf = os.path.join(tmp_dir, ".paperforge")
        paper_dir = os.path.join(tmp_dir, "paper")
        assets_dir = os.path.join(tmp_dir, "assets")

        os.makedirs(sources_dir, exist_ok=True)
        os.makedirs(dot_pf, exist_ok=True)
        os.makedirs(paper_dir, exist_ok=True)
        os.makedirs(assets_dir, exist_ok=True)

        # Create dummy source and report files
        dummy_source = os.path.join(sources_dir, "test.txt")
        with open(dummy_source, "w") as f:
            f.write("test source content")

        dummy_plan = os.path.join(tmp_dir, "PAPER_PLAN.md")
        with open(dummy_plan, "w") as f:
            f.write("plan content")

        config = {
            "paths": {
                "sources_dir": "sources",
                "paper_dir": "paper",
                "assets_dir": "assets",
                "db_path": ".paperforge/paperforge.db"
            }
        }

        res = reset_repository(config, project_dir=tmp_dir, remove_sources=True)

        assert res["status"] == "success"
        assert res["sources_removed"] == 1
        assert not os.path.exists(dummy_source)
        assert not os.path.exists(dummy_plan)

        # Ensure directories and DB are cleanly re-initialized
        assert os.path.exists(sources_dir)
        assert os.path.exists(dot_pf)
        db_path = os.path.join(dot_pf, "paperforge.db")
        assert os.path.exists(db_path)

        session = get_session(db_path)
        sources_count = session.query(Source).count()
        assert sources_count == 0
        session.close()


def test_reset_repository_keep_sources():
    with tempfile.TemporaryDirectory() as tmp_dir:
        sources_dir = os.path.join(tmp_dir, "sources")
        dot_pf = os.path.join(tmp_dir, ".paperforge")

        os.makedirs(sources_dir, exist_ok=True)
        os.makedirs(dot_pf, exist_ok=True)

        dummy_source = os.path.join(sources_dir, "test.txt")
        with open(dummy_source, "w") as f:
            f.write("test source content")

        config = {
            "paths": {
                "sources_dir": "sources",
                "paper_dir": "paper",
                "assets_dir": "assets",
                "db_path": ".paperforge/paperforge.db"
            }
        }

        res = reset_repository(config, project_dir=tmp_dir, remove_sources=False)

        assert res["status"] == "success"
        assert res["sources_removed"] == 0
        assert os.path.exists(dummy_source)
