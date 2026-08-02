"""Retrieval over the local Chroma store of GLP-1 trial evidence.

The collection and the embedding model are cached at module level so the API
loads them once per process rather than once per request.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHROMA_DIR = PROJECT_ROOT / "knowledge_base" / "chroma_db"
COLLECTION_NAME = "glp1_trials"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
TOP_K = 3

_collection = None
_encoder = None

# Used when the vectorstore has not been built yet, so the messenger still has
# grounded evidence to work from instead of failing the request.
FALLBACK_CONTEXT = (
    "STEP 1 (Wilding JPH et al. N Engl J Med. 2021;384:989-1002): waist "
    "circumference fell 13.54 cm and C-reactive protein fell 44% versus placebo "
    "over 68 weeks, and those changes do not happen in a straight line.\n\n"
    "STEP 4 (Rubino D et al. JAMA. 2021;325(14):1414-1425): patients who stayed "
    "on therapy held systolic blood pressure steady while those who stopped saw "
    "it rise, a mean difference of -3.9 mmHg.\n\n"
    "SURMOUNT-1 post-hoc (Annals of Internal Medicine, doi 10.7326/annals-24-02623): "
    "HOMA-IR and HbA1c keep improving during modest weight loss, so insulin "
    "sensitivity can improve while the scale is flat."
)


def load_vectorstore():
    """Load and cache the Chroma collection and the sentence-transformers model."""
    global _collection, _encoder

    if _collection is None:
        import chromadb

        if not CHROMA_DIR.exists():
            raise FileNotFoundError(
                f"{CHROMA_DIR} not found. Run: python knowledge_base/build_vectorstore.py"
            )

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        try:
            _collection = client.get_collection(
                name=COLLECTION_NAME, embedding_function=None
            )
        except TypeError:
            _collection = client.get_collection(name=COLLECTION_NAME)

    if _encoder is None:
        # Must match the model used in build_vectorstore.py or distances are meaningless.
        _encoder = load_encoder()

    return _collection, _encoder


def load_encoder():
    """Load the embedding model, preferring the local cache when offline.

    sentence-transformers contacts the Hugging Face Hub even for a model that is
    already cached, which fails on an air-gapped or flaky network. Retrying with
    local_files_only keeps retrieval working offline once the model is cached.
    """
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(EMBEDDING_MODEL)
    except Exception as exc:
        print(f"[vectorstore] hub unreachable ({exc}); loading {EMBEDDING_MODEL} from cache.")
        return SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)


def query_trial_data(weeks_on_therapy: int, barrier_type: str) -> str:
    """Return the top trial passages for this patient's week and barrier."""
    query = (
        f"week {weeks_on_therapy} plateau non-scale victory "
        f"metabolic improvement {barrier_type}"
    )

    try:
        collection, encoder = load_vectorstore()
        query_embedding = encoder.encode([query]).tolist()
        results = collection.query(query_embeddings=query_embedding, n_results=TOP_K)
        documents = (results.get("documents") or [[]])[0]
        if not documents:
            return FALLBACK_CONTEXT
        return "\n\n".join(documents)
    except Exception as exc:
        print(f"[vectorstore] query failed ({exc}); using fallback trial context.")
        return FALLBACK_CONTEXT
