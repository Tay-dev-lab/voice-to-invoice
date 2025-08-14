def get_prompt_for_step(step: str, transcript: str) -> str:
    if step == "invoice_type":
        return f"What type of invoice is being requested here?\n\nVoice:\n{transcript}\n\nOnly return one word: 'deposit' or 'works_completed'."
    elif step == "client_info":
        return f"Extract the client's name and address from the voice input below:\n\n{transcript}\n\nReturn as JSON: {{\"name\": \"...\", \"address\": \"...\"}}"
    elif step == "item_description":
        return f"Extract the description of the invoice item:\n\n{transcript}\n\nReturn as plain text."
    elif step == "item_value":
        return f"What is the value of this invoice item?\n\n{transcript}\n\nReturn a number only."
    elif step == "item_vat":
        return f"Is VAT applicable? If so, what is the VAT rate (as a number)?\n\n{transcript}\n\nReturn {{\"vat_rate\": 20.0}} or {{\"vat_rate\": 0.0}}"
    elif step == "item_cis":
        return f"Is CIS applicable? If so, what rate?\n\n{transcript}\n\nReturn {{\"cis_rate\": 20.0}} or {{\"cis_rate\": 0.0}}"
    elif step == "item_retention":
        return f"Is retention applicable? What rate?\n\n{transcript}\n\nReturn {{\"retention_rate\": 5.0}} or {{\"retention_rate\": 0.0}}"
    elif step == "item_discount":
        return f"Is any discount applied? What rate?\n\n{transcript}\n\nReturn {{\"discount_rate\": 10.0}} or {{\"discount_rate\": 0.0}}"
    elif step == "add_another":
        return f"Should we add another item or generate the invoice?\n\n{transcript}\n\nReturn 'add' or 'submit'."
    else:
        return "Invalid step"