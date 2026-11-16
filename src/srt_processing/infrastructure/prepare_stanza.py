"""Explicit model provisioning; never invoked by an asset-processing handler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .stanza_chunking import MODEL_LOCK_PATH, STANZA_VERSION, _sha256

PROCESSORS = {"tokenize": "combined", "mwt": "combined", "pos": "combined_charlm",
              "constituency": "ptb3-revised_electra-large"}
TRANSFORMER = "google/electra-large-discriminator"
TRANSFORMER_REVISION = "c13c3df7efadc2162f42588bd28eb4e187d602a5"


def prepare_bundle(directory: str) -> Path:
    """Download once by explicit operator action, then freeze every dependency hash."""
    from importlib.metadata import version
    import stanza
    from huggingface_hub import snapshot_download

    if version("stanza") != STANZA_VERSION:
        raise ValueError("install the pinned stanza version before preparation")
    root = Path(directory).resolve()
    identity = root / "model_identity.json"
    if identity.exists():
        raise FileExistsError("model bundle already frozen; use its identity or a new directory")
    root.mkdir(parents=True, exist_ok=True)
    stanza.download("en", model_dir=str(root / "stanza"), package=None,
                    processors=PROCESSORS, resources_version=STANZA_VERSION)
    snapshot_download(TRANSFORMER, revision=TRANSFORMER_REVISION, local_dir=str(root / "transformer"),
                      allow_patterns=["config.json", "pytorch_model.bin", "tokenizer.json",
                                      "tokenizer_config.json", "vocab.txt", "special_tokens_map.json"])
    lock_bytes = MODEL_LOCK_PATH.read_bytes()
    lock = json.loads(lock_bytes)
    for relative, expected in lock["files"].items():
        if _sha256(root / relative) != expected:
            raise ValueError(f"download differs from the pinned model file: {relative}")
    with identity.open("xb") as stream:
        stream.write(lock_bytes)
    (root / "provisioning.json").write_text(json.dumps(
        {"transformer": TRANSFORMER, "revision": TRANSFORMER_REVISION}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="new local model-bundle directory")
    print(prepare_bundle(parser.parse_args().directory))
