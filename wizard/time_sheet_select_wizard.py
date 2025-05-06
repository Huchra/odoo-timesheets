# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.


from odoo import api, fields, models, _
from datetime import date, datetime, timedelta, time as dt_time
import xlsxwriter
import io
import base64
import itertools
import pytz
from odoo.exceptions import ValidationError




class timesheet_select(models.TransientModel):
    _name = 'timesheet.select'
    _description = "timesheet select"

    start_date = fields.Date(string="Start date",required=True)
    end_date = fields.Date(string="End Date",required=True)

    employee_ids = fields.Many2many('hr.employee',string="Select employee",required=True)


    def generate_pdf_report(self):
        if self.start_date > self.end_date:
            raise ValidationError(_("Invalid Date !! End date should be greater than the start date"))
        else:
            data_dict = {'id': self.id,'start_date': self.start_date, 'end_date': self.end_date,'employee_ids':self.employee_ids}
            return self.env.ref('bi_employee_timesheet_report.timesheet_report_id').report_action(self,
                                                                                                 data=data_dict)

    def generate_excel_report(self):

        if self.start_date > self.end_date:
            raise ValidationError(_("Invalid Date !! End date should be greater than the start date"))
        else:
            self.ensure_one()
            file_path = 'timesheet report' + '.xlsx'
            workbook = xlsxwriter.Workbook('/tmp/' + file_path)

            title_format = workbook.add_format(
                {'border': 1, 'bold': True, 'valign': 'vcenter', 'align': 'center', 'font_size': 11, 'bg_color': '#D8D8D8'})

            formate_1 = workbook.add_format({'bold': True, 'align': 'center', 'font_size': 11,'font_color':'red'})

            record = self.env['account.analytic.line'].search(
                [('employee_id', 'in', self.employee_ids.ids), ('date', '>=', self.start_date),
                 ('date', '<=', self.end_date)])

            sheet = workbook.add_worksheet('Timesheet Report')

            row = 8
            col = 2
            total = 0

            grouped_records = {}
            for rec in record:
                employee_id = rec['employee_id']
                if employee_id in grouped_records:
                    grouped_records[employee_id].append(rec)
                else:
                    grouped_records[employee_id] = [rec]

            # --- Compute project hours per employee ---
            # Structure: { employee_name: { project_name: total_hours } }
            project_hours_map = {}
            for employee_id, employee_records in grouped_records.items():
                emp_name = employee_id.name
                project_hours_map[emp_name] = {}
                for rec in employee_records:
                    project = rec.project_id.name or ''
                    project_hours_map[emp_name][project] = project_hours_map[emp_name].get(project, 0) + rec.unit_amount

            sheet.set_column('C:C', 28)  # Scheduled Work Hours and other info
            sheet.set_column('D:E', 25)
            sheet.set_column('E:F', 25)
            sheet.set_column('G:G', 18)
            sheet.set_column('H:H', 25)  # Project column (index 8)
            sheet.set_column('I:I', 25)  # Project Hours column (index 9)
            sheet.set_column('J:J', 25)  # Description column (index 10)
            sheet.set_column('B:B', 28)  # Scheduled Work Hours (column B, index 1)
            sheet.set_column('A:A', 28)

            row_t = 1
            col_t = 4
            sheet.merge_range(row_t, col_t-1, row_t + 1, col_t + 1, "Timesheet Report", title_format)
            sheet.merge_range(row - 4, 3, row - 4, 5, f' Timesheet Period : From {self.start_date} To {self.end_date}',title_format)

            store_list = []
            for rec in self.env['hr.employee'].search(
                    [('name', 'in', [i.name for i in self.employee_ids])]):
                if rec:
                    store_list.append({'id': rec.id, 'name': rec.name})

            for emp_name in store_list:
                # Get the employee record
                employee = self.env['hr.employee'].browse(emp_name['id'])
                scheduled_hours = 0.0
                if employee.resource_calendar_id:
                    # Convert date to datetime with timezone
                    user_tz = self.env.user.tz or 'UTC'
                    tz = pytz.timezone(user_tz)
                    start_dt = tz.localize(datetime.combine(self.start_date, dt_time.min))
                    end_dt = tz.localize(datetime.combine(self.end_date, dt_time.max))
                    scheduled_hours = employee.resource_calendar_id.get_work_hours_count(
                        start_dt, end_dt, compute_leaves=True)
                    # Calculate leave hours for employee
                    leave_hours = 0.0

                    leaves = self.env['hr.leave'].search([
                        ('employee_id', '=', employee.id),
                        ('state', '=', 'validate'),
                        ('date_from', '<=', end_dt),
                        ('date_to', '>=', start_dt)
                    ])
                    for leave in leaves:
                        hours = employee.resource_calendar_id.get_work_hours_count(
                            leave.date_from, leave.date_to) # this is 24 hours not 8 per
                        leave_hours += hours

                    scheduled_hours -= leave_hours

                # Calculate total worked hours for this employee in the selected period
                worked_hours = sum(
                    rec.unit_amount for rec in self.env['account.analytic.line'].search([
                        ('employee_id', '=', employee.id),
                        ('date', '>=', self.start_date),
                        ('date', '<=', self.end_date)
                    ])
                )

                # Write scheduled hours info before the tables
                sheet.write(row - 3, 2, f"Scheduled Work Hours: {scheduled_hours}", title_format)
                # Next to it, write time difference
                sheet.write(row - 3, 3, f"Time Difference: {round(worked_hours - scheduled_hours, 3)}", title_format)

                sheet.merge_range(row - 2, 2, row - 2, 3, f" Employee Name : {emp_name['name']}", title_format)
                if emp_name['name'] in [i.name for i in grouped_records]:
                    for employee_id, employee_records in grouped_records.items():

                        if employee_id.name == emp_name['name']:
                            # Timesheet details table
                            sheet.write(row, 2, 'Date', title_format)
                            sheet.write(row, 3, 'Project', title_format)
                            sheet.write(row, 4, 'Task', title_format)
                            sheet.write(row, 5, 'Description', title_format)
                            sheet.write(row, 6, 'Time Spent(Hours)', title_format)
                            # Leave one empty column (col 7)
                            # Project summary table headers
                            sheet.write(row, 8, 'Project', title_format)
                            sheet.write(row, 9, 'Project Hours', title_format)

                            start_row = row
                            for rec in employee_records:
                                row += 1
                                project_name = rec.project_id.name or ''
                                sheet.write(row, 2, rec.date.strftime("%Y-%m-%d"))
                                sheet.write(row, 3, project_name)
                                sheet.write(row, 4, rec.task_id.name if rec.task_id.name else "")
                                sheet.write(row, 5, rec.name)
                                sheet.write(row, 6, rec.unit_amount)
                                # Do not write project hours here
                                total += rec.unit_amount
                                sheet.write(row+1, 6, total, title_format)
                            # Write project summary table (one row per project)
                            proj_row = start_row + 1
                            for project, hours in project_hours_map[emp_name['name']].items():
                                sheet.write(proj_row, 8, project)
                                sheet.write(proj_row, 9, hours)
                                proj_row += 1

                            row = max(row, proj_row) + 3
                            total = 0
                else:
                    sheet.merge_range(row , 3, row , 5,"No Data Was Found For This Employee In Selected Date", formate_1)
                    row += 4

            workbook.close()
            ex_report = base64.b64encode(open('/tmp/' + file_path, 'rb+').read())

            excel_report_id = self.env['save.ex.report.wizard'].create({"document_frame": file_path,
                                                                        "file_name": ex_report})

            return {
                'res_id': excel_report_id.id,
                'name': 'Files to Download',
                'view_type': 'form',
                "view_mode": 'form',
                'view_id': False,
                'res_model': 'save.ex.report.wizard',
                'type': 'ir.actions.act_window',
                'target': 'new',
            }


