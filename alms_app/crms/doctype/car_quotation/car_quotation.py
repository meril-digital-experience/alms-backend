import frappe
from openpyxl import load_workbook
from frappe.model.document import Document
from frappe.utils.file_manager import save_file
import xlrd
from alms_app.api.emailsService import email_sender
from frappe.utils import flt
import math
from frappe.utils import now_datetime
from mds_master.mds_approval.approval_router import trigger_approval_if_matrix_exists
from mds_master.mds_approval.approval_router import process_approval_action



class CarQuotation(Document):

    def before_insert(self):
        # Auto-submit to start approval matrix instantly
        self.is_submitted = 1

        self.submission_datetime = now_datetime()
        
        # Populate car_indent_form_id if not present
        if self.employee_details and not self.car_indent_form_id:
            cif = frappe.get_all("Car Indent Form", filters={"employee_code": self.employee_details}, pluck="name", limit=1)
            if cif:
                self.car_indent_form_id = cif[0]

        # CASE 1: NEW quotation (root)
        if self.quotation_status == "New":
            self.root_quotation = self.name
            self.version_number = 1

        # CASE 2: REVISED quotation
        elif self.quotation_status == "Revised":

            if not self.revised_modify_quotation_id:
                frappe.throw("Missing base quotation")

            parent = frappe.get_doc("Car Quotation", self.revised_modify_quotation_id)

            # Root stays same
            self.root_quotation = parent.root_quotation or parent.name

            # Parent linkage
            self.parent_quotation = parent.name

            # Version increment
            self.version_number = (parent.version_number or 1) + 1

            # Naming logic
            self.name = f"{self.root_quotation}-v{self.version_number}"

    def on_update(self):
        is_active = self.status == "Approved" or (self.finance_team_status == "Approved" and self.status != "Rejected")
        if is_active:
            reject_other_quotations(self)
        else:
            handle_no_approved_case(self)

    def validate(self):
        self.sync_status()
        self.calculate_quarterly_payment()
    
    def calculate_quarterly_payment(self):
        total_emi = flt(self.total_emi)

        if total_emi < 0:
            frappe.throw("Total EMI cannot be negative")

        self.quarterly_payment = total_emi * 4

    def sync_status(self):
        if getattr(self, "approval_entry", None):
            ae_status = frappe.db.get_value("Approval Entry", self.approval_entry, "status")
            if ae_status == "Approved":
                self.status = "Approved"
                self.finance_team_status = "Approved"
                self.finance_head_status = "Approved"
                reject_other_quotations(self)
                return
            elif ae_status == "Rejected":
                self.status = "Rejected"
                if self.finance_team_status != "Approved":
                    self.finance_team_status = "Rejected"
                else:
                    self.finance_head_status = "Rejected"
                return

        ft = (self.finance_team_status or "").strip().lower()
        fh = (self.finance_head_status or "").strip().lower()

        # Normalize
        if ft in ["", "-select-"]:
            self.finance_team_status = "Pending"
            ft = "pending"

        if fh in ["", "-select-"]:
            self.finance_head_status = "Pending"
            fh = "pending"

        # ===== STATUS LOGIC =====
        if ft == "rejected" or fh == "rejected":
            self.status = "Rejected"

        elif ft == "approved" and fh == "approved":
            self.status = "Approved"

            # enforce only one approved
            reject_other_quotations(self)

        else:
            self.status = "Pending"



    def after_insert(self):
        try:
            employee_details = self.employee_details
            finance_company = self.finance_company
            ref_no = self.name

            if not employee_details or not finance_company or not ref_no:
                frappe.log_error("Missing required values in CarQuotation", "CarQuotation Error")
            else:
                # Step 1: Check if Selected Vendor exists
                selected_vendor = frappe.db.get_value(
                    "Selected Vendor",
                    {"employee_details": employee_details},
                    "name"
                )

                if selected_vendor:
                    doc = frappe.get_doc("Selected Vendor", selected_vendor)

                    # Check duplicate
                    exists = any(
                        row.finance_company == finance_company and row.ref_no == ref_no
                        for row in doc.selected_finance_company
                    )

                    if not exists:
                        doc.append("selected_finance_company", {
                            "finance_company": finance_company,
                            "ref_no": ref_no
                        })
                        doc.save(ignore_permissions=True)

                else:
                    # Create new Selected Vendor
                    doc = frappe.get_doc({
                        "doctype": "Selected Vendor",
                        "employee_details": employee_details,
                        "selected_finance_company": [
                            {
                                "finance_company": finance_company,
                                "ref_no": ref_no
                            }
                        ]
                    })
                    doc.insert(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "CarQuotation after_insert Error")
        
        try:
            email_sender(
                name=self.employee_details,
                email_send_to="Finance Fill Quotation Acknowledgement",
                payload={
                    "vendors": [self.finance_company],
                    "email_phase": "Revised" if self.quotation_status == "Revised" else "Initial"
                }
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "ACK EMAIL FAILED")

        

def restore_other_quotations(doc):
    others = frappe.get_all(
        "Car Quotation",
        filters={
            "employee_details": doc.employee_details,
            "name": ["!=", doc.name]
        },
        pluck="name"
    )

    for q in others:
        q_doc = frappe.get_doc("Car Quotation", q)

        if q_doc.status != "Rejected":
            continue

        q_doc.finance_team_status = "Pending"
        q_doc.finance_head_status = "Pending"
        q_doc.status = "Pending"

        q_doc.save(ignore_permissions=True)

def handle_no_approved_case(doc):
    if frappe.flags.reverting_quotations:
        return
        
    all_quotations = frappe.get_all(
        "Car Quotation",
        filters={"employee_details": doc.employee_details},
        fields=["name", "status", "finance_team_status"]
    )

    has_active = False
    for q in all_quotations:
        if q.status == "Approved" or (q.finance_team_status == "Approved" and q.status != "Rejected"):
            has_active = True
            break

    if not has_active:
        frappe.flags.reverting_quotations = True
        try:
            for q in all_quotations:
                if q.status == "Rejected":
                    if q.name == doc.name:
                        # Do not revert the currently rejected document back to Pending
                        pass
                    else:
                        q_doc = frappe.get_doc("Car Quotation", q.name)
                        q_doc.db_set("finance_team_status", "Pending", update_modified=False)
                        q_doc.db_set("finance_head_status", "Pending", update_modified=False)
                        q_doc.db_set("finance_team_remarks", "", update_modified=False)
                        q_doc.db_set("finance_head_remarks", "", update_modified=False)
                        q_doc.db_set("status", "Pending", update_modified=False)
                        
                        # Properly restart the Approval Entry
                        q_doc.db_set("is_submitted", 0, update_modified=False)
                        q_doc.save(ignore_permissions=True)
                        q_doc.db_set("is_submitted", 1, update_modified=False)
                        q_doc.save(ignore_permissions=True)
        finally:
            frappe.flags.reverting_quotations = False


@frappe.whitelist()
def process_uploaded_file(file_url):
    if not file_url:
            frappe.throw("No file attached for upload.")

    try:
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        file_path = file_doc.get_full_path()

        rows = []
        if file_path.endswith(".xlsx"):
            wb = load_workbook(file_path, data_only=True)
            sheet = wb.active
            headers = [cell.value for cell in sheet[1]]
            for row_cells in sheet.iter_rows(min_row=2, values_only=True):
                rows.append(dict(zip(headers, row_cells)))
        elif file_path.endswith(".xls"):
            wb = xlrd.open_workbook(file_path)
            sheet = wb.sheet_by_index(0)
            headers = sheet.row_values(0)
            for rowx in range(1, sheet.nrows):
                rows.append(dict(zip(headers, sheet.row_values(rowx))))
        elif file_path.endswith(".csv"):
            import csv
            with open(file_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        else:
            frappe.throw("Unsupported file format. Please upload an Excel or CSV file.")

        for row in rows:
            car_quotation_item = frappe.get_doc({
                "doctype": "Car Quotation",
                "finance_company": row.get("finance_company"),
                "accessory": row.get("accessory"),
                "gst_and_cess": row.get("gst_and_cess"),
                "employee_details": row.get("employee_details"),
                "discount_excluding_gst": row.get("discount_excluding_gst"),
                "insurance": row.get("insurance"),
                "location": row.get("location"),
                "base_price_less_discounts": row.get("base_price_less_discounts"),
                "fleet_management_repairs_and_tyres": row.get("fleet_management_repairs_and_tyres"),
                "kms": row.get("kms"),
                "total_discount": row.get("total_discount"),
                "24x7_assist": row.get("24x7_assist"),
                "variant": row.get("variant"),
                "ex_showroom_amount_net_of_discount": row.get("ex_showroom_amount_net_of_discount"),
                "pickup_and_drop": row.get("pickup_and_drop"),
                "quote": row.get("quote"),
                "registration_charges": row.get("registration_charges"),
                "interest_rate": row.get("interest_rate"),
                "residual_value_percent": row.get("residual_value_percent"),
                "std_relief_car_non_accdt": row.get("std_relief_car_non_accdt"),
                "tenure": row.get("tenure"),
                "financed_amount": row.get("financed_amount"),
                "gst_on_fms": row.get("gst_on_fms"),
                "base_price_excluding_gst": row.get("base_price_excluding_gst"),
                "total_emi": row.get("total_emi"),
                "gst": row.get("gst"),
                "emi_financing": row.get("emi_financing"),
                "status": row.get("status"),
                "ex_showroom_amount": row.get("ex_showroom_amount"),
                "finance_emi_road_tax": row.get("finance_emi_road_tax"),
                "finance_hod_status": row.get("finance_hod_status"),
            })

            # car_quotation_item.insert()

        return {"car_quotation_item":car_quotation_item}
        # frappe.db.commit()
        # return f"File processed successfully: {file_path}"

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "File Processing Error")
        frappe.throw(f"An error occurred while processing the file: {str(e)}")


@frappe.whitelist()
def generate_deduction(quotation_id):

    quotation = frappe.get_doc("Car Quotation", quotation_id)

    doc = frappe.new_doc("Company and Employee Deduction")

    doc.finance_quotation_id = quotation.name
    doc.employee_details = quotation.employee_details
    doc.finance_company = quotation.finance_company

    # Company values
    doc.quarterly_payment = quotation.quarterly_payment

    # Employee values
    doc.employee_quarterly_payment = quotation.employee_quarterly_payment

    # copy other required calculation fields
    doc.interest_rate = quotation.interest_rate
    doc.tenure = quotation.tenure
    doc.ex_showroom_amount_net_of_discount = quotation.ex_showroom_amount_net_of_discount
    doc.registration_charges = quotation.registration_charges
    doc.residual_value = quotation.residual_value

    doc.insert(ignore_permissions=True)

    return doc.name


def pmt(rate, nper, pv, fv=0, when=1):
    if rate == 0:
        return -(pv + fv) / nper
    return -(rate * (fv + pv * (1 + rate) ** nper)) / ((1 + rate * when) * ((1 + rate) ** nper - 1))


@frappe.whitelist()
def preview_deduction(quotation_id):

    q = frappe.get_doc("Car Quotation", quotation_id)
    employee = frappe.get_doc("Employee", q.employee_details)
    
    # ---- Company contribution logic (same as calculate_emi) ----

    interest_rate = flt(q.interest_rate) / 100
    tenure = flt(q.tenure)

    registration = flt(q.registration_charges)
    gst = flt(q.gst)

    insurance = flt(q.insurance)
    fms = flt(q.fleet_management_repairs_and_tyres)
    assist = flt(q.get("24x7_assist"))
    print("Value of 24x7 assist:",assist)
    # assist = flt(97)
    pickup = flt(q.pickup_and_drop)
    relief = flt(q.std_relief_car_non_accdt)
    monthly_rate = interest_rate / 12

    company_ex_showroom_amount_net_of_discount = flt(employee.eligibility)
    print("Company ex-showroom amount net of discount:", company_ex_showroom_amount_net_of_discount)

    registration = flt(q.registration_charges)

    # Company financed amount
    financed_amount = company_ex_showroom_amount_net_of_discount + registration
    print("Company financed amount:", financed_amount)

    # Residual value calculation (53%)
    residual_percent = flt(q.residual_value_percent) / 100
    residual_amount = flt(q.residual_value)

    pmt_val = pmt(monthly_rate, tenure, -financed_amount, residual_amount, 1)
    print("PMT for company:", pmt_val)

    gst_per_month = gst / tenure if tenure else 0

    emi_financing = round(pmt_val - gst_per_month)
    print("EMI financing for company:", emi_financing)

    finance_emi_road_tax = round(emi_financing - (registration / tenure if tenure else 0))
    print("Finance EMI road tax for company:", finance_emi_road_tax)

    gst_and_cess = round(finance_emi_road_tax * 45 / 100)
    print("GST and cess for company:", gst_and_cess)

    gst_on_fms = round((insurance + fms + assist + pickup + relief) * 18 / 100)
    print("GST on FMS for company:", gst_on_fms)
    print("Insurance for company:", insurance)
    print("FMS for company:", fms)
    print("Assist for company:", assist)

    total_emi1 = (
        emi_financing
        + gst_and_cess
        + insurance
        + fms
        + assist
        + pickup
        + relief
        + gst_on_fms
    )

    total_emi = round(total_emi1)
    print("Total EMI for company:", total_emi)

    quarterly_payment = math.ceil(total_emi * 3)
    interim_payment = math.ceil(quarterly_payment * 39 / 90)

    # ---- Employee contribution logic (same as calculate_employee_fields) ----

    employee_ex_showroom_amount_net_of_discount = (flt(q.ex_showroom_amount_net_of_discount) - company_ex_showroom_amount_net_of_discount)

    employee_financed_amount = math.ceil(employee_ex_showroom_amount_net_of_discount)

    pmt_emp = pmt(monthly_rate, tenure, -employee_financed_amount, 0, 1)
    print("PMT for employee:", pmt_emp)

    employee_emi_financing = pmt_emp

    employee_finance_emi_road_tax = employee_emi_financing
    print("Finance EMI road tax for employee:", employee_finance_emi_road_tax)

    employee_gst_and_cess = round(employee_finance_emi_road_tax * 45 / 100)
    print("GST and cess for employee:", employee_gst_and_cess)

    employee_total_emi = round(employee_emi_financing + employee_gst_and_cess)
    print("Total EMI for employee:", employee_total_emi)

    employee_quarterly_payment = math.ceil(employee_total_emi * 3)
    employee_interim_payment = math.ceil(employee_quarterly_payment * 39 / 90)

    return {
        # company
        "company_ex_showroom": company_ex_showroom_amount_net_of_discount,
        "company_financed_amount": financed_amount,
        "company_emi_financing": emi_financing,
        "company_finance_emi_road_tax": finance_emi_road_tax,
        "company_gst_and_cess": gst_and_cess,
        "company_gst_on_fms": gst_on_fms,
        "total_emi": total_emi,
        "quarterly_payment": quarterly_payment,
        "interim_payment": interim_payment,

        # employee
        "employee_ex_showroom": employee_ex_showroom_amount_net_of_discount,
        "employee_financed_amount": employee_financed_amount,
        "employee_emi_financing": employee_emi_financing,
        "employee_finance_emi_road_tax": employee_finance_emi_road_tax,
        "employee_gst_and_cess": employee_gst_and_cess,
        "employee_total_emi": employee_total_emi,
        "employee_quarterly_payment": employee_quarterly_payment,
        "employee_interim_payment": employee_interim_payment
    }

@frappe.whitelist()
def create_deduction_doc(quotation_id):

    q = frappe.get_doc("Car Quotation", quotation_id)
    values = preview_deduction(quotation_id)

    doc = frappe.new_doc("Company and Employee Deduction")

    doc.finance_quotation_id = quotation_id
    doc.employee_name = q.employee_details

    # company
    doc.ex_showroom_amount = values["company_ex_showroom"]
    doc.financed_amount = values["company_financed_amount"]
    doc.emi_financing = values["company_emi_financing"]
    doc.finance_emi_road_tax = values["company_finance_emi_road_tax"]
    doc.gst_and_cess = values["company_gst_and_cess"]
    doc.gst_on_fms = values["company_gst_on_fms"]

    doc.total_emi = values["total_emi"]
    doc.quarterly_payment = values["quarterly_payment"]
    doc.interim_payment = values["interim_payment"]

    # employee
    doc.employee_ex_showroom_amount_net_of_discount = values["employee_ex_showroom"]
    doc.employee_financed_amount = values["employee_financed_amount"]
    doc.employee_emi_financing = values["employee_emi_financing"]
    doc.employee_finance_emi_road_tax = values["employee_finance_emi_road_tax"]
    doc.employee_gst_and_cess = values["employee_gst_and_cess"]
    doc.employee_total_emi = values["employee_total_emi"]
    doc.employee_quarterly_payment = values["employee_quarterly_payment"]
    doc.employee_interim_payment = values["employee_interim_payment"]

    doc.insert(ignore_permissions=True)

    return doc.name

def reject_other_quotations(doc):
    others = frappe.get_all(
        "Car Quotation",
        filters={
            "employee_details": doc.employee_details,
            "name": ["!=", doc.name]
        },
        pluck="name"
    )

    for q in others:
        q_doc = frappe.get_doc("Car Quotation", q)

        if q_doc.status == "Rejected" or q_doc.status == "Approved":
            continue

        # Formally reject via approval matrix so the ledger is closed properly
        try:
            from mds_master.mds_approval.approval_router import process_approval_action
            original_user = frappe.session.user
            frappe.set_user("Administrator") # Auto-reject as system
            try:
                process_approval_action("Car Quotation", q_doc.name, "Reject", f"Auto-rejected because quotation {doc.name} was approved.")
            except Exception as e:
                frappe.log_error(str(e), "Auto-reject matrix fallback")
            finally:
                frappe.set_user(original_user)
        except Exception:
            pass

        # Fallback to ensure all statuses are explicitly rejected
        q_doc.db_set("status", "Rejected", update_modified=False)
        q_doc.db_set("finance_team_status", "Rejected", update_modified=False)
        q_doc.db_set("finance_head_status", "Rejected", update_modified=False)



@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_available_purchase_forms(doctype, txt, searchfield, start, page_len, filters):

    # Step 1: Approved Purchase Forms
    purchase_forms = frappe.get_all(
        "Purchase Form",
        filters={"status": "Approved"},
        pluck="name"
    )

    # Step 2: Already used (Approved quotation exists)
    used_forms = frappe.get_all(
        "Car Quotation",
        filters={"status": "Approved"},
        pluck="employee_details"
    )

    # Step 3: Forms that have at least one quotation submitted
    submitted_forms = frappe.get_all(
        "Car Quotation",
        pluck="employee_details"
    )

    # Step 4: Keep only approved forms with quotations, and remove used ones
    available = list((set(purchase_forms).intersection(set(submitted_forms))) - set(used_forms))

    # Step 4: Apply search filter (VERY IMPORTANT for typing in link field)
    if txt:
        available = [pf for pf in available if txt.lower() in pf.lower()]

    # Step 5: Return as list of tuples (Frappe expects this)
    return [(pf,) for pf in available[start:start + page_len]]


@frappe.whitelist()
def get_quotation_timeline(root_id):

    quotations = frappe.get_all(
        "Car Quotation",
        filters={"root_quotation": root_id},
        fields=[
            "name",
            "parent_quotation",
            "version_number",
            "status",
            "finance_company",
            "creation"
        ],
        order_by="version_number asc"
    )

    return quotations

@frappe.whitelist()
def create_revised_quotation(old_id):

    old = frappe.get_doc("Car Quotation", old_id)

    new_doc = frappe.copy_doc(old)

    new_doc.quotation_status = "Revised"
    new_doc.revised_modify_quotation_id = old.name

    new_doc.insert(ignore_permissions=True)

    return new_doc.name

@frappe.whitelist()
def process_workflow(quotation_id, action, remarks=""):
    # First update the legacy status fields based on current user role (Finance Team or Finance Head)
    doc = frappe.get_doc("Car Quotation", quotation_id)
    
    role = ""
    if "Administrator" in frappe.get_roles():
        role = "Administrator"
    elif "Finance Head" in frappe.get_roles():
        role = "Finance Head"
    elif "Finance Team" in frappe.get_roles() or "Finance" in frappe.get_roles():
        role = "Finance"

    if role == "Finance":
        doc.finance_team_status = action
        doc.finance_team_remarks = remarks
        doc.finance_team_action_by = frappe.session.user
    elif role == "Finance Head" or role == "Administrator":
        doc.finance_head_status = action
        doc.finance_head_remarks = remarks
        doc.finance_head_action_by = frappe.session.user
        if not doc.finance_team_status or doc.finance_team_status == "Pending":
            doc.finance_team_status = action
            doc.finance_team_remarks = remarks
            doc.finance_team_action_by = frappe.session.user
            
    doc.save(ignore_permissions=True)

    # Then process through standard approval router
    try:
        
        router_action = "Approve" if action == "Approved" else "Reject" if action == "Rejected" else action
        
        result = process_approval_action("Car Quotation", quotation_id, router_action, remarks)
        
        if action == "Approved" and doc.finance_head_status == "Approved":
            email_sender(
                name=doc.employee_details,
                email_send_to="FinanceHead To All",
                payload={"quotation_id": quotation_id}
            )
            
        return result
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "process_workflow fallback")
        # If approval matrix fails or is not setup, rely on doc.save logic
        return {"status": "success", "message": f"Action {action} completed manually (Approval Router skipped)"}