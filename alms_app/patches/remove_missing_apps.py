import frappe

def execute():
    """Removes old missing apps and fixes module bindings so doctypes aren't orphaned."""
    frappe.db.sql("DELETE FROM `tabInstalled Application` WHERE name IN ('approval_app', 'remittance_app')")
    
    # Fix Module Def app_names so Frappe doesn't orphan their DocTypes
    frappe.db.sql("UPDATE `tabModule Def` SET app_name = 'alms_app' WHERE module_name IN ('ALMS', 'master', 'CRMS', 'Approval')")
    frappe.db.sql("UPDATE `tabModule Def` SET app_name = 'lease_app' WHERE module_name IN ('Lease Management System', 'Lease Masters')")

    # Remove from default value
    val = frappe.db.get_value('DefaultValue', {'defkey': 'installed_apps'}, 'defvalue')
    if val:
        val = val.replace('"approval_app"', '"alms_app"')
        frappe.db.sql("UPDATE `tabDefaultValue` SET defvalue = %s WHERE defkey = 'installed_apps'", (val,))
        
    # Crucially, clear cache so get_installed_apps() refreshes
    frappe.cache().delete_value("installed_apps")
    frappe.cache().delete_value("global:installed_apps")
    frappe.cache().delete_value("app_hooks")
    frappe.clear_cache()
    if hasattr(frappe.local, "request_cache"):
        frappe.local.request_cache.clear()
    if hasattr(frappe.local, "doc_events_hooks"):
        delattr(frappe.local, "doc_events_hooks")

