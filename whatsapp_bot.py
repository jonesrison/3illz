from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
import os, uuid, json
from dotenv import load_dotenv
from billz import calculate_totals, generate_invoice, TAX_TYPE_CGST_SGST
from ai_parser import parse_message_with_ai

load_dotenv()
app = Flask(__name__)

DATA_DIR = "data"
CLIENT_FILE = os.path.join(DATA_DIR, "clients.json")
INVOICE_DIR = "invoices"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(INVOICE_DIR, exist_ok=True)

user_sessions = {}  # temporary per-chat session


def load_clients():
    if not os.path.exists(CLIENT_FILE):
        return {}
    with open(CLIENT_FILE, "r") as f:
        return json.load(f)


def save_clients(data):
    with open(CLIENT_FILE, "w") as f:
        json.dump(data, f, indent=2)


@app.route("/whatsapp", methods=["POST"])
def whatsapp_bot():
    sender = request.form.get("From")
    message = request.form.get("Body", "").strip().lower()
    response = MessagingResponse()
    session = user_sessions.get(sender, {})
    clients = load_clients()

    # Step 1: Start
    if message in ["hi", "hello", "start"]:
        user_sessions[sender] = {}
        response.message("👋 Hi! Let's create an invoice.\nPlease tell me the *client name*.")
        return str(response)

    # Step 2: Get client name
    if "client_name" not in session:
        name = message.strip().title()
        session["client_name"] = name
        if name in clients:
            session.update(clients[name])
            response.message(f"📍 Found saved client: *{name}*\nAddress: {session['client_address']}\nGST: {session.get('gst_number', 'N/A')}\n\nNow tell me the *items* (e.g. '3 soaps ₹50 each and 2 shampoos ₹120 each').")
        else:
            response.message("Please enter the client address:")
        user_sessions[sender] = session
        return str(response)

    # Step 3: Address input
    if "client_address" not in session:
        session["client_address"] = message.strip()
        user_sessions[sender] = session
        response.message("✅ Address saved.\nNow tell me the *items and quantities* (e.g. '2 pens ₹10 each and 3 notebooks ₹50 each').")
        return str(response)

    # Step 4: Parse items with AI (if not parsed yet)
    if "items" not in session and "pending_confirmation" not in session:
        ai_parsed = parse_message_with_ai(message)
        if not ai_parsed["items"]:
            response.message("❌ Sorry, I couldn’t detect any valid items. Try describing again (e.g. '2 shirts ₹500 each').")
            return str(response)

        session["parsed_items"] = ai_parsed["items"]
        session["gst_rate"] = ai_parsed.get("gst_rate", 18)
        session["pending_confirmation"] = True
        user_sessions[sender] = session

        # Create readable summary for user
        summary = "\n".join(
            [f"{i['sl']}. {i['description']} – {i['qty']} × ₹{i['rate']} (HSN: {i['hsn']})" for i in ai_parsed["items"]]
        )
        response.message(f"📦 I found these items:\n{summary}\n\nGST: {ai_parsed.get('gst_rate', 18)}%\n\nShall I generate the invoice? (yes/no)")
        return str(response)

    # Step 5: Handle confirmation
    if session.get("pending_confirmation"):
        if message in ["yes", "y", "confirm"]:
            session["items"] = session.pop("parsed_items")
            session.pop("pending_confirmation", None)
            session["invoice_no"] = f"INV-{uuid.uuid4().hex[:6].upper()}"
            session["date"] = datetime.now().strftime("%d-%m-%Y")
            session["tax_type"] = TAX_TYPE_CGST_SGST

            totals = calculate_totals(session["items"], tax_type=session["tax_type"], gst_rate=session["gst_rate"])
            session["totals"] = totals

            output_file = f"Invoice_{session['invoice_no']}.docx"
            output_path = os.path.join(INVOICE_DIR, output_file)
            generate_invoice("Invoice_Template.docx", output_path, session)
            file_url = f"{request.url_root}invoices/{output_file}"

            # Save client data
            clients[session["client_name"]] = {
                "client_address": session["client_address"],
                "gst_number": session.get("gst_number", "")
            }
            save_clients(clients)

            response.message(f"✅ Invoice generated successfully!\n🧾 Download here: {file_url}")
            user_sessions.pop(sender, None)
            return str(response)

        elif message in ["no", "n", "cancel"]:
            session.pop("pending_confirmation", None)
            session.pop("parsed_items", None)
            response.message("Okay, please re-enter the item details correctly:")
            user_sessions[sender] = session
            return str(response)
        else:
            response.message("Please reply *yes* or *no* to confirm invoice generation.")
            return str(response)

    # Default fallback
    response.message("⚠️ Please type 'start' to begin a new invoice.")
    return str(response)


if __name__ == "__main__":
    app.run(port=5000, debug=True)
