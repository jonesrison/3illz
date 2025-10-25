import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
print(os.getenv("GROQ_API_KEY"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

def parse_message_with_ai(message):
    """
    Uses Groq (Llama-3) to extract structured invoice data from user message.
    The user can write naturally like:
    'Add 3 soaps for ₹50 each and 2 shampoos for ₹120 each.'
    """
    prompt = f"""
    You are an expert invoice data parser.
    The user will describe items in natural language.

    Extract all products mentioned with:
    - Serial number (sl)
    - Description
    - HSN (if known, else guess or use '0000')
    - Quantity (qty)
    - Rate (price per unit)

    Return ONLY a valid JSON like this:
    {{
      "items": [
        {{"sl": 1, "description": "Soap", "hsn": "3401", "qty": 3, "rate": 50}},
        {{"sl": 2, "description": "Shampoo", "hsn": "3305", "qty": 2, "rate": 120}}
      ],
      "gst_rate": 18
    }}

    Message: "{message}"
    """

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }

    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=data, timeout=15)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        # Extract JSON
        start = content.find("{")
        end = content.rfind("}") + 1
        json_str = content[start:end]
        parsed = json.loads(json_str)
        return parsed
    except Exception as e:
        print("AI parsing error:", e)
        return {"items": [], "gst_rate": 18}
