import frappe
import os
import sys
import importlib

def execute():
    bench_path = frappe.utils.get_bench_path()
    apps_txt_path = os.path.join(bench_path, "sites", "apps.txt")
    apps_dir = os.path.join(bench_path, "apps")

    # Determine monorepo directory dynamically based on current file location
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    monorepo_dir = os.path.dirname(pkg_dir)
    remittance_dir = os.path.join(monorepo_dir, "remittance")

    # Ensure python paths are in sys.path
    for p in [remittance_dir, monorepo_dir, apps_dir]:
        if os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)

    importlib.invalidate_caches()

    # Create top-level symlink in bench apps directory if missing
    top_level_symlink = os.path.join(apps_dir, "remittance_tool")
    if not os.path.exists(top_level_symlink) and os.path.exists(remittance_dir):
        try:
            os.symlink(remittance_dir, top_level_symlink)
        except Exception:
            pass

    try:
        with open(apps_txt_path, "r") as f:
            apps = [line.strip() for line in f.read().splitlines() if line.strip()]
    except Exception:
        apps = []

    if apps and "remittance_tool" not in apps:
        print("Adding remittance_tool to apps.txt dynamically...")
        if "lease_app" in apps:
            idx = apps.index("lease_app")
            apps.insert(idx, "remittance_tool")
        elif "leasemanagement" in apps:
            idx = apps.index("leasemanagement")
            apps.insert(idx, "remittance_tool")
        else:
            apps.append("remittance_tool")

        with open(apps_txt_path, "w") as f:
            f.write("\n".join(apps) + "\n")

        frappe.cache().delete_value("all_apps")
        frappe.cache().delete_value("app_modules")
        try:
            frappe.setup_module_map()
        except Exception as e:
            print(f"Warning setting up module map for remittance_tool: {e}")

    try:
        installed_apps = frappe.get_installed_apps()
        if "remittance_tool" not in installed_apps:
            from frappe.installer import add_to_installed_apps
            print("Adding remittance_tool to tabInstalled Applications dynamically...")
            add_to_installed_apps("remittance_tool", rebuild_website=False)
            frappe.db.commit()
    except Exception as e:
        print(f"Warning adding remittance_tool to installed apps: {e}")
