# Copyright (c) 2025, Blue Phoenix and contributors
# For license information, please see license.txt

import re
import frappe
import json
from frappe.utils import cstr
from frappe.model.document import Document
from frappe.core.doctype.user.user import User
from lease_app.utils.custom_send_mail import custom_sendmail
from frappe.utils.password import update_password
from frappe.email.doctype.email_template.email_template import get_email_template


class Employee(Document):
    
    def before_save(self):
        """
        Called before saving the Employee document
        Handles user creation for individual saves, bulk edits, and data imports
        """
        if self.create_user and self.company_email and self.first_name and self.designation:
            if not self.user_id:
               
                existing_user = frappe.db.exists("User", {"email": self.company_email})
                if existing_user:
                    self.user_id = existing_user
                    if not frappe.flags.in_import:
                        frappe.msgprint(f"Existing user linked to employee: {self.name}")
                else:
                   
                    try:
                        user_doc = self.create_user_during_save()
                        if user_doc:
                            self.user_id = user_doc.name
                            if not frappe.flags.in_import:
                                frappe.msgprint(f"New user created for employee: {self.name}")
                    except Exception as e:
                        frappe.log_error(f"Error creating user during save for {self.name}: {str(e)}")
                        if not frappe.flags.in_import:
                            frappe.msgprint(f"Error creating user for {self.name}: {str(e)}")

    def after_insert(self):
        """
        Called after inserting the Employee document
        """
        try:
          
            if frappe.flags.in_import and self.create_user and self.user_id:
                frappe.log_error(f"User successfully created/linked for employee {self.name} during import", "User Creation Success")
        except Exception as e:
            frappe.log_error(f"Error in after_insert for employee {self.name}: {str(e)}")

    def validate(self):
        """
        Called during validation of the Employee document
        """
        if self.create_user:
           
            if not self.company_email:
                frappe.throw("Company email is required when 'Create User' is checked")
            
            if not self.first_name:
                frappe.throw("First name is required when 'Create User' is checked")
            
            if not self.designation:
                frappe.throw("Designation is required when 'Create User' is checked")
            
           
            if not self.validate_email_format(self.company_email):
                frappe.throw(f"Invalid email format: {self.company_email}")
            
            
            existing_employee = frappe.db.exists("Employee", {
                "company_email": self.company_email,
                "name": ["!=", self.name]
            })
            if existing_employee:
                frappe.throw(f"Another employee already has this email: {self.company_email}")

    def create_user_during_save(self):
        """
        Create user during employee save - works for all scenarios
        """
        try:
            
            if not self.company_email or not self.first_name or not self.designation:
                return None
            
            
            roles = self.get_roles_from_designation(self.designation)
            if not roles:
                if not frappe.flags.in_import:
                    frappe.msgprint(f"No roles found for designation: {self.designation}")
                frappe.log_error(f"No roles found for designation: {self.designation}")
                return None
            
            user_doc = frappe.new_doc("User")
            user_doc.email = self.company_email
            user_doc.username = self.company_email
            user_doc.first_name = self.first_name
            user_doc.last_name = self.last_name or ""
            user_doc.send_welcome_email = 0  
            user_doc.enabled = 1
            
            
            for role in roles:
                user_doc.append("roles", {
                    "role": role
                })
            
           
            user_doc.insert(ignore_permissions=True)
            
          
            frappe.log_error(f"User created: {self.company_email}", "User Creation Log")
            
            if not frappe.flags.in_import:
                frappe.msgprint(f"User created: {self.company_email}")
            
            return user_doc
            
        except Exception as e:
            frappe.log_error(f"Error creating user during save: {str(e)}")
            return None

    def get_roles_from_designation(self, designation):
        """
        Get roles from the role profile linked to designation
        """
        try:
            if not designation:
                return []
            
            
            if not frappe.db.exists("Role Profile", designation):
                frappe.log_error(f"Role Profile not found: {designation}")
                return []
            
           
            role_profile = frappe.get_doc("Role Profile", designation)
            
            roles = []
            for role_row in role_profile.roles:
                roles.append(role_row.role)
            
            return roles
        
        except Exception as e:
            frappe.log_error(f"Error getting roles from designation {designation}: {str(e)}")
            return []


    def validate_email_format(self, email):
        """
        Validate email format
        """
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

    def on_update(self):
        """
        Called after the document is saved/updated
        Handles bulk edit scenarios where create_user is checked later
        """
        
        if self.create_user and self.company_email and self.first_name and self.designation and not self.user_id:
           
            existing_user = frappe.db.exists("User", {"email": self.company_email})
            if existing_user:
                frappe.db.set_value("Employee", self.name, "user_id", existing_user)
                frappe.db.set_value(
                    "Employee",
                    self.name,
                    "full_name",
                    " ".join(filter(None, [self.first_name, self.middle_name, self.last_name]))
                    )
                frappe.msgprint(f"Existing user linked to employee: {self.name}")
            else:
               
                try:
                    user_doc = self.create_user_during_save()
                    if user_doc:
                        frappe.db.set_value("Employee", self.name, "user_id", user_doc.name)
                        frappe.db.set_value(
                            "Employee",
                            self.name,
                            "full_name",
                            " ".join(filter(None, [self.first_name, self.middle_name, self.last_name]))
                            )
                        frappe.msgprint(f"User created for employee: {self.name}")
                except Exception as e:
                    frappe.log_error(f"Error in on_update user creation for {self.name}: {str(e)}")
        
    @staticmethod
    @frappe.whitelist()
    def create_users_for_employees():
        """
        Utility method to create users for all employees with create_user checked
        Can be called manually if needed
        """
        try:
            employees = frappe.get_all("Employee", 
                filters={
                    "create_user": 1,
                    "user_id": ["in", ["", None]]
                },
                fields=["name"]
            )
            
            if not employees:
                frappe.msgprint("No employees found with 'Create User' checked and no existing user.")
                return {"status": "No employees found"}
                
            success_count = 0
            error_count = 0
            
            for employee_data in employees:
                try:
                   
                    employee_doc = frappe.get_doc("Employee", employee_data.name)
                    if employee_doc.create_user and not employee_doc.user_id:
                        employee_doc.save()
                        if employee_doc.user_id:
                            success_count += 1
                        else:
                            error_count += 1
                            
                except Exception as e:
                    error_count += 1
                    frappe.log_error(f"Error processing employee {employee_data.name}: {str(e)}")
            
            message = f"Process completed. Success: {success_count}, Errors: {error_count}"
            frappe.msgprint(message)
            return {"status": "completed", "success": success_count, "errors": error_count}
            
        except Exception as e:
            frappe.log_error(f"Error in bulk user creation: {str(e)}")
            frappe.throw(f"Error in bulk user creation: {str(e)}")

    @staticmethod
    @frappe.whitelist()
    def link_existing_users():
        """
        Link existing users to employees based on email
        """
        try:
            employees = frappe.get_all("Employee", 
                filters={
                    "company_email": ["!=", ""],
                    "user_id": ["in", ["", None]]
                },
                fields=["name", "company_email"]
            )
            
            updated_count = 0
            
            for employee_data in employees:
                existing_user = frappe.db.exists("User", {"email": employee_data.company_email})
                if existing_user:
                    frappe.db.set_value("Employee", employee_data.name, "user_id", existing_user)
                    updated_count += 1
            
            frappe.db.commit()
            message = f"Linked {updated_count} employees with existing users"
            frappe.msgprint(message)
            return {"status": "completed", "linked": updated_count}
            
        except Exception as e:
            frappe.log_error(f"Error linking existing users: {str(e)}")
            frappe.throw(f"Error linking existing users: {str(e)}")

        
@frappe.whitelist()
def send_credential_email(employee_names):

    if isinstance(employee_names, str):
        try:
            employee_names = json.loads(employee_names)
        except Exception:
            employee_names = [employee_names]

    if not employee_names:
        return

    try:
        http_server = frappe.conf.get("frontend_http") or "https://ri-sharedservices.bilakhiagroup.com/login"
        sent_count = 0

        for name in employee_names:
            emp = frappe.get_doc("Employee", name)
            
            if not emp.user_id:
                continue

            user_id = emp.user_id
            employee_name = " ".join(filter(None, [emp.first_name, emp.last_name]))
            
            clean_code = re.sub(r'[^a-zA-Z0-9]', '', emp.employee_code or "")
            if clean_code:
                password = f"Meril@{clean_code}"
            else:
                password = "Meril@123"

            update_password(user=user_id, pwd=password)
            frappe.db.commit()

            template = get_email_template(
                "Send login credentials to employee",
                {
                    "employee_name": employee_name,
                    "user_id": user_id,
                    "password": password,
                    "http_server": http_server
                }
            )

            custom_sendmail(
                recipients=user_id,
                subject=template.get("subject"),
                message=template.get("message"),
                now=True
            )
            sent_count += 1
            
        frappe.msgprint(f"Credentials sent to {sent_count} employee(s).")
    except Exception as e:
        frappe.log_error(f"Error sending credential email: {str(e)}")
        frappe.throw(f"Error sending credential email: {str(e)}")

@frappe.whitelist(allow_guest=True)
def get_eligibility_from_designation(designation):
    if not designation:
        return {"error": "No designation provided"}

    doc = frappe.get_doc("Employee Designation", designation)
    return {"eligibility": doc.eligibility}


def get_permission_query_conditions(user):
    if not user:
        user = frappe.session.user
    
    if user == "Administrator":
        return ""
    
    roles = frappe.get_roles(user)
    
    # Do not restrict System Managers or HRs
    if any(role in roles for role in ["System Manager", "HR Manager", "HR", "HR Head", "HR (CRMS)"]):
        return ""
        
    if "Reporting Head" in roles:
        emp_name = frappe.db.get_value("Employee", {"company_email": user}, "name")
        if emp_name:
            # Allow them to see themselves and the employees reporting to them
            return f"(`tabEmployee`.reporting_head = '{emp_name}' OR `tabEmployee`.name = '{emp_name}')"
        else:
            return "1=2" # If no employee record linked, deny access
            
    return ""

def has_permission(doc, ptype="read", user=None):
    if not user:
        user = frappe.session.user
    
    if user == "Administrator":
        return True
        
    roles = frappe.get_roles(user)
    
    if any(role in roles for role in ["System Manager", "HR Manager", "HR", "HR Head", "HR (CRMS)"]):
        return True
        
    if "Reporting Head" in roles:
        emp_name = frappe.db.get_value("Employee", {"company_email": user}, "name")
        if emp_name:
            if doc.reporting_head == emp_name or doc.name == emp_name:
                return True
            return False
            
    return True
