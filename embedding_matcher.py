# embedding_matcher.py
import os
import traceback
from dotenv import load_dotenv
import google.generativeai as genai
from lancedb.table import LanceTable
import lancedb
import time
import uuid

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
    uri="db://laytime-a1cksj",
    api_key="sk_BIS2K7WWEVF47AT4B4KSYBBCNZDBU4K5ZT6BTHZ676AG3QJW7TZQ====",
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
    # 1) Generate records with embeddings
    records = []
    for i, txt in enumerate(clauses):
        records.append({"id": i, "type": "clause", "text": txt, "vector": get_embedding(txt)})
    base = len(clauses)
    for j, txt in enumerate(remarks):
        records.append({"id": base + j, "type": "remark", "text": txt, "vector": get_embedding(txt)})

    if not db:
        raise RuntimeError("LanceDB connection not available; hybrid search cannot proceed.")

    # 2) Create or get remote table
    # table_name = "laytime_pairs"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    table_name = f"laytime_pairs_{timestamp}_{uuid.uuid4().hex[:6]}" 

    try:
        # Attempt to create the table anew with all records
        table = db.create_table(table_name, data=records)
    except Exception:
        # If it already exists, open and append
        table = db.open_table(table_name)
        table.add(records)

    try:
        # table.create_fts_index("text")
        table.create_fts_index("text")
        table.wait_for_index(["text_idx"])
        print(f"✅ FTS index created for {table_name}")
    except Exception as e:
        print(f"❌ Failed to create FTS index: {e}")

    pairs = []
    for rec in records[len(clauses):]:  # only remarks
        # Perform vector search for top_k results

        try:
            search_builder = (
                table.search(query_type="hybrid", fast_search=True)
                .vector(rec["vector"])
                .text(rec["text"])
                .distance_type("cosine")
                .limit(top_k)
            )
            arrow_table = search_builder.to_arrow()
            hits = arrow_table.to_pandas()

        except Exception as e:
            print(f"⚠️ Hybrid search failed: {e} — falling back to vector only.")
            search_builder = (
                table.search(rec["vector"])
                .distance_type("cosine")
            )
            arrow_table = search_builder.to_arrow()
            hits = arrow_table.to_pandas()
        for _, hit in hits.iterrows():
            # Only consider remark rows
            if hit["type"] != "clause":
                continue

            score = hit.get("_relevance_score")
            # if score >= min_score:
            pairs.append({
                "remark":         rec["text"],
                "clause":         hit["text"],
                "score":          round(1.0 - score, 4)
            })

    return pairs