# DANDI Atlas

An interactive semantic map for discovering datasets in the [DANDI Archive](https://dandiarchive.org). Titles, descriptions, keywords, anatomy, species, approaches, techniques, and measured variables are vectorized with TF–IDF, reduced with SVD and t-SNE, and grouped with k-means.

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
