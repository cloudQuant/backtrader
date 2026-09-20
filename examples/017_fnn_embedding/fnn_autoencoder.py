#!/usr/bin/env python
"""PyTorch autoencoder + rolling trainer for iteration 35-1 (D351-04/05).

The encoder compresses the 12-dim normalised feature windows to
``embed_dim``; training is walk-forward (only samples whose labels are
realised before the retrain instant), seeded and single-threaded for
determinism, with weights cached under ``models/`` so that backtests replay
from disk instead of re-training.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from torch import nn

N_FEATURES = 12
TRAIN_DEFAULTS = {
    "embed_dim": 4,
    "retrain_freq": 20,
    "stride": 1,
    "norm_window": 2000,
    "norm_min": 500,
    "epochs": 100,
    "lr": 0.001,
    "batch": 512,
    "patience": 10,
    "seed": 42,
    "max_train_samples": 50000,
}
MIN_TRAIN_SAMPLES = 100


def make_deterministic(seed: int = 42) -> None:
    """Fix every randomness source that affects CPU training (NFR351-02)."""
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)


class Autoencoder(nn.Module):
    """12 -> 32 -> 16 -> embed encoder with a symmetric decoder (D351-04)."""

    def __init__(self, embed_dim: int = 4, n_features: int = N_FEATURES) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(n_features, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, embed_dim),
        )
        self.decoder = nn.Sequential(
            nn.Linear(embed_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 32),
            nn.ReLU(),
            nn.Linear(32, n_features),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(x))


def train_autoencoder(
    features: np.ndarray,
    *,
    embed_dim: int,
    epochs: int,
    lr: float,
    batch: int,
    patience: int,
    seed: int,
) -> tuple[dict, dict]:
    """Train the AE on ``features`` (already normalised float32).

    Returns ``(state_dict, meta)`` with the early-stopped best weights and
    training metadata (loss summary, epochs actually run).
    """
    make_deterministic(seed)
    x = torch.from_numpy(np.ascontiguousarray(features, dtype=np.float32))
    model = Autoencoder(embed_dim=embed_dim)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    n = x.shape[0]
    batch = max(1, min(int(batch), n))
    generator = torch.Generator().manual_seed(seed)
    best_loss = math.inf
    best_state = None
    stale = 0
    epochs_run = 0
    first_epoch_loss = None
    for epoch in range(int(epochs)):
        perm = torch.randperm(n, generator=generator)
        epoch_loss = 0.0
        n_batches = 0
        for begin in range(0, n, batch):
            idx = perm[begin : begin + batch]
            batch_x = x[idx]
            optimiser.zero_grad()
            recon = model(batch_x)
            loss = loss_fn(recon, batch_x)
            loss.backward()
            optimiser.step()
            epoch_loss += float(loss.item())
            n_batches += 1
        epoch_loss /= max(n_batches, 1)
        if first_epoch_loss is None:
            first_epoch_loss = epoch_loss
        epochs_run = epoch + 1
        if epoch_loss < best_loss - 1e-6:
            best_loss = epoch_loss
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= int(patience):
                break
    if best_state is None:  # pragma: no cover - first epoch always improves inf
        best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    meta = {
        "final_loss": best_loss,
        "epochs_run": epochs_run,
        "n_samples": int(n),
        "first_epoch_loss": first_epoch_loss,
    }
    return best_state, meta


class EncoderBundle:
    """One encoder version plus the library it has encoded (D351-05.2)."""

    def __init__(self, model: Autoencoder, version: str) -> None:
        self.model = model.eval()
        self.version = version
        self.embedding_matrix: Optional[np.ndarray] = None

    def encode_matrix(self, features: np.ndarray) -> np.ndarray:
        x = torch.from_numpy(np.ascontiguousarray(features, dtype=np.float32))
        with torch.no_grad():
            emb = self.model.encoder(x).numpy().astype(np.float32)
        return emb

    def encode_single(self, feature: np.ndarray) -> np.ndarray:
        return self.encode_matrix(feature[None, :])[0]


def _neighbourhood_retention(
    bundle: EncoderBundle, features: np.ndarray, n_probe: int = 200, k: int = 10
) -> float:
    """Jaccard overlap of raw-space and embedding-space kNN (D351-05.3)."""
    n = features.shape[0]
    if n < 2 * k + 1:
        return float("nan")
    rng = np.random.default_rng(0)
    probe = rng.choice(n, size=min(n_probe, n), replace=False)
    raw = features[probe].astype(np.float64)
    emb = bundle.encode_matrix(features)[probe].astype(np.float64)

    def knn_sets(mat: np.ndarray) -> list[set]:
        dists = ((mat[:, None, :] - mat[None, :, :]) ** 2).sum(axis=2)
        np.fill_diagonal(dists, np.inf)
        return [{int(j) for j in row} for row in np.argsort(dists, axis=1)[:, :k]]

    raw_sets = knn_sets(raw)
    emb_sets = knn_sets(emb)
    jacc = [len(a & b) / max(len(a | b), 1) for a, b in zip(raw_sets, emb_sets)]
    return float(np.mean(jacc))


def _procustes_drift(old_emb: np.ndarray, new_emb: np.ndarray, n_anchor: int = 1000) -> float:
    """Orthogonal Procrustes residual between two embeddings of one anchor set."""
    from scipy.linalg import orthogonal_procrustes

    m = min(len(old_emb), len(new_emb), n_anchor)
    if m < 10:
        return float("nan")
    old = old_emb[:m].astype(np.float64)
    new = new_emb[:m].astype(np.float64)
    old_c = old - old.mean(axis=0)
    new_c = new - new.mean(axis=0)
    R, _ = orthogonal_procrustes(old_c, new_c)
    return float(np.linalg.norm(old_c @ R - new_c) / max(np.linalg.norm(new_c), 1e-12))


class RollingTrainer:
    """Walk-forward retraining with disk caching (D351-05, D351-11).

    ``advance_to(dt)`` trains (or loads) the encoder version whose training
    set contains exactly the library samples with ``label_ready <= dt``
    (G351-02 defence 1), re-encodes the library atomically and appends a
    row to ``reports/train_report.jsonl``.
    """

    def __init__(
        self,
        library,
        training_cfg: dict,
        models_dir: Path,
        reports_dir: Path,
        cache_key: str,
        use_cache: bool = True,
    ) -> None:
        self.library = library
        cfg = dict(TRAIN_DEFAULTS)
        cfg.update({k: v for k, v in (training_cfg or {}).items() if v is not None})
        self.cfg = cfg
        self.embed_dim = int(cfg["embed_dim"])
        self.seed = int(cfg["seed"])
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.cache_key = cache_key
        self.use_cache = use_cache
        self._bundle: Optional[EncoderBundle] = None
        self._step = -1
        self.train_reports: list[dict] = []
        self._prev_anchor_emb: Optional[np.ndarray] = None

    # -- public API -------------------------------------------------------

    def current_bundle(self) -> Optional[EncoderBundle]:
        return self._bundle

    def advance_to(self, dt, trigger: str = "retrain") -> Optional[EncoderBundle]:
        """Train or load the encoder version whose data ends at ``dt``."""
        import pandas as pd

        cutoff = pd.Timestamp(dt)
        ready = np.searchsorted(self.library.label_ready_ns, cutoff.value, side="right")
        n_available = int(ready)
        if n_available < MIN_TRAIN_SAMPLES:
            # Not enough realised history yet: keep any existing bundle
            # (a failed retrain never discards the previous encoder).
            return self._bundle

        sample_idx = self._training_sample_indices(n_available)
        features = self.library.features[sample_idx]

        self._step += 1
        version = "step%03d" % self._step
        weight_path, meta_path = self._paths(self._step, cutoff)

        trained_from_cache = False
        if self.use_cache and weight_path.exists() and meta_path.exists():
            state = torch.load(weight_path, map_location="cpu", weights_only=True)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            trained_from_cache = True
        else:
            state, meta = train_autoencoder(
                features,
                embed_dim=self.embed_dim,
                epochs=self.cfg["epochs"],
                lr=self.cfg["lr"],
                batch=self.cfg["batch"],
                patience=self.cfg["patience"],
                seed=self.seed,
            )
            torch.save(state, weight_path)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

        model = Autoencoder(embed_dim=self.embed_dim)
        model.load_state_dict(state)
        new_bundle = EncoderBundle(model, version)

        retention = _neighbourhood_retention(new_bundle, features)
        anchor_emb = new_bundle.encode_matrix(
            self.library.features[: min(len(self.library.features), 1000)]
        )
        drift = (
            _procustes_drift(self._prev_anchor_emb, anchor_emb)
            if self._prev_anchor_emb is not None
            else float("nan")
        )
        self._prev_anchor_emb = anchor_emb

        report = {
            "version": version,
            "trigger": trigger,
            "cutoff": str(cutoff),
            "n_train_samples": int(len(sample_idx)),
            "from_cache": trained_from_cache,
            "neighborhood_retention": retention,
            "drift_procustes": drift,
            "final_loss": meta.get("final_loss"),
            "epochs_run": meta.get("epochs_run"),
        }
        self.train_reports.append(report)
        serialisable = {
            k: (None if isinstance(v, float) and v != v else v)
            for k, v in report.items()
        }
        with (self.reports_dir / "train_report.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(serialisable, ensure_ascii=False, default=str) + "\n")

        self._bundle = new_bundle
        return new_bundle

    def apply_to_library(self, library) -> None:
        """Encode the full library under the current bundle (D351-05.2)."""
        if self._bundle is None:
            return
        library.embeddings = self._bundle.encode_matrix(library.features)
        library.encoder_version = self._bundle.version

    # -- internals --------------------------------------------------------

    def _training_sample_indices(self, n_available: int) -> np.ndarray:
        """Deterministic capped draw over the available window."""
        cap = int(self.cfg["max_train_samples"])
        if n_available <= cap:
            return np.arange(n_available)
        rng = np.random.default_rng(self.seed)
        return np.sort(rng.choice(n_available, size=cap, replace=False))

    def _paths(self, step: int, cutoff) -> tuple[Path, Path]:
        digest = hashlib.sha1(
            ("%s|%s|%s" % (self.cache_key, cutoff, json.dumps(self.cfg, sort_keys=True))).encode()
        ).hexdigest()[:12]
        stem = self.models_dir / self.cache_key / ("step%03d_%s" % (step, digest))
        stem.parent.mkdir(parents=True, exist_ok=True)
        return stem.with_suffix(".pt"), stem.with_suffix(".json")
