import requests
import json
import frappe
import traceback
from frappe.utils.file_manager import get_file_path


def send_to_leaseapp(doc):
    print(f"Preparing to send data to Lease App for Invoice Batch: {doc.name}")

    url = "https://uat-leasemanagementsystem.bilakhiagroup.com/api/method/leasemanagement.api.invoice_details.insert_invoice_batch_data"

    api_key = "2a10a46990ed2a6"
    api_secret = "191802208eba798"

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
    }
    # ---------- FILE PATH ----------
    excel_path = get_file_path(doc.excel_file)
    attachment_path = get_file_path(doc.invoice_attachment) if doc.invoice_attachment else None

    # ---- PREPARE ROWS ---- #
    rows_data = []

    for row in doc.rows:
        if row.status != "Success":
            continue

        if not row.invoice_date_from or not row.invoice_date_to:
            continue

        rows_data.append({
            "contract_number": row.contract_number,
            "employee_code": row.employee_name,
            "invoice_from_date": str(row.invoice_date_from) if row.invoice_date_from else "",
            "invoice_to_date": str(row.invoice_date_to) if row.invoice_date_to else "",
            "invoice_amount": row.total_invoice_value or 0,
            "cost_center": row.cost_center or "",
            "company_contribution": row.company_contribution or 0,
            "employee_contribution": row.employee_contribution or 0
        })

    payload = {
        "vendor_name": doc.vendor_name,
        "rows": frappe.as_json(rows_data),
        "batch_name": doc.name,
        "total_value_of_rental_charges": doc.total_value_of_rental_charges,
        "total_value_of_fleet_charges": doc.total_value_of_fleet_charges,
        "total_value_of_rto": doc.total_value_of_rto,
        "total_value_of_insurance": doc.total_value_of_insurance,
        "total_value_of_all": doc.total_value_of_all,
        "total_value_of_company_contribution": doc.total_value_of_company_contribution,
        "total_value_of_employee_contribution": doc.total_value_of_employee_contribution
    }
    # ---------- FILES ----------
    files = {
        "excel_file": open(excel_path, "rb")
    }

    if attachment_path:
        files["invoice_attachment"] = open(attachment_path, "rb")

    # ---- LOG DOC ---- #
    log = frappe.new_doc("API Log")
    log.api_url = url
    log.api_method = "POST"
    log.api_json_body = payload
    log.invoice_batch_doc = doc.name
    message = None

    try:
        response = requests.post(
            url,
            headers=headers,
            data=payload,
            files=files,
            timeout=60
        )

        log.status_code = response.status_code
        log.response_data = response.text

        if response.status_code == 200:
            log.status = "Success"
            try:
                res_json = response.json()
                message = res_json.get("message", {}).get("message")
            except Exception:
                message = "Success but response parsing failed"

        else:
            log.status = "Failed"
            log.error_message = response.text
            message = "API Failed"

    except Exception as e:
        log.status = "Failed"
        log.error_message = str(e)
        log.traceback = traceback.format_exc()
        message = "Exception occurred"

    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return {
        "log_name": log.name,
        "message": message,
        "status": log.status
    }