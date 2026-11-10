"""Skill Normalization Module.

Handles cleaning, standardizing, and mapping skill variations, abbreviations,
and aliases to canonical skill concepts while preserving distinct technologies.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set


# Standard technology & domain acronym / alias map
# Distinct technologies (e.g. PostgreSQL vs MySQL) MUST NOT be merged.
CANONICAL_ALIASES: Dict[str, str] = {
    # Programming & Tech
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "dl": "Deep Learning",
    "deep learning": "Deep Learning",
    "nlp": "Natural Language Processing",
    "natural language processing": "Natural Language Processing",
    "cv": "Computer Vision",
    "computer vision": "Computer Vision",
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "py": "Python",
    "python": "Python",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "docker": "Docker",
    "aws": "Amazon Web Services",
    "amazon web services": "Amazon Web Services",
    "gcp": "Google Cloud Platform",
    "google cloud": "Google Cloud Platform",
    "google cloud platform": "Google Cloud Platform",
    "azure": "Microsoft Azure",
    "microsoft azure": "Microsoft Azure",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    # Databases - preserved as distinct
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "sqlite": "SQLite",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "cassandra": "Apache Cassandra",
    "oracle db": "Oracle Database",
    "oracle database": "Oracle Database",
    "sql server": "Microsoft SQL Server",
    "mssql": "Microsoft SQL Server",
    "sql": "SQL",
    "nosql": "NoSQL",
    "rdbms": "RDBMS",
    # Frameworks & Libraries
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "angular": "Angular",
    "angularjs": "AngularJS",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "express": "Express.js",
    "expressjs": "Express.js",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "spring": "Spring Framework",
    "spring boot": "Spring Boot",
    "tf": "TensorFlow",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "torch": "PyTorch",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "scikit-learn": "scikit-learn",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "scipy": "SciPy",
    # BI / Analytics
    "bi": "Business Intelligence",
    "business intelligence": "Business Intelligence",
    "power bi": "Power BI",
    "powerbi": "Power BI",
    "tableau": "Tableau",
    "excel": "Microsoft Excel",
    "ms excel": "Microsoft Excel",
    "microsoft excel": "Microsoft Excel",
    "etl": "ETL",
    "data warehouse": "Data Warehousing",
    "data warehousing": "Data Warehousing",
    "big data": "Big Data",
    "spark": "Apache Spark",
    "apache spark": "Apache Spark",
    "hadoop": "Apache Hadoop",
    "apache hadoop": "Apache Hadoop",
    "kafka": "Apache Kafka",
    "apache kafka": "Apache Kafka",
    # Languages
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "golang": "Go",
    "go lang": "Go",
    "html": "HTML",
    "html5": "HTML5",
    "css": "CSS",
    "css3": "CSS3",
    "java": "Java",
}


def clean_skill_string(raw: Optional[str]) -> str:
    """Removes outer whitespace, unifies internal whitespace, preserves programming symbols (+, #, ., /)."""
    if not raw or not isinstance(raw, str):
        return ""
    # Strip bullet points and edge punctuation
    cleaned = raw.strip(" \t\r\n•·-*~,;:")
    # Replace multiple spaces with a single space
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_skill_name(raw: Optional[str], esco_canonical_map: Optional[Dict[str, str]] = None) -> str:
    """
    Normalizes a single skill string:
    1. Trims and cleans whitespace.
    2. Checks alias mapping (case-insensitive).
    3. Checks provided ESCO canonical mapping (if supplied).
    4. Applies title capitalization for unrecognized terms.
    """
    cleaned = clean_skill_string(raw)
    if not cleaned:
        return ""

    lookup_key = cleaned.lower()

    # 1. Alias dictionary
    if lookup_key in CANONICAL_ALIASES:
        return CANONICAL_ALIASES[lookup_key]

    # 2. ESCO canonical map if provided
    if esco_canonical_map and lookup_key in esco_canonical_map:
        return esco_canonical_map[lookup_key]

    # 3. Handle common tech preserve (C++, C#, .NET, etc.)
    if lookup_key in {"c++", "c#", ".net"}:
        return lookup_key.upper() if lookup_key != ".net" else ".NET"

    # Default: Title casing preserving internal casing if already capitalized nicely
    if any(c.isupper() for c in cleaned):
        return cleaned
    return cleaned.title()


def normalize_skill_list(
    skills: Iterable[Optional[str]],
    esco_canonical_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    Normalizes an iterable of skills:
    - Cleans whitespace and handles variations
    - Resolves known aliases
    - Deduplicates case-insensitively
    - Returns a sorted list of unique canonical skill names
    """
    if not skills:
        return []

    seen: Set[str] = set()
    normalized: List[str] = []

    for item in skills:
        norm = normalize_skill_name(item, esco_canonical_map=esco_canonical_map)
        if norm:
            key = norm.lower()
            if key not in seen:
                seen.add(key)
                normalized.append(norm)

    normalized.sort(key=str.casefold)
    return normalized
