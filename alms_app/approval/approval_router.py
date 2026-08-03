import frappe
import traceback
from frappe.utils.data import cast, compare, cstr, sql_like
try:
	from leasemanagement.api.utils.email_context import get_email_context
except ImportError:
	try:
		from alms_app.api.utils.email_context import get_email_context
	except ImportError:
		get_email_context = None

RESTART_FROM_BEGINNING = "Restart from beginning"

# Approval Condition child table uses UI labels; Frappe compare() expects internal operators.
_CONDITION_LABEL_TO_OPERATOR = {
    "Equals": "=",
    "Not Equals": "!=",
    "Like": "like",
    "Not Like": "not like",
    "In": "in",
    "Not In": "not in",
    "Is": "is",
}

# ---------------------------------------------------------
# 1. TRIGGER APPROVAL FLOW
# ---------------------------------------------------------

def trigger_approval_if_matrix_exists(doc, method=None):
    """
    Generic DocEvent triggered on doc update/submit.
    Evaluates matrix conditions and initializes the Approval Entry flow.
    """
    if not _should_process_approval(doc):
        return

    matched_matrix_name = _get_matching_matrix(doc)
    print("matched_matrix_name @@@@@@@@@@@@@@@@@@@@@@@@@", matched_matrix_name)

    if matched_matrix_name:
        approval_matrix = frappe.get_doc("Approval Matrix", matched_matrix_name)
        generic_process_approval_entry(doc, approval_matrix)
    else:
        frappe.msgprint(f"Warning: No matching 'Approval Matrix' found for {doc.doctype}. Approval routing could not be started. Please configure the matrix.", alert=True, indicator="orange")


def auto_restart_rejected_document(doc, method=None):
    if not hasattr(doc, "is_submitted") or not hasattr(doc, "status"):
        return
        
    if doc.status == "Rejected":
        doc.status = "Pending"
        doc.is_submitted = 1
        
        try:
            entry_name = frappe.db.get_value("Approval Entry", {
                "applied_to_doctype": doc.doctype,
                "record": doc.name,
                "status": "Rejected"
            }, "name", order_by="creation desc")
            
            if entry_name:
                entry = frappe.get_doc("Approval Entry", entry_name)
                matrix = frappe.get_doc("Approval Matrix", entry.approval_matrix)
                
                # Reset ALL stage legacy fields defined in the Matrix
                stages_list = getattr(matrix, "stages", getattr(matrix, "approval_stages", []))
                for stage in stages_list:
                    app_field = getattr(stage, "status_field", None)
                    rem_field = getattr(stage, "remarks_field", None)
                    sig_field = getattr(stage, "signature_field", None)

                    if app_field and hasattr(doc, app_field):
                        doc.set(app_field, "Pending")
                    if rem_field and hasattr(doc, rem_field):
                        doc.set(rem_field, "")
                    if sig_field and hasattr(doc, sig_field):
                        doc.set(sig_field, "")

                first_stage = _get_first_stage(matrix)
                if first_stage:
                    _reset_approval_entry_to_first_stage(entry.name, doc, first_stage)
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"Auto Restart Error - {doc.doctype}")

def _should_process_approval(doc):
    """
    Run when the document is submitted and either:
    - approval_initiated is not set yet (first run), or
    - the latest Approval Entry is Rejected (resubmit / append new first-stage row).

    If approval_initiated is 1 but the entry is still Pending or Approved, skip — avoids duplicate runs.
    """
    if not (doc.get("is_submitted") == 1 or doc.docstatus == 1):
        return False
    if not doc.get("approval_initiated"):
        return True
    latest = _get_latest_approval_entry_row(doc)
    if latest and latest.status == "Rejected":
        return True
    return False

def _get_matching_matrix(doc):
    """Finds the first Approval Matrix that matches the document's conditions."""
    matrices = frappe.get_all(
        "Approval Matrix",
        filters={"applies_to_doctype": doc.doctype},
        pluck="name"
    )

    for matrix_name in matrices:
        matrix = frappe.get_doc("Approval Matrix", matrix_name)
        if _evaluate_matrix_conditions(doc, matrix):
            return matrix_name
            
    return None

def _evaluate_matrix_conditions(doc, matrix):
    """Verifies if a specific Document matches all conditions of a given Matrix."""
    doctype = doc.doctype
    for cond_row in getattr(matrix, "conditions", []):
        fieldname = cond_row.conditional_field
        raw_val = doc.get(fieldname)
        label = getattr(cond_row, "condition", None) or "Equals"
        expected = cond_row.value
        op = _CONDITION_LABEL_TO_OPERATOR.get(label, "=")

        try:
            df = frappe.get_meta(doctype).get_field(fieldname)
            fieldtype = df.fieldtype if df else None
        except Exception:
            fieldtype = None

        # Legacy: Equals rows that used %...% or *...* for "contains" before explicit Like.
        if label in (None, "", "Equals") and isinstance(expected, str):
            ev = expected
            if ev.startswith("%") and ev.endswith("%") and len(ev) > 2:
                if not sql_like(cstr(raw_val), ev):
                    return False
                continue
            if ev.startswith("*") and ev.endswith("*") and len(ev) > 2:
                if ev.strip("*") not in cstr(raw_val):
                    return False
                continue

        if op in ("in", "not in"):
            # Handle string representations like "[abc,xyz]", "(abc,xyz)", or plain comma-separated "abc,xyz"
            val2 = []
            if isinstance(expected, (list, tuple)):
                val2 = [cstr(x).strip() for x in expected if cstr(x).strip() != ""]
            elif isinstance(expected, str):
                s = expected.strip()
                # Remove brackets or parentheses if present
                if (s.startswith("[") and s.endswith("]")) or (s.startswith("(") and s.endswith(")")):
                    s = s[1:-1]
                val2 = [p.strip() for p in s.split(",") if p.strip() != ""]
            else:
                val2 = [cstr(expected).strip()]
            if fieldtype:
                val2 = [cast(fieldtype, x) for x in val2]
       
        elif op == "is":
            val2 = (cstr(expected).strip().lower() or "set") if expected is not None else "set"
        else:
            val2 = expected

        if not compare(raw_val, op, val2, fieldtype):
            return False

    return True

# ---------------------------------------------------------
# 2. INITIALIZE APPROVAL ENTRY
# ---------------------------------------------------------

def generic_process_approval_entry(doc, approval_matrix):
    """Creates a new Approval Entry, or after Rejected appends a fresh first-stage row on the same entry."""
    try:
        first_stage = _get_first_stage(approval_matrix)
        if not first_stage:
            frappe.throw(f"Approval Matrix {approval_matrix.name} matched but has no Approval Stages configured! Please add approvers to the matrix.")

        latest = _get_latest_approval_entry_row(doc)
        if latest:
            if latest.status == "Pending":
                return
            if latest.status == "Approved":
                return
            if latest.status == "Rejected":
                try:
                    if check_restart_approval(latest):
                        _reset_approval_entry_to_first_stage(latest.name, doc, first_stage)
                except Exception as e:
                    print(e, "error")
                    frappe.log_error(frappe.get_traceback(), "Generic Reset Approval Entry Error")
                return

        try:
            _create_initial_approval_entry(doc, first_stage)
        except Exception as e:
            print(e, "error")
            frappe.log_error(frappe.get_traceback(), "Generic Create Approval Entry Error")

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Generic Create Approval Entry Error")

def _get_first_stage(approval_matrix):
    """Fetch the first valid configured Stage from a Matrix."""
    stages_list = getattr(approval_matrix, "stages", getattr(approval_matrix, "approval_stages", []))
    for row in stages_list:
        if getattr(row, "employee", None) or getattr(row, "role", None) or getattr(row, "team", None):
            return row
    return None

def _get_latest_approval_entry_row(doc):
    """Most recently modified Approval Entry for this document (one per record)."""
    rows = frappe.get_all(
        "Approval Entry",
        filters={"record": doc.name, "applied_to_doctype": doc.doctype},
        fields=["name", "status", "approval_matrix"],
        order_by="modified desc",
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _ledger_table_name(entry):
    return "approval_ledger" if hasattr(entry, "approval_ledger") else "approval_entry"

def _get_employee_from_doc(doc):
    """Attempt to find the Employee record associated with the document. 
    Useful when the owner is Guest or when forms are submitted on behalf of others."""
    if doc.doctype == "Employee":
        return doc.name
    if getattr(doc, "employee", None):
        return doc.employee
    if getattr(doc, "employee_code", None):
        return doc.employee_code
    
    # fallback to owner
    return frappe.db.get_value("Employee", {"user_id": doc.owner, "status": "Active"}, "name")


def _append_first_pending_stage(entry, doc, first_stage, ledger_table):
    """
    Append one Pending row for the first approval stage. Mutates entry.
    Returns next_user for email context (may be None for Team).
    """
    next_stage_val = getattr(first_stage, "stage_number", getattr(first_stage, "approval_stage", 1))
    next_approver = getattr(first_stage, "employee", None)
    next_user = getattr(first_stage, "user", None)
    next_approver_role = getattr(first_stage, "role", None)

    if getattr(first_stage, "approver_type", None) == "Team" and getattr(first_stage, "team", None):
        entry.append(ledger_table, {
            "status": "Pending",
            "current_stage": 0,
            "assigned_at": frappe.utils.now_datetime(),
            "next_stage": next_stage_val,
            "next_approver": None,
            "next_approver_role": None,
            "next_approver_team": getattr(first_stage, "team", None),
        })
    elif getattr(first_stage, "approver_type", None) == "Role" and getattr(first_stage, "from_hierarchy", False):
        approver = get_role_based_approver(
            first_stage.role,
            _get_employee_from_doc(doc),
        )
        if approver:
            next_user = approver["user"]
            entry.append(ledger_table, {
                "status": "Pending",
                "current_stage": 0,
                "assigned_at": frappe.utils.now_datetime(),
                "next_stage": next_stage_val,
                "next_approver": approver["employee"],
                "next_approver_role": approver["role"],
            })
        else:
            doc.db_set("is_submitted", 0, update_modified=False)
            frappe.flags.doc_event_result = {"status": "error", "message": f"Approver not found for role: {first_stage.role}"}
            frappe.throw(f"Approver not found for role: {first_stage.role}")
    else:
        entry.append(ledger_table, {
            "status": "Pending",
            "current_stage": 0,
            "assigned_at": frappe.utils.now_datetime(),
            "next_stage": next_stage_val,
            "next_approver": next_approver,
            "next_approver_role": next_approver_role,
        })
    return next_user, next_stage_val


def _notify_first_stage_if_configured(first_stage, doc, next_user):
    matrix_doc = frappe.get_cached_doc("Approval Matrix", first_stage.parent)
    if not getattr(matrix_doc, "send_email_alert", None):
        return
    context = get_email_context(
        doc.doctype,
        doc,
        next_user=next_user,
        next_team=getattr(first_stage, "team", None),
        action="Submitted",
    )

    if not context:
        return

    if getattr(matrix_doc, "email_template", None):
        _send_email(matrix_doc.email_template, context)

def _set_doc_approval_initiated_and_link(doc, entry_name):
    if hasattr(doc, "approval_initiated"):
        doc.db_set("approval_initiated", 1, update_modified=False)
    if hasattr(doc, "approval_entry"):
        doc.db_set("approval_entry", entry_name, update_modified=False)


def _reset_approval_entry_to_first_stage(entry_name, doc, first_stage):
    """Append a new first-stage Pending row on the same Approval Entry; prior ledger rows stay for history."""
    entry = frappe.get_doc("Approval Entry", entry_name)
    ledger_table = _ledger_table_name(entry)
    entry.status = "Pending"
    entry.approval_matrix = first_stage.parent
    next_user, next_stage_val = _append_first_pending_stage(entry, doc, first_stage, ledger_table)
    entry.save(ignore_permissions=True)
    entry.db_set("next_approval_stage", next_stage_val, update_modified=False)
    _notify_first_stage_if_configured(first_stage, doc, next_user)
    _set_doc_approval_initiated_and_link(doc, entry.name)


def _create_initial_approval_entry(doc, first_stage):
    """
    Instantiate and properly link the new Approval Entry tracking record.

    If approver_type is "Role" and from_hierarchy, climb hierarchy to find first eligible approver.
    If approver_type is "Team", all team members are eligible to approve, so set next_approver as team and leave specific user empty.
    If approver_type is "User" or "Employee", assign directly.
    """
    entry = frappe.new_doc("Approval Entry")
    entry.status = "Pending"
    entry.applied_to_doctype = doc.doctype
    entry.record = doc.name
    entry.approval_matrix = first_stage.parent

    ledger_table = _ledger_table_name(entry)
    next_user, next_stage_val = _append_first_pending_stage(entry, doc, first_stage, ledger_table)
    entry.next_approval_stage = next_stage_val

    entry.insert(ignore_permissions=True)
    entry.db_set("next_approval_stage", next_stage_val, update_modified=False)

    _notify_first_stage_if_configured(first_stage, doc, next_user)
    _set_doc_approval_initiated_and_link(doc, entry.name)


def get_role_based_approver(role, starting_employee, max_depth=10):
    """
    Given a role and optional starting employee, return the first Employee
    (climbing up the 'reports_to' chain) whose linked User has that role.
    Returns the Employee name and User if found, else None.

    - role: the role name to match (str).
    - starting_employee: optional Employee name (str). If None, uses current user's employee.
    - max_depth: safety to prevent infinite recursion.

    Returns dict: {"employee": ..., "user": ...} or None if not found.
    """
    if not role:
        return None

    current_employee = starting_employee
    depth = 0

    # If not provided, attempt to find the Employee record for the current session user
    if not current_employee:
        current_user = frappe.session.user
        emp_name = frappe.db.get_value("Employee", {"user_id": current_user, "status": "Active"}, "name")
        if not emp_name:
            emp_name = frappe.db.get_value("Employee", {"company_email": current_user, "status": "Active"}, "name")
        if not emp_name:
            emp_name = frappe.db.get_value("Employee", {"personal_email": current_user, "status": "Active"}, "name")
        if not emp_name:
            return None
        current_employee = emp_name

    def resolve_employee_id(emp_id_or_name):
        if not emp_id_or_name: return None
        if frappe.db.exists("Employee", emp_id_or_name):
            return emp_id_or_name
        resolved = frappe.db.get_value("Employee", {"full_name": emp_id_or_name}, "name")
        return resolved

    current_employee = resolve_employee_id(current_employee)
    if not current_employee:
        return None

    if role == "Reporting Head":
        emp_doc = frappe.get_doc("Employee", current_employee)
        reports_to = resolve_employee_id(emp_doc.reporting_head)
        if reports_to:
            mgr_doc = frappe.get_doc("Employee", reports_to)
            return {"employee": reports_to, "user": mgr_doc.company_email or mgr_doc.user_id, "role": role}
        return None

    visited = set()

    while current_employee and depth < max_depth:
        if current_employee in visited:
            break  # loop detected
        visited.add(current_employee)
        emp_doc = frappe.get_doc("Employee", current_employee)

        # Get User ID and check for role
        user_id = emp_doc.company_email or emp_doc.user_id
        if user_id:
            roles = frappe.get_roles(user_id)
            if role in roles:
                return {"employee": current_employee, "user": user_id, "role":role}

        # Climb up to "reporting_head"
        reports_to = resolve_employee_id(emp_doc.reporting_head)
        if reports_to:
            current_employee = reports_to
        else:
            break
        depth += 1

    return None

# ---------------------------------------------------------
# 3. ACTION PROCESSOR (API)
# ---------------------------------------------------------

@frappe.whitelist(methods=["POST"])
def process_approval_action(doctype, doc_name, action, remarks=""):
    """
    Whitelist API invoked by the frontend to Register an Approve or Reject action.
    """
    try:
        entry, ledger_items, ledger_table = _get_active_entry_and_ledger(doctype, doc_name)
        pending_row = _get_pending_stage(ledger_items,entry.next_approval_stage)
        
        _validate_approver_permissions(pending_row)
        
        if action == "Reject":
            _handle_reject_action(doctype, doc_name, entry, pending_row, ledger_table, remarks)
            return {"status": "success", "message": f"Document rejected successfully"}
            
        elif action == "Approve":
            return _handle_approve_action(doctype, doc_name, entry, pending_row, ledger_table, remarks)
        else:
            frappe.throw(f"Invalid action: {action}")

    except Exception as e:
        frappe.log_error(traceback.format_exc(), "Approval Routing Error")
        frappe.throw(f"Error processing approval: {str(e)}")


@frappe.whitelist()
def revoke_and_reject_approval(doctype, doc_name, remarks, specific_user=None):
    try:
        user = specific_user or frappe.session.user
        entry_name = frappe.db.get_value("Approval Entry", {
            "applied_to_doctype": doctype,
            "record": doc_name,
            "status": ["in", ["Pending", "Approved", "Rejected"]]
        }, "name", order_by="creation desc")
        
        if not entry_name:
            frappe.throw("No approval entry found to revoke.")
            
        entry = frappe.get_doc("Approval Entry", entry_name)
        ledger_table = "approval_ledger" if hasattr(entry, "approval_ledger") else "approval_entry"
        
        # Verify the user has previously approved
        has_approved = False
        if entry.get(ledger_table):
            for row in entry.get(ledger_table):
                if row.action == "Approved" and row.approver_user == user:
                    has_approved = True
                    break
                
        if user == "Administrator" and doctype == "Car Indent Form":
            has_approved = True
            
        if not has_approved:
            frappe.throw("You cannot revoke/reject because you have not previously approved this document.")
            
        pending_row = [r for r in entry.get(ledger_table) if r.status == "Pending"]
        if pending_row:
            pending_row = pending_row[-1]
        elif entry.get(ledger_table):
            # If no pending row, the document was fully approved or rejected. We use the last row.
            pending_row = entry.get(ledger_table)[-1]
        else:
            frappe.throw("No stages found to reject.")
        
        # Proceed with rejection
        _handle_reject_action(doctype, doc_name, entry, pending_row, ledger_table, remarks, specific_user=user)
        return {"status": "success", "message": "Document revoked and rejected successfully"}
        
    except Exception as e:
        frappe.log_error(traceback.format_exc(), "Revoke & Reject Error")
        frappe.throw(f"Error processing revocation: {str(e)}")

# --- Action Helpers ---

def _get_active_entry_and_ledger(doctype, doc_name):
    entry_name = frappe.db.get_value("Approval Entry", {
        "applied_to_doctype": doctype,
        "record": doc_name,
        "status": "Pending"
    }, "name")
    
    if not entry_name:
        frappe.throw("No pending approval entry found for this document.")
        
    frappe.flags.ignore_permissions = True
    try:
        entry = frappe.get_doc("Approval Entry", entry_name)
        ledger_table = "approval_ledger" if hasattr(entry, "approval_ledger") else "approval_entry"
        ledger_items = entry.get(ledger_table)
    finally:
        frappe.flags.ignore_permissions = False
    
    if not ledger_items:
        frappe.throw("Approval ledger is empty.")
        
    return entry, ledger_items, ledger_table

def _get_pending_stage(ledger_items, next_stage=None):
    """Use the last matching row so restarts that re-append the same stage number still resolve to the current step."""
    target = int(next_stage)
    print("----------------------------------",next_stage, "----------------------------------")
    match = None
    for row in ledger_items:
        if row.next_stage == target:
            match = row
    if match:
        return match
    frappe.throw("No pending stage found for this document.")

def _validate_approver_permissions(pending_row):
    user = frappe.session.user  
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        employee = frappe.db.get_value("Employee", {"company_email": user}, "name")
    if not employee:
        employee = frappe.db.get_value("Employee", {"personal_email": user}, "name")
    allowed_user = pending_row.next_approver
    allowed_role = pending_row.next_approver_role
    allowed_team = getattr(pending_row, "next_approver_team", None)

    # Check individual user permission strictly
    if allowed_user:
        if employee and allowed_user == employee:
            return True
        frappe.throw("You do not have permission to approve this stage. It is assigned to a specific user.")

    # Check role permission
    if allowed_role and allowed_role in frappe.get_roles(user):
        return True

    # Check team permission
    if allowed_team:
        # Find Employee record
        if employee:
            employee_teams = frappe.get_all("Employee",
                filters={"name": employee, "department": allowed_team},
                fields=["name"]
            )
            if employee_teams:
                return True

    # Allow Administrator
    if user == "Administrator":
        return True

    waiting_for = allowed_user or allowed_role or allowed_team
    frappe.throw(f"You are not authorized to approve this step. Waiting for {waiting_for}.")

def _handle_reject_action(doctype, doc_name, entry, pending_row, ledger_table, remarks, specific_user=None):
    user = specific_user or frappe.session.user
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        employee = frappe.db.get_value("Employee", {"company_email": user}, "name")
    if not employee:
        employee = frappe.db.get_value("Employee", {"personal_email": user}, "name")

    entry.append(ledger_table, {
        "action":"Rejected",
        "status": "Rejected",
        "action_at": frappe.utils.now_datetime(),
        "approved_by": employee,
        "approver_user": user,
        "remarks": remarks,
        "current_stage": getattr(pending_row, "next_stage", None),
        "next_stage": None,
        "next_approver": None,
        "next_approver_role": None
    })
    
    entry.status = "Rejected"
    entry.save(ignore_permissions=True)

    matrix = frappe.get_doc("Approval Matrix", entry.approval_matrix)

    if frappe.db.has_column(doctype, "status"):
        frappe.db.set_value(doctype, doc_name, "status", "Rejected", update_modified=True)
        if frappe.get_value("Approval Matrix", entry.approval_matrix, "action_on_rejection") == RESTART_FROM_BEGINNING:
            frappe.db.set_value(doctype, doc_name, "is_submitted", 0, update_modified=True)
        
        current_stage = _find_current_stage(matrix, pending_row)
        
        try:
            reject_email_map = {
                ("Car Indent Form", "Reporting Head"): "Reject Reporting to Employee",
                ("Car Indent Form", "HR Team"): "Reject HRTeam to Employee",
                ("Car Indent Form", "Travel Desk"): "Reject TravelDesk to Employee",
                ("Car Indent Form", "HR Head"): "Reject HRHead to Employee",
                ("Purchase Form", "Purchase Team"): "Reject PurchaseForm to HR",
                ("Purchase Form", "Purchase Head"): "Reject PurchaseHead to PurchaseForm",
                ("Car Quotation", "Finance Team"): "Reject FinanceTeam to Vendor",
                ("Car Quotation", "Finance Head"): "Reject FinanceHead to FinanceTeam",
                ("Company and Employee Deduction", "Finance Head"): "Reject Finance Head To Finance Team"
            }
            email_send_to = reject_email_map.get((doctype, current_stage.role))
            if email_send_to:
                try:
                    from leasemanagement.api.emailsService import email_sender
                except ImportError:
                    try:
                        from alms_app.api.emailsService import email_sender
                    except ImportError:
                        email_sender = None
                doc = frappe.get_doc(doctype, doc_name)
                if doctype == "Car Quotation":
                    payload = {"quotation_id": doc_name}
                    emp_code = getattr(doc, "employee_details", None)
                elif doctype == "Company and Employee Deduction":
                    payload = {"name": doc_name}
                    emp_code = doc.employee_name
                else:
                    payload = None
                    emp_code = getattr(doc, "employee_name", None) or getattr(doc, "employee_code", None) or doc.owner
                    
                email_sender(name=emp_code, email_send_to=email_send_to, car_indent_form_name=doc.name, payload=payload)
        except Exception as e:
            frappe.log_error(str(e), "Custom Reject Email Error")
            
        if current_stage.send_email:
            doc = frappe.get_doc(doctype, doc_name)
            context = get_email_context(doctype, doc, next_user=doc.owner, action="Rejected")
            if not context:
                return {"status": "error", "message": "Email context not found."}
            context["remarks"] = remarks or "-"
            email_template = current_stage.email_template
            if email_template:
                _send_email(email_template, context)

        _sync_generic_legacy_fields(doctype, doc_name, current_stage, "Rejected", remarks)

        if frappe.get_value("Approval Matrix", entry.approval_matrix, "action_on_rejection") == RESTART_FROM_BEGINNING:
            doc = frappe.get_doc(doctype, doc_name)
            stages_list = getattr(matrix, "stages", getattr(matrix, "approval_stages", []))
            updates = {}
            for stage in stages_list:
                app_field = getattr(stage, "status_field", None)
                rem_field = getattr(stage, "remarks_field", None)
                sig_field = getattr(stage, "signature_field", None)

                if app_field and hasattr(doc, app_field):
                    updates[app_field] = "Pending"
                if rem_field and hasattr(doc, rem_field):
                    updates[rem_field] = ""
                if sig_field and hasattr(doc, sig_field):
                    updates[sig_field] = ""
            
            if updates:
                frappe.db.set_value(doctype, doc_name, updates, update_modified=True)

def _sync_generic_legacy_fields(doctype, doc_name, stage, action, remarks):
    if not stage:
        return
    app_field = getattr(stage, "status_field", None)
    rem_field = getattr(stage, "remarks_field", None)
    sig_field = getattr(stage, "signature_field", None)

    updates = {}
    if app_field and frappe.get_meta(doctype).has_field(app_field):
        updates[app_field] = action
        
        # Auto-infer user field from status field
        if app_field.endswith("_status"):
            user_field = app_field.replace("_status", "_user")
            if frappe.get_meta(doctype).has_field(user_field):
                user = frappe.session.user
                employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
                if not employee:
                    employee = frappe.db.get_value("Employee", {"company_email": user, "status": "Active"}, "name")
                if not employee:
                    employee = frappe.db.get_value("Employee", {"personal_email": user, "status": "Active"}, "name")
                updates[user_field] = employee or user
                
    if rem_field and frappe.get_meta(doctype).has_field(rem_field):
        updates[rem_field] = remarks or ""
        
    if sig_field and frappe.get_meta(doctype).has_field(sig_field):
        user = frappe.session.user
        signature = user
        employee_doc = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, ["name", "esignature"], as_dict=True)
        if not employee_doc:
            employee_doc = frappe.db.get_value("Employee", {"company_email": user, "status": "Active"}, ["name", "esignature"], as_dict=True)
        if not employee_doc:
            employee_doc = frappe.db.get_value("Employee", {"personal_email": user, "status": "Active"}, ["name", "esignature"], as_dict=True)

        if employee_doc and employee_doc.get("esignature"):
            signature = employee_doc.get("esignature")
            
        updates[sig_field] = signature

    if updates:
        frappe.db.set_value(doctype, doc_name, updates, update_modified=False)

def _handle_approve_action(doctype, doc_name, entry, pending_row, ledger_table, remarks):
    user = frappe.session.user
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        employee = frappe.db.get_value("Employee", {"company_email": user}, "name")
    if not employee:
        employee = frappe.db.get_value("Employee", {"personal_email": user}, "name")

    # Fetch approval matrix and determine next stage
    matrix = frappe.get_doc("Approval Matrix", entry.approval_matrix)
    next_stage = _find_next_stage(matrix, pending_row)
    
    # If Administrator is approving on behalf of someone else, use the assigned approver for hierarchy climb
    hierarchy_employee = employee
    if pending_row.next_approver and pending_row.next_approver != employee:
        hierarchy_employee = pending_row.next_approver
    if not hierarchy_employee:
        doc_owner = frappe.db.get_value(doctype, doc_name, "owner")
        hierarchy_employee = frappe.db.get_value("Employee", {"user_id": doc_owner, "status": "Active"}, "name")

    # Append a new approval ledger row for APPROVED action (do not update the pending row)
    next_stage_user = None
    if next_stage:
        if next_stage.approver_type == "Role" and next_stage.from_hierarchy:
            approver = get_role_based_approver(next_stage.role, hierarchy_employee)
            if approver:
                next_stage.employee = approver["employee"]
                next_stage.role = approver["role"]
            else:
                frappe.throw(f"Approver not found for role: {next_stage.role}")

        if next_stage.employee:
            next_stage_user = frappe.get_value("Employee", next_stage.employee, "company_email")
            
        entry.append(ledger_table, {
            "action":"Approved",
            "status": "Approved",
            "approved_by": employee,
            "action_at": frappe.utils.now_datetime(),
            "approver_user": user,
            "remarks": remarks,
            "current_stage": getattr(pending_row, "next_stage", 0),
            "next_stage": getattr(next_stage, "stage_number", getattr(next_stage, "approval_stage", 0)),
            "next_approver": getattr(next_stage, "employee", None),
            "next_approver_role": getattr(next_stage, "role", None),
            "next_approver_team": getattr(next_stage, "team", None),
            "assigned_at": frappe.utils.now_datetime(),
        })
        entry.save(ignore_permissions=True)
        
        # Update the parent's next_approval_stage pointer
        new_stage_val = getattr(next_stage, "stage_number", getattr(next_stage, "approval_stage", 0))
        entry.db_set("next_approval_stage", new_stage_val, update_modified=False)
        
        current_stage = _find_current_stage(matrix, pending_row)
        if current_stage.send_email:
            doc = frappe.get_doc(doctype, doc_name)
            context = get_email_context(
                doctype, 
                doc, 
                next_user=next_stage_user, 
                next_team=getattr(next_stage, "team", None), 
                next_role=getattr(next_stage, "role", None), 
                action="Approved"
            )
            if not context:
                return {"status": "error", "message": "Email context not found."}
            
            context["remarks"] = remarks or "-"
            
            email_template = current_stage.email_template
            if email_template:
                _send_email(email_template, context)
        
        _sync_generic_legacy_fields(doctype, doc_name, current_stage, "Approved", remarks)
            
        return {"status": "success", "message": f"Document approved successfully and sent to next stage."}
    else:
        return _finalize_approval(doctype, doc_name, entry, pending_row, ledger_table, employee, user, remarks)

def _find_next_stage(matrix, pending_row):
    stages_list = getattr(matrix, "stages", getattr(matrix, "approval_stages", []))
    current_stage_num = getattr(pending_row, "next_stage", 0)
    print(current_stage_num, stages_list)
    
    for row in sorted(stages_list, key=lambda x: getattr(x, "stage_number", getattr(x, "approval_stage", 0))):
        if getattr(row, "stage_number", getattr(row, "approval_stage", 0)) > current_stage_num:
            return row
    return None

def _find_current_stage(matrix, row):
    stages_list = getattr(matrix, "stages", getattr(matrix, "approval_stages", []))
    current_stage_num = getattr(row, "next_stage", 0)
    for stage in stages_list:
        if getattr(stage, "stage_number", getattr(stage, "approval_stage", 0)) == current_stage_num:
            return stage
    return None

def _send_email(template_name, context):
    template_data = frappe.get_doc("Email Template", template_name)
    if not template_data:
        raise frappe.DoesNotExistError(f"Email Template '{template_name}' not found")

    subject = template_data.get("subject", "")
    response = template_data.get("response_html", "")

    subject = frappe.render_template(subject, context) if subject else ""
    response = frappe.render_template(response, context) if response else ""

    recipients = context.get("recipients", ["rishi.hingad@merillife.com"])
    if isinstance(recipients, str): recipients = [recipients]
    recipients = [r for r in recipients if r and str(r).lower() not in ("administrator", "guest")]

    cc = context.get("cc", ["rishi.hingad@merillife.com"])
    if isinstance(cc, str): cc = [cc]
    cc = [c for c in cc if c and str(c).lower() not in ("administrator", "guest")]

    if not recipients:
        return

    alms_settings = frappe.get_single("ALMS Settings")
    sender = getattr(alms_settings, "from_address", None)

    bcc = []
    if hasattr(alms_settings, "bcc_address") and alms_settings.bcc_address:
        for row in alms_settings.bcc_address:
            email = row.get("email_address") if isinstance(row, dict) else getattr(row, "email_address", None)
            template_type = row.get("email_template") if isinstance(row, dict) else getattr(row, "email_template", None)
            
            if email and template_type in ("All", template_name):
                bcc.append(email.strip())

    frappe.sendmail(
        sender=sender,
        recipients=recipients,
        cc=cc,
        bcc=bcc,
        subject=subject,
        message=response
    )

def _add_next_pending_stage(entry, next_stage, ledger_table, current_stage_num):
    next_stage_val = getattr(next_stage, "stage_number", getattr(next_stage, "approval_stage", 0))
    approver_type = getattr(next_stage, "approver_type", None)
    
    next_approver = getattr(next_stage, "employee", getattr(next_stage, "user", None)) if approver_type in ["User", None] else None
    next_approver_role = getattr(next_stage, "role", None) if approver_type in ["Role", None] else None
    next_approver_team = getattr(next_stage, "team", getattr(next_stage, "department", None)) if approver_type in ["Team", "Department", None] else None
    
    entry.append(ledger_table, {
        "status": "Pending",
        "current_stage": current_stage_num,
        "next_stage": next_stage_val,
        "next_approver": next_approver,
        "next_approver_role": next_approver_role,
        "next_approver_team": next_approver_team
    })
    entry.save(ignore_permissions=True)
    
def _finalize_approval(doctype, doc_name, entry, pending_row=None, ledger_table=None, employee=None, user=None, remarks=None):
    """
    Finalize the approval process and update the document and entry statuses.
    Optionally allows for backward compatibility if only (doctype, doc_name, entry) are supplied.
    Additionally, append a new row in the ledger table for the current approver.
    """
    entry.status = "Approved"

    # Append a new row in the ledger table for the current approver
    if ledger_table and pending_row:
        entry.append(ledger_table, {
            "action":"Approved",
            "action_at": frappe.utils.now_datetime(),
            "status": "Approved",
            "approved_by": employee,
            "approver_user": user,
            "remarks": remarks,
            "current_stage": getattr(pending_row, "next_stage", None),
            "next_stage": None,
            "next_approver": None,
            "next_approver_role": None
        })

    entry.save(ignore_permissions=True)

    # Set the original document's status to Approved if the status field exists
    original_doc = frappe.get_doc(doctype, doc_name)
    
    # Sync the final stage legacy fields BEFORE saving, so that validate hooks see the correct values
    matrix = frappe.get_doc("Approval Matrix", entry.approval_matrix)
    current_stage = _find_current_stage(matrix, pending_row)
    if current_stage:
        _sync_generic_legacy_fields(doctype, doc_name, current_stage, "Approved", remarks)
        original_doc.reload() # Reload the document to get the updated legacy fields

    if hasattr(original_doc, "status") or frappe.db.has_column(doctype, "status"):
        original_doc.status = "Approved"
        original_doc.save(ignore_permissions=True)

    # Send closure email if configured
    try:
        matrix = frappe.get_doc("Approval Matrix", entry.approval_matrix)
        current_stage = _find_current_stage(matrix, pending_row)
        if current_stage:
            n_user = original_doc.owner
            n_role = None
            
            # ALMS custom logic: if final stage approves, trigger specific emailsService logic
            email_send_to = None
            if doctype == "Car Indent Form" and current_stage.role == "HR Head":
                email_send_to = "HRHead To PurchaseForm"
                n_user = None
                n_role = "Purchase Team"
            elif doctype == "Purchase Form" and current_stage.role == "Purchase Head":
                email_send_to = "PurchaseHead To FinanceTeam"
                n_user = None
                n_role = "Finance Team"
            elif doctype == "Car Quotation" and current_stage.role == "Finance Head":
                email_send_to = "FinanceHead To All"
            
            if email_send_to:
                try:
                    from leasemanagement.api.emailsService import email_sender
                except ImportError:
                    try:
                        from alms_app.api.emailsService import email_sender
                    except ImportError:
                        email_sender = None
                    employee_code = getattr(original_doc, "employee_code", None)
                    if not employee_code:
                        employee_code = getattr(original_doc, "employee_name", None)
                    if not employee_code:
                        employee_code = original_doc.owner
                        
                    payload = None
                    if doctype == "Car Quotation":
                        payload = {"quotation_id": original_doc.name}
                        employee_code = getattr(original_doc, "employee_details", employee_code)
                    email_sender(
                        name=employee_code,
                        email_send_to=email_send_to,
                        car_indent_form_name=original_doc.name,
                        payload=payload
                    )
                except Exception as e:
                    frappe.log_error(f"Error calling emailsService email_sender: {str(e)}", "Approval Closure Email Error")

            context = get_email_context(doctype, original_doc, next_user=n_user, next_role=n_role, action="Closed")
            if context:
                # Ensure the original submitter gets CC'd if they are not the main recipient
                if n_role in ["Purchase Team", "Finance Team"] and "cc" in context:
                    if original_doc.owner not in context["cc"]:
                        context["cc"].append(original_doc.owner)

                context["remarks"] = remarks or "-"

                email_template = current_stage.email_template
                if email_template:
                    _send_email(email_template, context)
    except Exception as e:
        frappe.log_error(f"Error sending closure email: {str(e)}", "Approval Closure Email Error")

    _sync_generic_legacy_fields(doctype, doc_name, current_stage, "Approved", remarks)

    return {"status": "success", "message": "Document approved successfully"}

@frappe.whitelist()
def can_approve(doctype, doc_name):
    """
    Check if the current session user can approve the document based on the pending Approval Entry.
    """
    try:
        frappe.flags.ignore_permissions = True
        try:
            entry_name = frappe.db.get_value("Approval Entry", {
                "applied_to_doctype": doctype,
                "record": doc_name,
                "status": "Pending"
            }, "name")
            
            user = frappe.session.user
            if not entry_name:
                return False
                
            entry = frappe.get_doc("Approval Entry", entry_name)
            ledger_table = "approval_ledger" if hasattr(entry, "approval_ledger") else "approval_entry"
            ledger_items = entry.get(ledger_table)
        finally:
            frappe.flags.ignore_permissions = False
        
        if not ledger_items:
            return False
            
        target_stage = entry.next_approval_stage
        pending_row = None
        for row in ledger_items:
            if row.next_stage == target_stage:
                pending_row = row
        
        if not pending_row:
            pending_row = ledger_items[-1]

        employee = frappe.db.get_value("Employee", {"user_id": user}, "name")

        allowed_team = getattr(pending_row, "next_approver_team", None)
        allowed_user = getattr(pending_row, "next_approver", None)
        allowed_role = getattr(pending_row, "next_approver_role", None)

        print(f"[DEBUG can_approve] doc: {doctype} {doc_name}")
        print(f"[DEBUG can_approve] user: {user}, employee: {employee}")
        print(f"[DEBUG can_approve] allowed_team: {allowed_team}, allowed_user: {allowed_user}, allowed_role: {allowed_role}")

        if user == "Administrator":
            print("[DEBUG can_approve] User is Administrator -> True")
            return True

        if allowed_user:
            if employee and allowed_user == employee:
                print("[DEBUG can_approve] User matches allowed_user -> True")
                return True
            else:
                print("[DEBUG can_approve] User does NOT match strictly enforced allowed_user -> False")
                return False

        roles = frappe.get_roles(user)
        print(f"[DEBUG can_approve] user roles: {roles}")
        
        if allowed_role and allowed_role in roles:
            print("[DEBUG can_approve] User has allowed_role -> True")
            return True

        if allowed_team and employee:
            if frappe.db.exists("Employee", {"department": allowed_team, "name": employee}):
                print("[DEBUG can_approve] User is in allowed_team -> True")
                return True
            else:
                print(f"[DEBUG can_approve] User is NOT in allowed_team {allowed_team}")

        print("[DEBUG can_approve] All checks failed -> False")
        return False
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Can Approve Error: {e}")
        return False

@frappe.whitelist()
def can_revoke(doctype, doc_name):
    try:
        user = frappe.session.user
        if user == "Administrator":
            return True
            
        frappe.flags.ignore_permissions = True
        try:
            entry_name = frappe.db.get_value("Approval Entry", {
                "applied_to_doctype": doctype,
                "record": doc_name
            }, "name", order_by="creation desc")
            
            if not entry_name:
                return False
                
            entry = frappe.get_doc("Approval Entry", entry_name)
            ledger_table = "approval_ledger" if hasattr(entry, "approval_ledger") else "approval_entry"
            ledger_items = entry.get(ledger_table)
        finally:
            frappe.flags.ignore_permissions = False
            
        if not ledger_items:
            return False
            
        # Find the last approved row
        last_approved_row = None
        for row in reversed(ledger_items):
            if row.action == "Approved":
                last_approved_row = row
                break
                
        if not last_approved_row:
            return False
            
        employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if last_approved_row.approver_user == user or (employee and last_approved_row.approved_by == employee):
            return True
            
        return False
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Can Revoke Error: {e}")
        return False

@frappe.whitelist()
def has_previously_approved(doctype, doc_name):
    """
    Check if the current session user has approved any previous stage of the document.
    """
    try:
        user = frappe.session.user
        if user == "Administrator" and doctype == "Car Indent Form":
            return True

        frappe.flags.ignore_permissions = True
        try:
            entry_name = frappe.db.get_value("Approval Entry", {
                "applied_to_doctype": doctype,
                "record": doc_name,
                "status": ["in", ["Pending", "Approved", "Rejected"]]
            }, "name", order_by="creation desc")
            
            if not entry_name:
                return False
                
            entry = frappe.get_doc("Approval Entry", entry_name)
        finally:
            frappe.flags.ignore_permissions = False
        for row in getattr(entry, "approval_entry", []):
            if row.action == "Approved" and row.approver_user == user:
                return True
        return False
    except Exception:
        return False



def get_approval_status(approval_entry:str) -> str:
    entry = frappe.get_doc("Approval Entry", approval_entry)
    if not entry:
        return None
    next_approver = None
    if entry.next_approver:
        next_approver = frappe.get_value("Employee", entry.next_approver, "full_name")
    if entry.status == "Pending":
        if not next_approver:
            pending_row = entry.approval_entry[-1]
            if pending_row.next_approver_team:
                next_approver = pending_row.next_approver_team
                return f"Awaiting Approval from {next_approver} Team",entry.previous_approver_remarks or "-"
            elif pending_row.next_approver_role:
                next_approver = pending_row.next_approver_role
                return f"Awaiting Approval from {next_approver} Role",entry.previous_approver_remarks or "-"
            else:
                return "Awaiting Approval",entry.previous_approver_remarks or "-"
        return f"Awaiting Approval from {next_approver}",entry.previous_approver_remarks or "-"
    if entry.previous_approver:
        previous_approver = frappe.get_value("Employee", entry.previous_approver, "full_name")
        return f"Rejected by {previous_approver}",entry.previous_approver_remarks or "-"
    return entry.status,entry.previous_approver_remarks or "-"

def check_restart_approval(entry) -> bool:    
    return frappe.get_value("Approval Matrix", entry.approval_matrix, "action_on_rejection") == RESTART_FROM_BEGINNING if entry else False

def revoke_last_approval(doctype, doc_name, reason=None):
    """
    Revoke the last approval on a document's Approval Entry.
    Called when a post-approval process (e.g. SAP integration) fails and
    the approval needs to be rolled back to Pending.
    
    Args:
        doctype: The doctype of the original document
        doc_name: The name of the original document
        reason: Optional reason for the revocation (logged in remarks)
    
    Returns:
        dict with status and message
    """
    try:
        entry = get_approval_entry(doctype, doc_name)
        if not entry:
            return {"status": "error", "message": f"No Approval Entry found for {doctype} {doc_name}"}

        if entry.status != "Approved":
            return {"status": "skipped", "message": f"Approval Entry is already '{entry.status}', not revoking."}

        # Revert the Approval Entry: set status back to Pending and remove the last ledger row
        revert_approval_status(entry)

        # Also revert the original document's status field back to Pending
        if frappe.db.has_column(doctype, "status"):
            frappe.db.set_value(doctype, doc_name, "status", "Pending", update_modified=True)

        frappe.db.commit()

        frappe.log_error(
            f"Approval revoked for {doctype} {doc_name}. Reason: {reason or 'Not specified'}",
            "Approval Revoked - Post-Approval Failure"
        )

        return {"status": "success", "message": f"Last approval revoked for {doc_name}. Entry reverted to Pending."}

    except Exception as e:
        frappe.log_error(
            f"Failed to revoke approval for {doctype} {doc_name}: {str(e)}\n\n{frappe.get_traceback()}",
            "Revoke Approval Error"
        )
        return {"status": "error", "message": f"Failed to revoke approval: {str(e)}"}

def revert_approval_status(entry):
    entry.status = "Pending"
    if entry.approval_entry and len(entry.approval_entry) > 0:
        entry.approval_entry.pop(-1)
    entry.save(ignore_permissions=True)

def get_approval_entry(doctype, doc_name):
    return frappe.get_doc("Approval Entry", {
        "applied_to_doctype": doctype,
        "record": doc_name
    })
@frappe.whitelist()
def get_approval_trail(doctype, doc_name):
    entry_name = frappe.db.get_value('Approval Entry', {
        'applied_to_doctype': doctype,
        'record': doc_name
    }, 'name')
    
    if not entry_name:
        return []
        
    frappe.flags.ignore_permissions = True
    try:
        entry = frappe.get_doc('Approval Entry', entry_name)
        ledger_table = 'approval_ledger' if hasattr(entry, 'approval_ledger') else 'approval_entry'
        ledger_items = entry.get(ledger_table)
        
        matrix = None
        if getattr(entry, 'approval_matrix', None):
            matrix = frappe.get_doc("Approval Matrix", entry.approval_matrix)

        trail = []
        for i, item in enumerate(ledger_items):
            # Skip historical 'Pending' rows. Only show a Pending row if it's the current active stage (the very last item)
            if item.status == "Pending" and i < len(ledger_items) - 1:
                continue

            role_name = None
            if matrix and getattr(item, 'current_stage', None) is not None:
                stages = getattr(matrix, "stages", getattr(matrix, "approval_stages", []))
                for stage in stages:
                    st_num = getattr(stage, "stage_number", getattr(stage, "approval_stage", None))
                    if st_num == item.current_stage:
                        role_name = getattr(stage, "role", getattr(stage, "team", None))
                        break

            approver_val = getattr(item, 'approver_user', None)
            if approver_val and role_name:
                approver_val = f"{approver_val} ({role_name})"

            trail.append({
                'action': item.action,
                'status': item.status,
                'action_at': item.action_at if hasattr(item, 'action_at') else None,
                'approver_user': approver_val,
                'next_approver_role': getattr(item, 'next_approver_role', None),
                'next_approver_team': getattr(item, 'next_approver_team', None),
                'remarks': getattr(item, 'remarks', None)
            })
        return trail
    finally:
        frappe.flags.ignore_permissions = False
