#!/usr/bin/env python3
"""Fetch DANDI metadata, embed it, and write the web artifact.

Modeling pipeline (BERTopic-style):
    sentence embeddings -> UMAP (2D) -> HDBSCAN -> c-TF-IDF labels

Clustering and the map layout are derived from the *same* 2D UMAP embedding, so
a dataset's color always matches its position on the map.
"""

from __future__ import annotations

import argparse
import colorsys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

API = "https://api.dandiarchive.org/api"
EMBED_MODEL = "all-MiniLM-L6-v2"
# Curated, colorblind-friendlier base palette; extended procedurally if more topics appear.
BASE_COLORS = ["#2c7a66", "#e07a4e", "#6b66a9", "#d6a73c", "#4386a6", "#a75873", "#76a657", "#8b6b4e", "#41a0a0", "#bc5960", "#8c65a4", "#c07a2c"]
OUTLIER_COLOR = "#9aa4ae"
STOP = {"data", "dataset", "dandiset", "using", "based", "recording", "recordings", "study", "approach", "technique", "series", "neural", "brain", "mouse", "mice"}


def get_json(url: str) -> dict:
    response = requests.get(url, timeout=45, headers={"User-Agent": "dandi-atlas/1.0"})
    response.raise_for_status()
    return response.json()


def get_catalog(limit: int | None) -> list[dict]:
    records, url = [], f"{API}/dandisets/?page_size=100&ordering=identifier"
    while url and (limit is None or len(records) < limit):
        page = get_json(url)
        records.extend(page["results"])
        url = page.get("next")
    return records[:limit] if limit else records


def names(items: list | None) -> list[str]:
    return [str(item.get("name", "")).strip() for item in (items or []) if isinstance(item, dict) and item.get("name")]


def fetch_metadata(record: dict) -> dict:
    identifier = record["identifier"]
    version = "draft" if record.get("draft_version") else (record.get("most_recent_published_version") or {}).get("version", "draft")
    try:
        meta = get_json(f"{API}/dandisets/{identifier}/versions/{version}/")
    except Exception as exc:
        print(f"warning: DANDI:{identifier}: {exc}")
        meta = {}
    summary = meta.get("assetsSummary") or {}
    authors = [str(c.get("name", "")).strip() for c in (meta.get("contributor") or []) if isinstance(c, dict) and c.get("name") and "dcite:Author" in (c.get("roleName") or [])]
    keywords = [str(x).strip() for x in (meta.get("keywords") or []) if x]
    about = names(meta.get("about"))
    species = names(summary.get("species"))
    approaches = names(summary.get("approach"))
    techniques = names(summary.get("measurementTechnique"))
    variables = [str(x) for x in (summary.get("variableMeasured") or [])]
    title = meta.get("name") or (record.get("draft_version") or {}).get("name") or f"Dandiset {identifier}"
    description = meta.get("description") or ""
    # Natural-language document: title + abstract carry the embedding signal (encoder
    # truncates ~256 tokens); trailing metadata sharpens the c-TF-IDF topic labels.
    parts = [title.strip(), description.strip()]
    for prefix, values in (("Anatomy", about), ("Species", species), ("Approaches", approaches), ("Techniques", techniques), ("Keywords", keywords), ("Variables", variables)):
        if values:
            parts.append(f"{prefix}: {', '.join(dict.fromkeys(v for v in values if v))}.")
    document = "\n".join(part for part in parts if part)
    return {
        "id": identifier, "title": title, "description": description, "document": document,
        "authors": authors, "keywords": keywords, "species": species, "approaches": approaches, "techniques": techniques,
        "bytes": summary.get("numberOfBytes") or 0,
        "files": summary.get("numberOfFiles") or (record.get("draft_version") or record.get("most_recent_published_version") or {}).get("asset_count") or 0,
        "subjects": summary.get("numberOfSubjects") or 0, "modified": record.get("modified", ""),
        "url": meta.get("url") or f"https://dandiarchive.org/dandiset/{identifier}/{version}",
    }


def scale(values):
    """Normalize an (n, 2) array into the unit square for the web layout."""
    low, high = values.min(axis=0), values.max(axis=0)
    span = high - low
    span[span == 0] = 1
    return (values - low) / span


def palette(count: int) -> list[str]:
    """Return `count` distinct hex colors, extending the curated base procedurally."""
    colors = list(BASE_COLORS[:count])
    while len(colors) < count:
        hue = (len(colors) * 0.61803398875) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.52, 0.72)
        colors.append(f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}")
    return colors


def clean_terms(raw_terms: list[str], limit: int = 5) -> list[str]:
    """Drop stopwords and near-duplicate stems from a cluster's c-TF-IDF terms."""
    terms: list[str] = []
    for term in raw_terms:
        term = term.strip().lower()
        if not term or term in STOP or any(word in STOP for word in term.split()):
            continue
        stem = term[:5]
        if any(stem == picked[:5] or term in picked or picked in term for picked in terms):
            continue
        terms.append(term)
        if len(terms) == limit:
            break
    return terms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Fetch only this many records (useful for previews)")
    parser.add_argument("--output", default="public/data/dandisets.json")
    args = parser.parse_args()

    # Heavy ML imports are local so `--help` and the fetch stay fast to load.
    from bertopic import BERTopic
    from bertopic.vectorizers import ClassTfidfTransformer
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    from umap import UMAP

    catalog = get_catalog(args.limit)
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(fetch_metadata, record) for record in catalog]
        records = [future.result() for future in as_completed(futures)]
    records = [record for record in records if record["files"] > 0]
    records.sort(key=lambda item: item["id"])
    documents = [item.pop("document") for item in records]

    print(f"embedding {len(documents)} documents with {EMBED_MODEL}…")
    encoder = SentenceTransformer(EMBED_MODEL)
    embeddings = encoder.encode(documents, normalize_embeddings=True, show_progress_bar=True)

    # A single 2D UMAP drives BOTH the map layout and the clustering, so colors and
    # positions can never disagree. HDBSCAN then finds natural, uneven topic regions
    # and flags genuine outliers (label -1) instead of forcing a mega-cluster.
    n = len(records)
    umap_model = UMAP(n_components=3, n_neighbors=min(15, max(2, n - 1)), min_dist=0.0, metric="cosine", random_state=42)
    # Keep this small so tight, genuinely distinct groups (e.g. C. elegans) survive as their
    # own topics instead of being swept into the outlier pile. EOM selection then keeps the
    # regions stable without fragmenting into dozens of near-duplicate specks.
    min_cluster_size = max(6, n // 85)
    hdbscan_model = HDBSCAN(min_cluster_size=min_cluster_size, min_samples=1, metric="euclidean", cluster_selection_method="eom", prediction_data=True)
    vectorizer_model = CountVectorizer(stop_words=list(ENGLISH_STOP_WORDS | STOP), ngram_range=(1, 2), min_df=2 if n > 50 else 1)
    topic_model = BERTopic(
        embedding_model=encoder,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model,
        ctfidf_model=ClassTfidfTransformer(reduce_frequent_words=True),
        top_n_words=10,
        calculate_probabilities=False,
        verbose=True,
    )
    labels, _ = topic_model.fit_transform(documents, embeddings)
    labels = np.asarray(labels)

    points = scale(np.asarray(umap_model.embedding_, dtype=float))

    topic_ids = sorted(tid for tid in set(labels.tolist()) if tid != -1)
    colors = palette(len(topic_ids))
    color_of = {tid: colors[i] for i, tid in enumerate(topic_ids)}
    color_of[-1] = OUTLIER_COLOR

    cluster_rows = []
    for tid in topic_ids:
        raw = [term for term, _ in (topic_model.get_topic(tid) or [])]
        terms = clean_terms(raw)
        label = " · ".join(word.title() for word in terms[:2]) or f"Topic {tid + 1}"
        cluster_rows.append({"id": int(tid), "label": label, "count": int((labels == tid).sum()), "color": color_of[tid], "terms": terms})
    cluster_rows.sort(key=lambda row: row["count"], reverse=True)
    outliers = int((labels == -1).sum())
    if outliers:
        cluster_rows.append({"id": -1, "label": "Unclustered", "count": outliers, "color": OUTLIER_COLOR, "terms": []})

    for item, point, tid in zip(records, points, labels):
        item.update({"x": round(float(point[0]), 5), "y": round(float(point[1]), 5), "z": round(float(point[2]), 5), "cluster": int(tid)})

    payload = {"generatedAt": datetime.now(timezone.utc).isoformat(), "total": len(records), "method": "MiniLM embeddings · UMAP (3D) · HDBSCAN · c-TF-IDF", "clusters": cluster_rows, "dandisets": records}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records across {len(topic_ids)} topics ({outliers} unclustered) to {output}")


if __name__ == "__main__":
    main()
