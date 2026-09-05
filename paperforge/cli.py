import os
import shutil
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from paperforge.config import load_config
from paperforge.db.session import init_db, get_session
from paperforge.db.models import Evidence, StatusEnum, Claim, Contradiction
from paperforge.providers.llm import get_llm_provider
from paperforge.providers.embedding import get_embedding_provider
from paperforge.tracker import log_tracker
from paperforge.scanner import scan_sources
from paperforge.index import HybridIndex

from paperforge.research_engine import process_research_understanding, extract_claims_and_contradictions
from paperforge.gap_agent import analyze_gaps_and_update_needs_input, get_project_status
from paperforge.planner import generate_paper_plan
from paperforge.asset_generator import generate_assets
from paperforge.latex_generator import generate_and_compile_paper
from paperforge.reviewer import perform_peer_review
from paperforge.revision_engine import show_target_content, propose_edit, apply_edit, get_git_history, revert_git_commit

app = typer.Typer(name="paperforge", help="Local-first CLI research manuscript generator")
console = Console()

@app.command()
def init(project_dir: str = typer.Argument(".", help="Target project directory")):
    """Initializes a new PaperForge research repository structure."""
    target_path = os.path.abspath(project_dir)
    os.makedirs(target_path, exist_ok=True)

    sources_dir = os.path.join(target_path, "sources")
    dot_paperforge_dir = os.path.join(target_path, ".paperforge")
    assets_dir = os.path.join(target_path, "assets")

    os.makedirs(sources_dir, exist_ok=True)
    os.makedirs(dot_paperforge_dir, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)

    source_template = os.path.join(os.path.dirname(__file__), "..", "assets", "ieee_conference_template.tex")
    target_template = os.path.join(assets_dir, "ieee_conference_template.tex")
    if os.path.exists(source_template):
        shutil.copy(source_template, target_template)

    config_file = os.path.join(target_path, "config.yaml")
    if not os.path.exists(config_file):
        with open(config_file, "w", encoding="utf-8") as f:
            f.write("""llm:
  provider: ollama
  host: http://localhost:11434
  model: llama3.2

embeddings:
  provider: local
  model: BAAI/bge-small-en-v1.5

paths:
  sources_dir: sources
  paper_dir: paper
  assets_dir: assets
  db_path: .paperforge/paperforge.db
""")

    env_example = os.path.join(target_path, ".env.example")
    if not os.path.exists(env_example):
        with open(env_example, "w", encoding="utf-8") as f:
            f.write("""# PaperForge Environment Variables
OLLAMA_HOST=http://localhost:11434
GEMINI_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
""")

    readme_file = os.path.join(target_path, "README.md")
    if not os.path.exists(readme_file):
        with open(readme_file, "w", encoding="utf-8") as f:
            f.write("""# PaperForge Project

PaperForge is a local-first, CLI-only, agentic research-repository tool that ingests raw research files and produces a self-contained, Overleaf-ready IEEE conference LaTeX manuscript.

## Run This Free and Local (Default)
1. Install and start Ollama locally (`ollama pull llama3.2`).
2. Ensure `config.yaml` is set to `llm.provider: ollama` and `embeddings.provider: local`.
3. Run `paperforge doctor` to verify system health.
4. Place your research papers, notes, CSVs, and code into `sources/`.

## Run With a Free-Tier Cloud API
1. Set an API key in `.env`: `export GEMINI_API_KEY="your-key"`.
2. Update `config.yaml` to `llm.provider: gemini`.
3. Run `paperforge doctor` to verify API connectivity.
""")

    db_path = os.path.join(dot_paperforge_dir, "paperforge.db")
    init_db(db_path)

    tracker_file = os.path.join(target_path, "TRACKER.md")
    log_tracker(
        command="paperforge init",
        summary="Initialized project repository layout",
        reasoning=f"Created sources/, .paperforge/, assets/, config.yaml, .env.example, README.md at {target_path}",
        tracker_file=tracker_file,
        db_path=db_path
    )

    console.print(Panel(f"[bold green]PaperForge project initialized successfully at {target_path}[/bold green]"))


@app.command()
def doctor(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Checks configured LLM and Embedding provider health and prints status."""
    cfg = load_config(config_path)
    table = Table(title="PaperForge Health Check")
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Configured Provider", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Details")

    llm_p = get_llm_provider(cfg)
    llm_health = llm_p.check_health()
    table.add_row("LLM Provider", cfg.get("llm", {}).get("provider", "unknown"), "[green]OK[/green]" if llm_health["status"] else "[red]FAILED[/red]", llm_health["message"])

    emb_p = get_embedding_provider(cfg)
    emb_health = emb_p.check_health()
    table.add_row("Embedding Provider", cfg.get("embeddings", {}).get("provider", "unknown"), "[green]OK[/green]" if emb_health["status"] else "[red]FAILED[/red]", emb_health["message"])

    db_path = cfg.get("paths", {}).get("db_path", ".paperforge/paperforge.db")
    db_exists = os.path.exists(db_path)
    table.add_row("SQLite DB", db_path, "[green]OK[/green]" if db_exists else "[yellow]NOT INITIALIZED[/yellow]", "Database file present" if db_exists else "Run 'paperforge init' to initialize DB")

    console.print(table)


@app.command()
def scan(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Scans sources/ folder incrementally and indexes evidence."""
    cfg = load_config(config_path)
    res = scan_sources(cfg)
    console.print(Panel(
        f"[bold green]Scan Complete[/bold green]\n"
        f"New files: {len(res['new_files'])}\n"
        f"Updated files: {len(res['updated_files'])}\n"
        f"Unchanged files: {len(res['unchanged_files'])}\n"
        f"Items marked STALE: {res['stale_items_count']}"
    ))


@app.command()
def ask(question: str = typer.Argument(..., help="Question to ask repository evidence"), config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Asks a question grounded strictly in ingested sources/ evidence."""
    cfg = load_config(config_path)
    db_path = cfg.get("paths", {}).get("db_path", ".paperforge/paperforge.db")
    chroma_dir = ".paperforge/chroma_db"

    emb_provider = get_embedding_provider(cfg)
    hybrid_index = HybridIndex(chroma_dir=chroma_dir, embedding_provider=emb_provider)
    results = hybrid_index.search(question, top_k=5)

    if not results:
        session = get_session(db_path)
        fresh_evs = session.query(Evidence).filter(Evidence.status == StatusEnum.FRESH).limit(5).all()
        results = [
            {
                "id": str(ev.id),
                "content": ev.extracted_content,
                "meta": {"location_json": str(ev.location_json), "evidence_type": ev.evidence_type}
            }
            for ev in fresh_evs
        ]
        session.close()

    context_str = ""
    sources_table = Table(title="Grounded Provenance Citations")
    sources_table.add_column("Evidence ID", style="cyan")
    sources_table.add_column("Provenance Location", style="magenta")
    sources_table.add_column("Snippet Preview", style="white")

    for item in results:
        ev_id = item.get("id", "N/A")
        content = item.get("content", "")
        meta = item.get("meta", {})
        location = meta.get("location_json", "Unknown")
        context_str += f"[Evidence #{ev_id} | Provenance: {location}]\n{content}\n\n"
        sources_table.add_row(f"#{ev_id}", str(location), content[:80].replace("\n", " ") + "...")

    llm = get_llm_provider(cfg)
    system_prompt = "You are PaperForge Evidence QA Assistant. Answer based ONLY on provided context. Cite Evidence ID for claims."
    prompt = f"Question: {question}\n\nRetrieved Evidence:\n{context_str}"
    
    try:
        answer = llm.complete(prompt, system_prompt=system_prompt)
    except Exception:
        answer = f"[LLM direct response unavailable - local fallback grounded mode]\nQuestion: {question}\nTop Evidence:\n{context_str}"

    console.print(Panel(f"[bold blue]Answer:[/bold blue]\n{answer}"))
    console.print(sources_table)


@app.command()
def summarize(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Generates structured research summary of ingested repo entities (Phase 2)."""
    cfg = load_config(config_path)
    res = process_research_understanding(cfg)
    console.print(Panel(f"[bold green]Research Summary[/bold green]\n{res['summary']}"))


@app.command()
def claims(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Extracts candidate claims and verifies evidence links (Phase 3)."""
    cfg = load_config(config_path)
    res = extract_claims_and_contradictions(cfg)
    console.print(Panel(f"[bold green]Evidence Claims[/bold green]\nTotal Claims: {res['claims_count']}\nContradictions Detected: {res['contradictions_count']}"))


@app.command()
def contradictions(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Displays conflicting evidence records for user resolution (Phase 3)."""
    cfg = load_config(config_path)
    db_path = cfg.get("paths", {}).get("db_path", ".paperforge/paperforge.db")
    session = get_session(db_path)
    cons = session.query(Contradiction).all()
    session.close()

    table = Table(title="Contradictions Detected")
    table.add_column("ID", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Status", style="magenta")
    for c in cons:
        table.add_row(str(c.id), c.description, c.resolution_status)
    console.print(table)


@app.command()
def resume(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Rescans sources/ and updates gap analysis (Phase 4)."""
    cfg = load_config(config_path)
    scan_sources(cfg)
    extract_claims_and_contradictions(cfg)
    gap_res = analyze_gaps_and_update_needs_input(cfg)
    console.print(Panel(f"[bold green]Resume Complete[/bold green]\nBlocking Gaps Remaining: {gap_res['blocking_gaps']}"))


@app.command()
def status(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Summarizes current stale items, blocking gaps, and project readiness (Phase 4)."""
    cfg = load_config(config_path)
    st = get_project_status(cfg)
    console.print(Panel(
        f"[bold blue]PaperForge Project Status[/bold blue]\n"
        f"Verified Claims: {st['verified_claims']}\n"
        f"Unverified Claims: {st['unverified_claims']}\n"
        f"Stale Items: {st['stale_items']}\n"
        f"Author Info Resolved: {st['authors_resolved']}\n"
        f"Blocking Gaps: {st['blocking_gaps']}\n"
        f"Ready For Paper Plan: {'[green]YES[/green]' if st['ready_for_plan'] else '[red]NO (Check NEEDS_INPUT.md)[/red]'}"
    ))


@app.command()
def plan(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Plans IEEE section structure, claim allocation, and assets (Phase 5)."""
    cfg = load_config(config_path)
    res = generate_paper_plan(cfg)
    console.print(Panel(f"[bold green]Paper Plan Generated[/bold green]\n{res['plan_summary']}"))


@app.command()
def assets(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Generates vector figures, TikZ diagrams, booktabs tables, and references.bib (Phase 6)."""
    cfg = load_config(config_path)
    res = generate_assets(cfg)
    console.print(Panel(f"[bold green]Assets Generated[/bold green]\nFigures: {res['figures']}\nTables: {res['tables']}\nBib: {res['bib']}"))


@app.command()
def build(apply_review: bool = typer.Option(False, "--apply-review", help="Automatically loop review fixes"), config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Forks IEEE template, assembles manuscript, verifies refs, compiles with Tectonic, and zips Overleaf bundle (Phase 7)."""
    cfg = load_config(config_path)
    generate_assets(cfg)
    res = generate_and_compile_paper(cfg)
    
    if apply_review:
        perform_peer_review(cfg)
        res = generate_and_compile_paper(cfg)

    console.print(Panel(
        f"[bold green]Build Successful — Overleaf-Ready Package Created[/bold green]\n"
        f"Zip Bundle: {res['zip_path']}\n"
        f"Compile Status: {'PASS' if res['compile_success'] else 'FAIL'}\n"
        f"Build Log: {res['build_log']}"
    ))


@app.command()
def review(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Executes skeptical IEEE peer reviewer pass and writes review_report.md (Phase 8)."""
    cfg = load_config(config_path)
    res = perform_peer_review(cfg)
    console.print(Panel(f"[bold green]Peer Review Complete[/bold green]\nVerdict: {res['verdict']}\nReport: {res['report_path']}"))


@app.command()
def show(target_ref: str = typer.Argument(..., help="Section or element reference"), config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Displays manuscript section with line numbers and markers (Phase 9)."""
    cfg = load_config(config_path)
    out = show_target_content(target_ref, cfg)
    console.print(out)


@app.command()
def edit(
    instruction: Optional[str] = typer.Argument(None, help="Edit instruction"),
    target: str = typer.Option("introduction", help="Target section or element"),
    apply: Optional[int] = typer.Option(None, "--apply", help="Apply proposed edit ID"),
    allow_unsupported: bool = typer.Option(False, "--allow-unsupported", help="Force allow unsupported claims"),
    config_path: str = typer.Option("config.yaml", help="Path to config.yaml")
):
    """Proposes or applies interactive revisions to the manuscript (Phase 9)."""
    cfg = load_config(config_path)
    if apply is not None:
        res = apply_edit(apply, cfg)
        console.print(Panel(f"[bold green]Edit #{apply} Applied[/bold green]\nGit Commit: {res.get('commit_hash')}"))
    else:
        res = propose_edit(instruction, target, cfg, allow_unsupported=allow_unsupported)
        if res["status"] == "BLOCKED":
            console.print(Panel(f"[bold red]Edit Blocked[/bold red]\n{res['reason']}"))
        else:
            console.print(Panel(f"[bold yellow]Proposed Edit #{res['edit_id']} Preview[/bold yellow]\n{res['diff']}\n\nRun 'paperforge edit --apply {res['edit_id']}' to commit."))


@app.command()
def history(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Displays git commit history inside paper/ directory (Phase 9)."""
    cfg = load_config(config_path)
    out = get_git_history(cfg)
    console.print(Panel(f"[bold blue]Git Commit History[/bold blue]\n{out}"))


@app.command()
def revert(commit: str = typer.Argument(..., help="Git commit hash to revert"), config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Reverts a git commit in paper/ (Phase 9)."""
    cfg = load_config(config_path)
    res = revert_git_commit(commit, cfg)
    console.print(Panel(f"[bold green]Reverted Commit {res['commit']}[/bold green]"))


if __name__ == "__main__":
    app()
