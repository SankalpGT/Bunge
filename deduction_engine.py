import google.generativeai as genai

model = genai.GenerativeModel("models/gemini-1.5-flash-latest")

def get_deduction(clause, remark):
    prompt = f"""
Given the clause: \"{clause}\"
And the operational remark: \"{remark}\"
Return output in JSON format:
{{
  \"type\": \"deduction\" | \"exemption\" | \"none\",
  \"justification\": \"brief explanation\"
}}
"""
    response = model.generate_content(prompt)
    raw = response.text.strip()
    json_start = raw.find("{")
    json_end = raw.rfind("}") + 1
    return json.loads(raw[json_start:json_end])