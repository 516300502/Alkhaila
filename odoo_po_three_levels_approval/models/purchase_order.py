from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import date, datetime,timedelta


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _po_dept_manager_domain(self):
        return [('id', 'in', self.env.ref('purchase.group_purchase_manager').users.ids)]

    def _po_finance_manager_domain(self):
        return [('id', 'in', self.env.ref('odoo_po_three_levels_approval.group_purchase_finance_manager').users.ids)]

    def _po_director_domain(self):
        return [('id', 'in', self.env.ref('odoo_po_three_levels_approval.group_purchase_director').users.ids)]

    state = fields.Selection([('draft', 'RFQ'), ('sent', 'RFQ Sent'), ('to approve', 'To Approve'),
                              ('finance_approve', 'Finance Approval'), ('director_approve', 'Director Approval'),
                              ('purchase', 'Purchase Order'), ('done', 'Locked'), ('refuse', 'Refuse'), ('cancel', 'Cancelled')
                              ], string='Status', readonly=True, index=True, copy=False, default='draft', tracking=True)

    dept_manager_approval_required = fields.Boolean(compute='check_approval_required')
    dept_manager_id = fields.Many2one('res.users', string='Approval Department Manager', domain=_po_dept_manager_domain, copy=False)
    dept_manager_approve_date = fields.Date('Department Manager Approval Date', readonly=True, copy=False)

    finance_approval_required = fields.Boolean(compute='check_approval_required')
    finance_approval_id = fields.Many2one('res.users', string='Approval Finance Manager', domain=_po_finance_manager_domain, copy=False)
    finance_manager_approve_date = fields.Date('Finance Manager Approval Date', readonly=True, copy=False)

    director_approval_required = fields.Boolean(compute='check_approval_required')
    director_approval_id = fields.Many2one('res.users', string='Approval Director', domain=_po_director_domain, copy=False)
    director_approve_date = fields.Date('Director Approval Date', readonly=True, copy=False)

    refused_user_id = fields.Many2one('res.users', string='Refused By', copy=False)
    refused_date = fields.Date('Refused Date', readonly=True, copy=False)
    refused_reason = fields.Text('Refused Reason', readonly=True, copy=False)

    @api.depends('amount_total')
    def check_approval_required(self):
        for po in self:
            vals = {'finance_approval_required': False, 'director_approval_required': False, 'dept_manager_approval_required': False}
            if po.company_id and po.company_id.three_step_approval and po.company_id.set_approval_user_required:
                if po.amount_total > po.company_id.finance_approve_limit:
                    vals.update({'finance_approval_required': True})
                if po.amount_total > po.company_id.director_approve_limit:
                    vals.update({'director_approval_required': True})
                if po.amount_total > po.company_id.dept_manager_approve_limit:
                    vals.update({'dept_manager_approval_required': True})
            po.write(vals)

    def button_confirm(self):
        # Regular Confirm Override Base Method And Added Three Step Approval
        for po in self:
            if po.state not in ['draft', 'sent']:
                continue
            po._add_supplier_to_product()
            if not po.company_id.three_step_approval == True or po.amount_total < self.env.user.company_id.currency_id.compute(
                    po.company_id.dept_manager_approve_limit, po.currency_id):
                po.button_approve(force=True)
            else:
                modelid = (self.env['ir.model'].search([('model', '=', 'purchase.order')])).id
                select = "select uid from res_groups_users_rel as gs where gs.gid in (select id from res_groups as gg where name = '%s' and category_id in (select id from ir_module_category where name = '%s')   ) " % (
                    'Administrator', 'Purchase')
                self.env.cr.execute(select)
                results = self.env.cr.dictfetchall()
                users = []
                for obj in results:
                    users.append(obj['uid'])


                select = "select uid from res_groups_users_rel as gs where gs.gid in (select id from res_groups as gg where name = '%s' and category_id in (select id from ir_module_category where name = '%s')   ) " % (
                    'Purchase Finance Manager', 'Purchase')
                self.env.cr.execute(select)
                results = self.env.cr.dictfetchall()
                finance_users = []
                for obj in results:
                    finance_users.append(obj['uid'])


                select = "select uid from res_groups_users_rel as gs where gs.gid in (select id from res_groups as gg where name = '%s' and category_id in (select id from ir_module_category where name = '%s')   ) " % (
                    'Director', 'Purchase')
                self.env.cr.execute(select)
                results = self.env.cr.dictfetchall()
                Director_users = []
                for obj in results:
                    Director_users.append(obj['uid'])



                print("users", users)

                user_id = (self.env['res.users'].search([('id', 'in', users),('id', 'not in', finance_users),('id', 'not in', Director_users)]))
                activity = self.env['mail.activity']
                for user in user_id:
                    activity_ins = activity.create(
                        {'res_id': self.id,
                         'res_model_id': modelid,
                         'res_model': 'purchase.order',
                         'activity_type_id': (
                             self.env['mail.activity.type'].search([('res_model_id', '=', modelid)])).id,
                         'summary': '',
                         'note': '',
                         'date_deadline': date.today(),
                         'activity_category': 'default',
                         'previous_activity_type_id': False,
                         'recommended_activity_type_id': False,
                         'user_id': user.id
                         })

                po.write({'state': 'to approve'})  # Call For Manager Approval
        return True

    def button_approve(self, force=False):
        # Regular Approve Override Base Method And Added Three Step Approval
        for po in self:
            activity_old = (
                self.env['mail.activity'].search(
                    [('res_model', '=', 'purchase.order'), ('res_id', '=', self.id)]))
            for ac in activity_old:
                ac.action_done()

            company = po.company_id
            if not company.three_step_approval or (company.dept_manager_approve_limit <= 0 or company.finance_approve_limit <= 0 or company.director_approve_limit <= 0):
                return super(PurchaseOrder, self).button_approve(force=force)
            if po.dept_manager_id and self.env.user != po.dept_manager_id and not force:
                raise UserError(_("Only %s User Can Approve This Order." % (po.dept_manager_id.name)))
            if po.amount_total < self.env.user.company_id.currency_id.compute(po.company_id.finance_approve_limit, po.currency_id):
                if force:
                    po.write({'state': 'purchase'})
                else:
                    po.write({'state': 'purchase', 'dept_manager_id': self.env.uid, 'dept_manager_approve_date': fields.Date.context_today(self)})
                po._create_picking()
                po.filtered(lambda p: p.company_id.po_lock == 'lock').write({'state': 'done'})
            else:

                modelid = (self.env['ir.model'].search([('model', '=', 'purchase.order')])).id
                select = "select uid from res_groups_users_rel as gs where gs.gid in (select id from res_groups as gg where name = '%s' and category_id in (select id from ir_module_category where name = '%s')   ) " % (
                    'Purchase Finance Manager', 'Purchase')
                self.env.cr.execute(select)
                results = self.env.cr.dictfetchall()
                users = []
                for obj in results:
                    users.append(obj['uid'])
                print("users", users)
                select = "select uid from res_groups_users_rel as gs where gs.gid in (select id from res_groups as gg where name = '%s' and category_id in (select id from ir_module_category where name = '%s')   ) " % (
                    'Director', 'Purchase')
                self.env.cr.execute(select)
                results = self.env.cr.dictfetchall()
                Director_users = []
                for obj in results:
                    Director_users.append(obj['uid'])

                user_id = (self.env['res.users'].search([('id', 'in', users),('id', 'not in', Director_users)]))
                activity = self.env['mail.activity']
                for user in user_id:
                    activity_ins = activity.create(
                        {'res_id': self.id,
                         'res_model_id': modelid,
                         'res_model': 'purchase.order',
                         'activity_type_id': (
                             self.env['mail.activity.type'].search([('res_model_id', '=', modelid)])).id,
                         'summary': '',
                         'note': '',
                         'date_deadline': date.today(),
                         'activity_category': 'default',
                         'previous_activity_type_id': False,
                         'recommended_activity_type_id': False,
                         'user_id': user.id
                         })
                po.write({'state': 'finance_approve', 'dept_manager_id': self.env.uid,
                          'dept_manager_approve_date': fields.Date.context_today(self)})
        return {}

    def purchase_finance_manager_approve(self):
        for po in self:
            activity_old = (
                self.env['mail.activity'].search(
                    [('res_model', '=', 'purchase.order'), ('res_id', '=', self.id)]))
            for ac in activity_old:
                ac.action_done()

            company = po.company_id
            if po.finance_approval_id and self.env.user != po.finance_approval_id:
                raise UserError(_("Only %s User Can Approve This Order." % (po.finance_approval_id)))
            if po.amount_total < self.env.user.company_id.currency_id.compute(po.company_id.director_approve_limit, po.currency_id):
                po.write({'state': 'purchase', 'date_approve': fields.Date.context_today(self)})
                po._create_picking()
                po.filtered(lambda p: p.company_id.po_lock == 'lock').write({'state': 'done'})
            else:


                modelid = (self.env['ir.model'].search([('model', '=', 'purchase.order')])).id
                select = "select uid from res_groups_users_rel as gs where gs.gid in (select id from res_groups as gg where name = '%s' and category_id in (select id from ir_module_category where name = '%s')   ) " % (
                    'Director', 'Purchase')
                self.env.cr.execute(select)
                results = self.env.cr.dictfetchall()
                users = []
                for obj in results:
                    users.append(obj['uid'])
                print("users", users)
                user_id = (self.env['res.users'].search([('id', 'in', users)]))
                activity = self.env['mail.activity']
                for user in user_id:
                    activity_ins = activity.create(
                        {'res_id': self.id,
                         'res_model_id': modelid,
                         'res_model': 'purchase.order',
                         'activity_type_id': (
                             self.env['mail.activity.type'].search([('res_model_id', '=', modelid)])).id,
                         'summary': '',
                         'note': '',
                         'date_deadline': date.today(),
                         'activity_category': 'default',
                         'previous_activity_type_id': False,
                         'recommended_activity_type_id': False,
                         'user_id': user.id
                         })
                po.write({'state': 'director_approve', 'finance_approval_id': self.env.uid,
                          'finance_manager_approve_date': fields.Date.context_today(self)})
        return {}

    def purchase_director_approve(self):
        for po in self:
            company = po.company_id
            if po.director_approval_id and self.env.user != po.director_approval_id:
                raise UserError(_("Only %s User Can Approve This Order." % (po.director_approval_id)))
            activity_old = (
                self.env['mail.activity'].search(
                    [('res_model', '=', 'purchase.order'), ('res_id', '=', self.id)]))
            for ac in activity_old:
                ac.action_done()

            po.write({'state': 'purchase', 'director_approval_id': self.env.uid,
                      'director_approve_date': fields.Date.context_today(self), 'date_approve': fields.Date.context_today(self)})
            po._create_picking()
            po.filtered(lambda p: p.company_id.po_lock == 'lock').write({'state': 'done'})
        return {}

    def refused_order(self):
        
        # Check User Access
        groups_ids = self.env.user.groups_id.ids
        access = ''
        if self.env.ref('odoo_po_three_levels_approval.group_purchase_director').id in groups_ids:
            access = 'purchase_director'
        elif self.env.ref('odoo_po_three_levels_approval.group_purchase_finance_manager').id in groups_ids:
            access = 'finance_manager'
        elif self.env.ref('purchase.group_purchase_manager').id in groups_ids:
            access = 'purchase_manager'
        for po in self:
            if po.state == 'director_approve' and access != 'purchase_director':
                raise UserError(_('You Can Not Reject This Order'))
            elif po.state == 'finance_approve' and access not in ['finance_manager', 'purchase_director']:
                raise UserError(_('You Can Not Reject This Order'))
            elif po.state == 'to approve' and access not in ['purchase_manager', 'finance_manager', 'purchase_director']:
                raise UserError(_('You Can Not Reject This Order'))
            return {
                'name': 'Purchase Order Refuse',
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order.refuse',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_purchase_order_id': po.id},
            }
