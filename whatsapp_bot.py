from flask import Flask, request, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
from num2words import num2words
import os, json
from dotenv import load_dotenv
from billz import calculate_totals, generate_invoice, TAX_TYPE_CGST_SGST, TAX_TYPE_IGST
from ai_parser import parse_message_with_ai

load_dotenv()
app = Flask(__name__)

DATA_DIR = "data"
CLIENT_FILE = os.path.join(DATA_DIR, "clients.json")
SESSION_FILE = os.path.join(DATA_DIR, "sessions.json")
INVOICE_DIR = "invoices"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(INVOICE_DIR, exist_ok=True)


# ✅ SESSION UTILITIES — Persistent JSON store
def load_sessions():
    if not os.path.exists(SESSION_FILE):
        return {}
    try:
        with open(SESSION_FILE, "r") as f:
            return json.load(f)
    except:
        return {}  # fallback if corrupted


def save_sessions(sessions):
    with open(SESSION_FILE, "w") as f:
        json.dump(sessions, f, indent=2)


def get_session(phone):
    sessions = load_sessions()
    if phone not in sessions:
        sessions[phone] = {}
        save_sessions(sessions)
    return sessions


def update_session(phone, data):
    sessions = load_sessions()
    sessions[phone] = {**sessions.get(phone, {}), **data}
    save_sessions(sessions)


def clear_session(phone):
    sessions = load_sessions()
    if phone in sessions:
        del sessions[phone]
        save_sessions(sessions)


# ✅ CLIENT DATA UTILS
def load_clients():
    if not os.path.exists(CLIENT_FILE):
        return {}
    try:
        with open(CLIENT_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_clients(data):
    with open(CLIENT_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ✅ Invoice download endpoint
@app.route("/invoices/<path:filename>")
def download_invoice(filename):
    return send_from_directory(INVOICE_DIR, filename, as_attachment=True)


@app.route("/", methods=["POST"])
def whatsapp_bot():
    sender = request.form.get("From")
    message = request.form.get("Body", "").strip()
    response = MessagingResponse()

    clients = load_clients()
    sessions = load_sessions()
    session = sessions.get(sender, {})

    # STEP 1 → Initialize
    if message.lower() in ["hi", "hello", "start"]:
        clear_session(sender)
        update_session(sender, {})
        response.message("👋 Hey! Let's make an invoice.\nWho is the *client*?")
        return str(response)

    # STEP 2 → Capture client name
    if "client_name" not in session:
        name = message.title()
        session["client_name"] = name

        if name in clients:
            c = clients[name]
            session.update(c)
            response.message(
                f"✅ Saved Client Found:\n"
                f"Name: *{name}*\n"
                f"Address: {c['client_address']}\n"
                f"GST: {c.get('gst_number', 'N/A')}\n"
                f"Tax: {c.get('tax_type', TAX_TYPE_CGST_SGST)}"
                "\n\nUse these details? *(yes/change)*"
            )
            session["awaiting_client_choice"] = True
        else:
            response.message("Cool — drop the client address:")
        update_session(sender, session)
        return str(response)

    # STEP 3 → Choose saved or edit
    if session.get("awaiting_client_choice"):
        if message.lower() in ["yes", "y"]:
            session.pop("awaiting_client_choice", None)
            response.message("🔥 Nice. Give me an *invoice number* (ex: INV-2005)")
        elif message.lower() in ["change", "c"]:
            session.pop("awaiting_client_choice", None)
            session.pop("client_address", None)
            response.message("Alright — new address, please:")
        else:
            response.message("Just reply *(yes)* or *(change)* bro 😄")
        update_session(sender, session)
        return str(response)

    # STEP 4 → Handle Address / GST / Tax
    if "client_address" not in session:
        session["client_address"] = message
        response.message("GST number? *(or 'skip')*")
        update_session(sender, session)
        return str(response)

    if "gst_number" not in session:
        session["gst_number"] = "" if message.lower() == "skip" else message
        response.message("Same state? *(yes = CGST+SGST / no = IGST)*")
        update_session(sender, session)
        return str(response)

    if "tax_type" not in session:
        session["tax_type"] = TAX_TYPE_CGST_SGST if message.lower() in ["yes", "y"] else TAX_TYPE_IGST
        response.message("Invoice number please 😎")
        update_session(sender, session)
        return str(response)

    # STEP 5 → Invoice number
    if "invoice_no" not in session:
        session["invoice_no"] = message.upper()
        session["awaiting_item_input"] = True
        response.message("Now add items:\n👉 Example: *3 pens 10 each*")
        update_session(sender, session)
        return str(response)

    # ✅ STEP 6 → Item Parsing
    if session.get("awaiting_item_input"):
        parsed = parse_message_with_ai(message)
        if not parsed.get("items"):
            response.message("Couldn’t find items 🥲 Try like:\n*2 shirts 500 each*")
            return str(response)

        if "parsed_items" not in session:
            session["parsed_items"] = []

        start = len(session["parsed_items"]) + 1
        for i, item in enumerate(parsed["items"], start):
            item["sl"] = i
            item.setdefault("hsn", "")
            session["parsed_items"].append(item)

        session.pop("awaiting_item_input")
        session["awaiting_discount"] = True
        response.message("Discount %? *(0 for none)*")
        update_session(sender, session)
        return str(response)

    # ✅ STEP 7 → Discount
    if session.get("awaiting_discount"):
        try:
            session["parsed_items"][-1]["discount"] = float(message)
        except:
            session["parsed_items"][-1]["discount"] = 0.0

        session.pop("awaiting_discount")
        session["adding_items_confirmation"] = True
        response.message("Add more items? *(yes/no)*")
        update_session(sender, session)
        return str(response)

    # ✅ STEP 8 → Confirm item addition
    if session.get("adding_items_confirmation"):
        if message.lower() in ["yes", "y"]:
            session.pop("adding_items_confirmation")
            session["awaiting_item_input"] = True
            response.message("Send next item:")
        elif message.lower() in ["no", "n"]:
            session.pop("adding_items_confirmation")
            session["pending_confirmation"] = True
            summary = "\n".join([f"{i['sl']}. {i['description']} — {i['qty']}×₹{i['rate']} (-{i.get('discount',0)}%)" for i in session["parsed_items"]])
            total_preview = sum(i["qty"] * i["rate"] * (1 - i.get("discount",0)/100) for i in session["parsed_items"])
            response.message(f"🧾 Invoice Preview:\n{summary}\n\nTotal: ₹{total_preview:.2f}\n(confirm/edit/cancel)")
        else:
            response.message("Just *(yes)* or *(no)* please 😄")
        update_session(sender, session)
        return str(response)

    # ✅ STEP 9 → Final Confirmation
    if session.get("pending_confirmation"):
        if message.lower() in ["confirm", "yes", "y"]:
            session["items"] = session.pop("parsed_items")
            totals = calculate_totals(session["items"], session["tax_type"], 18)
            session["totals"] = totals
            session["date"] = datetime.now().strftime("%d-%m-%Y")
            session["amount_in_words"] = num2words(totals["total"], to="currency", lang="en_IN").title()

            output_file = f"{session['invoice_no']}.docx"
            output_path = os.path.join(INVOICE_DIR, output_file)
            generate_invoice("Invoice_Template.docx", output_path, session)

            # 🔗 Live Download Link
            file_url = f"{request.url_root}invoices/{output_file}"

            clients[session["client_name"]] = {
                "client_address": session["client_address"],
                "gst_number": session["gst_number"],
                "tax_type": session["tax_type"]
            }
            save_clients(clients)

            clear_session(sender)
            response.message(f"✅ Invoice Created!\nDownload: {file_url}")

        elif message.lower() in ["edit", "e"]:
            session.pop("pending_confirmation")
            session["parsed_items"] = []
            session["awaiting_item_input"] = True
            response.message("Cool — editing mode. Re-send all items 👇")

        elif message.lower() in ["cancel", "n", "no"]:
            clear_session(sender)
            response.message("🚫 Cancelled. Type *start* if you want a fresh one.")
        else:
            response.message("Say *(confirm)*, *(edit)*, or *(cancel)*")
        update_session(sender, session)
        return str(response)

    response.message("Bruh idk what’s happening 🤨 Just type *start* again.")
    return str(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
