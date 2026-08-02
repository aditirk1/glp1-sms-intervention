"""Build the local Chroma vectorstore of GLP-1 trial evidence.

Chunks the trial text files at paragraph level, embeds them with a local
sentence-transformers model, and persists them to knowledge_base/chroma_db/.
No API key and no network account are required.

Run:  python knowledge_base/build_vectorstore.py
"""

import shutil
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent
CHROMA_DIR = KB_DIR / "chroma_db"
COLLECTION_NAME = "glp1_trials"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
MIN_CHUNK_CHARS = 40

SOURCE_FILES = ["step_trials.txt", "surmount_trials.txt"]


def load_chunks() -> tuple[list[str], list[dict], list[str]]:
    """Split each trial file on blank lines into paragraph-sized chunks."""
    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []

    for filename in SOURCE_FILES:
        path = KB_DIR / filename
        if not path.exists():
            raise SystemExit(f"Missing knowledge base file: {path}")

        text = path.read_text(encoding="utf-8")
        paragraphs = [chunk.strip() for chunk in text.split("\n\n")]
        kept = [chunk for chunk in paragraphs if len(chunk) >= MIN_CHUNK_CHARS]

        for index, chunk in enumerate(kept):
            documents.append(chunk)
            metadatas.append({"source": filename, "chunk_index": index})
            ids.append(f"{path.stem}-{index}")

        print(f"  {filename}: {len(kept)} chunks kept ({len(paragraphs)} paragraphs)")

    return documents, metadatas, ids


def load_encoder():
    """Download the embedding model, or reuse the local cache when offline."""
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(EMBEDDING_MODEL)
    except Exception as exc:
        print(f"  hub unreachable ({exc}); loading from local cache.")
        return SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)


def main() -> None:
    import chromadb

    print("Chunking knowledge base files...")
    documents, metadatas, ids = load_chunks()

    print(f"Loading embedding model {EMBEDDING_MODEL}...")
    encoder = load_encoder()
    embeddings = encoder.encode(documents, show_progress_bar=False).tolist()

    # Rebuild from scratch so re-running never leaves stale chunks behind.
    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        # Embeddings are supplied explicitly, so Chroma needs no embedder of its own.
        collection = client.create_collection(
            name=COLLECTION_NAME, embedding_function=None
        )
    except Exception:
        collection = client.create_collection(name=COLLECTION_NAME)

    collection.add(
        ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings
    )

    print(
        f"Vectorstore built with {len(documents)} chunks "
        f"from {len(SOURCE_FILES)} files"
    )
    print(f"Persisted to {CHROMA_DIR}")


if __name__ == "__main__":
    main()
