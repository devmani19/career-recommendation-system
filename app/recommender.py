import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path

from pypdf import PdfReader
import spacy
from spacy.matcher import PhraseMatcher

BASE_DIR = Path(__file__).resolve().parent.parent
CAREER_DATA_PATH = BASE_DIR / "data" / "esco_careers.json"
VERIFICATION_LOG_PATH = BASE_DIR / "data" / "verification_log.json"

with CAREER_DATA_PATH.open("r", encoding="utf-8") as file:
    CAREER_DATA = json.load(file)

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg"}
SKILL_ACTION_VERBS = {
    "analyse", "analyze", "apply", "build", "configure", "conduct", "create", "develop",
    "design", "execute", "identify", "implement", "install", "manage", "monitor", "operate",
    "perform", "plan", "prepare", "provide", "test", "use", "utilise", "utilize", "write",
}

CERTIFICATION_LIBRARY = {
    "python": "Python for Everybody",
    "sql": "SQL Fundamentals",
    "excel": "Microsoft Excel Specialist",
    "power bi": "Microsoft Power BI Data Analyst",
    "statistics": "Statistics for Data Analysis",
    "tableau": "Tableau Desktop Specialist",
    "machine learning": "Machine Learning Specialization",
    "tensorflow": "TensorFlow Developer Certificate",
    "aws": "AWS Certified Cloud Practitioner",
    "azure": "Microsoft Azure Fundamentals",
    "docker": "Docker Essentials",
    "kubernetes": "Certified Kubernetes Administrator",
    "linux": "Linux Essentials",
    "networking": "Cisco Networking Essentials",
    "security": "CompTIA Security+",
    "ethical hacking": "Certified Ethical Hacker (CEH)",
    "siem": "Splunk Core Certified User",
    "figma": "Figma Design Certification",
    "ux": "Google UX Design Certificate",
    "wireframing": "UX Wireframing Course",
    "communication": "Professional Communication Certificate",
    "leadership": "Leadership Essentials",
    "agile": "ICAgile Agile Certified Professional",
    "risk management": "Risk Management Certificate",
    "stakeholder management": "Stakeholder Management Program",
    "business analysis": "Business Analysis Foundations",
    "documentation": "Technical Documentation Certificate",
    "git": "GitHub Foundations",
    "apis": "API Design and Integration Certificate",
    "data structures": "Data Structures Certification",
    "algorithms": "Algorithms & Problem Solving Certificate",
    "devops": "Azure DevOps Certification",
    "java": "Oracle Java SE Certification",
    "pandas": "Pandas for Data Analysis",
    "model evaluation": "AI Model Evaluation Certificate",
    "visualization": "Data Visualization Fundamentals",
    "data cleaning": "Data Cleaning and Wrangling Certification",
    "requirements gathering": "Requirements Engineering Certificate",
}


def normalize_skill(skill: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", "", skill.lower())
    return " ".join(cleaned.split())


def skill_text_variants(skill: str):
    variants = {normalize_skill(skill)}
    without_parenthetical = re.sub(r"\s*\([^)]*\)", "", skill).strip()
    if without_parenthetical:
        variants.add(normalize_skill(without_parenthetical))

    normalized = normalize_skill(without_parenthetical)
    first_word, separator, remainder = normalized.partition(" ")
    if separator and first_word in SKILL_ACTION_VERBS and (
        len(remainder.split()) >= 2 or first_word in {"use", "utilise", "utilize"}
    ):
        variants.add(remainder)

    return {variant for variant in variants if variant}


NLP = spacy.blank("en")
NLP.add_pipe("sentencizer")
SKILL_ALIAS_LOOKUP = {}
for occupation in CAREER_DATA.values():
    for skill in occupation["skills"]:
        for variant in skill_text_variants(skill):
            SKILL_ALIAS_LOOKUP.setdefault(variant, set()).add(normalize_skill(skill))

SKILL_MATCHER = PhraseMatcher(NLP.vocab, attr="LOWER")
SKILL_MATCHER.add("ESCO_SKILL_PHRASES", [NLP.make_doc(alias) for alias in SKILL_ALIAS_LOOKUP])


def read_text_from_upload(file_storage) -> str:
    if file_storage is None:
        return ""

    filename = (file_storage.filename or "").lower()
    data = file_storage.read()
    file_storage.stream.seek(0)

    if not data:
        return ""

    ext = os.path.splitext(filename)[1]

    if ext == ".txt":
        return data.decode("utf-8", errors="ignore")

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n".join(pages)

    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                content = archive.read("word/document.xml")
            text = content.decode("utf-8", errors="ignore")
            cleaned = re.sub(r"<.*?>", " ", text)
            return re.sub(r"\s+", " ", cleaned)
        except Exception:
            return "DOCX document uploaded. Advanced text extraction was unavailable for this file."

    if ext == ".doc":
        return "Word document uploaded. Advanced parsing is not available in this demo version."

    if ext in {".png", ".jpg", ".jpeg"}:
        return "Certificate image uploaded. Text recognition not performed in this demo."

    return data.decode("utf-8", errors="ignore")


def extract_skills_from_text(text: str):
    document = NLP(text)
    skills = set()
    for _, start, end in SKILL_MATCHER(document):
        alias = normalize_skill(document[start:end].text)
        skills.update(SKILL_ALIAS_LOOKUP.get(alias, set()))

    return sorted(skills)


def extract_resume_sections(text: str):
    section_aliases = {
        "education": {"education", "academic background", "qualifications"},
        "experience": {"experience", "work experience", "professional experience", "employment history"},
        "projects": {"projects", "personal projects", "academic projects", "project experience"},
    }
    stop_headings = {
        "skills", "technical skills", "summary", "professional summary", "objective",
        "certifications", "awards", "publications", "interests", "references",
    }
    heading_lookup = {
        alias: section
        for section, aliases in section_aliases.items()
        for alias in aliases
    }
    collected = {section: [] for section in section_aliases}
    active_section = None

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" \t-:|•")
        if not line:
            continue
        heading = re.sub(r"[^a-z ]", "", line.lower()).strip()
        if heading in heading_lookup:
            active_section = heading_lookup[heading]
            continue
        if heading in stop_headings:
            active_section = None
            continue
        if active_section:
            collected[active_section].append(line)

    return {section: " ".join(lines)[:900] for section, lines in collected.items()}


def cosine_similarity(candidate_skills, role_skills):
    all_skills = sorted(set(candidate_skills) | set(role_skills))
    candidate_vector = [1 if skill in candidate_skills else 0 for skill in all_skills]
    role_vector = [1 if skill in role_skills else 0 for skill in all_skills]

    dot_product = sum(a * b for a, b in zip(candidate_vector, role_vector))
    candidate_norm = sum(value * value for value in candidate_vector) ** 0.5
    role_norm = sum(value * value for value in role_vector) ** 0.5

    if candidate_norm == 0 or role_norm == 0:
        return 0.0

    return dot_product / (candidate_norm * role_norm)


def weighted_cosine_similarity(candidate_skills, essential_skills, optional_skills):
    candidate_set = {normalize_skill(skill) for skill in candidate_skills}
    essential_set = {normalize_skill(skill) for skill in essential_skills}
    optional_set = {normalize_skill(skill) for skill in optional_skills} - essential_set
    skill_weights = {skill: 1.0 for skill in essential_set}
    skill_weights.update({skill: 0.5 for skill in optional_set})

    if not candidate_set or not skill_weights:
        return 0.0

    dot_product = sum(weight for skill, weight in skill_weights.items() if skill in candidate_set)
    candidate_norm = len(candidate_set) ** 0.5
    role_norm = sum(weight * weight for weight in skill_weights.values()) ** 0.5
    return dot_product / (candidate_norm * role_norm)


def suggest_certifications_for_missing_skills(missing_skills, limit=3):
    ordered = []
    seen = set()

    for skill in missing_skills:
        cert = next(
            (CERTIFICATION_LIBRARY[variant] for variant in skill_text_variants(skill) if variant in CERTIFICATION_LIBRARY),
            None,
        )
        if cert and cert not in seen:
            ordered.append(cert)
            seen.add(cert)
        if len(ordered) >= limit:
            break

    return ordered


def looks_like_certificate_document(text: str, filename: str = "") -> bool:
    if not text and not filename:
        return False

    full_text = f"{text or ''} {filename or ''}".lower()
    ext = os.path.splitext(filename.lower())[1]

    # Explicit rejection for homework, lab reports, assignments
    assignment_keywords = [
        "assignment",
        "homework",
        "lab report",
        "class work",
        "answer sheet",
    ]
    if any(keyword in full_text for keyword in assignment_keywords):
        return False

    # Image files uploaded as certificates are accepted as visual proof
    if ext in {".png", ".jpg", ".jpeg"}:
        return True

    # Filename indicators
    file_name_indicators = [
        "cert",
        "certificate",
        "certification",
        "completion",
        "training",
        "achievement",
        "award",
        "workshop",
        "internship",
        "course",
        "diploma",
        "degree",
        "credential",
        "license",
        "badge",
        "proof",
        "udemy",
        "coursera",
        "edx",
        "nptel",
        "hackerrank",
        "google",
        "microsoft",
        "aws",
        "ibm",
        "meta",
        "cisco",
        "oracle",
        "bootcamp",
        "assessment",
        "exam",
    ]
    if any(indicator in full_text for indicator in file_name_indicators):
        return True

    # Certificate content keywords
    certificate_keywords = [
        "certificate",
        "certification",
        "certified",
        "certify",
        "training",
        "workshop",
        "course completion",
        "completed",
        "participant",
        "internship",
        "achievement",
        "issued by",
        "award",
        "awarded",
        "proof",
        "qualified",
        "completion",
        "completed successfully",
        "completion certificate",
        "successful completion",
        "diploma",
        "degree",
        "credential",
        "specialization",
        "passed",
        "grade",
        "score",
        "honors",
        "verified",
        "coursera",
        "udemy",
        "edx",
        "nptel",
        "platform",
        "online course",
        "curriculum",
        "congratulations",
    ]
    if any(keyword in full_text for keyword in certificate_keywords):
        return True

    issuer_indicators = [
        "issued by",
        "organized by",
        "conducted by",
        "university",
        "college",
        "institute",
        "academy",
        "training center",
        "company",
        "department",
        "platform",
        "program",
        "school",
        "foundation",
        "organization",
        "authorized",
    ]
    if any(indicator in full_text for indicator in issuer_indicators):
        return True

    # If the document has meaningful text content and is not an assignment
    if len(text.strip()) > 30:
        return True

    return False


def recommend_careers(
    candidate_skills,
    limit=5,
    education="",
    experience_text="",
    experience_years=None,
    projects=None,
    certifications=None,
    verified_certificates=None,
):
    try:
        from .services.career_recommendation_service import get_career_recommendation_service
        from .services.resume_processing import CandidateProfile, estimate_years_of_experience

        exp_years = experience_years
        if exp_years is None and experience_text:
            exp_years = estimate_years_of_experience(experience_text)

        cand_profile = CandidateProfile(
            skills=list(candidate_skills),
            education=education or "",
            experience_years=float(exp_years or 0.0),
            experience_summary=experience_text or "",
            projects=projects or [],
            certifications=certifications or [],
        )

        service = get_career_recommendation_service()
        response = service.recommend(
            cand_profile,
            limit=limit,
            verified_certificates=verified_certificates,
        )

        ranked = []
        for rec in response["recommendations"]:
            ranked.append({
                "role": rec["occupation_title"],
                "description": rec["description"],
                "score": round(rec["score"], 1),
                "match": rec["matched_skills"],
                "missing": rec["missing_skills"][:4],
                "all_missing": rec["missing_skills"],
                "optional_missing": [],
                "certifications": rec["suggested_certifications"],
                "occupation_id": rec["occupation_id"],
                "ranking_method": rec["ranking_method"],
                "score_components": rec["score_components"],
                "explanation": rec["explanation"],
            })
        return ranked

    except Exception:
        skill_set = {normalize_skill(skill) for skill in candidate_skills}
        ranked = []

        for role_name, job in CAREER_DATA.items():
            essential_skills = {
                normalize_skill(skill)
                for skill in job.get("essential_skills", job["skills"])
            }
            optional_skills = {
                normalize_skill(skill)
                for skill in job.get("optional_skills", [])
            } - essential_skills
            role_skill_set = essential_skills | optional_skills
            match_skills = sorted(role_skill_set & skill_set)
            missing_skills = sorted(essential_skills - skill_set)
            optional_missing = sorted(optional_skills - skill_set)
            score = weighted_cosine_similarity(skill_set, essential_skills, optional_skills) * 100
            if score > 0:
                ranked.append({
                    "role": role_name,
                    "description": job["description"],
                    "score": round(score, 1),
                    "match": match_skills,
                    "missing": missing_skills[:4],
                    "all_missing": missing_skills,
                    "optional_missing": optional_missing,
                    "certifications": suggest_certifications_for_missing_skills(missing_skills, limit=3),
                })

        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:limit]


def verify_secure_file(file_storage, file_type="resume"):
    if file_storage is None:
        raise ValueError(f"No {file_type} file uploaded.")

    filename = file_storage.filename or ""
    extension = os.path.splitext(filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"{file_type.title()} file type is not allowed.")

    content = file_storage.read()
    file_storage.stream.seek(0)

    if len(content) == 0:
        raise ValueError(f"{file_type.title()} file is empty.")

    if len(content) > 20 * 1024 * 1024:
        raise ValueError(f"{file_type.title()} file is too large. Max allowed size is 20 MB.")

    digest = hashlib.sha256(content).hexdigest()
    result = {
        "file_type": file_type,
        "filename": filename,
        "extension": extension,
        "size_bytes": len(content),
        "sha256": digest,
        "verified": True,
    }

    VERIFICATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if VERIFICATION_LOG_PATH.exists():
        records = json.loads(VERIFICATION_LOG_PATH.read_text(encoding="utf-8"))
    else:
        records = []

    records.append(result)
    VERIFICATION_LOG_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return result
