from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

from modules.config import EMBEDDING_MODEL


BASE_DIR = Path(__file__).resolve().parent
KB_DIR = BASE_DIR / "data" / "knowledge_bases" / "active"


def load_knowledge_base() -> FAISS:
    """Load the persisted FAISS knowledge base."""
    if not KB_DIR.exists():
        raise FileNotFoundError(f"Knowledge base not found: {KB_DIR}")

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )

    return FAISS.load_local(
        str(KB_DIR),
        embeddings,
        allow_dangerous_deserialization=True,
    )


def check_gap_chunks(vector_store: FAISS) -> None:
    """Find and print DRS/Jira gap-analysis chunks stored in the KB."""
    docstore = vector_store.docstore

    gap_documents = []

    for doc_id, document in docstore._dict.items():
        metadata = document.metadata or {}
        content = document.page_content or ""

        is_gap_document = (
            metadata.get("source_type") == "gap_analysis"
            or "gaps/missing informations in the BRD" in content
        )

        if is_gap_document:
            gap_documents.append((doc_id, document))

    print("=" * 80)
    print("GAP CHUNK CHECK")
    print("=" * 80)
    print(f"KB path      : {KB_DIR}")
    print(f"Total chunks : {len(docstore._dict)}")
    print(f"Gap chunks   : {len(gap_documents)}")
    print()

    if not gap_documents:
        print("❌ NO GAP CHUNKS FOUND IN THE ACTIVE KB.")
        print()
        print("Expected text:")
        print("content: gaps/missing informations in the BRD")
        return

    print("✅ GAP CHUNK(S) FOUND IN THE ACTIVE KB.")
    print()

    for index, (doc_id, document) in enumerate(gap_documents, start=1):
        print("-" * 80)
        print(f"Gap chunk #{index}")
        print(f"Document ID : {doc_id}")
        print(f"Metadata    : {document.metadata}")
        print()
        print("Page content:")
        print(document.page_content)
        print()

        artifact_type = document.metadata.get("artifact_type")

        if artifact_type == "drs":
            print("✅ This is the DRS gap chunk.")
        elif artifact_type == "jira":
            print("✅ This is the Jira gap chunk.")
        else:
            print(f"⚠️ Artifact type: {artifact_type}")

        print("-" * 80)


def main() -> None:
    try:
        vector_store = load_knowledge_base()
        check_gap_chunks(vector_store)
    except Exception as exc:
        print(f"❌ Error: {exc}")


if __name__ == "__main__":
    main()