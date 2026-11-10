# ESCO career skill data

The recommender reads `esco_careers.json`, a local English-language snapshot imported from the European Commission's ESCO web-service API. The importer targets ESCO v1.2.0 and retains each occupation URI, description, essential skills, and optional skills.

## Refresh the snapshot

From the project folder, run:

```powershell
python scripts/import_esco_dataset.py
```

The importer requests the selected occupation profiles from the official ESCO API and writes the source version and import date to `esco_dataset_metadata.json`.

## Attribution and limitations

- ESCO is a European occupation-and-skills classification, not a regional job-postings dataset or a record of actual hiring outcomes.
- The importer includes profiles matching this project's selected career families, not every occupation in ESCO.
- Resume skill extraction uses spaCy tokenization, sentence segmentation, and PhraseMatcher over ESCO skill labels and aliases. It does not use a pretrained statistical NLP model.
- Essential ESCO skills receive more score weight than optional ESCO skills; this weighting is a project choice, not an ESCO accuracy claim.
- The classification can support skill matching, but cannot establish that recommendations are more accurate than previous research without evaluation on labeled student examples.
- ESCO API documentation: https://esco.ec.europa.eu/en/use-esco/use-esco-services-api/esco-web-service-api
- ESCO downloads: https://esco.ec.europa.eu/en/use-esco/download