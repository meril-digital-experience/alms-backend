# Methods to be used in Lease Report Calculation
import calendar
from calendar import monthrange
from collections import Counter
from datetime import date, datetime, time, timedelta

import frappe
from dateutil.relativedelta import relativedelta
from frappe.desk.query_report import run
from frappe.utils import add_days, getdate


@frappe.whitelist()
def get_formatted_date(dt):
	day = dt.day

	# Suffix logic
	if 4 <= day <= 20 or 24 <= day <= 30:
		suffix = "th"
	else:
		suffix = ["st", "nd", "rd"][day % 10 - 1]

	formatted_date = dt.strftime(f"%d{suffix} %B, %Y")
	return formatted_date


@frappe.whitelist()
def get_financial_year():
	today = getdate()

	year = today.year
	month = today.month

	if month < 4:
		return {"start_year": year - 1, "end_year": year}
	else:
		return {"start_year": year, "end_year": year + 1}


@frappe.whitelist()
def get_sd_amount(lease, fin_start_year, fin_end_year):
	fstart = date(int(fin_start_year), 3, 31)
	fend = date(int(fin_end_year), 3, 31)
	sd_amount_immovable = 0
	sd_amount_car = 0
	# n=""
	if len(lease) > 0:
		for i in lease:
			report_data = run("Security Deposit Calculation", filters={"lease_id": i})
			rows = report_data.get("result", [])
			# filtered = [row for row in rows if getdate(row.get("to_date")) == fend]
			record1 = next((row for row in rows if getdate(row.get("to_date")) == fstart), None)
			record2 = next((row for row in rows if getdate(row.get("to_date")) == fend), None)
			if record1 is None:
				opening_sd = 0
			else:
				opening_sd = record1["prepaid_lease"]
			if record2 is None:
				closing_sd = 0
			else:
				closing_sd = record2["prepaid_lease"]
			type_of_asset = frappe.get_value("Lease Management", {"name": i}, "type_of_asset")
			if type_of_asset == "Immovable":
				sd_amount_immovable += round((closing_sd - opening_sd), 2)
			else:
				sd_amount_car += round((closing_sd - opening_sd), 2)
			# n+= str(i)+" "+str(closing_sd)+" "+str(opening_sd)+" "+str(closing_sd-opening_sd)
	return sd_amount_immovable, sd_amount_car


@frappe.whitelist()
def get_terminated_lease_data(terminated_leases):
	cur_ter_gross_wdv_immovable = 0
	cur_ter_gross_wdv_vehicle = 0
	cur_ter_acc_deprec_immovable = 0
	cur_ter_acc_deprec_vehicle = 0

	for lease in terminated_leases:
		lease_doc = frappe.get_doc("Lease Management", lease)
		if lease_doc.calculation_rate_type == "Daily Rate":
			lreport = "Lease Report"
		else:
			lreport = "Lease Report Monthly (With Escalation)"
		terminated_on = lease_doc.termination_date
		lease_report_result = run(lreport, filters={"docname": lease_doc.name, "sum_modified": None})
		lease_report_rows = lease_report_result.get("result")

		ter_report_result = run(
			lreport, filters={"docname": lease_doc.name, "sum_modified": terminated_on + timedelta(days=1)}
		)
		ter_report_rows = ter_report_result.get("result")
		
		# Process ter_report_rows without pandas
		valid_dates = []
		for row in ter_report_rows:
			if row.get("month_end_date"):
				valid_dates.append((getdate(row["month_end_date"]), row))

		for i, (date_val, row) in enumerate(valid_dates):
			if lease_doc.agreement_start_date <= date_val <= terminated_on:
				# equivalent to ter_report_df.iloc[i + 1]["depreciation"]
				# if we are at i, i+1 is the next row in valid_dates
				if i + 1 < len(valid_dates):
					next_depreciation = valid_dates[i + 1][1].get("depreciation", 0)
					if lease_doc.type_of_asset == "Car":
						cur_ter_acc_deprec_vehicle += round(float(next_depreciation), 3)
					else:
						cur_ter_acc_deprec_immovable += round(float(next_depreciation), 3)
		
		first_wdv = 0
		if lease_report_rows and len(lease_report_rows) > 0:
			first_wdv = float(lease_report_rows[0].get("wdv", 0))

		if lease_doc.type_of_asset == "Car":
			cur_ter_gross_wdv_vehicle += first_wdv
		else:
			cur_ter_gross_wdv_immovable += first_wdv

	return (
		cur_ter_acc_deprec_vehicle,
		cur_ter_acc_deprec_immovable,
		cur_ter_gross_wdv_vehicle,
		cur_ter_gross_wdv_immovable,
	)


@frappe.whitelist()
def get_prev_notes_record(company_name, fin_start_year):
	prev_gross_immovable = 0
	prev_gross_vehicle = 0
	prev_gross_add_immovable = 0
	prev_gross_add_vehicle = 0
	prev_gross_disposal_immovable = 0
	prev_gross_disposal_vehicle = 0
	prev_acc_depre_immovable = 0
	prev_acc_depre_vehicle = 0
	prev_acc_year_ended_immovable = 0
	prev_acc_year_ended_vehicle = 0
	prev_acc_disposal_immovable = 0
	prev_acc_disposal_vehicle = 0
	prev_journal_result = run(
		"Lease Notes",
		filters={
			"company_name": company_name,
			"fin_start_year": int(fin_start_year),
			"fin_end_year": int(fin_start_year) + 1,
		},
	)
	prev_journal_rows = prev_journal_result.get("result", [])
	if prev_journal_rows and len(prev_journal_rows) > 15:
		def get_val(idx, field):
			val = prev_journal_rows[idx].get(field, 0)
			return float(val) if val else 0.0

		prev_gross_immovable = get_val(4, "rou_immovable")
		prev_gross_vehicle = get_val(4, "rou_vehicle")
		prev_gross_add_immovable = get_val(5, "rou_immovable")
		prev_gross_add_vehicle = get_val(5, "rou_vehicle")
		prev_gross_disposal_immovable = get_val(6, "rou_immovable")
		prev_gross_disposal_vehicle = get_val(6, "rou_vehicle")
		prev_acc_depre_immovable = get_val(12, "rou_immovable")
		prev_acc_depre_vehicle = get_val(12, "rou_vehicle")
		prev_acc_year_ended_immovable = get_val(13, "rou_immovable")
		prev_acc_year_ended_vehicle = get_val(13, "rou_vehicle")
		prev_acc_disposal_immovable = get_val(14, "rou_immovable")
		prev_acc_disposal_vehicle = get_val(14, "rou_vehicle")
	return {
		"gross_immovable": prev_gross_immovable,
		"gross_vehicle": prev_gross_vehicle,
		"gross_add_immovable": prev_gross_add_immovable,
		"gross_add_vehicle": prev_gross_add_vehicle,
		"gross_disposal_immovable": prev_gross_disposal_immovable,
		"gross_disposal_vehicle": prev_gross_disposal_vehicle,
		"acc_depre_immovable": prev_acc_depre_immovable,
		"acc_depre_vehicle": prev_acc_depre_vehicle,
		"acc_year_ended_immovable": prev_acc_year_ended_immovable,
		"acc_year_ended_vehicle": prev_acc_year_ended_vehicle,
		"acc_disposal_immovable": prev_acc_disposal_immovable,
		"acc_disposal_vehicle": prev_acc_disposal_vehicle,
	}
	# return prev_gross_immovable,prev_gross_vehicle,prev_acc_depre_immovable,prev_acc_depre_vehicle


@frappe.whitelist()
def get_previous_lease_details(company, financial_start_year):
	doc = frappe.db.exists(
		"Previous Lease Note Details",
		{
			"company": company,
			"financial_start_year": str(financial_start_year),
		},
	)

	if doc:
		doc = frappe.get_doc("Previous Lease Note Details", doc)

		return {
			"gross_immovable": doc.gross_amount_immovable,
			"gross_vehicle": doc.gross_amount_vehicle,
			"gross_add_immovable": doc.gross_additions_immovable,
			"gross_add_vehicle": doc.gross_additions_vehicle,
			"gross_disposal_immovable": doc.gross_disposals_immovable,
			"gross_disposal_vehicle": doc.gross_disposals_vehicle,
			"acc_depre_immovable": doc.accumulated_amortization_immovable,
			"acc_depre_vehicle": doc.accumulated_amortization_vehicle,
			"acc_year_ended_immovable": doc.accumulated_amortization_at_year_ended_immovable,
			"acc_year_ended_vehicle": doc.accumulated_amortization_at_year_ended_vehicle,
			"acc_disposal_immovable": doc.accumulated_amortization_disposals_immovable,
			"acc_disposal_vehicle": doc.accumulated_amortization_disposals_vehicle,
			"from_saved": 1,
		}

	return None


@frappe.whitelist()
def upsert_previous_lease_details(company, financial_start_year, data):
	import json

	if isinstance(data, str):
		data = json.loads(data)

	doc_name = frappe.db.exists(
		"Previous Lease Note Details", {"company": company, "financial_start_year": str(financial_start_year)}
	)

	if doc_name:
		doc = frappe.get_doc("Previous Lease Note Details", doc_name)
		doc.gross_amount_immovable = data.get("gross_immovable")
		doc.gross_amount_vehicle = data.get("gross_vehicle")
		doc.gross_additions_immovable = data.get("gross_add_immovable")
		doc.gross_additions_vehicle = data.get("gross_add_vehicle")
		doc.gross_disposals_immovable = data.get("gross_disposal_immovable")
		doc.gross_disposals_vehicle = data.get("gross_disposal_vehicle")
		doc.accumulated_amortization_immovable = data.get("acc_depre_immovable")
		doc.accumulated_amortization_vehicle = data.get("acc_depre_vehicle")
		doc.accumulated_amortization_at_year_ended_immovable = data.get("acc_year_ended_immovable")
		doc.accumulated_amortization_at_year_ended_vehicle = data.get("acc_year_ended_vehicle")
		doc.accumulated_amortization_disposals_immovable = data.get("acc_disposal_immovable")
		doc.accumulated_amortization_disposals_vehicle = data.get("acc_disposal_vehicle")
		doc.save()

		return "updated"
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Previous Lease Note Details",
				"company": company,
				"financial_start_year": str(financial_start_year),
				"gross_amount_immovable": data.get("gross_immovable"),
				"gross_amount_vehicle": data.get("gross_vehicle"),
				"gross_additions_immovable": data.get("gross_add_immovable"),
				"gross_additions_vehicle": data.get("gross_add_vehicle"),
				"gross_disposals_immovable": data.get("gross_disposal_immovable"),
				"gross_disposals_vehicle": data.get("gross_disposal_vehicle"),
				"accumulated_amortization_immovable": data.get("acc_depre_immovable"),
				"accumulated_amortization_vehicle": data.get("acc_depre_vehicle"),
				"accumulated_amortization_at_year_ended_immovable": data.get("acc_year_ended_immovable"),
				"accumulated_amortization_at_year_ended_vehicle": data.get("acc_year_ended_vehicle"),
				"accumulated_amortization_disposals_immovable": data.get("acc_disposal_immovable"),
				"accumulated_amortization_disposals_vehicle": data.get("acc_disposal_vehicle"),
			}
		)
		doc.insert()

		return "created"


@frappe.whitelist()
def auto_set_end_year(start_year):
	if not start_year:
		return None

	return int(start_year) + 1


@frappe.whitelist()
def calculate_daily_rate(doc):
	disc_doc = float(doc.discounting_rate) / 100
	if doc.calculation_rate_type == "Daily Rate":
		return (1 + disc_doc) ** (1 / 365) - 1
	return (1 + disc_doc) ** (1 / 12) - 1


@frappe.whitelist()
def get_diff_years(start_date, end_date):
	arg_sd = start_date
	arg_ed = end_date + timedelta(days=1)
	diff_years = relativedelta(arg_ed, arg_sd)
	diff_years = int(str(diff_years.years))
	return diff_years, arg_sd, arg_ed


@frappe.whitelist()
def get_month_details(cdate):
	month_start = cdate
	_, last_day = monthrange(cdate.year, cdate.month)
	month_end = datetime(cdate.year, cdate.month, last_day)

	month_start2 = cdate.replace(day=1)
	_, last_day2 = monthrange(cdate.year, cdate.month)
	month_end2 = datetime(cdate.year, cdate.month, last_day2)
	date_difference2 = month_end2 - month_start2
	total_days_of_month = date_difference2.days + 1

	return month_start, month_end, month_start2, month_end2, total_days_of_month


@frappe.whitelist()
def get_escalation_dates(doc, current_date, start_date, end_date, diff_years):
	etype = []
	escl_dates_pafr = []
	escl_dates_bdates = []
	total_escl_dates_bdates = []
	escl_dates_pannum = []
	date_list = []
	calc_dict = {}
	calc_keys = []
	bd_start_date = ""
	bd_end_date = ""
	cnt_etype = 0
	new_start_date = []
	famt = 0
	mrent = 0
	rate = 0
	esc_bd_end_date = None
	escalation = True
	edates_pannum = []
	edates_bd = []
	edates_pafa = []
	dict_ed_pannum = {}
	dict_ed_pafa = {}
	dict_ed_bdates = {}
	diff_annually = False
	per_annum_rows = [child for child in doc.escalation if child.escalation_type == "Per Annum"]
	if len(per_annum_rows) == 1:
		row = per_annum_rows[0]
		rate_val = float(row.rate) if row.rate is not None else 0
		rent_val = float(row.monthly_rent) if row.monthly_rent is not None else 0
		fixed_amt_val = float(row.fixed_amount) if row.fixed_amount is not None else 0

		if rate_val == 0 and rent_val == 0 and fixed_amt_val == 0:
			escalation = False
			return escalation, [], [], [], {}, {}, {}, None, False, 0, 0, 0

	for child in doc.escalation:
		escl_type = child.escalation_type
		if escl_type:
			etype.append(escl_type)
			if "Based On Dates" == escl_type:
				if child.monthly_rent in (
					None,
					"",
				):
					monthly_rent_bdates = 0
				else:
					monthly_rent_bdates = float(child.monthly_rent)
				if child.rate in (
					None,
					"",
				):
					rate_bdates = 0
				else:
					rate_bdates = float(child.rate)
				if child.fixed_amount in (
					None,
					"",
				):
					fixed_amt_bdates = 0
				else:
					fixed_amt_bdates = float(child.fixed_amount)
				bd_start_date = child.start_date
				bd_end_date = child.end_date
				new_date = current_date
				new_date = new_date.date()
				while new_date <= bd_end_date:
					if new_date >= bd_start_date and new_date <= bd_end_date:
						escl_dates_bdates.append(new_date)
						new_date = new_date + timedelta(days=1)
					else:
						new_date = new_date + timedelta(days=1)

				if new_date > bd_end_date:
					new_start_date.append(new_date)
				dkey = (
					"Based On Dates"
					+ "-"
					+ str(monthly_rent_bdates)
					+ "-"
					+ str(rate_bdates)
					+ "-"
					+ str(fixed_amt_bdates)
					+ "-"
					+ str(bd_start_date)
					+ "-"
					+ str(bd_end_date)
				)
				dsubkey = (
					str(rate_bdates)
					+ "-"
					+ str(monthly_rent_bdates)
					+ "-"
					+ str(fixed_amt_bdates)
					+ "-"
					+ str(bd_start_date)
					+ "-"
					+ str(bd_end_date)
				)

				calc_dict[dkey] = {dsubkey: escl_dates_bdates}
				total_escl_dates_bdates += escl_dates_bdates
				if len(new_start_date) > 0:
					l = len(new_start_date)
					for q in range(l):
						if new_start_date[q] in total_escl_dates_bdates:
							new_start_date.remove(new_start_date[q])
							break
				escl_dates_bdates = []
	else:
		if not doc.escalation:
			escalation = False

	if escalation:
		for i in range(len(etype)):
			if etype[i] == "Per Annum" or etype[i] == "Per Annum and Fixed Amount":
				if etype[i - 1] == "Based On Dates":
					bd_date = doc.escalation[i - 1]
					d = bd_date.end_date
					esc_bd_end_date = d + timedelta(days=1)
		if len(total_escl_dates_bdates) > 0:
			date_list = total_escl_dates_bdates

		for child in doc.escalation:
			if child.monthly_rent in (
				None,
				"",
			):
				monthly_rent = 0
			else:
				monthly_rent = float(child.monthly_rent)
			if child.rate in (
				None,
				"",
			):
				rate = 0
			else:
				rate = float(child.rate)
			if child.fixed_amount in (
				None,
				"",
			):
				fixed_amt = 0
			else:
				fixed_amt = float(child.fixed_amount)
			if child.escalation_type == "Per Annum":
				cnt_etype += 1
				for i in range(diff_years):
					if i == 0 and cnt_etype == 1:
						if esc_bd_end_date is None:
							new_date = start_date + relativedelta(years=1)
						else:
							new_date = esc_bd_end_date
						if new_date not in date_list:
							if isinstance(new_date, datetime):
								new_date = new_date.date()
							escl_dates_pannum.append(new_date)

							new_date = new_date + relativedelta(years=1)
							continue
					else:
						if new_date in date_list:
							new_date = new_date + relativedelta(years=1)
							break
						if isinstance(new_date, datetime):
							new_date = new_date.date()

						if new_date < end_date.date() and new_date not in date_list:
							escl_dates_pannum.append(new_date)
							new_date = new_date + relativedelta(years=1)
				dkey = "Per Annum" + "-" + str(rate)
				dsubkey = str(rate) + "-" + str(monthly_rent) + "-" + str(fixed_amt)
				calc_dict[dkey] = {dsubkey: escl_dates_pannum}
				escl_dates_pannum = []

			elif child.escalation_type == "Per Annum and Fixed Amount":
				cnt_etype += 1
				for i in range(diff_years):
					if i == 0 and cnt_etype == 1:
						if esc_bd_end_date is None:
							new_date = start_date + relativedelta(years=1)
						else:
							new_date = esc_bd_end_date

						if new_date not in date_list:
							if isinstance(new_date, datetime):
								new_date = new_date.date()
							escl_dates_pafr.append(new_date)
							new_date = new_date + relativedelta(years=1)
					else:
						if new_date in date_list:
							new_date = new_date + relativedelta(years=1)
							break
						if isinstance(new_date, datetime):
							new_date = new_date.date()
						if new_date < end_date.date() and new_date not in date_list:
							escl_dates_pafr.append(new_date)
							new_date = new_date + relativedelta(years=1)
				dkey = "Per Annum and Fixed Amount" + "-" + str(rate) + "-" + str(fixed_amt)
				dsubkey = str(rate) + "-" + str(monthly_rent) + "-" + str(fixed_amt)
				calc_dict[dkey] = {dsubkey: escl_dates_pafr}
				escl_dates_pafr = []

		for key in calc_dict:
			calc_keys.append(key)

	if escalation:
		for i in range(len(calc_keys)):
			temp_str = calc_keys[i]
			temp = calc_keys[i].split("-")
			calc_escl_type = temp[0]

			if calc_escl_type == "Per Annum":
				sub_dict = calc_dict[temp_str]
				subkey = next(iter(sub_dict))
				edates_pannum += sub_dict[subkey]
				dict_ed_pannum[subkey] = sub_dict[subkey]

			elif calc_escl_type == "Based On Dates":
				sub_dict = calc_dict[temp_str]
				subkey = next(iter(sub_dict))
				edates_bd += sub_dict[subkey]
				dict_ed_bdates[subkey] = sub_dict[subkey]

			elif calc_escl_type == "Per Annum and Fixed Amount":
				sub_dict = calc_dict[temp_str]
				subkey = next(iter(sub_dict))
				edates_pafa += sub_dict[subkey]
				dict_ed_pafa[subkey] = sub_dict[subkey]

	if (len(etype) == 1 and etype[0] == "Per Annum") or (
		len(etype) == 1 and etype[0] == "Per Annum and Fixed Amount"
	):
		month_start = current_date

		_, last_day = monthrange(current_date.year, current_date.month)
		month_end = datetime(current_date.year, current_date.month, last_day)

		month_start2 = current_date.replace(day=1)
		_, last_day2 = monthrange(current_date.year, current_date.month)
		month_end2 = datetime(current_date.year, current_date.month, last_day2)
		date_difference2 = month_end2 - month_start2
		total_days_of_month = date_difference2.days + 1

		date_difference = month_end - month_start
		n = date_difference.days + 1

		if n < total_days_of_month:
			diff_annually = True

	if len(edates_pannum) > 0:
		if edates_pannum[0] != edates_pannum[0].replace(day=1) and current_date != current_date.replace(
			day=1
		):
			diff_annually = True
	if len(edates_pafa) > 0:
		if edates_pafa[0] != edates_pafa[0].replace(day=1) and current_date != current_date.replace(day=1):
			diff_annually = True

	return (
		escalation,
		edates_pannum,
		edates_bd,
		edates_pafa,
		dict_ed_pannum,
		dict_ed_bdates,
		dict_ed_pafa,
		esc_bd_end_date,
		diff_annually,
		rate,
		mrent,
		famt,
	)


@frappe.whitelist()
def get_common_month(doc, dict_ed_bdates, escalation, esc_bd_end_date):
	cnt_keys = len(dict_ed_bdates)
	dict_new = {}
	common_month = []
	common_dict = {}
	prev_mlp_next = {}
	mid_diff_annually = False
	if dict_ed_bdates is not None and escalation and cnt_keys > 1:
		for key in dict_ed_bdates.keys():
			temp_val = key
			temp = temp_val.split("-")
			escl = dict_ed_bdates[key]
			escl_months = []
			escl_months = [f"{d.year}-{d.month:02d}" for d in escl]
			month_count = dict(Counter(escl_months))
			month_count = dict(sorted(month_count.items()))
			dict_new[key] = month_count
		keys = list(dict_new.keys())
		if len(keys) > 1:
			for i in range(len(keys) - 1):
				k1, k2 = keys[i], keys[i + 1]
				month_1 = set(dict_new[k1].keys())
				month_2 = set(dict_new[k2].keys())
				common = sorted(month_1.intersection(month_2))
				common_month.extend(common)
			if len(common_month) > 0:
				for i in range(len(common_month)):
					total_mlp_escl = 0
					mid_mlp_escl = []
					for k in range(len(keys)):
						key_n = keys[k]
						date_dict = dict_new[key_n]
						if common_month[i] in date_dict.keys():
							temp = key_n.split("-")
							cmonth = common_month[i]
							year, month = [int(part) for part in cmonth.split("-")]
							total_days_of_month = calendar.monthrange(year, month)[1]
							n = date_dict[common_month[i]]
							rate = float(temp[0])
							mrent = float(temp[1])
							famt = float(temp[2])
							if mrent != 0:
								mlp_escl = mrent
								# mlp_escl = mlp_escl * n / total_days_of_month
							if mrent == 0 and rate == 0 and famt == 0:
								mlp_escl = 0
							if rate != 0 and mrent == 0:
								if len(mid_mlp_escl) > 0:
									l = len(mid_mlp_escl)
									mlp_escl = mid_mlp_escl[l - 1]
								else:
									mlp_escl = float(doc.monthly_rent)
							mlp_escl = mlp_escl + (rate * mlp_escl / 100) + famt
							mid_mlp_escl.append(mlp_escl)
							prev_mlp_next[cmonth] = mlp_escl
							# if rate!=0 and mrent==0:
							mlp_escl = mlp_escl * n / total_days_of_month
							total_mlp_escl += mlp_escl
					common_dict[cmonth] = total_mlp_escl

	if esc_bd_end_date is not None:
		if esc_bd_end_date != esc_bd_end_date.replace(day=1):
			mid_diff_annually = True
		else:
			mid_diff_annually = False
	else:
		mid_diff_annually = False

	return (dict_new, common_month, common_dict, prev_mlp_next, mid_diff_annually)


def get_q_start_q_end(cnt, current_date, quarterly_months, end_date, sum_modified):
	q_start = current_date
	if cnt == 1 and current_date.day != 15:
		if current_date.month not in quarterly_months:
			if current_date.month >= 10:
				q_end = datetime(current_date.year + 1, 1, 15)
				# break
			else:
				for i in range(len(quarterly_months)):
					if quarterly_months[i] > current_date.month:
						q_end = datetime(current_date.year, quarterly_months[i], 15)
						break
		elif current_date.month in quarterly_months:
			if q_start.day > 15:
				for i in range(len(quarterly_months)):
					if quarterly_months[i] > current_date.month:
						q_end = datetime(current_date.year, quarterly_months[i], 15)
						break
			else:
				q_end = datetime(current_date.year, current_date.month, 15)

		else:
			if current_date.month == 12:
				q_end = datetime(current_date.year + 1, 1, 15)
			else:
				q_end = datetime(current_date.year, current_date.month + 1, 15)
	else:
		if current_date.month == 12:
			q_end = datetime(current_date.year + 1, 1, 15)
			if q_end > end_date:
				q_end = end_date
		else:
			if current_date.month in quarterly_months:
				for i in range(len(quarterly_months)):
					if quarterly_months[i] > current_date.month and current_date.month != 10:
						q_end = datetime(current_date.year, quarterly_months[i], 15)
						break
					else:
						q_end = datetime(current_date.year + 1, 1, 15)
				if current_date.month == 4 and current_date.day == 1:
					q_end = datetime(current_date.year, current_date.month, 15)
				# q_end = datetime(current_date.year, current_date.month+1, 15)
			elif current_date.month not in quarterly_months:
				if current_date.month >= 10:
					q_end = datetime(current_date.year + 1, 1, 15)
					# break
				else:
					for i in range(len(quarterly_months)):
						if quarterly_months[i] > current_date.month:
							q_end = datetime(current_date.year, quarterly_months[i], 15)
							break
			else:
				q_end = datetime(current_date.year, current_date.month + 1, 15)
			if q_end > end_date:
				q_end = end_date
	if (
		(q_start.month == 1 and q_end.month == 4)
		or (q_start.month == 3 and q_end.month == 4)
		or (q_start.month == 2 and q_end.month == 4)
	):
		q_end = datetime(current_date.year, 3, 31)
	if cnt == 1 and q_end.month == 4 and q_start.month >= 1 and not (q_start.month == 4 and q_end.month == 4):
		if q_start.month == 2:
			_, last_day = monthrange(current_date.year, current_date.month)
		else:
			# _, last_day = monthrange(current_date.year, 2)
			_, last_day = monthrange(current_date.year, current_date.month)
		q_end = datetime(current_date.year, current_date.month, last_day)

	if sum_modified is not None:
		sum_modified = sum_modified - timedelta(days=1)
		sum_modified = datetime(sum_modified.year, sum_modified.month, sum_modified.day)
		if sum_modified.date() >= q_start.date() and sum_modified.date() <= q_end.date():
			q_end = datetime(sum_modified.year, sum_modified.month, sum_modified.day)
	return (q_start, q_end)


def advance_to_next_period(
	current_date,
	diff_annually,
	mid_diff_annually,
	quarterly_report,
	modified_start,
	q_end=None,
	month_end=None,
	end_date=None,
	esc_bd_end_date=None,
):
	is_dec = current_date.month == 12

	if diff_annually and not mid_diff_annually:
		base_year = current_date.year + 1 if is_dec else current_date.year
		base_month = 1 if is_dec else current_date.month + 1
		return datetime(base_year, base_month, current_date.day) - relativedelta(days=1)

	if diff_annually and mid_diff_annually:
		base_year = current_date.year + 1 if is_dec else current_date.year
		base_month = 1 if is_dec else current_date.month + 1
		return datetime(base_year, base_month, esc_bd_end_date.day) - relativedelta(days=1)

	if quarterly_report and q_end is not None:
		return _advance_quarterly(current_date, q_end, month_end, end_date, is_dec, modified_start)

	if (
		modified_start is not None
		and current_date.date().month == modified_start.month
		and current_date.date().year == modified_start.year
		and modified_start.day != 1
		and current_date.date().day != modified_start.day
	):
		modified_start = datetime(modified_start.year, modified_start.month, modified_start.day)
		return datetime(modified_start.year, modified_start.month, modified_start.day)

	# Default monthly advance
	if is_dec:
		return datetime(current_date.year + 1, 1, 1)
	# frappe.msgprint("curr="+str(current_date.date())+"||"+str(datetime(current_date.year, current_date.month + 1, 1)))

	# else:
	# frappe.msgprint("curr="+str(current_date.date())+"||"+str(datetime(current_date.year, current_date.month + 1, 1)))
	return datetime(current_date.year, current_date.month + 1, 1)


def _advance_quarterly(current_date, q_end, month_end, end_date, is_dec, modified_start):
	_, last_day_q_end = monthrange(q_end.year, q_end.month)
	if modified_start:
		actual_modified = modified_start - timedelta(days=1)
		actual_modified = datetime(
			actual_modified.year, actual_modified.month, actual_modified.day
		)  # convert in datetime then return modified start date
		if actual_modified.date() == q_end.date():
			return datetime(modified_start.year, modified_start.month, modified_start.day)
	if q_end == end_date:
		if q_end.month != 12:
			return datetime(q_end.year + 1 if is_dec else q_end.year, 1 if is_dec else q_end.month + 1, 1)
		return datetime(q_end.year + 1, 1, 1)

	if q_end.month in (2, 3):
		return datetime(q_end.year, q_end.month + 1, 1)
	if q_end != month_end and q_end.month != 3:
		if last_day_q_end == q_end.day:
			next_month = 1 if q_end.month == 12 else q_end.month + 1
			next_year = q_end.year + 1 if q_end.month == 12 else q_end.year
			return datetime(next_year, next_month, 1)
		else:
			if is_dec:
				return datetime(q_end.year, 1, q_end.day + 1)
			return datetime(q_end.year, q_end.month, q_end.day + 1)
	if modified_start:
		if q_end == month_end:
			next_month = 1 if q_end.month == 12 else q_end.month + 1
			next_year = q_end.year + 1 if q_end.month == 12 else q_end.year
			return datetime(next_year, next_month, 1)

	if is_dec:
		return datetime(current_date.year, 1, 16)
	return datetime(current_date.year, current_date.month + 1, 16)


@frappe.whitelist()
def get_prev_wdv_modification(
	calculation_rate_type, previous_lease, agreement_start_date, prev_closing_liability
):
	prev_wdv = None
	if calculation_rate_type == "Daily Rate":
		lreport = "Lease Report"
	else:
		lreport = "Lease Report Monthly (With Escalation)"
	previous_date = add_days(agreement_start_date, -1)
	result = run(lreport, filters={"docname": previous_lease, "sum_modified": agreement_start_date})
	rows = result.get("result", [])
	
	if rows:
		prev_date_val = getdate(previous_date)
		last_row = None
		for row in rows:
			if row.get("month_end_date") and getdate(row["month_end_date"]) == prev_date_val:
				last_row = row
				break
				
		if last_row is not None:
			prev_wdv = (
				float(last_row.get("wdv", 0))
				- float(last_row.get("closing_liability", 0))
				+ float(prev_closing_liability)
			)
			return round(prev_wdv, 3)

	return prev_wdv


def get_period_details(current_date, start_date, end_date, diff_annually, mid_diff_annually, modified_start):
	month_start, month_end, month_start2, month_end2, total_days_of_month = get_month_details(current_date)
	if (
		modified_start is not None
		and month_start.date().month == modified_start.month
		and month_start.date().year == modified_start.year
		and modified_start.day != 1
		and month_start.day != modified_start.day
	):
		modified_start = datetime(modified_start.year, modified_start.month, modified_start.day)
		month_end = modified_start - timedelta(days=1)

	# Calculate n_prior
	if diff_annually:
		if current_date.month == 12:
			prior_date = datetime(current_date.year + 1, 1, current_date.day)
		else:
			prior_date = datetime(current_date.year, current_date.month + 1, current_date.day)
		prior_month_end = datetime(prior_date.year, prior_date.month, current_date.day)
		prior_month_start = prior_date.replace(day=1)
		n_prior = (prior_month_end - prior_month_start).days
	else:
		n_prior = 0

	if end_date < month_end:
		month_end = end_date

	# Calculate n and n_next based on annually/mid flags
	if diff_annually and not mid_diff_annually:
		if month_end < month_end2 and month_end == end_date:
			month_end = current_date
			month_start = current_date.replace(day=1)
		n_next = (month_end - month_start).days + 1
		n = total_days_of_month

	elif mid_diff_annually:
		if month_end < month_end2 and month_end != end_date:
			month_end = current_date
			month_start = current_date.replace(day=1)
		if month_end == end_date:
			month_end = end_date
			month_start = current_date.replace(day=1)
		n_next = (month_end - month_start).days + 1
		n = total_days_of_month

	else:
		n = (month_end - month_start).days + 1
		n_next = 0

	if current_date.strftime("%Y-%m") == end_date.strftime("%Y-%m"):
		month_end = end_date
	if current_date == start_date or month_end == end_date:
		n = (month_end - month_start).days + 1
		n_prior = n
	return month_start, month_end, total_days_of_month, n, n_prior, n_next


def get_sum_modified_mlp(
	sum_modified,
	q_start,
	q_end,
	total_days_prior,
	mlp,
	cnt,
	current_date,
	quarterly_months,
	end_date,
	quarterly_n,
):
	d = datetime(sum_modified.year, sum_modified.month, sum_modified.day)
	d_prior = datetime(sum_modified.year, sum_modified.month, sum_modified.day) - timedelta(days=1)
	if q_end.date() == d_prior.date():
		prior_q_start, prior_q_end = get_q_start_q_end(cnt, current_date, quarterly_months, end_date, None)
		if q_start.date() == prior_q_start.date() and q_end.date() == prior_q_end.date():
			return mlp, total_days_prior
		total_days_prior = total_days_prior + int((prior_q_end - prior_q_start).days + 1)
		mlp = mlp * quarterly_n / total_days_prior
		if q_end.month == 1:
			mlp = 0
	if d.date() == q_start.date():
		if total_days_prior != 0:
			mlp = mlp * quarterly_n / total_days_prior
	return round(mlp, 3), total_days_prior


@frappe.whitelist()
def get_mlp(
	escalation,
	n_prior,
	total_days_of_month,
	n,
	n_next,
	mlp,
	diff_annually,
	famt_prev_mlp1,
	current_date,
	start_date,
	end_date,
	month_end,
	edates_pafa,
	dict_ed_pafa,
	edates_pannum,
	dict_ed_pannum,
	edates_bd,
	dict_ed_bdates,
	common_month,
	common_dict,
	prev_mlp_escl,
	prev_mlp_next,
	modified_start,
):
	mrent, rate, famt = 0, 0, 0
	if n_prior < total_days_of_month or n < total_days_of_month:
		prev_mlp = mlp
		if not diff_annually:
			if famt_prev_mlp1 != 0 and current_date.date() in edates_pafa:
				mlp = famt_prev_mlp1
			mlp = mlp * n / total_days_of_month
			if current_date.date() == start_date and escalation and edates_pafa is not None:
				for k in dict_ed_pafa.keys():
					temp_val = k
					temp = temp_val.split("-")
					famt = float(temp[2])
					famt_prev_mlp1 = prev_mlp
					new_famt = famt * n / total_days_of_month
					mlp = mlp + new_famt
					break
			if current_date.date() in edates_pannum:
				for k in dict_ed_pannum.keys():
					temp_val = k
					temp = temp_val.split("-")
					escl = dict_ed_pannum[k]
					if current_date.date() in escl:
						# pa_rate=rate_pa
						rate = float(temp[0])
						mrent = float(temp[1])
						famt = float(temp[2])
						if mrent != 0:
							mlp = mrent
							mlp = mlp * n / total_days_of_month
						if mrent == 0 and rate == 0 and famt == 0:
							mlp = 0
						mlp = mlp + (rate * mlp / 100) + famt
						if (
							modified_start is not None
							and current_date.date().month == modified_start.month
							and current_date.date().year == modified_start.year
							and modified_start.day != 1
							and current_date.date().day != modified_start.day
						):
							prev_mlp_escl = prev_mlp + (rate * prev_mlp / 100) + famt
						else:
							prev_mlp_escl = mlp
						break
			elif current_date.date() in edates_bd:
				for k in dict_ed_bdates.keys():
					temp_val = k
					temp = temp_val.split("-")
					escl = dict_ed_bdates[k]
					current_month_str = current_date.strftime("%Y-%m")
					if len(common_month) > 0:
						mlp_common_dict = common_dict.get(current_month_str)
						if mlp_common_dict is not None:
							mlp = mlp_common_dict
							if prev_mlp_next[current_month_str] is not None:
								prev_mlp_escl = prev_mlp_next[current_month_str]
								prev_mlp = prev_mlp_escl
							else:
								prev_mlp_escl = prev_mlp
							break
					if current_date.date() in escl:
						rate = float(temp[0])
						mrent = float(temp[1])
						famt = float(temp[2])
						if mrent != 0:
							mlp = mrent
							_, last_day_of_month = monthrange(current_date.year, current_date.month)
							current_month_end = datetime(
								current_date.year, current_date.month, last_day_of_month
							)
							if (
								escl[len(escl) - 1] == current_month_end.date()
								and current_month_end.date() in escl
							) or (
								escl[len(escl) - 1] == end_date.date()
								and end_date.replace(day=1).date() == current_date.date()
								and escl[0] == end_date.replace(day=1).date()
							):
								mlp = mrent
							else:
								mlp = mlp * n / total_days_of_month

						if mrent == 0 and rate == 0 and famt == 0:
							mlp = 0
						if rate != 0 and mrent == 0:
							if escl[0] == current_date.date():
								rate = float(temp[0])
								famt = float(temp[2])
							else:
								rate = famt = 0
						mlp = mlp + (rate * mlp / 100) + famt
						if mrent == 0 and rate == 0 and famt == 0:
							prev_mlp_escl = prev_mlp
							if float(temp[0]) != 0 and rate == 0 and famt == 0:
								prev_mlp_escl = mlp
							else:
								prev_mlp_escl = prev_mlp
						else:
							prev_mlp_escl = mlp
						break
			elif current_date.date() in edates_pafa:
				for k in dict_ed_pafa.keys():
					temp_val = k
					temp = temp_val.split("-")
					escl = dict_ed_pafa[k]
					if current_date.date() in escl:
						rate = float(temp[0])
						mrent = float(temp[1])
						famt = float(temp[2])
						if mrent != 0:
							mlp = mrent
							mlp = mlp * n / total_days_of_month
						if mrent == 0 and rate == 0 and famt == 0:
							mlp = 0
						if rate != 0 and mrent != 0:
							if escl[0] == current_date.date():
								mlp = float(temp[1])
								new_famt = famt * n / total_days_of_month
								mlp = mlp + new_famt
							else:
								mlp = prev_mlp_escl
						mlp = mlp + (rate * mlp / 100) + famt
						prev_mlp_escl = mlp
						famt_prev_mlp1 = famt_prev_mlp1 + (famt_prev_mlp1 * rate / 100)
						break
			return (mlp, prev_mlp_escl, famt_prev_mlp1, prev_mlp, mrent, rate, famt)
		else:
			if famt_prev_mlp1 != 0 and current_date.date() in edates_pafa:
				mlp = famt_prev_mlp1
			mlp_1 = mlp * n_prior / total_days_of_month
			mlp_2 = 0
			if current_date == start_date or month_end == end_date:
				mlp = mlp_1
			mlp_new = mlp
			if current_date.date() == start_date.date() and escalation and edates_pafa is not None:
				for k in dict_ed_pafa.keys():
					temp_val = k
					temp = temp_val.split("-")
					famt = float(temp[2])
					famt_prev_mlp1 = prev_mlp
					new_famt = famt * n_prior / total_days_of_month
					mlp_new = mlp_new + new_famt
					prev_mlp_escl = prev_mlp + famt
					break
			if current_date.date() in edates_pannum and escalation:
				for k in dict_ed_pannum.keys():
					temp_val = k
					temp = temp_val.split("-")
					escl = dict_ed_pannum[k]
					if current_date.date() in escl:
						rate = float(temp[0])
						mrent = float(temp[1])
						famt = float(temp[2])
						if mrent != 0:
							mlp = mrent
							mlp = mlp * n / total_days_of_month
						if mrent == 0 and rate == 0 and famt == 0:
							mlp = 0
						mlp = mlp + (rate * mlp / 100) + famt
						mlp_2 = mlp * n_next / total_days_of_month
						mlp_new = mlp_1 + mlp_2
						prev_mlp_escl = mlp
						break
			elif current_date.date() in edates_bd and escalation:
				for k in dict_ed_bdates.keys():
					temp_val = k
					temp = temp_val.split("-")
					escl = dict_ed_bdates[k]
					if current_date.date() in escl:
						rate = float(temp[0])
						mrent = float(temp[1])
						famt = float(temp[2])
						if mrent != 0:
							mlp = mrent
							# mlp = mlp * n / total_days_of_month
							_, last_day_of_month = monthrange(current_date.year, current_date.month)
							current_month_end = datetime(
								current_date.year, current_date.month, last_day_of_month
							)
							if (
								escl[len(escl) - 1] == current_month_end.date()
								and current_month_end.date() in escl
							) or (
								escl[len(escl) - 1] == end_date.date()
								and end_date.replace(day=1).date() == current_date.date()
								and escl[0] == end_date.replace(day=1).date()
							):
								mlp = mrent
							else:
								mlp = mlp * n / total_days_of_month

						if mrent == 0 and rate == 0 and famt == 0:
							mlp = 0
						if rate != 0 and mrent == 0:
							if escl[0] == current_date.date():
								rate = float(temp[0])
								famt = float(temp[2])
							else:
								rate = famt = 0
						mlp = mlp + (rate * mlp / 100) + famt
						mlp_new = mlp
						if mrent == 0 and rate == 0 and famt == 0:
							if float(temp[0]) != 0 and rate == 0 and famt == 0:
								prev_mlp_escl = mlp
							else:
								prev_mlp_escl = prev_mlp
						else:
							prev_mlp_escl = mlp
						break
			elif current_date.date() in edates_pafa and escalation:
				for k in dict_ed_pafa.keys():
					temp_val = k
					temp = temp_val.split("-")
					escl = dict_ed_pafa[k]
					if current_date.date() in escl:
						rate = float(temp[0])
						mrent = float(temp[1])
						famt = float(temp[2])
						if mrent != 0:
							mlp = mrent
							mlp = mlp * n / total_days_of_month
						if mrent == 0 and rate == 0 and famt == 0:
							mlp = 0
						if rate != 0 and mrent != 0:
							if escl[0] == current_date.date():
								mlp = float(temp[1])
								new_famt = famt * n / total_days_of_month
								mlp = mlp + new_famt
							else:
								mlp = prev_mlp_escl
						mlp = mlp + (rate * mlp / 100) + famt

						if famt != 0:
							mlp_1 = mlp_1 + (famt * n_prior / total_days_of_month)
						mlp_2 = mlp * n_next / total_days_of_month
						mlp_new = mlp_1 + mlp_2
						prev_mlp_escl = mlp
						famt_prev_mlp1 = famt_prev_mlp1 + (famt_prev_mlp1 * rate / 100)
						break

			return (mlp_new, prev_mlp_escl, famt_prev_mlp1, prev_mlp, mrent, rate, famt)
	else:
		prev_mlp = mlp
		if current_date.date() == start_date.date() and escalation and edates_pafa is not None:
			for k in dict_ed_pafa.keys():
				temp_val = k
				temp = temp_val.split("-")
				famt = float(temp[2])
				famt_prev_mlp1 = prev_mlp
				mlp = mlp + famt
				break
		if current_date.date() in edates_pannum:
			for k in dict_ed_pannum.keys():
				temp_val = k
				temp = temp_val.split("-")
				escl = dict_ed_pannum[k]
				if current_date.date() in escl:
					rate = float(temp[0])
					mrent = float(temp[1])
					famt = float(temp[2])
					if mrent != 0:
						mlp = mrent
					mlp = mlp + (rate * mlp / 100) + famt
					prev_mlp_escl = mlp
					break
		elif current_date.date() in edates_bd:
			for k in dict_ed_bdates.keys():
				temp_val = k
				temp = temp_val.split("-")
				escl = dict_ed_bdates[k]
				current_month_str = current_date.strftime("%Y-%m")
				if len(common_month) > 0:
					mlp_common_dict = common_dict.get(current_month_str)
					if mlp_common_dict is not None:
						mlp = mlp_common_dict
						if prev_mlp_next[current_month_str] is not None:
							prev_mlp_escl = prev_mlp_next[current_month_str]
							prev_mlp = prev_mlp_escl
						else:
							prev_mlp_escl = prev_mlp
						break
				if current_date.date() in escl:
					rate = float(temp[0])
					mrent = float(temp[1])
					famt = float(temp[2])
					if mrent != 0:
						mlp = mrent
					if mrent == 0 and rate == 0 and famt == 0:
						mlp = 0
					if rate != 0 and mrent == 0:
						if escl[0] == current_date.date():
							rate = float(temp[0])
							famt = float(temp[2])
						else:
							rate = famt = 0
					mlp = mlp + (rate * mlp / 100) + famt
					break
		elif current_date.date() in edates_pafa:
			for k in dict_ed_pafa.keys():
				temp_val = k
				temp = temp_val.split("-")
				escl = dict_ed_pafa[k]
				if current_date.date() in escl:
					rate = float(temp[0])
					mrent = float(temp[1])
					famt = float(temp[2])
					if mrent != 0:
						mlp = mrent
					if rate != 0 and mrent != 0:
						if escl[0] == current_date.date():
							mlp = float(temp[1])
							mlp = mlp + famt
						else:
							mlp = prev_mlp
					mlp = mlp + (rate * mlp / 100) + famt
					break

		return (mlp, prev_mlp_escl, prev_mlp, mrent, rate, famt)
