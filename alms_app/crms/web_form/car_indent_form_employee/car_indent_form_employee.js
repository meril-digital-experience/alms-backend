
console.log("✅ car_indent_form.js loaded");
frappe.ready(function () {

    function getEmployeeCodeFromURL() {
        const params = new URLSearchParams(window.location.search);
        let code = decodeURIComponent(params.get("employee_code") || "");
        if (code) {
            localStorage.setItem("alms_current_employee_code", code);
        } else {
            code = localStorage.getItem("alms_current_employee_code") || "";
        }
        return code;
    }
    const employeeCode = getEmployeeCodeFromURL();
    console.log('Employee Code from URL:', employeeCode);
    
    // Automatically set form_type to Car and hide it so user doesn't have to select again
    frappe.web_form.set_value('form_type', 'Car');
    frappe.web_form.set_df_property('form_type', 'hidden', 1);

    let data_restored = false;

    function restore_user_data() {
        if (data_restored) return;
        const savedData = localStorage.getItem('car_indent_form_data');
        if (savedData) {
            try {
                const parsedData = JSON.parse(savedData);
                setTimeout(() => {
                    for (let key in parsedData) {
                        // Don't overwrite the auto-populated read-only fields
                        if (!['designation', 'location', 'company_name', 'employee_reporting', 'contact_number', 'email_id', 'department', 'employee_name', 'employee_code', 'form_type'].includes(key)) {
                            if (parsedData[key] !== null && parsedData[key] !== undefined && parsedData[key] !== '') {
                                frappe.web_form.set_value(key, parsedData[key]);
                            }
                        }
                    }
                    // Recalculate totals after restoring
                    calculate_totals();
                }, 500); // 500ms delay to ensure all field DOMs (like Links) are fully initialized
            } catch (e) {
                console.error('Error restoring form data', e);
            }
        }
        data_restored = true;
    }
    if (employeeCode) {
        frappe.web_form.set_value('employee_code', employeeCode);
        console.log('Employee Code:', employeeCode);

        frappe.call({
            method: "alms_app.crms.web_form.car_indent_form_employee.car_indent_form_employee.get_employee_details",
            args: {
                employee_code: employeeCode
            },
            callback: function (response) {
                console.log('API Response:', response);
                const employeeDetails = response.message;
                if (employeeDetails) {

                    frappe.web_form.set_value('designation', employeeDetails[0].designation);
                    frappe.web_form.set_value('eligibility', employeeDetails[0].eligibility);
                    frappe.web_form.set_value('ex_showroom_price', employeeDetails[0].eligibility);
                    frappe.web_form.set_value('location', employeeDetails[0].location);
                    frappe.web_form.set_value('company_name', employeeDetails[0].company);
                    frappe.web_form.set_value('employee_reporting', employeeDetails[0].reporting_head_name || employeeDetails[0].reporting_head);
                    frappe.web_form.set_value('contact_number', employeeDetails[0].contact_number);
                    frappe.web_form.set_value('email_id', employeeDetails[0].email_id);
                    frappe.web_form.set_value('department', employeeDetails[0].department);
                    frappe.web_form.set_value('employee_name', employeeDetails[0].full_name);

                    frappe.web_form.set_df_property('designation', 'read_only', true);
                    frappe.web_form.set_df_property('ex_showroom_price', true);
                    frappe.web_form.set_df_property('eligibility', 'read_only', true);
                    frappe.web_form.set_df_property('location', 'read_only', true);
                    frappe.web_form.set_df_property('company_name', 'read_only', true);
                    frappe.web_form.set_df_property('employee_reporting', 'read_only', true);
                    frappe.web_form.set_df_property('contact_number', 'read_only', true);
                    frappe.web_form.set_df_property('email_id', 'read_only', true);
                    frappe.web_form.set_df_property('department', 'read_only', true);
                    frappe.web_form.set_df_property('employee_name', 'read_only', true);
                    frappe.web_form.set_df_property('form_type', 'read_only', true);

                    restore_user_data();
                }
            },
            error: function (error) {
                console.log('Error fetching employee details:', error);
                restore_user_data();
            }
        });
    } else {
        restore_user_data();
    }

    frappe.web_form.on("ex_showroom_price", calculate_totals);
    frappe.web_form.on("discount", calculate_totals);
    frappe.web_form.on("tcs", calculate_totals);
    frappe.web_form.on("registration_charges", calculate_totals);
    frappe.web_form.on("accessories", calculate_totals);

    function formatINR(amount) {
        return new Intl.NumberFormat('en-IN', {
            style: 'currency',
            currency: 'INR',
            maximumFractionDigits: 2
        }).format(amount);
    }

    function calculate_totals() {
        const ex_showroom_price = parseFloat(frappe.web_form.get_value('ex_showroom_price')) || 0;
        const discount = parseFloat(frappe.web_form.get_value('discount')) || 0;
        const tcs = parseFloat(frappe.web_form.get_value('tcs')) || 0;
        const registration_charges = parseFloat(frappe.web_form.get_value('registration_charges')) || 0;
        const accessories = parseFloat(frappe.web_form.get_value('accessories')) || 0;

        const net_ex_showroom_price = ex_showroom_price - discount + tcs;
        const finance_amount = net_ex_showroom_price + registration_charges + accessories;

        frappe.web_form.set_value('net_ex_showroom_price', net_ex_showroom_price);
        frappe.web_form.set_value('finance_amount', finance_amount);
        console.log('Formatted INR:', formatINR(100000));

        frappe.web_form.set_value('net_ex_showroom_price_inr', formatINR(net_ex_showroom_price));
        frappe.web_form.set_value('finance_amount_inr', formatINR(finance_amount));
    }

    calculate_totals();

    // Save data to localStorage periodically
    setInterval(() => {
        if (frappe && frappe.web_form && data_restored) {
            const currentData = frappe.web_form.get_values();
            if (currentData) {
                localStorage.setItem('car_indent_form_data', JSON.stringify(currentData));
            }
        }
    }, 1000);

    frappe.web_form.validate = function () {
        const formType = frappe.web_form.get_value("form_type");
        const employeeCode = frappe.web_form.get_value("employee_code");
        console.log("Form Type:", formType);
        console.log("Employee Code:", employeeCode);
        if (formType === "Allowance") {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "alms_app.crms.web_form.car_indent_form.car_indent_form.send_allowance_email",
                    args: { employee_code: employeeCode },
                    callback: function () {
                        frappe.msgprint("Your Car Allowance request was submitted successfully.");
                        setTimeout(() => {
                            window.location.href = "/allowance";
                        }, 2000);
                        reject("Skipping save - allowance selected.");
                    },
                    error: function (error) {
                        console.error("Error sending allowance email:", error);
                        frappe.throw("Something went wrong while sending the allowance email.");
                        reject("Error in allowance submission.");
                    }
                });
            });
        }

        if (formType === "Car") {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "alms_app.crms.web_form.car_indent_form_employee.car_indent_form_employee.check_indent_exists",
                    args: { employee_code: employeeCode },
                    callback: function (response) {
                        if (response.message === "redirect") {
                            frappe.msgprint("You already have an active indent.");
                            setTimeout(() => {
                                window.location.href = "/already-present";
                            }, 2000);
                            reject("Already exists");
                        } else {
                            // ✅ Just allow save
                            localStorage.removeItem('car_indent_form_data');
                            localStorage.removeItem('alms_current_employee_code');
                            resolve();
                        }
                    },
                    error: function () {
                        frappe.throw("Error checking indent existence.");
                        reject("Check indent error");
                    }
                });
            });
        }

        frappe.throw("Invalid form type selected.");
        return Promise.reject("Invalid form type");
    };


});