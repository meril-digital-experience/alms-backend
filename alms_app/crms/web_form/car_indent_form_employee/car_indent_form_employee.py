import frappe
from frappe.core.doctype.communication.email import make
from email.mime.text import MIMEText
import smtplib
from alms_app.api.emailsService import email_sender


@frappe.whitelist(allow_guest=True)
def get_employee_details(employee_code):
    employee = frappe.get_all("Employee", filters={"name": employee_code}, fields=["*"])
    
    if not employee:
        # Fallback for old name format 'CODE-Name'
        possible_code = employee_code.split('-')[0].strip()
        employee = frappe.get_all("Employee", filters={"employee_code": possible_code}, fields=["*"])

    if not employee:
        frappe.throw(f"Employee with name '{employee_code}' not found.")
        
    emp = employee[0]
        
    # Determine eligibility from Employee Designation or fallback to inline value
    eligibility_val = emp.get("eligibility") or 0
    if emp.get("meril_designation"):
        designation_eligibility = frappe.db.get_value("Employee Designation", emp.meril_designation, "eligibility")
        if designation_eligibility is not None:
            eligibility_val = designation_eligibility
            
    # Map fields for frontend compatibility
    emp["eligibility"] = eligibility_val
    emp["location"] = emp.get("branch")
    emp["contact_number"] = emp.get("cell_number")
    emp["email_id"] = emp.get("company_email") or emp.get("user_id")
    
    reporting_head = emp.get("reporting_head")
    if reporting_head:
        rh_name = frappe.db.get_value("Employee", reporting_head, "full_name")
        emp["reporting_head_name"] = rh_name if rh_name else reporting_head
    else:
        emp["reporting_head_name"] = ""
        
    return [emp]
        
@frappe.whitelist(allow_guest=True)
def calculate_totals(frm_data):
    ex_showroom_price = frm_data.get('ex_showroom_price', 0)
    discount = frm_data.get('discount', 0)
    tcs = frm_data.get('tcs', 0)
    registration_charges = frm_data.get('registration_charges', 0)
    accessories = frm_data.get('accessories', 0)
    
    net_ex_showroom_price = ex_showroom_price - discount + tcs
    finance_amount = net_ex_showroom_price + registration_charges + accessories
    
    result = {
        "net_ex_showroom_price": f"₹ {net_ex_showroom_price:,.2f}",
        "finance_amount": f"₹ {finance_amount:,.2f}"
    }
    
    return result

def get_context(context):
    context.employee_code = frappe.form_dict.get('employee_code')
    context.employee_details = {}

    if context.employee_code:
        employee_details = get_employee_details(context.employee_code)
        context.employee_details = employee_details

    return context

@frappe.whitelist(allow_guest=True)
def check_indent_exists(employee_code):
    """Check if a Car Indent Form already exists for the given employee."""
    print(f"Checking if Car Indent Form exists for employee code: {employee_code}")
    
    exists = frappe.db.exists("Car Indent Form", {"name": employee_code})
    
    print(f"Indent exists: {exists}")
    
    if exists:
        return "redirect"
    
    return False

    
@frappe.whitelist(allow_guest=True)
def send_allowance_email(employee_code):
    try:
        employee = frappe.get_doc("Employee", employee_code)
        
        if not employee.reporting_head:
            frappe.throw("Reporting Manager must be assigned to process this request. Please update the employee profile.")
            
        email_to = employee.email_id
        cc_employee = frappe.get_doc("Employee", employee.reporting_head)
        email_cc = cc_employee.email_id
        hr_entries = frappe.db.sql("""
            select u.email as email_id, u.full_name 
            from `tabUser` u 
            join `tabHas Role` hr on u.name = hr.parent 
            where hr.role = 'HR' and u.enabled = 1
        """, as_dict=True)
        hr_emails = [row.email_id for row in hr_entries if row.email_id]
        hr_name = ", ".join([row.full_name for row in hr_entries]) or "HR Team"

        if not hr_emails:
            frappe.throw("No HR emails found with the HR role.")

        # Fetch BCC from site_config.json
        site_config = frappe.get_site_config()
        bcc_emails = site_config.get("bcc_email", [])

        subject = "Car Allowance Request Submitted"
        message = f"Dear {hr_name},<br><br> {employee.employee_name} has requested for <strong>Car Allowance</strong> instead of Company Vehicle. Please reach out to the employee to share the process to get the car on allowance.<br><br>Thanks & Regards,<br>CRMS<br><br><strong>Note:</strong> This is an auto-generated email. Please do not reply to this email.<br><br>"
        # print("------------[EMAIL MESSAGE]------------------:",email_to,email_cc,hr_email)
        frappe.sendmail(
            recipients=hr_emails,
            subject=subject,
            message=message,
            cc=[email_cc] if email_cc else [],
            bcc=bcc_emails
        )
        return {"status": "success", "message": f"Email sent successfully to {', '.join(hr_emails)}."}

    except Exception as e:
        frappe.log_error(f"Error in send_allowance_email: {str(e)}")
        return {"status": "failed", "message": str(e)}