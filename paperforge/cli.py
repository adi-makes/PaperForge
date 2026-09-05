import os
import shutil
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, MofNCompleteColumn, TimeElapsedColumn

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
from paperforge.reset import reset_repository

app = typer.Typer(name="paperforge", help="Local-first CLI research manuscript generator")
console = Console()

@app.command()
def init(project_dir: str = typer.Argument(".", help="Target project directory")):
    """Initializes a new PaperForge research repository structure."""
    with console.status("[bold cyan]Initializing PaperForge project workspace...", spinner="dots"):
        target_path = os.path.abspath(project_dir)
        os.makedirs(target_path, exist_ok=True)

        sources_dir = os.path.join(target_path, "sources")
        dot_paperforge_dir = os.path.join(target_path, ".paperforge")
        assets_dir = os.path.join(target_path, "assets")

        os.makedirs(sources_dir, exist_ok=True)
        os.makedirs(dot_paperforge_dir, exist_ok=True)
        os.makedirs(assets_dir, exist_ok=True)

        source_template = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "ieee_conference_template.tex"))
        target_template = os.path.abspath(os.path.join(assets_dir, "ieee_conference_template.tex"))
        if os.path.exists(source_template) and source_template != target_template:
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
    with console.status("[bold cyan]Running PaperForge health checks...", spinner="dots") as status:
        cfg = load_config(config_path)

        status.update(f"[bold cyan][1/3] Checking LLM provider ({cfg.get('llm', {}).get('provider', 'unknown')})...[/bold cyan]")
        llm_p = get_llm_provider(cfg)
        llm_health = llm_p.check_health()

        status.update(f"[bold cyan][2/3] Checking Embedding provider ({cfg.get('embeddings', {}).get('provider', 'unknown')})...[/bold cyan]")
        emb_p = get_embedding_provider(cfg)
        emb_health = emb_p.check_health()

        status.update("[bold cyan][3/3] Checking SQLite database file...[/bold cyan]")
        db_path = cfg.get("paths", {}).get("db_path", ".paperforge/paperforge.db")
        db_exists = os.path.exists(db_path)

    table = Table(title="PaperForge Health Check")
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Configured Provider", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Details")

    table.add_row("LLM Provider", cfg.get("llm", {}).get("provider", "unknown"), "[green]OK[/green]" if llm_health["status"] else "[red]FAILED[/red]", llm_health["message"])
    table.add_row("Embedding Provider", cfg.get("embeddings", {}).get("provider", "unknown"), "[green]OK[/green]" if emb_health["status"] else "[red]FAILED[/red]", emb_health["message"])
    table.add_row("SQLite DB", db_path, "[green]OK[/green]" if db_exists else "[yellow]NOT INITIALIZED[/yellow]", "Database file present" if db_exists else "Run 'paperforge init' to initialize DB")

    console.print(table)


@app.command()
def scan(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Scans sources/ folder incrementally and indexes evidence."""
    cfg = load_config(config_path)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}[/bold cyan]"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task_id = progress.add_task("Initializing scan...", total=1)

        def on_progress(current: int, total: int, file_path: str, message: str):
            if total > 0:
                progress.update(task_id, total=total, completed=current, description=f"[bold cyan]Scanning sources[/bold cyan] [yellow]{message}[/yellow]")
            else:
                progress.update(task_id, description=f"[bold cyan]{message}[/bold cyan]")

        res = scan_sources(cfg, progress_callback=on_progress)

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

    with console.status("[bold cyan][1/3] Loading embedding model & hybrid index...", spinner="dots") as status:
        emb_provider = get_embedding_provider(cfg)
        hybrid_index = HybridIndex(chroma_dir=chroma_dir, embedding_provider=emb_provider)
        
        status.update("[bold cyan][2/3] Searching hybrid vector & keyword index for evidence...", spinner="dots")
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

        status.update("[bold cyan][3/3] Querying LLM provider for evidence-grounded response...", spinner="dots")
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
    with console.status("[bold cyan]Processing research understanding (Phase 2)...", spinner="dots") as status:
        status.update("[bold cyan][1/2] Loading ingested evidence & database entities...[/bold cyan]")
        status.update("[bold cyan][2/2] Synthesizing research summary with LLM...[/bold cyan]")
        res = process_research_understanding(cfg)
    console.print(Panel(f"[bold green]Research Summary[/bold green]\n{res['summary']}"))


@app.command()
def claims(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Extracts candidate claims and verifies evidence links (Phase 3)."""
    cfg = load_config(config_path)
    with console.status("[bold cyan]Extracting candidate claims and verifying evidence links (Phase 3)...", spinner="dots") as status:
        status.update("[bold cyan][1/3] Loading fresh evidence records...[/bold cyan]")
        status.update("[bold cyan][2/3] Extracting candidate claims with LLM...[/bold cyan]")
        status.update("[bold cyan][3/3] Detecting evidence contradictions across claims...[/bold cyan]")
        res = extract_claims_and_contradictions(cfg)
    console.print(Panel(f"[bold green]Evidence Claims[/bold green]\nTotal Claims: {res['claims_count']}\nContradictions Detected: {res['contradictions_count']}"))


@app.command()
def contradictions(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Displays conflicting evidence records for user resolution (Phase 3)."""
    cfg = load_config(config_path)
    with console.status("[bold cyan]Querying detected contradictions from database...", spinner="dots"):
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

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}[/bold cyan]"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task_id = progress.add_task("[1/3] Rescanning sources/ folder...", total=3, completed=0)

        def on_scan_progress(current: int, total: int, file_path: str, message: str):
            if total > 0:
                progress.update(task_id, description=f"[bold cyan][1/3] Rescanning sources[/bold cyan] [yellow]{message}[/yellow]")

        scan_sources(cfg, progress_callback=on_scan_progress)
        progress.update(task_id, completed=1, description="[bold cyan][2/3] Extracting candidate claims & checking contradictions...[/bold cyan]")
        
        extract_claims_and_contradictions(cfg)
        progress.update(task_id, completed=2, description="[bold cyan][3/3] Running gap analysis & updating NEEDS_INPUT.md...[/bold cyan]")
        
        gap_res = analyze_gaps_and_update_needs_input(cfg)
        progress.update(task_id, completed=3, description="[bold green]Resume step execution completed.[/bold green]")

    console.print(Panel(f"[bold green]Resume Complete[/bold green]\nBlocking Gaps Remaining: {gap_res['blocking_gaps']}"))


@app.command()
def status(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Summarizes current stale items, blocking gaps, and project readiness (Phase 4)."""
    cfg = load_config(config_path)
    with console.status("[bold cyan]Gathering project status & gap metrics...", spinner="dots"):
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
    with console.status("[bold cyan]Generating paper plan (Phase 5)...", spinner="dots") as status:
        status.update("[bold cyan][1/3] Analyzing verified claims & evidence records...[/bold cyan]")
        status.update("[bold cyan][2/3] Generating IEEE section allocation with LLM...[/bold cyan]")
        res = generate_paper_plan(cfg)
        status.update("[bold cyan][3/3] Writing PAPER_PLAN.md...[/bold cyan]")
    console.print(Panel(f"[bold green]Paper Plan Generated[/bold green]\n{res['plan_summary']}"))


@app.command()
def assets(config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Generates vector figures, TikZ diagrams, booktabs tables, and references.bib (Phase 6)."""
    cfg = load_config(config_path)
    with console.status("[bold cyan]Generating manuscript assets (Phase 6)...", spinner="dots") as status:
        status.update("[bold cyan][1/3] Generating vector figures & TikZ diagrams...[/bold cyan]")
        status.update("[bold cyan][2/3] Generating booktabs tables...[/bold cyan]")
        status.update("[bold cyan][3/3] Assembling BibTeX references (references.bib)...[/bold cyan]")
        res = generate_assets(cfg)
    console.print(Panel(f"[bold green]Assets Generated[/bold green]\nFigures: {res['figures']}\nTables: {res['tables']}\nBib: {res['bib']}"))


@app.command()
def build(apply_review: bool = typer.Option(False, "--apply-review", help="Automatically loop review fixes"), config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Forks IEEE template, assembles manuscript, verifies refs, compiles with Tectonic, and zips Overleaf bundle (Phase 7)."""
    cfg = load_config(config_path)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}[/bold cyan]"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        total_steps = 5 if apply_review else 4
        task_id = progress.add_task("[1/4] Generating manuscript assets...", total=total_steps, completed=0)

        progress.update(task_id, completed=0, description="[bold cyan][1/4] Generating figures, tables & references.bib...[/bold cyan]")
        generate_assets(cfg)

        progress.update(task_id, completed=1, description="[bold cyan][2/4] Assembling LaTeX sections & verifying references...[/bold cyan]")
        res = generate_and_compile_paper(cfg)

        progress.update(task_id, completed=2, description="[bold cyan][3/4] Compiling LaTeX manuscript with Tectonic/pdflatex...[/bold cyan]")

        if apply_review:
            progress.update(task_id, completed=3, description="[bold cyan][4/5] Performing IEEE peer review pass & applying fixes...[/bold cyan]")
            perform_peer_review(cfg)
            res = generate_and_compile_paper(cfg)
            progress.update(task_id, completed=4, description="[bold cyan][5/5] Packaging Overleaf-ready ZIP bundle...[/bold cyan]")
        else:
            progress.update(task_id, completed=3, description="[bold cyan][4/4] Packaging Overleaf-ready ZIP bundle...[/bold cyan]")

        progress.update(task_id, completed=total_steps, description="[bold green]Build execution complete.[/bold green]")

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
    with console.status("[bold cyan]Executing peer review pass (Phase 8)...", spinner="dots") as status:
        status.update("[bold cyan][1/3] Preparing manuscript sections & evidence claims...[/bold cyan]")
        status.update("[bold cyan][2/3] Running skeptical IEEE peer reviewer pass with LLM...[/bold cyan]")
        res = perform_peer_review(cfg)
        status.update("[bold cyan][3/3] Writing REVIEW_REPORT.md...[/bold cyan]")
    console.print(Panel(f"[bold green]Peer Review Complete[/bold green]\nVerdict: {res['verdict']}\nReport: {res['report_path']}"))


@app.command()
def show(target_ref: str = typer.Argument(..., help="Section or element reference"), config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Displays manuscript section with line numbers and markers (Phase 9)."""
    cfg = load_config(config_path)
    with console.status("[bold cyan]Fetching manuscript content...", spinner="dots"):
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
    with console.status("[bold cyan]Processing revision (Phase 9)...", spinner="dots"):
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
    with console.status("[bold cyan]Fetching paper/ git history...", spinner="dots"):
        out = get_git_history(cfg)
    console.print(Panel(f"[bold blue]Git Commit History[/bold blue]\n{out}"))


@app.command()
def revert(commit: str = typer.Argument(..., help="Git commit hash to revert"), config_path: str = typer.Option("config.yaml", help="Path to config.yaml")):
    """Reverts a git commit in paper/ (Phase 9)."""
    cfg = load_config(config_path)
    with console.status(f"[bold cyan]Reverting commit {commit}...", spinner="dots"):
        res = revert_git_commit(commit, cfg)
    console.print(Panel(f"[bold green]Reverted Commit {res['commit']}[/bold green]"))


@app.command()
def reset(
    force: bool = typer.Option(False, "--force", "-f", help="Bypass confirmation prompt"),
    keep_sources: bool = typer.Option(False, "--keep-sources", help="Preserve files inside sources/ directory"),
    config_path: str = typer.Option("config.yaml", help="Path to config.yaml")
):
    """Resets the PaperForge workspace (removes database, vector indexes, generated paper, assets, reports, and source files)."""
    if not force:
        sources_msg = " (including all source files in sources/)" if not keep_sources else " (retaining sources/)"
        confirm = typer.confirm(f"Are you sure you want to reset the repository{sources_msg}? This action cannot be undone.")
        if not confirm:
            console.print("[yellow]Reset cancelled.[/yellow]")
            raise typer.Exit(0)

    cfg = load_config(config_path)
    with console.status("[bold cyan]Resetting PaperForge project workspace...", spinner="dots"):
        res = reset_repository(cfg, remove_sources=not keep_sources)

    cleaned_str = "\n".join(f"• {item}" for item in res["cleaned_items"])
    console.print(Panel(
        f"[bold green]PaperForge Workspace Reset Complete[/bold green]\n\n"
        f"Cleaned components:\n{cleaned_str}\n\n"
        f"Workspace re-initialized to a clean repository state."
    ))


if __name__ == "__main__":
    app()
