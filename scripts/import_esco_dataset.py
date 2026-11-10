import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ESCO_API_BASE = "https://ec.europa.eu/esco/api"
ESCO_VERSION = "v1.2.0"
LANGUAGE = "en"

ESCO_SEARCH_TERMS = [
    ["data analyst"],
    ["data scientist"],
    ["data engineer"],
    ["artificial intelligence engineer"],
    ["database administrator"],
    ["software developer"],
    ["web developer"],
    ["mobile application developer"],
    ["software tester"],
    ["cloud DevOps engineer"],
    ["cloud engineer"],
    ["information security analyst"],
    ["ICT security engineer"],
    ["ICT network engineer"],
    ["ICT support technician"],
    ["user interface designer"],
    ["user experience designer"],
    ["business analyst"],
    ["project manager"],
    ["product manager"],
    ["digital marketing manager"],
    ["financial analyst"],
    ["operations analyst"],
    ["technical writer"],
    ["market research analyst"],
]


def normalize_label(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def get_json(path, params):
    query = urlencode(params, safe=":/")
    request = Request(
        f"{ESCO_API_BASE}/{path}?{query}",
        headers={"Accept": "application/json", "User-Agent": "CareerAI-ESCO-import/1.0"},
    )
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def search_occupation(search_term):
    results = get_json(
        "search",
        {
            "text": search_term,
            "type": "occupation",
            "language": LANGUAGE,
            "selectedVersion": ESCO_VERSION,
            "limit": 20,
            "full": "false",
        },
    ).get("_embedded", {}).get("results", [])

    normalized_search = normalize_label(search_term)
    for result in results:
        label = result.get("preferredLabel", {}).get(LANGUAGE, result.get("title", ""))
        if normalize_label(label) == normalized_search:
            return result
    return None


def resolve_profile(search_terms):
    for search_term in search_terms:
        result = search_occupation(search_term)
        if result:
            return search_term, result
    return None, None


def load_profile(item):
    search_term, search_result = item
    if search_result is None:
        return None, None

    occupation_uri = search_result.get("uri", "")
    details = get_json(
        "resource/occupation",
        {"uri": occupation_uri, "language": LANGUAGE, "selectedVersion": ESCO_VERSION},
    )
    links = details.get("_links", {})
    essential_relations = [
        {"uri": link.get("uri", ""), "label": link.get("title", "").strip(), "type": link.get("skillType", "")}
        for link in links.get("hasEssentialSkill", [])
        if link.get("uri") and link.get("title", "").strip()
    ]
    optional_relations = [
        {"uri": link.get("uri", ""), "label": link.get("title", "").strip(), "type": link.get("skillType", "")}
        for link in links.get("hasOptionalSkill", [])
        if link.get("uri") and link.get("title", "").strip()
    ]
    essential = [relation["label"] for relation in essential_relations]
    optional = [relation["label"] for relation in optional_relations]
    if not essential and not optional:
        return None, None

    preferred_label = details.get("preferredLabel", {}).get(LANGUAGE, details.get("title", "")).strip()
    if not preferred_label:
        return None, None
    description = details.get("description", {}).get(LANGUAGE, {}).get("literal", "").strip()
    return preferred_label, {
        "description": description,
        "skills": sorted(set(essential + optional), key=str.casefold),
        "essential_skills": sorted(set(essential), key=str.casefold),
        "optional_skills": sorted(set(optional) - set(essential), key=str.casefold),
        "essential_skill_relations": essential_relations,
        "optional_skill_relations": optional_relations,
        "esco_uri": occupation_uri,
        "esco_label": preferred_label,
        "esco_search_term": search_term,
        "esco_version": ESCO_VERSION,
    }


def main():
    with ThreadPoolExecutor(max_workers=4) as executor:
        resolved = list(executor.map(resolve_profile, ESCO_SEARCH_TERMS))
        imported = list(executor.map(load_profile, resolved))

    profiles = {}
    used_uris = set()
    for display_role, profile in imported:
        if profile and profile["esco_uri"] not in used_uris:
            profiles[display_role] = profile
            used_uris.add(profile["esco_uri"])

    if len(profiles) < 10:
        raise RuntimeError(
            f"Only {len(profiles)} distinct ESCO profiles were imported; refusing to replace the local dataset."
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dataset_path = DATA_DIR / "esco_careers.json"
    temporary_path = dataset_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(dataset_path)

    metadata = {
        "dataset": "European Skills, Competences, Qualifications and Occupations (ESCO)",
        "version": ESCO_VERSION,
        "language": LANGUAGE,
        "source": "https://ec.europa.eu/esco/api",
        "documentation": "https://esco.ec.europa.eu/en/use-esco/use-esco-services-api/esco-web-service-api",
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "occupation_profiles": len(profiles),
        "source_skill_relationships": "hasEssentialSkill and hasOptionalSkill",
        "unique_skill_concepts": len({
            relation["uri"]
            for profile in profiles.values()
            for relation in profile["essential_skill_relations"] + profile["optional_skill_relations"]
        }),
    }
    (DATA_DIR / "esco_dataset_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Imported {len(profiles)} ESCO {ESCO_VERSION} occupation profiles into {dataset_path}")
    for occupation_label in profiles:
        print(f"- {occupation_label}")


if __name__ == "__main__":
    main()