import frappe
from alms_app.api.emailClass import EmailServices
import traceback

Email = EmailServices()


@frappe.whitelist(allow_guest=True)
def process_car_indent_by_reporting(indent_form, remarks, token, action):
    try:
        from mds_master.mds_approval.approval_router import process_approval_action
        
        if action not in ["approve", "reject", "revoke_reject"]:
            return fail("Invalid action")

        if not remarks:
            return fail("Remarks are required")

        # Validate token
        db_token = frappe.db.get_value("Car Indent Form", indent_form, "approval_token")
        if not db_token or db_token != token:
            return fail("Invalid or expired token")

        # Impersonate Reporting Head
        i_form = frappe.get_doc("Car Indent Form", indent_form)
        user = frappe.get_doc("Employee", i_form.employee_code)
        rh_user_id, rh_company_email = frappe.db.get_value("Employee", user.reporting_head, ["user_id", "company_email"]) or (None, None)
        reporting_head_email = rh_user_id or rh_company_email
        if not reporting_head_email:
            return fail("Reporting Head has no registered email/user.")

        original_user = frappe.session.user
        frappe.set_user(reporting_head_email)
        
        try:
            if action == "revoke_reject":
                from mds_master.mds_approval.approval_router import revoke_and_reject_approval
                result = revoke_and_reject_approval("Car Indent Form", indent_form, remarks, specific_user=reporting_head_email)
                mapped_action = "Rejected"
            else:
                mapped_action = "Approve" if action == "approve" else "Reject"
                result = process_approval_action("Car Indent Form", indent_form, mapped_action, remarks)
            
            # Keep token alive to allow Revoke & Reject later
            
            # Sync the legacy fields on the Car Indent Form
            if result and result.get("status") == "success":
                status_val = "Approved" if mapped_action == "Approve" else "Rejected"
                frappe.db.set_value("Car Indent Form", indent_form, {
                    "reporting_head_approval": status_val,
                    "reporting_head_remarks": remarks
                })
                
                # Trigger email to HR if approved
                # if mapped_action == "Approve":
                #     try:
                #         Email.for_reporting_to_hr_team(user)
                #     except Exception as e:
                #         frappe.log_error(f"Failed to send HR email: {str(e)}", "Email Error")
            
            frappe.db.commit()
            
        finally:
            # Always revert back to original user
            frappe.set_user(original_user)
        
        return success(
            result.get("message", "Processed successfully"),
            status="updated"
        )

    except Exception as e:
        frappe.log_error(traceback.format_exc(), "Car Indent Approval Error")
        return fail(str(e))


# Helper responses (VERY IMPORTANT)
def success(message, **kwargs):
    return {
        "success": True,
        "message": message,
        **kwargs
    }


def fail(message):
    return {
        "success": False,
        "message": message,
        # "redirect_url": "/somethingwrong.html"

    }