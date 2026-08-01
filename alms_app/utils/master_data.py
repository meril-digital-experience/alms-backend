import frappe
import json

# Handle Error function
def api_error(message, status_code=400, error=None, log_title="API Error"):
    """
    Standard API error response handler
    """
    frappe.local.response["http_status_code"] = status_code

    if error:
        frappe.log_error(message=frappe.get_traceback(), title=log_title)

    return {
        "success": False,
        "message": message,
        "error": str(error) if error else None,
        "data": []
    }


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_company_codes_by_session_user():
    """
    API to get company list for logged-in user
    """
    try:
        usr = frappe.session.user

        # Validate User
        if not usr:
            return api_error(
                message="User session not found",
                status_code=401
            )

        # Get Employee
        employee_name = frappe.db.get_value("Employee",
            {"user_id": usr},
            "name"
        )

        if not employee_name:
            return api_error(
                message="Employee not found for this user",
                status_code=404
            )

        emp_doc = frappe.get_doc("Employee", employee_name)

        # Validate Company Child Table
        if not emp_doc.get("company"):
            return api_error(
                message="No companies mapped to this employee",
                status_code=404
            )

        # Fetch Valid Companies
        companies = []

        for row in emp_doc.company:
            if not row.company_name:
                continue

            company_data = frappe.db.get_value(
                "Company Master",
                row.company_name,
                ["name", "company_name", "description"],
                as_dict=True
            )

            if company_data:
                companies.append(company_data)

        if not companies:
            return api_error(
                message="No valid companies found for this user",
                status_code=404
            )

        # Success Response
        frappe.local.response["http_status_code"] = 200
        return {
            "success": True,
            "message": "Company list fetched successfully",
            "user": usr,
            "data": companies
        }

    except frappe.PermissionError:
        return api_error(
            message="Permission denied",
            status_code=403,
            log_title="Permission Error - Get Company For User"
        )

    except Exception as e:
        return api_error(
            message="Internal server error",
            status_code=500,
            error=e,    
            log_title="Get Company For User API Error"
        )
    

@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_purchase_org_master_data(company=None, page_no=1, page_size=20, search_term=None):
    """
        Get Purchase Organization Master based on Company
    """
    try:
        if not company:
            return api_error("Please provide a company name.", 400)

        if not frappe.db.exists("Company Master", company):
            return api_error("Company not found.", 404)

        page_no = int(page_no)
        page_size = int(page_size)
        start = (page_no - 1) * page_size

        filters = {
            "company": company,
            "inactive": 0
        }

        if search_term:
            filters["purchase_organization_name"] = ["like", f"%{search_term}%"]

        total_count = frappe.db.count("Purchase Organization Master", filters=filters)

        data = frappe.get_all(
            "Purchase Organization Master",
            filters=filters,
            fields=["name", "purchase_organization_name", "description"],
            start=start,
            page_length=page_size,
            order_by="purchase_organization_name asc"
        )

        frappe.local.response["http_status_code"] = 200
        return {
            "success": True,
            "message": "Purchase Organizations fetched successfully.",
            "data": data,
            "total_count": total_count,
            "page_no": page_no,
            "page_size": page_size
        }

    except Exception as e:
        return api_error("Failed to fetch Purchase Organizations.", 500, str(e))




@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_terms_of_payment_master_data(company=None, page_no=1, page_size=20, search_term=None):
    """
        Get Terms of Payment Master based on Company
    """
    try:
        if not company:
            return api_error("Please provide a company name.", 400)

        if not frappe.db.exists("Company Master", company):
            return api_error("Company not found.", 404)

        page_no = int(page_no)
        page_size = int(page_size)
        start = (page_no - 1) * page_size

        filters = {
            "company": company,
            "inactive": 0
        }

        if search_term:
            filters["terms_of_payment_name"] = ["like", f"%{search_term}%"]

        total_count = frappe.db.count("Terms of Payment Master", filters=filters)

        data = frappe.get_all(
            "Terms of Payment Master",
            filters=filters,
            fields=["name", "terms_of_payment_name", "description"],
            start=start,
            page_length=page_size,
            order_by="terms_of_payment_name asc"
        )

        frappe.local.response["http_status_code"] = 200
        return {
            "success": True,
            "message": "Terms of Payment fetched successfully.",
            "data": data,
            "total_count": total_count,
            "page_no": page_no,
            "page_size": page_size
        }

    except Exception as e:
        return api_error("Failed to fetch Terms of Payment.", 500, str(e))



@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_incoterms_master_data(company=None, page_no=1, page_size=20, search_term=None):
    """
        Get Incoterm Master based on Company
    """
    try:
        if not company:
            return api_error("Please provide a company name.", 400)

        page_no = int(page_no)
        page_size = int(page_size)
        start = (page_no - 1) * page_size

        conditions = "ict.company = %s AND im.inactive = 0"
        values = [company]

        if search_term:
            conditions += " AND im.incoterm_name LIKE %s"
            values.append(f"%{search_term}%")

        # Total Count
        count_query = f"""
            SELECT COUNT(DISTINCT im.name)
            FROM `tabIncoterm Master` im
            INNER JOIN `tabIncoterm Company Table` ict
                ON im.name = ict.parent
            WHERE {conditions}
        """

        total_count = frappe.db.sql(count_query, values, as_list=True)[0][0]

        # Data Query
        data_query = f"""
            SELECT DISTINCT
                im.name,
                im.incoterm_code,
                im.incoterm_name
            FROM `tabIncoterm Master` im
            INNER JOIN `tabIncoterm Company Table` ict
                ON im.name = ict.parent
            WHERE {conditions}
            ORDER BY im.incoterm_name
            LIMIT %s OFFSET %s
        """

        values.extend([page_size, start])

        data = frappe.db.sql(data_query, values, as_dict=True)

        frappe.local.response["http_status_code"] = 200
        return {
            "success": True,
            "message": "Incoterms fetched successfully.",
            "data": data,
            "total_count": total_count,
            "page_no": page_no,
            "page_size": page_size
        }

    except Exception as e:
        return api_error("Failed to fetch Incoterms.", 500, str(e))

    


@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_reconciliation_master_data(account_group=None, page_no=1, page_size=20, search_term=None):
    """
        Get Reconciliation Master based on Company
    """
    try:
        if not account_group:
            return api_error("Please provide a account_group name.", 400)

        page_no = int(page_no)
        page_size = int(page_size)
        limit_start = (page_no - 1) * page_size

        filters = {
            "account_group": account_group,
            "inactive": 0
        }

        # search filter
        if search_term:
            filters["reconcil_account"] = ["like", f"%{search_term}%"]

        # Total count 
        total_records = frappe.db.count("Reconciliation Account", filters=filters)

        # dataRelated
        rc_account = frappe.get_all(
            "Reconciliation Account",
            filters=filters,
            fields=["name", "reconcil_account", "reconcil_description"],
            limit_start=limit_start,
            limit_page_length=page_size
        )

        return {
            "status": "success",
            "message": f"{len(rc_account)} records found.",
            "total_records": total_records,
            "page_no": page_no,
            "page_size": page_size,
            "data": rc_account
        }

    except Exception as e:
        return api_error("Failed to fetch Incoterms.", 500, str(e))    




@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_account_group_master_data(data=None):
    """
    Get Account Group Master based on Purchase Organization & Vendor Types
    """
    try:
        # Parse JSON if data is string
        if isinstance(data, str):
            data = json.loads(data)

        if not data:
            return api_error("Request data is required.", 400)

        purchase_organization = data.get("purchase_organization")
        vendor_types = data.get("vendor_types")

        if not purchase_organization:
            return api_error("Please provide a purchase organization.", 400)

        if not vendor_types:
            return api_error("Please provide vendor types.", 400)

        # vendor_types list
        if isinstance(vendor_types, str):
            vendor_types = [vendor_types]

        # Validate Purchase Organization
        if not frappe.db.exists("Purchase Organization Master", purchase_organization):
            return api_error("Purchase Organization not found.", 404)

        filters = {
            "purchase_organization": purchase_organization,
            "inactive": 0
        }

        account_groups = frappe.get_all(
            "Account Group Master",
            filters=filters,
            fields=[
                "name",
                "account_group_name"            
            ]
        )

        result = []

        # Filter by Vendor Types
        for group in account_groups:
            child_records = frappe.get_all(
                "Vendor Type for Account",
                filters={
                    "parent": group.name,
                    "vendor_type_ac": ["in", vendor_types]
                },
                fields=["vendor_type_ac"]
            )

            if child_records:
                result.append(group)

        total_count = len(result)

        frappe.local.response["http_status_code"] = 200
        return {
            "success": True,
            "message": "Account Groups fetched successfully.",
            "data": result,
            "total_count": total_count      
        }

    except Exception as e:
        return api_error(
            "Failed to fetch Account Groups.",
            500,
            error=e,
            log_title="Account Group Details API Error"
        )


@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_pincode_master(page_no=1, page_size=20, search_term=None):
    """
    Get Pincode Master List with Pagination
    """
    try:
        page_no = int(page_no)
        page_size = int(page_size)
        limit_start = (page_no - 1) * page_size

        filters = {
            "inactive": 0
        }

        # Search filter
        if search_term:
            filters["name"] = ["like", f"%{search_term}%"]

        # Correct Doctype Count
        total_records = frappe.db.count("Pincode Master", filters=filters)

        # Fetch Data
        pincode_list = frappe.get_all(
            "Pincode Master",
            filters=filters,
            fields=["name"],
            limit_start=limit_start,
            limit_page_length=page_size
        )

        return {
            "status": "success",
            "message": f"{len(pincode_list)} records found.",
            "total_records": total_records,
            "page_no": page_no,
            "page_size": page_size,
            "data": pincode_list
        }

    except Exception as e:
        return api_error("Failed to fetch Pincodes.", 500, str(e))



@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_location_by_pincode(pincode=None):
    """
    Get City, District, State and Country details based on Pincode
    """
    try:
        if not pincode:
            return api_error("Please provide a pincode.", 400)

        # Fetch Pincode Basic Data (Lightweight Query)
        pincode_doc = frappe.db.get_value(
            "Pincode Master",
            pincode,
            ["name", "city", "district", "state", "country"],
            as_dict=True
        )

        if not pincode_doc:
            return api_error("Pincode not found.", 404)

        # Fetch Related Masters
        city = frappe.db.get_value(
            "City Master",
            pincode_doc.city,
            ["name", "city_name"],
            as_dict=True
        ) if pincode_doc.city else {}


        district = frappe.db.get_value(
            "District Master",
            pincode_doc.district,
            ["name", "district_name"],
            as_dict=True
        ) if pincode_doc.district else {}


        state = frappe.db.get_value(
            "State Master",
            pincode_doc.state,
            ["name", "state_name"],
            as_dict=True
        ) if pincode_doc.state else {}


        country = frappe.db.get_value(
            "Country",
            pincode_doc.country,
            ["name", "country_name"],
            as_dict=True
        ) if pincode_doc.country else {}

        return {
            "status": "success",
            "message": "Location details fetched successfully.",
            "data": {
                "pincode": pincode_doc.name,
                "city": city,
                "district": district,
                "state": state,
                "country": country
            }
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_location_by_pincode")
        return api_error("Failed to fetch location details.", 500, str(e))



@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_bank_key_master_data(country=None, page_no=1, page_size=20, search_term=None):
    """
    Get paginated list of Bank Master records
    """
    try:
        page_no = int(page_no)
        page_size = int(page_size)
        limit_start = (page_no - 1) * page_size

        filters = {
            "country": country,
            "inactive": 0
        }

        # Search filter
        if search_term:
            filters["bank_code"] = ["like", f"%{search_term}%"]

        total_records = frappe.db.count("Bank Master", filters=filters)

        bank_list = frappe.get_all(
            "Bank Master",
            filters=filters,
            fields=["name", "bank_code"],
            limit_start=limit_start,
            limit_page_length=page_size
        )

        return {
            "status": "success",
            "message": f"{len(bank_list)} records found.",
            "total_records": total_records,
            "page_no": page_no,
            "page_size": page_size,
            "data": bank_list
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_bank_master_list")
        return api_error("Failed to fetch Bank Master data.", 500, str(e))


    
@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_currency_master_list(page_no=1, page_size=20, search_term=None):
    """
    Get paginated list of Currency Master records
    """
    try:
        page_no = int(page_no)
        page_size = int(page_size)
        limit_start = (page_no - 1) * page_size

        filters = {
            "inactive": 0
        }

        # Search filter
        or_filters = []
        if search_term:
            or_filters = [
                ["name", "like", f"%{search_term}%"],
                ["currency_name", "like", f"%{search_term}%"]
            ]

        total_records = frappe.db.count("Currency Master", filters=filters)

        currency_list = frappe.get_all(
            "Currency Master",
            filters=filters,
            or_filters=or_filters,
            fields=["name", "currency_name"],
            limit_start=limit_start,
            limit_page_length=page_size,
            order_by="creation desc"
        )

        return {
            "status": "success",
            "message": f"{len(currency_list)} records found.",
            "total_records": total_records,
            "page_no": page_no,
            "page_size": page_size,
            "data": currency_list
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_currency_master_list")
        return api_error("Failed to fetch Currency Master data.", 500, str(e))


@frappe.whitelist(allow_guest=False, methods=['GET'])
def get_vendor_type_master_list():
    """
    Get list of Vendor Type Master
    """
    try:
        vendor_types = frappe.get_all(
            "Vendor Type Master",
            filters={"inactive": 0, "applicable_for": ["in", ["All", "Accounts Team"]]},
            fields=["name", "description"],
            order_by="creation desc"
        )

        vendor_title = frappe.db.sql("SELECT name FROM `tabVendor Title`", as_dict=True)

        return {
            "status": "success",
            "message": f"{len(vendor_types)} records found.",
            "vendor_types": vendor_types,
            "vendor_title": vendor_title
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_vendor_type_master_list")
        return api_error("Failed to fetch Vendor Type Master data.", 500, str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_country_master_list(page_no=1, page_size=20, search_term=None):
    """
    Get Country list
    """
    try:
        page_no = int(page_no)
        page_size = int(page_size)
        limit_start = (page_no - 1) * page_size

        filters = {
            "inactive": 0
        }

        # Search filter
        if search_term:
            filters["name"] = ["like", f"%{search_term}%"]

        total_records = frappe.db.count("Country", filters=filters)

        country_list = frappe.get_all(
            "Country",
            filters=filters,
            fields=["name", "country_code"],
            limit_start=limit_start,
            limit_page_length=page_size,
            order_by="creation desc"
        )

        return {
            "status": "success",
            "message": f"{len(country_list)} records found.",
            "total_records": total_records,
            "page_no": page_no,
            "page_size": page_size,
            "data": country_list
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_country_master_list")
        return api_error("Failed to fetch Country data.", 500, str(e))



@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_state_master_list(page_no=1, page_size=20, search_term=None):
    """
    Get State Master list
    """
    try:
        page_no = int(page_no)
        page_size = int(page_size)
        limit_start = (page_no - 1) * page_size

        filters = {}

        # Search filter
        if search_term:
            filters["name"] = ["like", f"%{search_term}%"]

        total_records = frappe.db.count("State Master", filters=filters)

        state_list = frappe.get_all(
            "State Master",
            filters=filters,
            fields=["name", "state_code"],
            limit_start=limit_start,
            limit_page_length=page_size,
            order_by="creation desc"
        )

        return {
            "status": "success",
            "message": f"{len(state_list)} records found.",
            "total_records": total_records,
            "page_no": page_no,
            "page_size": page_size,
            "data": state_list
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error in get_state_master_list")
        return api_error("Failed to fetch State Master data.", 500, str(e))


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_gl_accounts(company=None, search_term=None, page_no=1, page_length=10):
    """Get GL Accounts"""
    try:
        filters = {}
        or_filters = None

        page_no = int(page_no)
        page_length = int(page_length)
        limit_start = (page_no - 1) * page_length

        if search_term:
            or_filters = [
                ["name", "like", f"%{search_term}%"],
                ["gl_account_name", "like", f"%{search_term}%"]
            ]

        if company:
            filters["company"] = company

        gl_accounts = frappe.get_all(
            "GL Account",
            filters=filters,
            or_filters=or_filters,
            fields=["*"],
            limit_start=limit_start,
            limit_page_length=page_length,
        )

        total_count = frappe.db.count(
            "GL Account",
            filters=filters
        )
        
        return {
            "status": "success", 
            "data": gl_accounts,
            "page_no": page_no,
            "page_length": page_length,
            "total_records": total_count,
            "total_pages": (total_count + page_length - 1) // page_length
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get GL Accounts API Error")
        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": str(e)}
    

@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_cost_centers(company=None, search_term=None, page_no=1, page_length=10):
    """Get Cost Centers"""
    try:
        filters = {}
        or_filters = None

        page_no = int(page_no)
        page_length = int(page_length)
        limit_start = (page_no - 1) * page_length

        if search_term:
            or_filters = [
                ["name", "like", f"%{search_term}%"],
                ["cost_center_name", "like", f"%{search_term}%"]
            ]

        if company:
            filters["company_code"] = company

        cost_centers = frappe.get_all(
            "Cost Center",
            filters=filters,
            or_filters=or_filters,
            fields=["*"],
            limit_start=limit_start,
            limit_page_length=page_length,
        )

        total_count = frappe.db.count(
            "Cost Center",
            filters=filters
        )

        return {
            "status": "success", 
            "data": cost_centers,
            "page_no": page_no,
            "page_length": page_length,
            "total_records": total_count,
            "total_pages": (total_count + page_length - 1) // page_length
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Cost Centers API Error")
        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": str(e)}