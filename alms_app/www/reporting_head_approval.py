import frappe
from frappe.utils import now, get_datetime
from frappe import _

@frappe.whitelist(allow_guest=True)
def get_car_indent_data(indent_form_id, token=None):
    """
    API endpoint to get fresh car indent form data without caching
    """
    try:
        # Validate input
        if not indent_form_id:
            return {
                "success": False,
                "message": "Missing Car Indent Form ID"
            }
        
        # Disable caching for this request
        frappe.local.flags.ignore_cache = True
        
        try:
            form_data = frappe.get_doc("Car Indent Form", indent_form_id)
        except frappe.DoesNotExistError:
            try:
                # Try to find by employee name
                employee_name = indent_form_id
                emp = frappe.get_doc("Employee", employee_name)
                forms = frappe.get_all(
                    "Car Indent Form",
                    filters={"employee_code": emp.name},
                    fields=["name"],
                    order_by="creation desc",
                    limit=1
                )
                if not forms:
                    return {
                        "success": False,
                        "message": f"No Car Indent Form found for {emp.get('employee_name') or emp.get('full_name')}"
                    }
                form_data = frappe.get_doc("Car Indent Form", forms[0].name)
            except frappe.DoesNotExistError:
                return {
                    "success": False,
                    "message": f"No Employee or Car Indent Form found with ID: {indent_form_id}"
                }
        
        try:
            user = frappe.get_doc("Employee", form_data.employee_code)
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "message": f"Employee not found for employee code: {form_data.employee_code}"
            }
        
        # Check approval status using Approval Engine
        from mds_master.mds_approval.approval_router import get_approval_status, can_approve
        
        entry_name = getattr(form_data, 'approval_entry', None)
        if entry_name:
            status_text, remarks = get_approval_status(entry_name)
            approval_status = status_text if status_text else "Pending"
            current_remarks = remarks
        else:
            approval_status = "Pending"
            current_remarks = getattr(form_data, 'reporting_head_remarks', '')

        is_approved = 'Approved' in approval_status or 'Rejected' in approval_status
        
        # If a token is provided and matches, allow them to approve
        db_token = frappe.db.get_value("Car Indent Form", form_data.name, "approval_token")
        if token and db_token and token == db_token:
            user_can_approve = True
        else:
            user_can_approve = can_approve("Car Indent Form", form_data.name)
        
        # Determine if the user associated with this token has previously approved
        has_previously_approved = False
        if entry_name:
            entry = frappe.get_doc("Approval Entry", entry_name)
            rh_user_id, rh_company_email = frappe.db.get_value("Employee", user.reporting_head, ["user_id", "company_email"]) or (None, None)
            reporting_head_email = rh_user_id or rh_company_email
            for row in getattr(entry, "approval_entry", []):
                if row.action == "Approved" and row.approver_user == reporting_head_email:
                    has_previously_approved = True
                    break

        # Prepare response data
        current_time = now()
        page_id = f"{form_data.name}_{get_datetime().strftime('%Y%m%d_%H%M%S_%f')}"
        
        employee_full_name = user.get("full_name")
        if not employee_full_name or employee_full_name == user.name:
            name_parts = [part for part in [user.get("first_name"), user.get("middle_name"), user.get("last_name")] if part]
            employee_full_name = " ".join(name_parts) or user.name

        data = {
            "success": True,
            "data": {
                "id": form_data.name,
                "page_id": page_id,
                "timestamp": current_time,
                "employee_name": employee_full_name,
                "employee_email": form_data.email_id,
                "reporting_head_name": form_data.employee_reporting,
                "vehicle_make_model": f"{form_data.make}-{form_data.model}",
                "net_ex_showroom_price": str(form_data.net_ex_showroom_price),
                "finance_amount": str(form_data.finance_amount),
                "company_name": user.company,
                "designation": user.designation,
                "eligibility": str(user.eligibility),
                "reporting_head_approval": approval_status,
                "reporting_head_remarks": current_remarks,
                "is_approved": is_approved,
                "user_can_approve": user_can_approve,
                "has_previously_approved": has_previously_approved,
                "approved_by": getattr(form_data, 'approved_by', ''),
                "approval_date": str(getattr(form_data, 'approval_date', '')) if getattr(form_data, 'approval_date', '') else ''
            }
        }
        
        # Set response headers to prevent caching
        frappe.local.response.headers = {
            'Cache-Control': 'no-cache, no-store, must-revalidate, private',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Content-Type': 'application/json'
        }
        
        return data
        
    except Exception as e:
        frappe.log_error(f"Error in get_car_indent_data: {str(e)}", "Car Indent Data API Error")
        return {
            "success": False,
            "message": f"An error occurred: {str(e)}"
        }
    
def get_context(context):
    """
    Enhanced context with aggressive cache prevention for production
    """
    try:
        # Get the 'id' parameter from the URL query string
        record_id = frappe.form_dict.get("id")
        
        # Provide default values to prevent template errors
        context.id = record_id or "NO_ID_PROVIDED"
        
        # Add cache busting
        current_time = now()
        context.cache_buster = get_datetime().strftime('%Y%m%d_%H%M%S_%f')
        context.timestamp = current_time
        
        # Optional: Add other useful context data
        context.is_logged_in = frappe.session.user != "Guest"
        context.current_user = frappe.session.user
        context.unique_key = f"{record_id}_{context.cache_buster}"
        
        # If no ID provided, we'll still render the page but show an error
        if not record_id:
            frappe.msgprint("ID parameter is missing in the URL. Please provide a valid Car Indent Form ID.")
        
        # CRITICAL: Prevent all forms of caching in production
        frappe.local.flags.ignore_cache = True
        frappe.local.flags.ignore_website_cache = True
        
        # Set aggressive anti-cache headers for the web page
        if hasattr(frappe.local, 'response'):
            if not getattr(frappe.local.response, 'headers', None):
                frappe.local.response.headers = {}
            
            frappe.local.response.headers.update({
                'Cache-Control': 'no-cache, no-store, must-revalidate, private, max-age=0',
                'Pragma': 'no-cache',
                'Expires': '0',
                'Last-Modified': current_time,
                'ETag': f'"{context.unique_key}"',
                'Vary': 'Accept-Encoding, User-Agent',
                'X-Cache-Buster': context.cache_buster
            })
        
        # Clear any website cache for this route
        if hasattr(frappe, 'website') and hasattr(frappe.website, 'clear_cache'):
            frappe.website.clear_cache('reporting-head-approval')
        
        return context
        
    except Exception as e:
        frappe.log_error(f"Error in get_context: {str(e)}", "Reporting Head Approval Context Error")
        # Don't throw error, just provide minimal context
        context.id = "ERROR"
        context.error_message = str(e)
        context.cache_buster = now()
        return context


# Alternative function if you want to validate the ID exists before rendering
def validate_and_get_context(context):
    """
    Enhanced version that validates the ID exists before rendering the page
    """
    try:
        record_id = frappe.form_dict.get("id")
        
        if not record_id:
            frappe.throw("❌ ID parameter is missing in the URL")
        
        # Validate that the Car Indent Form exists
        try:
            form_data = frappe.get_doc("Car Indent Form", record_id)
            context.form_exists = True
            context.employee_name = form_data.get('employee_name', 'Unknown')
        except frappe.DoesNotExistError:
            # Try to find by employee name as fallback
            try:
                emp = frappe.get_doc("Employee", record_id)
                forms = frappe.get_all(
                    "Car Indent Form",
                    filters={"employee_code": emp.name},
                    fields=["name"],
                    order_by="creation desc",
                    limit=1
                )
                if forms:
                    record_id = forms[0].name
                    context.form_exists = True
                    context.employee_name = emp.get('employee_name', 'Unknown')
                else:
                    frappe.throw(f"No Car Indent Form found for employee: {record_id}")
            except frappe.DoesNotExistError:
                frappe.throw(f"No Car Indent Form or Employee found with ID: {record_id}")
        
        context.id = record_id
        context.api_url = frappe.utils.get_url()
        
        # Prevent caching
        frappe.local.flags.ignore_cache = True
        
        return context
        
    except Exception as e:
        frappe.log_error(f"Error in validate_and_get_context: {str(e)}", "Reporting Head Approval Context Error")
        frappe.throw(f"An error occurred: {str(e)}")