from __future__ import annotations

from typing import List

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from modules.llm import get_llm


PROMPT = ChatPromptTemplate.from_template(
    """
You are an expert business requirements analyst.

Answer the user's question using ONLY the information contained in the
provided context.

Your primary goal is to produce a CORRECT and COMPLETE answer.

Rules:

1. Use only the provided context as your source of truth.
2. Do not use outside knowledge.
3. Do not invent, assume, or infer facts that are not supported by the context.
4. Read ALL provided context before answering. Relevant information may be
   spread across multiple chunks.
5. Combine information from multiple chunks when necessary to answer the
   question correctly.
6. Include ALL relevant information from the context that directly answers
   the question. Do not omit an item just because it appears in another
   section or in plain text rather than a table.
7. Preserve exact names, IDs, numbers, percentages, priorities, values, and
   terminology from the context.
8. Do not confuse different categories of information. For example:
   business objectives are not business rules, risks are not requirements,
   and permissions are not user roles.
9. If the question asks for a specific category and that category is not
   explicitly present in the context, say so clearly instead of substituting
   a related category.
10. If the context contains only partial information, provide the supported
    information and clearly state what is not specified.
11. Do not create a fact merely because it would be reasonable or typical
    for a business requirements document.
12. If the context does not contain enough information to answer the
    question, say:
    "The provided context does not contain enough information to answer this."
13. Keep the answer focused on the question. Do not discuss your reasoning
    process.
14. Before answering, check every retrieved chunk for information relevant
    to the question. Do not stop after finding the first plausible answer.
15. Never assign an actor, role, permission, or relationship unless that
    relationship is explicitly supported by the context. The existence of
    a role and a functional requirement does not prove that the role
    performs that function.
16. When summarizing, do not omit relevant information that is explicitly
    present in the context, even if it appears in a different chunk.

Context:
{context}

Question:
{question}

Answer:
"""
)
def generate_answer(
    question: str,
    documents: List[Document],
) -> str:
    """Generate a grounded answer from retrieved documents."""
    if not documents:
        return (
            "The provided documents do not contain enough "
            "information to answer this."
        )

    context_parts: List[str] = []

    for index, document in enumerate(documents, start=1):
        context_parts.append(
            f"""
--- Context {index} ---
{document.page_content}
"""
        )

    context = "\n".join(context_parts)

    llm = get_llm()

    chain = PROMPT | llm

    response = chain.invoke(
        {
            "context": context,
            "question": question,
        }
    )

    return response.content