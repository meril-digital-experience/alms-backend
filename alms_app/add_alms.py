import frappe
import os
import sys
import importlib
import json

def execute():
    bench_path = frappe.utils.get_bench_path()
    apps_txt_path = os.path.join(bench_path, "sites", "apps.txt")
    apps_dir = os.path.join(bench_path, "apps")

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    monorepo_dir = os.path.dirname(pkg_dir)
    alms_dir = os.path.join(monorepo_dir, "alms_app")
    approval_dir = os.path.join(monorepo_dir, "alms_app")
    for p in [alms_dir, approval_dir, monorepo_dir, apps_dir]:
        if os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    importlib.invalidate_caches()

    needed_apps = ["frappe", "lease_app", "alms_app"]

    # 1. Mutate thread-local in-memory installed_apps list so bench migrate & Desk know all 5 apps are installed
    if hasattr(frappe, "local"):
        frappe.local.installed_apps = list(needed_apps)

    # 2. Ensure all monorepo apps are listed in apps.txt
    try:
        with open(apps_txt_path, "r") as f:
            apps = [line.strip() for line in f.read().splitlines() if line.strip()]
    except Exception:
        apps = []

    updated_apps = False
    for app_name in ["lease_app", "alms_app"]:
        if app_name not in apps:
            apps.append(app_name)
            updated_apps = True

    if updated_apps:
        try:
            with open(apps_txt_path, "w") as f:
                f.write("\n".join(apps) + "\n")
        except Exception:
            pass

    # 4. Clear cache and setup module map
    try:
        frappe.cache().delete_value("all_apps")
        frappe.cache().delete_value("app_modules")
        frappe.clear_cache()
        frappe.setup_module_map()
    except Exception as e:
        print(f"Warning setting up module map: {e}")

    # 5. Bind all monorepo modules in tabModule Def to alms_app so Frappe never throws Module Not Found
    try:
        frappe.db.sql("UPDATE `tabModule Def` SET app_name = 'alms_app' WHERE module_name IN ('Lease Management System', 'Car and Lease', 'Lease Masters', 'ALMS', 'master', 'CRMS', 'Approval')")
        frappe.db.commit()
    except Exception as e:
        print(f"Warning updating Module Def app_names: {e}")

    # 6. Enable Data Import tool for Core Role DocType
    try:
        frappe.db.sql("UPDATE `tabDocType` SET allow_import = 1 WHERE name = 'Role'")
        frappe.db.commit()
    except Exception as e:
        print(f"Warning enabling import for Role: {e}")

    # 7. Force reset custom flag & migration_hash, purge overrides, and save Vendor Master fields
    try:
        if frappe.db.exists("DocType", "Vendor Master"):
            frappe.flags.in_import = True
            dev_mode = getattr(frappe.conf, "developer_mode", 0)
            frappe.conf.developer_mode = 1

            frappe.db.sql("UPDATE `tabDocType` SET custom = 0, migration_hash = NULL WHERE name = 'Vendor Master'")
            frappe.db.sql("DELETE FROM `tabProperty Setter` WHERE doc_type = 'Vendor Master'")
            frappe.db.sql("DELETE FROM `tabCustom Field` WHERE dt = 'Vendor Master'")

            vm_path = os.path.join(monorepo_dir, "alms_app", "crms", "doctype", "vendor_master", "vendor_master.json")
            if os.path.exists(vm_path):
                from frappe.modules.import_file import import_file_by_path
                import_file_by_path(vm_path, force=True, ignore_version=True)
                
                with open(vm_path, "r", encoding="utf-8") as jf:
                    schema_data = json.load(jf)

                doc = frappe.get_doc("DocType", "Vendor Master")
                doc.migration_hash = None
                doc.custom = 0
                if schema_data.get("autoname"):
                    doc.autoname = schema_data.get("autoname")
                if schema_data.get("naming_rule"):
                    doc.naming_rule = schema_data.get("naming_rule")
                if schema_data.get("field_order"):
                    doc.field_order = schema_data.get("field_order")

                doc.fields = []
                for f in schema_data.get("fields", []):
                    doc.append("fields", f)

                doc.save(ignore_permissions=True)
                print(f"Successfully saved Vendor Master with {len(doc.fields)} fields!")

            frappe.conf.developer_mode = dev_mode
            frappe.flags.in_import = False

            frappe.clear_cache(doctype="Vendor Master")
            frappe.db.commit()
    except Exception as e:
        print(f"Warning reloading Vendor Master: {e}")
