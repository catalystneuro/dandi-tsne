#!/usr/bin/env python3
"""Fetch DANDI metadata, reduce it to two dimensions, and write the web artifact."""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.manifold import TSNE

API = "https://api.dandiarchive.org/api"
COLORS = ["#2c7a66", "#e07a4e", "#6b66a9", "#d6a73c", "#4386a6", "#a75873", "#76a657", "#8b6b4e", "#41a0a0", "#bc5960", "#74808e", "#8c65a4"]
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
    keywords = [str(x).strip() for x in (meta.get("keywords") or []) if x]
    about = names(meta.get("about"))
    species = names(summary.get("species"))
    approaches = names(summary.get("approach"))
    techniques = names(summary.get("measurementTechnique"))
    variables = [str(x) for x in (summary.get("variableMeasured") or [])]
    title = meta.get("name") or (record.get("draft_version") or {}).get("name") or f"Dandiset {identifier}"
    description = meta.get("description") or ""
    document = " ".join([title, description, " ".join(keywords * 2), " ".join(about * 2), " ".join(species), " ".join(approaches * 2), " ".join(techniques), " ".join(variables)])
    return {
        "id": identifier, "title": title, "description": description, "document": document,
        "keywords": keywords, "species": species, "approaches": approaches, "techniques": techniques,
        "bytes": summary.get("numberOfBytes") or 0,
        "files": summary.get("numberOfFiles") or (record.get("draft_version") or record.get("most_recent_published_version") or {}).get("asset_count") or 0,
        "subjects": summary.get("numberOfSubjects") or 0, "modified": record.get("modified", ""),
        "url": meta.get("url") or f"https://dandiarchive.org/dandiset/{identifier}/{version}",
    }


def scale(values):
    low, high = values.min(axis=0), values.max(axis=0)
    span = high - low
    span[span == 0] = 1
    return (values - low) / span


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Fetch only this many records (useful for previews)")
    parser.add_argument("--output", default="public/data/dandisets.json")
    args = parser.parse_args()
    catalog = get_catalog(args.limit)
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(fetch_metadata, record) for record in catalog]
        records = [future.result() for future in as_completed(futures)]
    records = [record for record in records if record["files"] > 0]
    records.sort(key=lambda item: item["id"])
    documents = [item.pop("document") for item in records]
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=2 if len(records) > 50 else 1, max_df=.94, max_features=7000, sublinear_tf=True)
    matrix = vectorizer.fit_transform(documents)
    dimensions = min(80, matrix.shape[0] - 1, matrix.shape[1] - 1)
    dense = TruncatedSVD(n_components=max(2, dimensions), random_state=42).fit_transform(matrix)
    perplexity = max(5, min(35, (len(records) - 1) // 3))
    points = TSNE(n_components=2, perplexity=perplexity, init="pca", learning_rate="auto", max_iter=1200, random_state=42).fit_transform(dense)
    points = scale(points)
    cluster_count = max(4, min(12, round(math.sqrt(len(records) / 2))))
    model = KMeans(n_clusters=cluster_count, random_state=42, n_init=20).fit(dense)
    feature_names = vectorizer.get_feature_names_out()
    cluster_rows = []
    for cluster_id in range(cluster_count):
        members = model.labels_ == cluster_id
        scores = matrix[members].mean(axis=0).A1
        ordered = scores.argsort()[::-1]
        terms = []
        for index in ordered:
            term = feature_names[index]
            if term not in STOP and not any(word in STOP for word in term.split()) and term not in terms:
                terms.append(term)
            if len(terms) == 5:
                break
        label = " · ".join(word.title() for word in terms[:2]) or f"Topic {cluster_id + 1}"
        cluster_rows.append({"id": cluster_id, "label": label, "count": int(members.sum()), "color": COLORS[cluster_id], "terms": terms})
    for item, point, cluster_id in zip(records, points, model.labels_):
        item.update({"x": round(float(point[0]), 5), "y": round(float(point[1]), 5), "cluster": int(cluster_id)})
    payload = {"generatedAt": datetime.now(timezone.utc).isoformat(), "total": len(records), "method": "TF–IDF · SVD · t-SNE · k-means", "clusters": cluster_rows, "dandisets": records}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {len(records)} records across {cluster_count} clusters to {output}")


if __name__ == "__main__":
    main()
