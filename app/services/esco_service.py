"""ESCO Career Knowledge Base Service.

Loads, validates, and provides access to European Skills, Competences,
Qualifications and Occupations (ESCO) data stored in data/esco_careers.json.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .skill_normalization import normalize_skill_name


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_ESCO_PATH = BASE_DIR / "data" / "esco_careers.json"
DEFAULT_METADATA_PATH = BASE_DIR / "data" / "esco_dataset_metadata.json"


@dataclass
class OccupationRecord:
    """Internal structured representation of an ESCO occupation profile."""
    occupation_id: str  # ESCO URI
    title: str  # Preferred label / occupation title
    description: str
    essential_skills: List[str] = field(default_factory=list)
    optional_skills: List[str] = field(default_factory=list)
    all_skills: List[str] = field(default_factory=list)
    essential_skill_relations: List[Dict[str, str]] = field(default_factory=list)
    optional_skill_relations: List[Dict[str, str]] = field(default_factory=list)
    alternative_labels: List[str] = field(default_factory=list)
    esco_version: str = "v1.2.0"
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def skill_count(self) -> int:
        return len(self.all_skills)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "occupation_id": self.occupation_id,
            "title": self.title,
            "description": self.description,
            "essential_skills": self.essential_skills,
            "optional_skills": self.optional_skills,
            "all_skills": self.all_skills,
            "alternative_labels": self.alternative_labels,
            "esco_version": self.esco_version,
        }


class ESCOService:
    """
    Singleton-capable service for loading and querying the ESCO dataset.
    Validates the presence of required fields and provides fast in-memory queries.
    """

    def __init__(self, dataset_path: Optional[str | Path] = None):
        env_path = os.getenv("ESCO_DATASET_PATH")
        if dataset_path:
            self.dataset_path = Path(dataset_path)
        elif env_path:
            self.dataset_path = Path(env_path)
        else:
            self.dataset_path = DEFAULT_ESCO_PATH

        self._occupations: Dict[str, OccupationRecord] = {}
        self._uri_index: Dict[str, OccupationRecord] = {}
        self._skill_concepts: Dict[str, str] = {}  # normalized skill label -> uri
        self._metadata: Dict[str, Any] = {}
        self._is_loaded: bool = False

    def load_dataset(self, reload: bool = False) -> None:
        """Loads and validates the ESCO dataset."""
        if self._is_loaded and not reload:
            return

        if not self.dataset_path.exists():
            raise FileNotFoundError(
                f"ESCO dataset file not found at: '{self.dataset_path}'. "
                "Expected JSON file containing ESCO occupations mapped by title, "
                "with fields: esco_uri, description, essential_skills, optional_skills."
            )

        try:
            with open(self.dataset_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"ESCO dataset at '{self.dataset_path}' is not valid JSON: {exc}"
            ) from exc

        if not isinstance(raw_data, dict) or len(raw_data) == 0:
            raise ValueError(
                f"ESCO dataset at '{self.dataset_path}' is empty or invalid format. "
                "Expected non-empty JSON dictionary of occupation profiles."
            )

        occupations: Dict[str, OccupationRecord] = {}
        uri_index: Dict[str, OccupationRecord] = {}
        skill_concepts: Dict[str, str] = {}

        for key, entry in raw_data.items():
            if not isinstance(entry, dict):
                continue

            # Validate minimum required fields
            uri = entry.get("esco_uri") or f"urn:esco:occupation:{key.replace(' ', '_')}"
            title = entry.get("esco_label") or key
            description = entry.get("description", "").strip()

            essential_skills = entry.get("essential_skills", [])
            optional_skills = entry.get("optional_skills", [])
            all_skills = entry.get("skills", essential_skills + optional_skills)
            essential_relations = entry.get("essential_skill_relations", [])
            optional_relations = entry.get("optional_skill_relations", [])

            # Index skill URIs
            for rel in essential_relations + optional_relations:
                if isinstance(rel, dict) and rel.get("label") and rel.get("uri"):
                    lbl_norm = normalize_skill_name(rel["label"]).lower()
                    skill_concepts[lbl_norm] = rel["uri"]

            alt_labels = []
            if entry.get("esco_search_term") and entry["esco_search_term"] != title:
                alt_labels.append(entry["esco_search_term"])

            record = OccupationRecord(
                occupation_id=uri,
                title=title,
                description=description,
                essential_skills=essential_skills,
                optional_skills=optional_skills,
                all_skills=sorted(set(all_skills), key=str.casefold),
                essential_skill_relations=essential_relations,
                optional_skill_relations=optional_relations,
                alternative_labels=alt_labels,
                esco_version=entry.get("esco_version", "v1.2.0"),
                raw_data=entry,
            )

            # Key by lowercase title and standard key
            occupations[title.lower()] = record
            if key.lower() not in occupations:
                occupations[key.lower()] = record
            uri_index[uri] = record

        if not occupations:
            raise ValueError(
                f"No valid occupations could be loaded from ESCO dataset at '{self.dataset_path}'."
            )

        self._occupations = occupations
        self._uri_index = uri_index
        self._skill_concepts = skill_concepts
        self._is_loaded = True

        # Try loading metadata
        if DEFAULT_METADATA_PATH.exists():
            try:
                with open(DEFAULT_METADATA_PATH, "r", encoding="utf-8") as mf:
                    self._metadata = json.load(mf)
            except Exception:
                self._metadata = {}

    def get_occupations(self) -> Dict[str, OccupationRecord]:
        """Returns all loaded unique occupation records mapped by title."""
        if not self._is_loaded:
            self.load_dataset()
        # Return unique records by URI to avoid duplicate alias keys
        return {record.title: record for record in self._uri_index.values()}

    def get_occupation_by_id(self, occupation_id: str) -> Optional[OccupationRecord]:
        if not self._is_loaded:
            self.load_dataset()
        return self._uri_index.get(occupation_id)

    def get_occupation_by_title(self, title: str) -> Optional[OccupationRecord]:
        if not self._is_loaded:
            self.load_dataset()
        return self._occupations.get(title.lower().strip())

    def get_skill_concept_uri(self, skill_label: str) -> Optional[str]:
        if not self._is_loaded:
            self.load_dataset()
        return self._skill_concepts.get(skill_label.lower().strip())

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._metadata


# Global cached singleton instance
_GLOBAL_ESCO_SERVICE: Optional[ESCOService] = None


def get_esco_service() -> ESCOService:
    global _GLOBAL_ESCO_SERVICE
    if _GLOBAL_ESCO_SERVICE is None:
        _GLOBAL_ESCO_SERVICE = ESCOService()
        _GLOBAL_ESCO_SERVICE.load_dataset()
    return _GLOBAL_ESCO_SERVICE
