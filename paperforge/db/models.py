import enum
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, Enum as SQLEnum, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class StatusEnum(str, enum.Enum):
    FRESH = "FRESH"
    STALE = "STALE"

class ClaimStatusEnum(str, enum.Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"

class ResolutionTierEnum(str, enum.Enum):
    A_AUTO_FOUND = "A_AUTO_FOUND"
    B_DERIVABLE = "B_DERIVABLE"
    C_GENERATABLE = "C_GENERATABLE"
    D_NEEDS_CLARIFICATION = "D_NEEDS_CLARIFICATION"
    E_NEEDS_NEW_EXPERIMENT = "E_NEEDS_NEW_EXPERIMENT"

class FigureGenMethodEnum(str, enum.Enum):
    matplotlib = "matplotlib"
    tikz = "tikz"
    vision_extracted = "vision_extracted"

class EditOperationEnum(str, enum.Enum):
    MODIFY = "MODIFY"
    ADD = "ADD"
    DELETE = "DELETE"
    REGENERATE = "REGENERATE"
    RESTRUCTURE = "RESTRUCTURE"

class EditStatusEnum(str, enum.Enum):
    PROPOSED = "PROPOSED"
    AMBIGUOUS = "AMBIGUOUS"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String(512), nullable=False, unique=True)
    file_type = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    status = Column(SQLEnum(StatusEnum), default=StatusEnum.FRESH)

    evidences = relationship("Evidence", back_populates="source", cascade="all, delete-orphan")


class Evidence(Base):
    __tablename__ = "evidences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    source_content_hash = Column(String(64), nullable=False)
    location_json = Column(JSON, nullable=False)  # e.g. {"file": "...", "page": 1, "lines": [10, 20]}
    extracted_content = Column(Text, nullable=False)
    embedding_id = Column(String(128), nullable=True)
    evidence_type = Column(String(64), nullable=False)  # text, table_cell, code_ast, figure_caption, etc.
    status = Column(SQLEnum(StatusEnum), default=StatusEnum.FRESH)

    source = relationship("Source", back_populates="evidences")


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    evidence_ids = Column(JSON, default=list)  # list of Evidence.id


class Model(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    code_evidence_ids = Column(JSON, default=list)


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=True)
    config_evidence_id = Column(Integer, ForeignKey("evidences.id"), nullable=True)
    result_evidence_ids = Column(JSON, default=list)


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=True)
    metric_name = Column(String(256), nullable=False)
    metric_value = Column(String(256), nullable=False)
    evidence_id = Column(Integer, ForeignKey("evidences.id"), nullable=True)


class LiteratureItem(Base):
    __tablename__ = "literature_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    authors = Column(Text, nullable=True)
    year = Column(Integer, nullable=True)
    doi = Column(String(256), nullable=True)
    semantic_scholar_id = Column(String(256), nullable=True)
    source_evidence_id = Column(Integer, ForeignKey("evidences.id"), nullable=True)


class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    status = Column(SQLEnum(ClaimStatusEnum), default=ClaimStatusEnum.UNSUPPORTED)
    staleness = Column(SQLEnum(StatusEnum), default=StatusEnum.FRESH)
    evidence_ids = Column(JSON, default=list)
    used_in_section = Column(String(128), nullable=True)


class Contradiction(Base):
    __tablename__ = "contradictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    description = Column(Text, nullable=False)
    conflicting_evidence_ids = Column(JSON, default=list)
    resolution_status = Column(String(64), default="UNRESOLVED")
    resolution_note = Column(Text, nullable=True)
    resolved_by_user_input = Column(Text, nullable=True)


class Figure(Base):
    __tablename__ = "figures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    figure_type = Column(String(128), nullable=False)
    source_evidence_ids = Column(JSON, default=list)
    generation_method = Column(SQLEnum(FigureGenMethodEnum), nullable=False)
    output_path = Column(String(512), nullable=True)
    status = Column(String(64), default="PENDING")
    staleness = Column(SQLEnum(StatusEnum), default=StatusEnum.FRESH)


class Table(Base):
    __tablename__ = "tables"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_type = Column(String(128), nullable=False)
    source_evidence_ids = Column(JSON, default=list)
    output_path = Column(String(512), nullable=True)
    status = Column(String(64), default="PENDING")
    staleness = Column(SQLEnum(StatusEnum), default=StatusEnum.FRESH)


class MissingEvidence(Base):
    __tablename__ = "missing_evidences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    description = Column(Text, nullable=False)
    resolution_tier = Column(SQLEnum(ResolutionTierEnum), nullable=False)
    blocking = Column(Boolean, default=True)
    suggested_action = Column(Text, nullable=False)


class AuthorInfo(Base):
    __tablename__ = "author_infos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    affiliation = Column(Text, nullable=True)
    department = Column(Text, nullable=True)
    city = Column(String(128), nullable=True)
    country = Column(String(128), nullable=True)
    email = Column(String(256), nullable=True)
    order_index = Column(Integer, default=1)
    resolved = Column(Boolean, default=False)


class EditRequest(Base):
    __tablename__ = "edit_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_instruction = Column(Text, nullable=False)
    target_ref = Column(String(256), nullable=True)
    operation = Column(SQLEnum(EditOperationEnum), nullable=False)
    resolved_target_type = Column(String(64), nullable=True)
    proposed_diff = Column(Text, nullable=True)
    status = Column(SQLEnum(EditStatusEnum), default=EditStatusEnum.PROPOSED)
    new_or_changed_claim_ids = Column(JSON, default=list)
    compile_status = Column(String(64), nullable=True)
    git_commit_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TrackerEntry(Base):
    __tablename__ = "tracker_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    command = Column(String(256), nullable=False)
    summary = Column(Text, nullable=False)
    reasoning = Column(Text, nullable=True)
    user_input = Column(Text, nullable=True)
    needs_input_ref = Column(String(256), nullable=True)
