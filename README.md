# DANDI Semantic Atlas

An interactive semantic map for discovering datasets in the [DANDI Archive](https://dandiarchive.org). Titles, descriptions, keywords, anatomy, species, approaches, techniques, and measured variables are embedded with a sentence-transformer (MiniLM), projected to 2D with UMAP, and grouped into topic regions with HDBSCAN. Cluster labels come from c-TF-IDF over each region's documents.

**Live site:** [catalystneuro.github.io/dandi-semantic-atlas](https://catalystneuro.github.io/dandi-semantic-atlas/)

Only Dandisets containing at least one file are included in the map.

## Local development

```bash
npm install
npm run dev
```

To refresh the map data:

```bash
python -m pip install -r requirements.txt
python scripts/build_dataset.py
```

Pass `--limit 150` for a faster local preview. The GitHub workflow in `.github/workflows/update-dandisets.yml` rebuilds and commits the complete archive map every night at 05:17 UTC, and can also be run manually.
