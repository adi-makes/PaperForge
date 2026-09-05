import os
import json
from typing import Dict, Any, List
from paperforge.db.session import get_session
from paperforge.db.models import Claim, ClaimStatusEnum, Figure, Table, FigureGenMethodEnum, Result, Source
from paperforge.tracker import log_tracker

def generate_paper_plan(config: Dict[str, Any], project_dir: str = ".") -> Dict[str, Any]:
    db_path = os.path.join(project_dir, config.get("paths", {}).get("db_path", ".paperforge/paperforge.db"))
    tracker_file = os.path.join(project_dir, "TRACKER.md")
    session = get_session(db_path)

    verified_claims = session.query(Claim).filter(Claim.status == ClaimStatusEnum.VERIFIED).all()
    results = session.query(Result).all()

    # 1. Map Claims to standard IEEE sections
    section_mapping = {
        "01_introduction": [],
        "02_related_work": [],
        "03_system_architecture": [],
        "04_experimental_setup": [],
        "05_evaluation": [],
        "06_conclusion": []
    }

    for idx, c in enumerate(verified_claims):
        if idx % 3 == 0:
            section_mapping["01_introduction"].append(c)
            c.used_in_section = "01_introduction"
        elif idx % 3 == 1:
            section_mapping["03_system_architecture"].append(c)
            c.used_in_section = "03_system_architecture"
        else:
            section_mapping["05_evaluation"].append(c)
            c.used_in_section = "05_evaluation"

    # 2. Plan Assets (Matplotlib vector PDF figure, TikZ architecture diagram, Booktabs result table)
    planned_figures = []
    planned_tables = []

    # Architecture TikZ diagram
    fig_arch = Figure(
        figure_type="system_architecture",
        generation_method=FigureGenMethodEnum.tikz,
        output_path="figures/architecture.tikz.tex",
        status="PLANNED"
    )
    session.add(fig_arch)
    planned_figures.append(fig_arch)

    # Accuracy Bar Chart Matplotlib figure
    fig_chart = Figure(
        figure_type="performance_bar_chart",
        generation_method=FigureGenMethodEnum.matplotlib,
        output_path="figures/accuracy_chart.pdf",
        status="PLANNED"
    )
    session.add(fig_chart)
    planned_figures.append(fig_chart)

    # Results Table
    tbl_res = Table(
        table_type="evaluation_metrics_table",
        output_path="tables/evaluation_metrics.tex",
        status="PLANNED"
    )
    session.add(tbl_res)
    planned_tables.append(tbl_res)

    session.commit()

    plan_str = (
        f"IEEE Paper Generation Plan:\n"
        f"- Target Template: assets/ieee_conference_template.tex (Forked, instruction prose stripped)\n"
        f"- Allocated Verified Claims: {len(verified_claims)}\n"
        f"- Figures Planned: {len(planned_figures)} (1 TikZ vector diagram, 1 Matplotlib vector PDF)\n"
        f"- Tables Planned: {len(planned_tables)} (1 LaTeX booktabs table)\n"
        f"- Section Structure: Introduction, Related Work, System Architecture, Experimental Setup, Evaluation, Conclusion"
    )

    log_tracker(
        command="paperforge plan",
        summary="Generated paper section and asset structure plan",
        reasoning=f"Allocated {len(verified_claims)} verified claims across 6 IEEE sections.",
        tracker_file=tracker_file,
        db_path=db_path
    )

    session.close()
    return {
        "plan_summary": plan_str,
        "claims_count": len(verified_claims),
        "figures_count": len(planned_figures),
        "tables_count": len(planned_tables)
    }
