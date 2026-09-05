# PaperForge: Architectural Design & Implementation Plan

PaperForge is a local-first, CLI-only, agentic research-repository tool designed to ingest raw research artifacts from a `sources/` directory and compile an Overleaf-ready IEEE conference LaTeX manuscript grounded entirely in traceable evidence.

## Key Design Principles & Requirements
1. **Zero Evidence Hallucination**: All quantitative and novelty claims link to a `VERIFIED` Claim with concrete provenance (file, page, line, row).
2. **Missing Evidence & Author Resolution**: Insufficient evidence or missing author information creates blocking gaps in `NEEDS_INPUT.md`.
3. **Static Parsing Only**: Source code in `sources/` is parsed statically via AST/parsers — NEVER executed.
4. **Real Citations**: Bibliography entries are retrieved via Semantic Scholar or CrossRef APIs.
5. **Overleaf & Tectonic Ready**: Output is a clean, single `paper/` directory compiled with Tectonic (zero unresolved references/citations). Clean fork of `assets/ieee_conference_template.tex` with placeholder prose removed.
6. **Incremental Rescan & Staleness Tracking**: File content hashes track updates. Upstream modifications mark dependent claims, figures, tables, and sections `STALE`.
7. **Auditability (TRACKER.md)**: Every state-changing command appends structured entries to `TRACKER.md`.
8. **Pluggable & Zero-Cost Default**: Ollama / local SentenceTransformers by default, with cloud adapters (Gemini, Groq, OpenRouter, Anthropic, OpenAI).
9. **Interactive Revisions & Diffing**: Phase 9 edits follow strict claim-evidence checks and git-backed version control inside `paper/`.

---

## Proposed System Architecture & Components

```
paperforge/
├── pyproject.toml
├── README.md
├── .env.example
├── config.yaml
├── paperforge/
│   ├── __init__.py
│   ├── cli.py               # Typer CLI commands
│   ├── config.py            # Pydantic configuration loader
│   ├── db/
│   │   ├── models.py        # SQLAlchemy data models (15 core models)
│   │   └── session.py       # SQLite database session & engine management
│   ├── providers/
│   │   ├── llm.py           # LLMProvider interface & Ollama/Gemini/Groq/etc. adapters
│   │   └── embedding.py     # EmbeddingProvider interface & LocalSentenceTransformer adapter
│   ├── tracker.py           # Structured TRACKER.md logger
│   ├── parsers/             # Multimodal parsers (PDF, DOCX, CSV/XLSX, MD, HTML, SVG, AST, OCR)
│   ├── index/               # Hybrid Search (Chroma vector DB + BM25 keyword search + RRF)
│   ├── engine/              # Claim & Contradiction verification engine
│   ├── planner/             # IEEE Paper Planner & Outline agent
│   ├── generator/           # Asset (Matplotlib/TikZ/BibTeX) & LaTeX template fork engine
│   ├── audit/               # Skeptical Reviewer agent
│   └── revision/            # Phase 9 Git-backed diff & edit engine
└── assets/
    └── ieee_conference_template.tex
```

---

## Data Model Schema (SQLAlchemy)

1. `Source`: id, path, file_type, content_hash, ingested_at, status
2. `Evidence`: id, source_id (FK), source_content_hash, location_json, extracted_content, embedding_id, evidence_type, status [FRESH, STALE]
3. `Dataset`: id, name, description, evidence_ids (JSON)
4. `Experiment`: id, name, dataset_id (FK), model_id (FK), config_evidence_id, result_evidence_ids (JSON)
5. `Model`: id, name, description, code_evidence_ids (JSON)
6. `Result`: id, experiment_id (FK), metric_name, metric_value, evidence_id (FK)
7. `LiteratureItem`: id, title, authors, year, doi, semantic_scholar_id, source_evidence_id (FK)
8. `Claim`: id, text, status [VERIFIED, PARTIAL, UNSUPPORTED], staleness [FRESH, STALE], evidence_ids (JSON), used_in_section
9. `Contradiction`: id, description, conflicting_evidence_ids (JSON), resolution_status, resolution_note, resolved_by_user_input
10. `Figure`: id, figure_type, source_evidence_ids (JSON), generation_method [matplotlib, tikz, vision_extracted], output_path, status, staleness
11. `Table`: id, table_type, source_evidence_ids (JSON), output_path, status, staleness
12. `MissingEvidence`: id, description, resolution_tier [A_AUTO_FOUND, B_DERIVABLE, C_GENERATABLE, D_NEEDS_CLARIFICATION, E_NEEDS_NEW_EXPERIMENT], blocking, suggested_action
13. `AuthorInfo`: id, name, affiliation, department, city, country, email, order_index, resolved (bool)
14. `EditRequest`: id, raw_instruction, target_ref, operation [MODIFY, ADD, DELETE, REGENERATE, RESTRUCTURE], resolved_target_type, proposed_diff, status [PROPOSED, AMBIGUOUS, APPLIED, REJECTED, ROLLED_BACK], new_or_changed_claim_ids (JSON), compile_status, git_commit_hash, created_at
15. `TrackerEntry`: id, timestamp, command, summary, reasoning, user_input, needs_input_ref

---

## Phased Implementation Roadmap

### Phase 0: Project Bootstrap & Provider Config
- Setup CLI foundation (`paperforge init`, `paperforge doctor`).
- Project layout creation: `sources/`, `.paperforge/`, `config.yaml`, `.env.example`, `assets/ieee_conference_template.tex`, `TRACKER.md`, `README.md`.
- Implement `LLMProvider` (Ollama, Gemini, Groq, OpenRouter, Anthropic, OpenAI) and `EmbeddingProvider` (Local SentenceTransformer / HuggingFace `bge-small-en-v1.5`).
- SQLite DB initial migration.

### Phase 1: Repository Intelligence (`sources/`)
- Implement file hash scanner in `sources/`.
- Concrete parsers: PDF (PyMuPDF/pdfplumber), DOCX, Markdown, HTML, SVG (lxml/cairosvg), CSV/XLSX (pandas/openpyxl), Code (Python `ast`), OCR (pytesseract).
- Hybrid search engine: Chroma DB + `rank_bm25` + Reciprocal Rank Fusion (RRF).
- `paperforge scan` & `paperforge ask "<question>"`.
- Incremental rescanning & downstream staleness propagation.

### Phase 2: Research Understanding
- Structured extraction pipeline populating `Dataset`, `Experiment`, `Model`, `Result`, `LiteratureItem`, and `AuthorInfo`.
- `paperforge summarize` output.

### Phase 3: Evidence Engine
- Candidate Claim extraction & grounding against Evidence (`VERIFIED`, `PARTIAL`, `UNSUPPORTED`).
- Contradiction detector and resolution workflow.
- `paperforge claims` & `paperforge contradictions`.

### Phase 4: Gap Agent (Human-in-the-loop via `sources/`)
- Gap taxonomy classification (Tiers A–E).
- `NEEDS_INPUT.md` generator.
- `paperforge resume` & `paperforge status`.

### Phase 5: Paper Planner
- Section planner & IEEE structure mapper.
- `paperforge plan`.

### Phase 6: Asset Generator
- Matplotlib vector PDF generation with provenance annotations.
- TikZ generator from YAML spec for architecture diagrams.
- LaTeX booktabs table generator.
- BibTeX API fetcher (Semantic Scholar / CrossRef).
- `paperforge assets`.

### Phase 7: LaTeX Generator & Tectonic Compile Check
- Clean template fork of `assets/ieee_conference_template.tex` (removing all placeholder prose).
- Structure `paper/` folder (`main.tex`, `sections/*.tex`, `figures/`, `tables/`, `references.bib`, `build.log`).
- Tectonic compilation loop with automatic error diagnostics & auto-fix retry.
- Git initialization & `paper_<timestamp>.zip` creation.
- `paperforge build`.

### Phase 8: Reviewer / Claim-Audit Agent
- Skeptical IEEE peer reviewer pass.
- `paperforge review` & `paperforge build --apply-review`.

### Phase 9: Interactive Revision Layer
- `paperforge show <ref>` with line numbers & claim tags.
- `paperforge edit "<instruction>"` & `paperforge edit --batch <yaml>`.
- Unsupported claim check & `--allow-unsupported` override flag.
- Diff preview, git commit/revert (`paperforge history`, `paperforge diff`, `paperforge revert`).

---

## Verification Plan

### Automated & CLI Testing Strategy
1. Construct a comprehensive test project (`test_workspace/sources/`) containing:
   - Experimental result CSVs (`accuracy.csv`, `ablation.csv`).
   - Architecture document (`arch.md`).
   - Sample Python source code (`train.py`, `model.py`).
   - PDF research paper reference (`related_work.pdf` or synthetic).
2. Execute each CLI command step by step and assert expected terminal output and database state.
3. Validate Tectonic compilation for Phase 7 output.
4. Verify `TRACKER.md` entries are generated at every step.
