import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


def parse_message_with_ai(message):
    """
    Strict invoice item extraction. AI must NOT guess client data, HSN, GST or tax type.
    Only extract: sl, description, qty, rate.
    """

    prompt = f"""
You are an invoice line-item extraction engine.

The user will describe items in natural language.
Extract ONLY what is explicitly stated:
✅ sl (serial number: index them automatically 1,2,3,…)
✅ description (product name)
✅ qty (integer)
✅ rate (price per unit if clearly mentioned)

❌ DO NOT guess:
- HSN
- GST or tax type
- Address or client info
- Any field not explicitly stated

If rate is not given, return null for rate.
If qty not given, return 1 as default.

Format:
{{
  "items": [
    {{"sl": 1, "description": "Item", "qty": 2, "rate": 50}},
    ...
  ]
}}

Respond with ONLY JSON. No text outside JSON.

User Message:
"{message}"
"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "groq/llama3-70b-8192",  # Updated model name — recommended
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }

    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=data, timeout=12)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]

        # Extract JSON only
        start = content.find("{")
        end = content.rfind("}") + 1
        parsed_data = json.loads(content[start:end])

        # Ensure schema correctness + add HSN placeholder
        for item in parsed_data.get("items", []):
            item.setdefault("hsn", None)
            item["sl"] = parsed_data["items"].index(item) + 1

        return parsed_data

    except Exception as e:
        print("AI parsing error:", e)
        return {"items": []}
