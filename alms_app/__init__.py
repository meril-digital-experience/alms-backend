__version__ = '0.0.1'

import sys
import types

# --- HOTFIX FOR MISSING APPS ON UAT ---
# Inject a custom importer to dynamically mock out any missing old apps or their submodules.
# This prevents `bench migrate` from crashing on ModuleNotFoundError for cached hooks.
# The patch `remove_missing_apps` will then permanently clean them from the database.
class DummyMissingAppImporter:
    def find_module(self, fullname, path=None):
        if fullname.startswith("approval_app") or fullname.startswith("remittance_app") or fullname.startswith("mds_master"):
            return self
        return None
        
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith("approval_app") or fullname.startswith("remittance_app") or fullname.startswith("mds_master"):
            import importlib.machinery
            return importlib.machinery.ModuleSpec(fullname, self)
        return None
        
    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
            
        class DummyModule(types.ModuleType):
            def __getattr__(self, name):
                if name == "commands":
                    return []
                # Return a dummy function for any attribute accessed (like a Frappe hook)
                return lambda *args, **kwargs: None
                
        mod = DummyModule(fullname)
        mod.__path__ = []
        mod.__file__ = "/tmp/fake_app_for_migration/__init__.py"
        sys.modules[fullname] = mod
        return mod

if not any(isinstance(i, DummyMissingAppImporter) for i in sys.meta_path):
    sys.meta_path.insert(0, DummyMissingAppImporter())
# --------------------------------------

import frappe
_original_get_attr = frappe.get_attr

def patched_get_attr(method_string):
    try:
        app_name = method_string.split(".", 1)[0]
        if app_name in ("approval_app", "remittance_app", "mds_master"):
            return lambda *args, **kwargs: None
        if method_string.startswith("leasemanagement.master."):
            method_string = method_string.replace("leasemanagement.master.", "alms_app.master.", 1)
        elif method_string.startswith("leasemanagement.crms."):
            method_string = method_string.replace("leasemanagement.crms.", "alms_app.crms.", 1)
        elif method_string.startswith("leasemanagement.api."):
            method_string = method_string.replace("leasemanagement.api.", "alms_app.api.", 1)
        elif method_string.startswith("leasemanagement.approval."):
            method_string = method_string.replace("leasemanagement.approval.", "alms_app.approval.", 1)
    except Exception:
        pass
    return _original_get_attr(method_string)

frappe.get_attr = patched_get_attr

