import frappe
from frappe import _
from lease_app.approval.approval_router import get_role_based_approver


def _norm_approval_stage(val):
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _entry_row_display_stage(row):
    """
    Map a child-table row to the matrix stage it represents in the trail.
    Approval Entry Details uses current_stage / next_stage (not approval_stage).
    """
    status = (getattr(row, "status", None) or "").strip()
    if status == "Pending":
        n = _norm_approval_stage(getattr(row, "next_stage", None))
        if n is not None and n >= 0:
            return n
        n = _norm_approval_stage(getattr(row, "current_stage", None))
        if n is not None and n >= 0:
            return n
        return None
    n = _norm_approval_stage(getattr(row, "current_stage", None))
    if n is not None and n >= 0:
        return n
    n = _norm_approval_stage(getattr(row, "next_stage", None))
    if n is not None and n >= 0:
        return n
    return None


def _employee_people(employee_id):
    if not employee_id:
        return []
    names = frappe.db.get_value("Employee", employee_id, "full_name") or ""
    emails = frappe.db.get_value("Employee", employee_id, "company_email") or ""
    return [
        {
            "employee_id": employee_id,
            "full_name": names or "",
            "email": emails or "",
        }
    ]


def _pending_row_superseded(approval_entry_list, idx, stage, approval_row):
    """
    Ledger rows are append-only: an old Pending snapshot remains after Approve/Reject.
    Skip that Pending in the trail when a later row closes the same stage.
    (A new Pending after Reject is kept — no later Approved/Rejected for that stage yet.)
    """
    for j in range(idx + 1, len(approval_entry_list)):
        st_j, row_j = approval_entry_list[j]
        if st_j != stage:
            continue
        if getattr(row_j, "status", None) in ("Approved", "Rejected"):
            return True
    return False


@frappe.whitelist(allow_guest=False)
def get_approval_trail(doctype, docname):
    # print("Inside get_approval_trail")
    try:
        approval_trail = []
        approval_entries = frappe.get_all(
            "Approval Entry",
            filters={
                "applied_to_doctype": doctype,
                "record": docname
            },
            pluck="name"
        )

        approval_entry_stage_map = {}
        approval_matrix_stage_map = {}
        approval_entry_list = []

        next_approval_stage = None

        for approval_entry in approval_entries:
            frappe.flags.ignore_permissions = True
            try:
                doc = frappe.get_doc("Approval Entry", approval_entry)
            finally:
                frappe.flags.ignore_permissions = False

            approval_matrix_items = frappe.get_all(
                "Approval Matrix Item",
                filters={
                    "parent": doc.approval_matrix
                },
                fields=["role", "team", "approval_stage", "employee"],
                order_by="approval_stage"
            )
            for m in approval_matrix_items:
                st = _norm_approval_stage(m.get("approval_stage"))
                if st is not None:
                    approval_matrix_stage_map[st] = m

            for entry_row in doc.approval_entry:
                stage = _entry_row_display_stage(entry_row)
                if stage is None:
                    continue
                    
                approval_entry_stage_map.setdefault(stage, []).append(entry_row)
                approval_entry_list.append((stage, entry_row))

            next_approval_stage = _norm_approval_stage(getattr(doc, "next_approval_stage", None))

        approval_trail = []
        existing_entry_stages = {stage for stage, _ in approval_entry_list}

        seen_stages = set()
        for idx, (stage, approval_row) in enumerate(approval_entry_list):
            if _pending_row_superseded(approval_entry_list, idx, stage, approval_row):
                continue
            seen_stages.add(stage)

            matrix_row = approval_matrix_stage_map.get(stage, {})
            people = []
            row_status = (getattr(approval_row, "status", None) or "").strip()
            if row_status in ["Approved", "Rejected"]:
                label = approval_row.status.upper()
                variant = "success" if approval_row.status == "Approved" else "danger"
                
                approved_by_val = getattr(approval_row, "approved_by", None)
                approver_user = getattr(approval_row, "approver_user", None)
                
                if approved_by_val:
                    people = _employee_people(approved_by_val)
                    approver_name_str = frappe.db.get_value("Employee", approved_by_val, "full_name") or approved_by_val
                else:
                    if approver_user:
                        full_name = frappe.db.get_value("User", approver_user, "full_name") or approver_user
                        people = [{"employee_id": approver_user, "full_name": full_name, "email": approver_user}]
                        approver_name_str = full_name
                    else:
                        people = []
                        approver_name_str = ""

                role_out_ar = matrix_row.get("role")
                team_out_ar = matrix_row.get("team")

                dt = getattr(approval_row, "action_at", None)
                action_line = None
                if dt:
                    action_line = f"{'Approved' if approval_row.status == 'Approved' else 'Rejected'} On: {frappe.utils.format_datetime(dt, 'dd-MM-YYYY HH:mm:ss')}"
                    if approver_name_str:
                        action_line += f"<br>By: {approver_name_str}"
                        if role_out_ar:
                            action_line += f" ({role_out_ar})"
                        elif team_out_ar:
                            action_line += f" ({team_out_ar} Team)"
                approval_trail.append({
                    "label": label,
                    "variant": variant,
                    "approver": people,
                    "action_line": action_line,
                    "role": role_out_ar,
                    "team": team_out_ar,
                    "stage": stage,
                })

                # Approved ledger rows can carry metadata for the next pending approver.
                # Render that as a separate pending item in the upcoming stage.
                next_stage = _norm_approval_stage(getattr(approval_row, "next_stage", None))
                next_approver = getattr(approval_row, "next_approver", None)
                next_team = getattr(approval_row, "next_approver_team", None)
                next_role = getattr(approval_row, "next_approver_role", None)
                has_next_context = next_approver or next_role or next_team
                if (
                    row_status == "Approved"
                    and has_next_context
                    and next_stage
                    and next_stage not in seen_stages
                    and next_stage not in existing_entry_stages
                ):
                    next_matrix_row = approval_matrix_stage_map.get(next_stage, {})
                    if next_approver:
                        next_people = _employee_people(next_approver)
                        role_out = None
                        team_out = None
                    elif next_role:
                        next_people = [{
                            "employee_id": next_role,
                            "full_name": next_role or "",
                            "email": "",
                        }]
                        role_out = next_role
                        team_out = None
                    elif next_team:
                        next_people = [{
                            "employee_id": next_team,
                            "full_name": next_team or "",
                            "email": "",
                        }]
                        role_out = None
                        team_out = next_team
                    else:
                        next_people = [{
                            "employee_id": next_matrix_row.get("employee"),
                            "full_name": next_matrix_row.get("employee") or "",
                            "email": "",
                        }]
                        role_out = next_matrix_row.get("role")
                        team_out = next_matrix_row.get("team")

                    approval_trail.append({
                        "label": "PENDING APPROVAL",
                        "variant": "pending",
                        "approver": next_people,
                        "action_line": f"Submitted On: {frappe.utils.format_datetime(getattr(approval_row, 'assigned_at', ''),'dd-MM-YYYY HH:mm:ss')}" if getattr(approval_row, 'assigned_at', '') else None,
                        "role": role_out,
                        "team": team_out,
                        "stage": next_stage,
                    })
                    seen_stages.add(next_stage)
            elif row_status == "Pending":
                label = "PENDING APPROVAL"
                variant = "pending"
                next_approver = getattr(approval_row, "next_approver", None)
                next_team = getattr(approval_row, "next_approver_team", None)
                next_role = getattr(approval_row, "next_approver_role", None)
                if next_approver:
                    people = _employee_people(next_approver)
                    role_out = None
                    team_out = None
                elif next_role:
                    people = [{
                        "employee_id": next_role,
                        "full_name": next_role or "",
                        "email": "",
                    }]
                    role_out = next_role
                    team_out = None
                elif next_team:
                    people = [{
                        "employee_id": next_team,
                        "full_name": next_team or "",
                        "email": "",
                    }]
                    role_out = None
                    team_out = next_team
                else:
                    people = [{
                        "employee_id": matrix_row.get("employee"),
                        "full_name": matrix_row.get("employee") or "",
                        "email": "",
                    }]
                    role_out = matrix_row.get("role")
                    team_out = matrix_row.get("team")
                approval_trail.append({
                    "label": label,
                    "variant": variant,
                    "approver": people,
                    "action_line": f"Submitted On: {frappe.utils.format_datetime(getattr(approval_row, 'assigned_at', ''),'dd-MM-YYYY HH:mm:ss')}" if getattr(approval_row, 'assigned_at', '') else None,
                    "role": role_out,
                    "team": team_out,
                    "stage": stage,
                })
            else:
                label = approval_row.status.upper()
                variant = "info"
                approval_trail.append({
                    "label": label,
                    "variant": variant,
                    "approver": [],
                    "role": matrix_row.get("role"),
                    "team": matrix_row.get("team"),
                    "stage": stage,
                })

        matrix_stage_numbers = sorted(approval_matrix_stage_map.keys())

        fully_approved = False
        for idx, (stage, approval_row) in enumerate(approval_entry_list):
            if approval_row.status == "Pending":
                fully_approved = False
                break
            elif idx == len(approval_entry_list) - 1 and approval_row.status == "Approved":
                fully_approved = True

        for stage in matrix_stage_numbers:
            if stage in seen_stages:
                continue
            matrix_row = approval_matrix_stage_map[stage]

            label = "YET TO RECEIVE"
            variant = "upcoming"

            people = []
            employee = matrix_row.get("employee")
            role = matrix_row.get("role")
            team = matrix_row.get("team")
            if employee:
                people = _employee_people(employee)
            elif role:
                owner = frappe.db.get_value(doctype, docname, "owner")
                emp = ""
                if frappe.db.has_column(doctype, "employee_code"):
                    emp = frappe.db.get_value(doctype, docname, "employee_code")
                elif frappe.db.has_column(doctype, "employee"):
                    emp = frappe.db.get_value(doctype, docname, "employee")
                
                owner_emp = emp
                if not owner_emp:
                    owner_emp = frappe.db.get_value("Employee", {"user_id": owner, "status": "Active"}, "name")
                
                approver_dict = get_role_based_approver(
                    role,
                    owner_emp
                )
                if approver_dict:
                    employee = approver_dict.get("employee")
                    people = [{
                        "employee_id": employee,
                        "full_name": frappe.db.get_value("Employee", employee, "full_name") or employee,
                        "email": approver_dict.get("user") or frappe.db.get_value("Employee", employee, "company_email"),
                    }]
                else:
                    people = []
            elif team:
                people =[{
                    "employee_id": f"{team} Team",
                    "full_name": team,
                    "email": team,
                }]

            approval_trail.append({
                "label": label,
                "variant": variant,
                "approver": people,
                "role": matrix_row.get("role"),
                "team": matrix_row.get("team"),
                "stage": stage,
            })
        # print("Returning approval_trail:", approval_trail)
        
        return {
            "status": "success",
            "data": approval_trail
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        # frappe.log_error(message=str(e), title="Get Approval Trail Error")
        return {"status": "error", "message": f"Internal server error: {str(e)}"}