"""Organism names to NCBI taxon ids (data/organism_taxa.tsv): scientific names, NCBI synonyms and old names, common
names ("yeast" = S. cerevisiae 4932; Candida only when named), strains (the first two words) and repository labels
("Homo sapiens (human)"). Names the table lacks keep their genus and species as the key."""

from __future__ import annotations

import csv
import functools
import os
import re


@functools.lru_cache(maxsize=None)
def _names():
    by = {}
    with open(os.path.join(os.path.dirname(__file__), "data", "organism_taxa.tsv")) as fh:
        for r in csv.DictReader((l for l in fh if not l.startswith("#")), delimiter="\t"):
            t = (int(r["taxid"]), r["scientific_name"])
            by[r["scientific_name"].lower()] = t
            by.setdefault(_clean(r["scientific_name"]), t)   # strains: "Salmonella typhimurium (strain LT2 ...)"
            for n in filter(None, r["other_names"].split("|")):
                by.setdefault(n, t)
    return by


def _clean(name):
    return " ".join(re.sub(r"\([^)]*\)", " ", str(name)).replace("_", " ").lower().split())


def resolve(name):
    """(taxid, scientific name) or None"""
    s = _clean(name)
    return _names().get(s) or _names().get(" ".join(s.split()[:2]))


def key(name):
    """comparison key: the taxid when known, else genus and species"""
    r = resolve(name)
    return f"taxid:{r[0]}" if r else " ".join(_clean(name).split()[:2])


def scientific(name):
    r = resolve(name)
    return r[1] if r else str(name)
