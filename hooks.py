from . import __version__ as app_version
import sys
import os

# Dynamically add the parent directory of lease_app to sys.path so that alms_app is importable
apps_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
lease_app_dir = os.path.join(apps_dir, 'lease_app')
if lease_app_dir not in sys.path:
    sys.path.insert(0, lease_app_dir)

app_name = "alms_app"
app_title = "Car Leasing App"
app_publisher = "Rishi Hingad"
app_description = "Car Leasing App"
app_email = "rishi.hingad@merillife.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "lease_app",
# 		"logo": "/assets/lease_app/logo.png",
# 		"title": "Car and Lease",
# 		"route": "/lease_app",
# 		"has_permission": "lease_app.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/lease_app/css/lease_app.css"
# app_include_js = "/assets/lease_app/js/lease_app.js"

# include js, css files in header of web template
# web_include_css = "/assets/lease_app/css/lease_app.css"
# web_include_js = "/assets/lease_app/js/lease_app.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "lease_app/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "lease_app/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "lease_app.utils.jinja_methods",
# 	"filters": "lease_app.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "lease_app.install.before_install"
# after_install = "lease_app.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "lease_app.uninstall.before_uninstall"
# after_uninstall = "lease_app.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "lease_app.utils.before_app_install"
# after_app_install = "lease_app.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "lease_app.utils.before_app_uninstall"
# after_app_uninstall = "lease_app.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "lease_app.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"lease_app.tasks.all"
# 	],
# 	"daily": [
# 		"lease_app.tasks.daily"
# 	],
# 	"hourly": [
# 		"lease_app.tasks.hourly"
# 	],
# 	"weekly": [
# 		"lease_app.tasks.weekly"
# 	],
# 	"monthly": [
# 		"lease_app.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "lease_app.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "lease_app.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "lease_app.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["lease_app.utils.before_request"]
# after_request = ["lease_app.utils.after_request"]

# Job Events
# ----------
# before_job = ["lease_app.utils.before_job"]
# after_job = ["lease_app.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"lease_app.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


# Merged from lease_app and lease_app

fixtures = [
    {"dt": "Role", "filters": {"name": ["in", ["Car Indent Form User", "ALMS User"]]}},
]

app_include_css = [
    "/assets/lease_app/css/custom.css"
]

app_include_js = [
    "/assets/lease_app/js/alms_listview_handler.js",
    "/assets/lease_app/js/approval_ui_v7.js",
    "/assets/lease_app/js/invoice_dialog.js"
]

doc_events = {
    "*": {
        "validate": "alms_app.approval.approval_router.auto_restart_rejected_document",
        "on_update": "alms_app.approval.approval_router.trigger_approval_if_matrix_exists",
        "on_submit": "alms_app.approval.approval_router.trigger_approval_if_matrix_exists"
    },
    "Invoice Batch": {
        "on_update": [
            "alms_app.crms.doctype.invoice_batch.invoice_batch.create_invoice_details_on_approval",
            "alms_app.approval.approval_router.trigger_approval_if_matrix_exists"
        ]
    },
    "Invoice Details": {
        "on_update": "alms_app.api.invoice_payment_status.on_update_invoice"
    }
}

scheduler_events = {
    "cron": {
        "0 0 * * *": [  # Runs at 12:00 AM daily
            "alms_app.api.fetch_invoice_details.run_daily_invoice_fetch"
        ]
    }
}

permission_query_conditions = {
    "Employee": "alms_app.master.doctype.employee.employee.get_permission_query_conditions",
}

has_permission = {
    "Employee": "alms_app.master.doctype.employee.employee.has_permission",
}

before_migrate = [
    "alms_app.add_alms.execute",
]
