# app.py

import streamlit as st
import tempfile
import os, time
import json
from datetime import datetime
from extractor import extract_with_gemini

st.set_page_config(page_title="Gemini OCR Agent", layout="wide")
st.title("📄 Gemini PDF OCR Agent")

# Upload section
uploaded_file = st.file_uploader("Upload a scanned PDF", type=["pdf"])

# API key input (optional)
if not os.getenv("GOOGLE_API_KEY"):
    api_key = st.text_input("Enter your Google API Key", type="password")
    if api_key:
        os.environ["GOOGLE_API_KEY"] = api_key

if uploaded_file:
    st.info("Click 'Extract' to process the uploaded PDF using Gemini.")
    if st.button("Extract"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name

        with st.spinner("🔍 Extracting structured data using Gemini..."):
            start_time = time.time()
            extracted_json, raw_output = extract_with_gemini(tmp_path)
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{uploaded_file.name.replace('.pdf', '')}_{timestamp}.json"
        output_dir = "storage"
        os.makedirs(output_dir, exist_ok=True)

        output_path = os.path.join(output_dir, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(extracted_json, f, indent=2)

        st.success(f"✅ Extraction Complete! Time taken: {duration} seconds")
        st.download_button("📥 Download JSON", data=json.dumps(extracted_json, indent=2), file_name=filename, mime="application/json")
        st.subheader("📦 Preview of Extracted JSON")
        st.json(extracted_json)

# Past Extractions
st.divider()
st.subheader("📁 View Previous Extractions")

storage_dir = "storage"
if os.path.exists(storage_dir):
    files = sorted([f for f in os.listdir(storage_dir) if f.endswith(".json")], reverse=True)
    if files:
        selected_file = st.selectbox("Choose a file to view", files)
        if selected_file:
            with open(os.path.join(storage_dir, selected_file), "r") as f:
                st.json(json.load(f))
    else:
        st.write("No previous extractions found.")
else:
    st.write("Storage directory not found.")
