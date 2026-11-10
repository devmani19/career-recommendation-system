"""Resume Processing Service.

Extracts text from supported documents (PDF, DOCX, TXT), parses resume sections
(Education, Experience, Projects, Certifications, Skills), and compiles a
structured candidate profile without logging sensitive personally identifiable data.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from pypdf import PdfReader
import spacy
from spacy.matcher import PhraseMatcher

from .skill_normalization import normalize_skill_list, normalize_skill_name


# Supported document extensions
SUPPORTED_RESUME_EXTENSIONS = {".txt", ".pdf", ".docx"}

# Initialize spaCy blank model for fast and deterministic text tokenization
NLP = spacy.blank("en")
if "sentencizer" not in NLP.pipe_names:
    NLP.add_pipe("sentencizer")


@dataclass
class CandidateProfile:
    """Structured candidate profile representation."""
    candidate_name: str = "Candidate"
    skills: List[str] = field(default_factory=list)
    education: str = ""
    experience_years: float = 0.0
    experience_summary: str = ""
    projects: List[str] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    raw_sections: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_name": self.candidate_name,
            "skills": self.skills,
            "education": self.education,
            "experience_years": self.experience_years,
            "experience_summary": self.experience_summary,
            "projects": self.projects,
            "certifications": self.certifications,
        }

    def get_summary_text(self) -> str:
        """Returns a consolidated text summary suitable for semantic embedding generation."""
        parts = []
        if self.skills:
            parts.append("Skills: " + ", ".join(self.skills))
        if self.education:
            parts.append("Education: " + self.education)
        if self.experience_summary:
            parts.append("Experience: " + self.experience_summary)
        if self.projects:
            parts.append("Projects: " + "; ".join(self.projects))
        if self.certifications:
            parts.append("Certifications: " + ", ".join(self.certifications))
        return " | ".join(parts) if parts else "Candidate Profile"


def extract_raw_text(file_source: Any, filename: Optional[str] = None) -> str:
    """
    Extracts text from a file-like object, bytes, or file path.
    Supports .pdf, .docx, and .txt.
    """
    if file_source is None:
        return ""

    # Resolve filename
    if filename is None:
        filename = getattr(file_source, "filename", "") or ""
    ext = os.path.splitext(filename.lower())[1] if filename else ""

    # Read binary bytes
    if hasattr(file_source, "read"):
        data = file_source.read()
        if hasattr(file_source, "seek"):
            file_source.seek(0)
    elif isinstance(file_source, (bytes, bytearray)):
        data = bytes(file_source)
    elif isinstance(file_source, (str, Path)) and os.path.exists(str(file_source)):
        with open(file_source, "rb") as f:
            data = f.read()
        if not ext:
            ext = os.path.splitext(str(file_source).lower())[1]
    elif isinstance(file_source, str):
        # Already extracted text passed directly
        return file_source
    else:
        return ""

    if not data:
        return ""

    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for page in reader.pages:
                text = page.extract_text() or ""
                pages.append(text)
            return "\n".join(pages).strip()
        except Exception:
            return ""

    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                content = archive.read("word/document.xml")
            text = content.decode("utf-8", errors="ignore")
            cleaned = re.sub(r"<.*?>", " ", text)
            return re.sub(r"\s+", " ", cleaned).strip()
        except Exception:
            return ""

    if ext == ".txt" or not ext:
        try:
            return data.decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""

    return ""


def parse_resume_sections(text: str) -> Dict[str, str]:
    """
    Splits resume text into recognized standard sections.
    """
    if not text:
        return {"education": "", "experience": "", "projects": "", "skills": "", "certifications": ""}

    section_aliases = {
        "education": {"education", "academic background", "academics", "qualifications", "academic qualifications"},
        "experience": {"experience", "work experience", "professional experience", "employment history", "work history"},
        "projects": {"projects", "personal projects", "academic projects", "key projects", "project experience"},
        "skills": {"skills", "technical skills", "core competencies", "competencies", "tools and technologies"},
        "certifications": {"certifications", "certificates", "licenses", "courses", "professional credentials"},
    }
    stop_headings = {
        "summary", "professional summary", "career objective", "objective",
        "awards", "publications", "interests", "hobbies", "references", "contact",
    }
    heading_lookup = {
        alias: sec
        for sec, aliases in section_aliases.items()
        for alias in aliases
    }

    collected: Dict[str, List[str]] = {sec: [] for sec in section_aliases}
    active_section: Optional[str] = None

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" \t-:|•*")
        if not line:
            continue
        cleaned_line = re.sub(r"[^a-z ]", "", line.lower()).strip()
        if cleaned_line in heading_lookup:
            active_section = heading_lookup[cleaned_line]
            continue
        if cleaned_line in stop_headings:
            active_section = None
            continue
        if active_section:
            collected[active_section].append(line)

    return {sec: " ".join(lines).strip() for sec, lines in collected.items()}


def estimate_years_of_experience(experience_text: str) -> float:
    """
    Estimates total years of experience from experience section text.
    Looks for explicit statements like '3 years of experience' or year ranges (e.g. 2021-2024).
    """
    if not experience_text:
        return 0.0

    # Check for direct phrase like 'X years of experience'
    match = re.search(r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+experience", experience_text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    # Find 4-digit years between 1980 and 2030
    years = [int(y) for y in re.findall(r"\b(19[89]\d|20[0-2]\d)\b", experience_text)]
    if len(years) >= 2:
        span = max(years) - min(years)
        return min(max(float(span), 0.5), 40.0)

    # If non-empty experience is present but no dates, give a baseline conservative 1.0 year
    if len(experience_text.split()) > 15:
        return 1.0

    return 0.0


def extract_project_items(projects_text: str) -> List[str]:
    """Extracts distinct project titles/summaries from project section text."""
    if not projects_text:
        return []
    # Split by common delimiters (bullets, newlines, semicolons)
    items = [p.strip() for p in re.split(r"[;\n•*|]+", projects_text) if p.strip()]
    cleaned = []
    for item in items:
        if len(item) > 3 and not item.lower().startswith("project"):
            cleaned.append(item[:150])
        elif len(item) > 3:
            cleaned.append(item[:150])
    return cleaned[:10]


def extract_skills_from_corpus(
    text: str,
    known_skills_vocab: Optional[Set[str]] = None,
) -> List[str]:
    """
    Extracts skill occurrences from resume text.
    Uses PhraseMatcher with known skills vocabulary or falls back to standard tech terms.
    """
    if not text:
        return []

    found_skills: Set[str] = set()

    if known_skills_vocab:
        # Build PhraseMatcher for given skills vocabulary
        matcher = PhraseMatcher(NLP.vocab, attr="LOWER")
        # Add terms up to reasonable length
        patterns = [NLP.make_doc(skill) for skill in known_skills_vocab if skill and len(skill) > 1]
        matcher.add("SKILL_TERMS", patterns)
        doc = NLP(text)
        for _, start, end in matcher(doc):
            found_skills.add(doc[start:end].text)

    # Also detect semicolon/comma separated lists if skills section is structured
    lines = text.splitlines()
    for line in lines:
        if any(kw in line.lower() for kw in ["python", "sql", "java", "react", "c++", "aws", "docker"]):
            parts = re.split(r"[,;]+", line)
            for part in parts:
                cleaned = part.strip()
                if 2 <= len(cleaned) <= 40:
                    found_skills.add(cleaned)

    # Normalize skills
    return normalize_skill_list(found_skills)


def build_candidate_profile(
    resume_file_or_text: Any,
    filename: Optional[str] = None,
    candidate_name: str = "Candidate",
    extra_skills: Optional[str] = None,
    verified_certificates: Optional[List[Dict[str, Any]]] = None,
    esco_skills_vocab: Optional[Set[str]] = None,
) -> CandidateProfile:
    """
    End-to-end pipeline to parse resume input and produce a structured CandidateProfile.
    """
    raw_text = extract_raw_text(resume_file_or_text, filename=filename)
    sections = parse_resume_sections(raw_text)

    # Skill extraction from resume text
    extracted_skills = extract_skills_from_corpus(raw_text, known_skills_vocab=esco_skills_vocab)

    # Include extra manually specified skills
    if extra_skills:
        extra_list = [s.strip() for s in re.split(r"[,;\n]+", extra_skills) if s.strip()]
        extracted_skills = normalize_skill_list(extracted_skills + extra_list)

    # Estimate experience years
    exp_years = estimate_years_of_experience(sections.get("experience", ""))

    # Extract projects
    projects = extract_project_items(sections.get("projects", ""))

    # Extract certifications
    certs = []
    if sections.get("certifications"):
        certs.extend([c.strip() for c in re.split(r"[,;\n•]+", sections["certifications"]) if c.strip()])

    if verified_certificates:
        for cert in verified_certificates:
            c_name = cert.get("certificate_name") or cert.get("filename") or ""
            if c_name and c_name not in certs:
                certs.append(c_name)

    return CandidateProfile(
        candidate_name=candidate_name or "Candidate",
        skills=extracted_skills,
        education=sections.get("education", ""),
        experience_years=exp_years,
        experience_summary=sections.get("experience", ""),
        projects=projects,
        certifications=certs,
        raw_sections=sections,
    )
