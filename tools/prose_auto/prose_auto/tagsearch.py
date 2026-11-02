"""The mini-search: score the top spectra of a run against in-silico digests to test hypotheses before the real
search (organism, Cys alkylation, protease, mass accuracy).

Every candidate in the precursor window is scored by its matched b/y ions (a binomial score, as in Andromeda and
MS Amanda); reversed decoys in the same index give the FDR. Digests do not depend on the run: they are cached on disk
per (FASTA content, enzyme, missed cleavages) and memory-mapped, and a modification setting (Cys, label) is only a
vectorised mass sum over the cached residue counts.
"""

from __future__ import annotations

import functools
import gzip
import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass

import numpy as np

PROTON = 1.007276466812
H2O = 18.010564684
ISO = 1.0033548378
MAX_LEN = 30
MAX_CANDIDATES = 500      # per precursor window and isotope

AA = {
    "G": 57.021464, "A": 71.037114, "S": 87.032028, "P": 97.052764, "V": 99.068414,
    "T": 101.047679, "C": 103.009185, "L": 113.084064, "I": 113.084064, "N": 114.042927,
    "D": 115.026943, "Q": 128.058578, "K": 128.094963, "E": 129.042593, "M": 131.040485,
    "H": 137.058912, "F": 147.068414, "R": 156.101111, "Y": 163.063329, "W": 186.079313,
}

CYS_MODS = {
    "Carbamidomethyl (C)": 57.021464,
    "none (free Cys)": 0.0,
    "Propionamide (C)": 71.037114,
    "Nethylmaleimide (C)": 125.047679,
    "Methylthio (C)": 45.987721,
    "Carboxymethyl (C)": 58.005479,
}

LABEL_MASS = {"TMT": 229.162932, "TMTpro": 304.207146, "iTRAQ4plex": 144.102063,
              "iTRAQ8plex": 304.205360}

ENZYMES = {
    # name: (cleave after, not before, side)
    "Trypsin": ("KR", "P", "C"),
    "Trypsin/P": ("KR", "", "C"),
    "Lys-C": ("K", "", "C"),
    "Arg-C": ("R", "P", "C"),
    "Chymotrypsin": ("FYWL", "P", "C"),
    "Glu-C": ("E", "", "C"),
    "Asp-N": ("D", "", "N"),
    "Lys-N": ("K", "", "N"),
}

CACHE_DIR = os.environ.get("PROSE_AUTO_INDEX_CACHE", os.path.join(os.path.expanduser("~"), ".cache", "prose_auto", "index"))


def read_fasta(path):
    op = gzip.open if str(path).endswith(".gz") else open
    acc, seq = None, []
    with op(path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                if acc is not None:
                    yield acc, "".join(seq)
                acc, seq = line[1:].split()[0] if len(line) > 1 else "", []
            elif line:
                seq.append(line)
    if acc is not None:
        yield acc, "".join(seq)


# proteins that cRAP lists for every species (trypsin, keratins, serum albumin), by UniProt entry name or gene
CRAP_HEADER = re.compile(r"\|(?:TRYP\w*|ALBU|K[12]C\w+)_|\bGN=(?:KRT\d+\w*|ALB|PRSS[123])\b")


@functools.lru_cache(maxsize=64)
def contaminant_peptides(path, enzyme="Trypsin"):
    """Peptides (missed cleavages up to 2) of a database's trypsin, keratin and serum albumin entries"""
    op = gzip.open if str(path).endswith(".gz") else open
    out, keep, seq = set(), False, []
    with op(path, "rt") as fh:
        for line in list(fh) + [">"]:
            if line.startswith(">"):
                if keep and seq:
                    out.update(digest("".join(seq), enzyme, missed=2, min_len=5))
                keep, seq = bool(CRAP_HEADER.search(line)), []
            elif keep:
                seq.append(line.strip())
    return frozenset(out)


def is_decoy(acc):
    a = acc.upper()
    return a.startswith(("DECOY_", "REV_", "XXX_", "DECOY")) or a.endswith(("_REVERSED", "_DECOY", "_REV"))


def digest(seq, enzyme="Trypsin", missed=1, min_len=7, max_len=MAX_LEN):
    after, not_before, side = ENZYMES[enzyme]
    sites = [0]
    for i in range(len(seq) - 1):
        if side == "C" and seq[i] in after and seq[i + 1] not in not_before:
            sites.append(i + 1)
        elif side == "N" and seq[i + 1] in after:
            sites.append(i + 1)
    sites.append(len(seq))
    out = []
    for i in range(len(sites) - 1):
        for j in range(i + 1, min(i + 2 + missed, len(sites))):
            p = seq[sites[i]:sites[j]]
            if min_len <= len(p) <= max_len:
                out.append(p)
    return out


@dataclass
class Mods:
    cys: float = 57.021464
    k: float = 0.0          # fixed mass on K (label)
    nterm: float = 0.0      # fixed mass on the peptide N-term (label)

    def residue_lut(self):
        """Residue mass by ASCII code (0 for padding)."""
        lut = np.zeros(256)
        for aa, m in AA.items():
            lut[ord(aa)] = m + (self.cys if aa == "C" else self.k if aa == "K" else 0.0)
        return lut


# --- digest cache -------------------------------------------------------------
def _digest_arrays(proteins, enzyme, missed):
    """Targets and reversed decoys, first-seen order; a peptide seen as target and decoy is a target."""
    seen = {}
    for acc, seq in proteins:
        if is_decoy(acc):
            continue
        seq = re.sub(r"[^A-Z]", "", seq.upper())
        for dec, s in ((False, seq), (True, seq[::-1])):
            for p in digest(s, enzyme, missed):
                if p in seen and (seen[p] is False or dec):
                    continue
                seen[p] = dec
    ok = set(AA)
    peps = [p for p in seen if set(p) <= ok]           # unknown residues (X, B, U, ...) have no mass
    codes = np.array(peps, dtype=f"S{MAX_LEN}")
    m = codes.view(np.uint8).reshape(len(peps), MAX_LEN)
    base = Mods(cys=0.0).residue_lut()[m].sum(1)
    return {"codes": codes, "decoy": np.array([seen[p] for p in peps], dtype=bool), "base": base,
            "n_c": (m == ord("C")).sum(1).astype(np.uint8), "n_k": (m == ord("K")).sum(1).astype(np.uint8)}


_HASHES = {}


def _cache_key(path, enzyme, missed):
    st = os.stat(path)
    ident = (os.path.realpath(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)   # hash once per process
    if ident not in _HASHES:
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        _HASHES[ident] = h.hexdigest()[:16]
    return f"{_HASHES[ident]}_{enzyme.replace('/', '_')}_{missed}_v1"


_LOADED = {}


def load_digest(path, enzyme="Trypsin", missed=1, cache_dir=None):
    """The digest of a FASTA file, from the disk cache (built once, written atomically, memory-mapped)."""
    key = _cache_key(path, enzyme, missed)
    if key in _LOADED:
        return _LOADED[key]
    d = os.path.join(cache_dir or CACHE_DIR, key)
    if not os.path.exists(os.path.join(d, "done")):
        arr = _digest_arrays(read_fasta(path), enzyme, missed)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=key + ".", dir=os.path.dirname(d))
        for k, v in arr.items():
            np.save(os.path.join(tmp, k + ".npy"), v)
        open(os.path.join(tmp, "done"), "w").close()
        try:
            os.rename(tmp, d)                      # another process may have finished first: keep its copy
        except OSError:
            for f in os.listdir(tmp):
                os.remove(os.path.join(tmp, f))
            os.rmdir(tmp)
    arr = {k: np.load(os.path.join(d, k + ".npy"), mmap_mode="r") for k in ("codes", "decoy", "base", "n_c", "n_k")}
    _LOADED[key] = arr
    return arr


@dataclass
class PeptideIndex:
    name: str
    codes: np.ndarray       # S30 sequences, sorted by mass
    masses: np.ndarray      # neutral peptide masses, ascending
    decoy: np.ndarray

    def seq(self, i):
        return self.codes[i].decode()

    def __len__(self):
        return len(self.masses)


def index_for(name, path, mods: Mods, enzyme="Trypsin", missed=1, cache_dir=None):
    """Peptide index of a FASTA file under one modification setting."""
    d = load_digest(path, enzyme, missed, cache_dir)
    masses = d["base"] + d["n_c"] * mods.cys + d["n_k"] * mods.k + (H2O + mods.nterm)
    order = np.argsort(masses, kind="stable")
    return PeptideIndex(name, d["codes"][order], masses[order], d["decoy"][order])


# --- spectra --------------------------------------------------------------------
def select_scans(run, n=2000, sample="top", seed=0):
    """n searchable MS2: the highest-TIC ones ("top"), or a uniform random sample ("random")."""
    ms2 = [s for s in run.ms2 if s.precursor_mz > 0 and s.mz.size >= 10]
    if sample == "random":
        if len(ms2) <= n:
            return ms2
        return [ms2[i] for i in np.sort(np.random.default_rng(seed).choice(len(ms2), n, replace=False))]
    ms2.sort(key=lambda s: -s.tic)
    return ms2[:n]


def load_panel(path):
    """A directory of FASTA files, one per organism (file name = organism)."""
    panel = {}
    for f in sorted(os.listdir(path)):
        if re.search(r"\.(fasta|fa|faa)(\.gz)?$", f, re.I):
            panel[re.sub(r"\.(fasta|fa|faa)(\.gz)?$", "", f, flags=re.I)] = os.path.join(path, f)
    return panel


def prepare_peaks(scan, top_per_100=10):
    """Keep the top peaks per 100 Th window (as most engines do)."""
    if scan.mz.size == 0:
        return scan.mz
    keep = []
    bins = (scan.mz // 100).astype(int)
    for b in np.unique(bins):
        sel = np.nonzero(bins == b)[0]
        keep.extend(sel[np.argsort(scan.intensity[sel])[::-1][:top_per_100]])
    return np.sort(scan.mz[np.array(keep, dtype=int)])


# --- scoring --------------------------------------------------------------------
def _fragment_matrix(codes, lut, nterm, double):
    """b and y ions of each peptide (rows; NaN where the peptide is shorter), with 2+ ions when double."""
    m = codes.view(np.uint8).reshape(len(codes), MAX_LEN)
    res = lut[m]
    length = (m > 0).sum(1)
    pm = np.cumsum(res, 1) + nterm                     # prefix masses after 1..30 residues
    total = pm[np.arange(len(m)), length - 1] + H2O
    inner = np.arange(MAX_LEN)[None, :] < (length - 1)[:, None]   # prefixes of length 1..L-1
    b = np.where(inner, pm + PROTON, np.nan)
    y = np.where(inner, total[:, None] - pm + PROTON, np.nan)
    frags = [b, y] + ([(b + PROTON) / 2, (y + PROTON) / 2] if double else [])
    return np.concatenate(frags, 1)


def _fragments(seq, mods: Mods, max_charge=1):
    """b and y ions of one peptide, sorted (for the fragment error estimate)."""
    f = _fragment_matrix(np.array([seq], dtype=f"S{MAX_LEN}"), mods.residue_lut(), mods.nterm, max_charge >= 2)[0]
    return np.sort(f[~np.isnan(f)])


_LOG_FACT = np.array([math.lgamma(i + 1) for i in range(4 * MAX_LEN + 1)])


def _binom_scores(k, n, p):
    """-log10 P(X >= k) for X ~ Binomial(n, p), per candidate; 0 where k <= 0."""
    out = np.zeros(len(k))
    r = np.nonzero(k > 0)[0]
    if r.size:
        i = np.arange(int(n[r].max()) + 1)[None, :]
        kr, nr, pr = k[r, None], n[r, None], p[r, None]
        lt = (_LOG_FACT[nr] - _LOG_FACT[i] - _LOG_FACT[np.maximum(nr - i, 0)]
              + i * np.log(pr) + (nr - i) * np.log1p(-pr))
        tail = np.where((i >= kr) & (i <= nr), np.exp(lt), 0.0).sum(1)
        out[r] = -np.log10(np.maximum(tail, 1e-300))
    return out


def score_search(scans, index: PeptideIndex, prec_ppm, frag_tol, frag_ppm, mods: Mods,
                 charges=(2, 3), peaks=None):
    """Best-scoring candidate per spectrum. Returns a list of
    (scan_index, score, is_decoy, peptide, precursor_ppm_error)."""
    lut = mods.residue_lut()
    out = []
    for k, s in enumerate(scans):
        pk = peaks[k] if peaks is not None else prepare_peaks(s)
        if pk.size < 5 or s.precursor_mz <= 0:
            continue
        rng = max(1.0, pk[-1] - pk[0])
        best = None
        for z in ((s.charge,) if s.charge > 0 else charges):
            mass = (s.precursor_mz - PROTON) * z
            for iso in (0, 1):
                m = mass - iso * ISO
                tol = m * prec_ppm * 1e-6
                lo = int(np.searchsorted(index.masses, m - tol))
                hi = min(int(np.searchsorted(index.masses, m + tol)), lo + MAX_CANDIDATES)
                if hi <= lo:
                    continue
                th = _fragment_matrix(index.codes[lo:hi], lut, mods.nterm, z >= 3)
                valid = ~np.isnan(th)
                thv = np.where(valid, th, 0.0)
                j = np.clip(np.searchsorted(pk, thv), 1, pk.size - 1)
                near = np.minimum(np.abs(pk[j] - thv), np.abs(pk[j - 1] - thv))
                t = thv * frag_tol * 1e-6 if frag_ppm else frag_tol
                hits = ((near <= t) & valid).sum(1)
                n_ions = valid.sum(1)
                tmean = np.where(valid, t, 0.0).sum(1) / n_ions if frag_ppm else np.full(len(hits), frag_tol)
                p = np.minimum(0.5, pk.size * 2 * tmean / rng)
                sc = _binom_scores(hits, n_ions, p)
                c = int(np.argmax(sc))                         # first of equal scores, as in scan order
                if best is None or sc[c] > best[1]:
                    i = lo + c
                    best = (k, float(sc[c]), bool(index.decoy[i]), index.seq(i),
                            (m - index.masses[i]) / index.masses[i] * 1e6)
        if best is not None:
            out.append(best)
    return out


def fdr_filter(psms, fdr=0.01):
    """Target PSMs passing a target-decoy FDR (decoys/targets above the
    threshold). Returns the passing target PSMs and the score threshold.
    Tied scores pass or fail together: the FDR is checked at group ends only."""
    psms = sorted(psms, key=lambda x: -x[1])
    t = d = 0
    best_n, thr = 0, float("inf")
    for i, p in enumerate(psms):
        if p[2]:
            d += 1
        else:
            t += 1
        if i + 1 < len(psms) and psms[i + 1][1] == p[1]:
            continue
        if t and d / t <= fdr and t > best_n:
            best_n, thr = t, p[1]
    passing = [p for p in psms if p[1] >= thr and not p[2]]
    return passing, thr
