# Copyright (c) 2024, Harsh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import math


class CompanyandEmployeeDeduction(Document):
    def before_insert(self):
        self.is_submitted = 1

    def after_insert(self):
        try:
            from mds_master.mds_approval.approval_router import trigger_approval_if_matrix_exists
            trigger_approval_if_matrix_exists(self)
        except Exception as e:
            frappe.log_error(str(e), "trigger_approval_if_matrix_exists fallback")

    def on_update(self):
        try:
            from mds_master.mds_approval.approval_router import trigger_approval_if_matrix_exists
            trigger_approval_if_matrix_exists(self)
        except Exception as e:
            frappe.log_error(str(e), "trigger_approval_if_matrix_exists fallback")

@frappe.whitelist()
def send_employee_approval_email(docname):
    doc = frappe.get_doc("Company and Employee Deduction", docname)
    employee_email = frappe.db.get_value("Employee", doc.employee_name, "company_email")
    if not employee_email:
        employee_email = frappe.db.get_value("Employee", doc.employee_name, "personal_email")
    
    if not employee_email:
        return {"status": "error", "message": "Employee does not have a registered email address."}
        
    subject = "Car Quotation Approved"
    
    # Get employee's full name if possible, else use ID
    employee_full_name = frappe.db.get_value("Employee", doc.employee_name, "full_name") or doc.employee_name

    message = f"Dear {employee_full_name},<br><br>"
    message += f"The Car quotation for your model car (<b>{doc.variant}</b>) has been approved.<br>"
    
    # Format currency nicely if possible, or just raw value
    emi_val = frappe.format(doc.employee_total_emi, {"fieldtype": "Currency"})
    
    message += f"Your total EMI will be <b>{emi_val}</b>.<br><br>"
    message += "Thank you."
    
    frappe.sendmail(
        recipients=[employee_email],
        subject=subject,
        message=message
    )
    return {"status": "success", "message": "Email sent to employee successfully."}
