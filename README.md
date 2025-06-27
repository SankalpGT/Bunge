# 📄 Gemini-Powered Project

## Current Features

- 📤 Upload any scanned or digital PDF
- 🤖 Extract:
  - Key-value pairs  
  - Hierarchical sections and sub-clauses  
  - Event logs, tables, and lists  
  - Named entities (dates, parties, quantities, ports, etc.)
- 💾 Save extractions for later viewing
- 🌐 Web UI or CLI usage
- 🔐 Secure Google API key input

---

## 🛠️ Setup Instructions (for All Users)

### ✅ Prerequisites

- Python 3.9 or higher  
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)  
- Poppler (for `pdf2image`)  
- A **Google Cloud API key** with Gemini access  
- Vertex AI API enabled on your GCP project  

---

### 1. Clone This Repository

```bash
git clone "https://github.com/GarimaPrachiGT/pdf-gemini-extractor.git"
cd pdf-gemini-extractor
```

### 2. Create and Activate a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # For Windows: venv\Scripts\activate
```

### 3. Install All Required Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Up Your Google Gemini API Key

You have three options:

A. Create a .env file:
    GOOGLE_API_KEY=your-google-api-key-here

B. Enter it manually in the Streamlit app when prompted

C. Export in bash

```bash
export GOOGLE_API_KEY="your-google-api-key-here"
```

Get your API key from:
👉 https://makersuite.google.com/app/apikey

### 5. Enable Vertex AI API on Your Google Cloud Project

```bash
gcloud auth application-default login
gcloud config set project your-project-id
gcloud services enable aiplatform.googleapis.com
```

## How to Run

### Streamlit Web App

```bash
streamlit run app.py
```
