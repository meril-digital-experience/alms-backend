import frappe
import os
import sys
import importlib

def execute():
    bench_path = frappe.utils.get_bench_path()
    apps_txt_path = os.path.join(bench_path, "sites", "apps.txt")
    apps_dir = os.path.join(bench_path, "apps")

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    monorepo_dir = os.path.dirname(pkg_dir)
    approval_dir = os.path.join(monorepo_dir, "alms_app")

    for p in [approval_dir, monorepo_dir, apps_dir]:
        if os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    importlib.invalidate_caches()

    # Symlink in apps/ if missing
    top_level_symlink = os.path.join(apps_dir, "alms_app")
    if not os.path.exists(top_level_symlink) and os.path.exists(approval_dir):
        try:
            os.symlink(approval_dir, top_level_symlink)
        except Exception:
            pass

    try:
        with open(apps_txt_path, "r") as f:
            apps = [line.strip() for line in f.read().splitlines() if line.strip()]
    except Exception:
        apps = []

    if apps and "alms_app" not in apps:
        print("Adding alms_app to apps.txt dynamically...")
        if "leasemanagement" in apps:
            idx = apps.index("leasemanagement")
            apps.insert(idx, "alms_app")
        elif "leasemanagement" in apps:
            idx = apps.index("leasemanagement")
            apps.insert(idx, "alms_app")
        else:
            apps.append("alms_app")

        with open(apps_txt_path, "w") as f:
            f.write("\n".join(apps) + "\n")

        frappe.cache().delete_value("all_apps")
        frappe.cache().delete_value("app_modules")
        try:
            frappe.setup_module_map()
        except Exception as e:
            print(f"Warning setting up module map for alms_app: {e}")

    try:
        installed_apps = frappe.get_installed_apps()
        if "alms_app" not in installed_apps:
            from frappe.installer import add_to_installed_apps
            print("Adding alms_app to tabInstalled Applications dynamically...")
            add_to_installed_apps("alms_app", rebuild_website=False)
            frappe.db.commit()
    except Exception as e:
        print(f"Warning adding alms_app to installed apps: {e}")
