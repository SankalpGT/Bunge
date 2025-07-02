# embedding_matcher.py
import os
import traceback
from dotenv import load_dotenv
import google.generativeai as genai
import lancedb

# Load environment and configure Google API
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def get_embedding(text):
    try:
        response = genai.embed_content(
            model="models/embedding-001",
            content=text,
            task_type="RETRIEVAL_DOCUMENT",
            title="Clause or Remark"
        )
        return response["embedding"]
    except Exception as e:
        print(f"Embedding failed: {e}")
        traceback.print_exc()
        return [0.0] * 768
    
try:
    db = lancedb.connect(
    uri="db://laytimecalculation-pf59ew",
    api_key="sk_LKESM6IU6FBFPOAJE636YPCNE6IH5NCBVW3X6535ABJZL36MYZZQ====",
    region="us-east-1"
    )
except Exception as e:
    print(f"LanceDB connect error: {e}")
    db = None


def match_clause_remark_pairs(clauses, remarks, top_k=3, min_score=0.75):
    """
    Stores clause and remark embeddings in LanceDB and performs semantic search
    to find top_k remark matches for each clause, filtered by a min score.
    """
    print("1")
    # 1) Generate records with embeddings
    records = []
    for i, txt in enumerate(clauses):
        records.append({"id": i, "type": "clause", "text": txt, "vector": get_embedding(txt)})
    base = len(clauses)
    for j, txt in enumerate(remarks):
        records.append({"id": base + j, "type": "remark", "text": txt, "vector": get_embedding(txt)})

    print("3")
    if not db:
        raise RuntimeError("LanceDB connection not available; hybrid search cannot proceed.")
    print("4")
    # 2) Create or get remote table
    table_name = "laytime_pairs"
    try:
        print("5")
        # Attempt to create the table anew with all records
        table = db.create_table(table_name, data=records)
    except Exception:
        print("6")
        # If it already exists, open and append
        table = db.open_table(table_name)
        table.add(records)

    # # 3) Semantic search: for each clause, find top-k remarks
    # pairs = []
    # for rec in records[:len(clauses)]:  # only clauses
    #     clause_vec = rec["vector"]
    #     # Perform vector search for top_k results
    #     search_builder = table.search(clause_vec, vector_column="vector", limit=top_k)
    #     arrow_table = search_builder.to_arrow()
    #     hits = arrow_table.to_pylist()
    #     for hit in hits:
    #         # Only consider remark rows
    #         if hit.get("type") != "remark":
    #             continue
    #         score = hit.get("_score", 0)
    #         if score >= min_score:
    #             pairs.append({
    #                 "clause":         rec["text"],
    #                 "remark":         hit["text"],
    #                 "combined_score": round(score, 4)
    #             })

    try:
        print("7")
        table.create_fts_index("text")
    except Exception:
        print("8")
        pass

    # 3) Execute hybrid search per clause
    pairs = []
    for rec in records[base:]:
        remark_txt = rec["text"]
        hits = (
                table
                .search(
                    remark_txt,
                    top_k,
                    query_type="hybrid"
                )
                .limit(top_k)
                .to_arrow()
                .to_pylist()
            )
        print(rec)
        for hit in hits:
            if hit.get("type") != "clause":
                continue
            score = hit.get("_score", 0.0)
            if score >= min_score:
                pairs.append({
                    "clause": rec["text"],
                    "remark": hit["text"],
                    "combined_score": round(score, 4)
                })
            print(hit)
    print("9")
    return pairs
