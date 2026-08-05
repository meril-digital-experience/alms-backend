# Copyright (c) 2026, Rishi Hingad

from frappe import config
from frappe.model.document import Document
import frappe
from frappe.recorder import status
from frappe.utils.file_manager import get_file
from frappe.utils import getdate, user
from frappe import _
import io
from frappe.utils import now_datetime
from frappe.model.naming import make_autoname
from alms_app.api.send_to_leaseapp import send_to_leaseapp
from alms_app.api.emailClass import EmailServices
from frappe.utils.file_manager import get_file_path
from frappe.utils import get_url

class InvoiceBatch(Document):

    ROLE_TO_DESIGNATION = {
        "finance_team": "Finance2",
        "finance_head": "Finance Head",
        "hr_head": "HR Head"
    }

    def autoname(self):
        now = now_datetime()

        year = now.strftime("%Y")
        month = now.strftime("%m")

        vendor = (self.vendor_name or "NA").replace(" ", "")

        prefix = f"IB-{vendor}-{year}-{month}-"

        self.name = make_autoname(prefix + ".#####")

    def before_insert(self):
        self.is_submitted = 1

    def after_insert(self):
        # Do not trigger approval on creation, wait for successful processing
        pass

    def on_update(self):
        if self.excel_sheet_status in ["Completed", "Partially Completed"] and not self.get("approval_initiated"):
            try:
                from mds_master.mds_approval.approval_router import trigger_approval_if_matrix_exists
                trigger_approval_if_matrix_exists(self)
            except Exception as e:
                frappe.log_error(str(e), "trigger_approval_if_matrix_exists fallback")




# -----------------------------
# Helpers
# -----------------------------

def clean_amount(val):
    if not val:
        return 0
    return float(str(val).replace(",", "").strip())


def clean_date(val):
    if not val:
        return None
    return getdate(val)


def get_total(row):
    return (
        (row.invoice_value_a or 0)
        + (row.invoice_value_b or 0)
        + (row.invoice_value_c or 0)
        + (row.invoice_value_d or 0)
    )

VENDOR_CONFIG = {

    "Eazy Assets": {
        "required_columns": [
            "Contract No.", "Installment No.", "Billing Date"
        ],

        "field_map": {
            "contract_number": "Contract No.",
            "employee_name": "Employee Name",
            "vehicle_details": "Vehicle Details",

            "installment_no": "Installment No.",
            "billing_date": "Billing Date",

            "invoice_date_from": "Invoice date from",
            "invoice_date_to": "Invoice date to",

            "invoice_no_rental": "Rental Invoice No.",
            "invoice_value_a": "Invoice Value ( A)",

            "invoice_no_fleet": "Fleet Invoice No",
            "invoice_value_b": "Invoice Value ( B)",

            "invoice_no_road": "Road Invoice No.",
            "invoice_value_c": "Invoice Value ( C)",

            "invoice_no_insurance": "Insurance Invoice No.",
            "invoice_value_d": "Invoice Value ( D)",
        },

        "has_insurance": True,
        "use_billing_date": True,
        "use_month_for_period": False
    },

    "ALD": {
        "required_columns": [
            "Contract No.", "Inst. No.", "Month"
        ],

        "field_map": {
            "contract_number": "Contract No.",
            "employee_name": "Emp. Name",
            "vehicle_details": "Vehicle Details",
            "month": "Month",

            "installment_no": "Inst. No.",

            "invoice_no_rental": "Inv.No.",
            "invoice_date_rental": "Inv.Date",
            "invoice_value_a": "Inv.Value (A)",

            "invoice_no_fleet": "Inv.No.",
            "invoice_date_fleet": "Inv.Date",
            "invoice_value_b": "Inv.Value (B)",

            "invoice_no_road": "Inv.No.",
            "invoice_date_road": "Inv.Date",
            "invoice_value_c": "RTO ( C )",
        },

        "has_insurance": False,
        "use_billing_date": False,
        "use_month_for_period": True
    }
}

def map_row(row, config):
    mapped = {}

    for field, col in config["field_map"].items():
        val = row.get(col)

        if "value" in field:
            val = clean_amount(val)

        mapped[field] = val

    return mapped


def get_installment_dates(contract_number, installment_no, month=None):

    children = frappe.get_all(
        "Installment Details",
        filters={"parent": contract_number},
        fields=[
            "installment_no",
            "installment_start_date",
            "installment_end_date",
            "month"
        ]
    )

    for row in children:

        # match by installment_no
        if str(row.installment_no) == str(installment_no):
            return row.installment_start_date, row.installment_end_date

        # match by month (properly)
        if month and row.month:
            try:
                if getdate(row.month).month == getdate(month).month:
                    return row.installment_start_date, row.installment_end_date
            except:
                pass

    return None, None


def create_invoice_details_on_approval(doc, method):
    print("Checking conditions for creating Invoice Details from Invoice Batch:", doc.name)
    frappe.logger().info(f"Creating invoices for batch {doc.name}")

    if (doc.hr_head_status != "Approved" or doc.excel_sheet_status != "Completed"):
        return
    
    config = VENDOR_CONFIG.get(doc.vendor_name)
    created_count = 0

    for row in doc.rows:

        if row.status != "Success":
            continue

        if frappe.db.exists("Invoice Details", {
            "contract_number": row.contract_number,
            "installment_no": row.installment_no
        }):
            continue

        inv = frappe.new_doc("Invoice Details")
        inv.vendor_name = doc.vendor_name

        # Contract data (single DB hit)
        contract_data = frappe.db.get_value(
            "Contract Master",
            row.contract_number,
            ["employee_car_process_form", "contract_end_date"],
            as_dict=True
        )

        if contract_data:
            inv.employee_name = contract_data.employee_car_process_form
            inv.contract_end_date = contract_data.contract_end_date

        for field in config["field_map"].keys():
            if hasattr(row, field):
                setattr(inv, field, getattr(row, field))

        # ---- PERIOD FIX ---- #
        if config.get("use_month_for_period"):

            start_date, end_date = get_installment_dates(
                row.contract_number,
                row.installment_no,
                getattr(row, "month", None)
            )

            if not start_date or not end_date:
                frappe.log_error(
                    f"Installment dates missing for {row.contract_number}",
                    "ALD Date Mapping Error"
                )
                continue

            inv.invoice_date_from = start_date
            inv.invoice_date_to = end_date

            row.invoice_date_from = start_date
            row.invoice_date_to = end_date

        else:
            inv.invoice_date_from = row.invoice_date_from
            inv.invoice_date_to = row.invoice_date_to

        inv.employee_name = frappe.db.get_value(
            "Contract Master",
            row.contract_number,
            "employee_car_process_form"
        )

        inv.total_invoice_value = row.total_invoice_value
        inv.company_contribution = row.company_contribution
        inv.employee_contribution = row.employee_contribution
        inv.excel_batch_id = doc.name
        inv.excel_uploaded_by = doc.excel_uploaded_by
        inv.excel_uploaded_on = doc.creation

        inv.insert(ignore_permissions=True)
        created_count += 1

    if any(r.status == "Success" for r in doc.rows):
        doc.db_set("invoice_created", 1)

    valid_rows = [ r for r in doc.rows if r.status == "Success" and r.contract_number and r.installment_no ]

    if not valid_rows:
        msg = f"No valid rows to send for {doc.name}"

        frappe.logger().warning(msg)
        doc.db_set("api_message", msg)

        return

    if not doc.lease_api_call:
        try:
            res = send_to_leaseapp(doc)
            if res.get("status") == "Success":
                doc.db_set("lease_api_call", 1)
                doc.db_set("api_message", res.get("message") or "Success")
                doc.db_set("api_log", res.get("log_name"))
            else:
                doc.db_set("api_message", "Retry failed. Check API Log.")

        except Exception:
            frappe.log_error(frappe.get_traceback(), "Lease API Failed")


@frappe.whitelist()
def retry_failed(docname):

    doc = frappe.get_doc("Invoice Batch", docname)
    config = VENDOR_CONFIG.get(doc.vendor_name)

    success = 0
    failed = 0

    rows_to_remove = []

    for frow in doc.failed_rows_table:

        try:
            if not frow.contract_number:
                raise Exception("Contract Number missing")

            if not frappe.db.exists("Contract Master", frow.contract_number):
                raise Exception("Contract not found")

            filters = {
                "contract_number": frow.contract_number,
                "installment_no": frow.installment_no
            }

            if config["use_billing_date"]:
                filters["billing_date"] = clean_date(frow.billing_date)

            # validate installment dates (if needed)
            if config.get("use_month_for_period"):
                start_date, end_date = get_installment_dates(
                    frow.contract_number,
                    frow.installment_no,
                    getattr(frow, "month", None)
                )

                if not start_date or not end_date:
                    raise Exception("Installment dates not found")

            if frappe.db.exists("Invoice Details", filters):
                raise Exception("Duplicate invoice exists")

            employee = frappe.db.get_value(
                "Contract Master",
                frow.contract_number,
                "employee_car_process_form"
            )

            doc.append("rows", {
                **frow.as_dict(),
                "status": "Success",
            })

            rows_to_remove.append(frow)
            success += 1

        except Exception as e:
            frow.status = "Error"
            frow.error_message = str(e)
            failed += 1

    for r in rows_to_remove:
        doc.remove(r)

    doc.success_rows += success
    doc.failed_rows = len(doc.failed_rows_table)
    doc.total_rows = doc.success_rows + doc.failed_rows

    if doc.failed_rows == 0 and doc.total_rows > 0:
        doc.excel_sheet_status = "Completed"
    elif doc.success_rows > 0:
        doc.excel_sheet_status = "Partially Completed"
    else:
        doc.excel_sheet_status = "Failed"

    doc.save()
    # trigger invoice creation if conditions met
    create_invoice_details_on_approval(doc, None)

    return {
        "success": success,
        "failed": failed,
        "message": f"{success} Success, {failed} Failed"
    }


@frappe.whitelist()
def download_error_report(docname):

    doc = frappe.get_doc("Invoice Batch", docname)

    rows = []

    for r in doc.rows:
        if r.status == "Error":

            rows.append({
                "Row": r.row_number,
                "Contract No": r.contract_number,
                "Installment": r.installment_no,
                "Billing Date": r.billing_date if doc.vendor_name == "Eazy Assets" else "",
                "Error": r.error_message
            })

    import csv
    file_name = "invoice_batch_errors.csv"
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Row", "Contract No", "Installment", "Billing Date", "Error"])
    writer.writeheader()
    writer.writerows(rows)

    frappe.response["filename"] = file_name
    frappe.response["filecontent"] = output.getvalue().encode('utf-8')
    frappe.response["type"] = "binary"


@frappe.whitelist()
def retry_lease_api(docname):

    doc = frappe.get_doc("Invoice Batch", docname)

    if doc.hr_head_status != "Approved":
        frappe.throw("HR Head must approve first")

    if doc.excel_sheet_status != "Completed":
        frappe.throw("Batch must be Completed")

    if doc.lease_api_call and doc.api_log:
        return {"message": "API already called successfully"}

    valid_rows = [
        r for r in doc.rows
        if r.status == "Success" and r.contract_number and r.installment_no
    ]

    if not valid_rows:
        msg = f"No valid rows to send for {doc.name}"
        doc.db_set("api_message", msg)
        return {"message": msg}

    try:
        res = send_to_leaseapp(doc)

        doc.db_set("lease_api_call", 1)

        if res.get("log_name"):
            doc.db_set("api_log", res.get("log_name"))

        if res.get("message"):
            doc.db_set("api_message", res.get("message"))

        return {
            "message": res.get("message") or "API retried successfully",
            "status": res.get("status")
        }

    except Exception:
        error = frappe.get_traceback()

        frappe.log_error(error, "Retry Lease API Failed")

        doc.db_set("api_message", "Retry failed. Check API Log.")

        return {"message": "Retry failed"}





@frappe.whitelist()
def get_file_preview_url(file_url):
    file_doc = frappe.get_doc("File", {"file_url": file_url})

    if not file_doc:
        frappe.throw("File not found")

    # Permission check (important)
    if file_doc.is_private:
        return get_url("/api/method/frappe.utils.file_manager.download_file?file_url=" + file_doc.file_url)
        # if not frappe.has_permission(file_doc.attached_to_doctype, "read", file_doc.attached_to_name):
        #     frappe.throw("No permission")

    # Convert to accessible URL
    return get_url(file_doc.file_url)