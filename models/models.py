from odoo import models, fields, api
from datetime import timedelta

SPORT_TYPES = [
    ('badminton', 'Badminton'), ('squash', 'Squash'), ('tennis', 'Tennis'),
    ('turf', 'Turf'), ('volleyball', 'Volleyball'), ('gym', 'Gym'),
    ('cycling', 'Cycling'), ('hockey', 'Hockey'), ('skating', 'Skating'),
    ('table_tennis', 'Table Tennis'),
]
PAYMENT_MODES = [
    ('cash', 'Cash'), ('upi', 'UPI'), ('card', 'Card'), ('bank_transfer', 'Bank Transfer'),
]


class VanguardTutor(models.Model):
    _name = 'vanguard.tutor'
    _description = 'Facility Tutor / Coach'
    _order = 'name'

    name = fields.Char('Tutor Name', required=True)
    facility_id = fields.Many2one('vanguard.facility', required=True, ondelete='cascade')
    sport_type = fields.Selection(SPORT_TYPES, string='Primary Sport', required=True)
    experience_years = fields.Integer('Experience (Years)', default=1)
    bio = fields.Text('Bio / Notes')
    is_active = fields.Boolean('Active', default=True)
    phone = fields.Char('Contact Phone')
    student_ids = fields.One2many('vanguard.customer', 'tutor_id', string='Assigned Students')

    student_count = fields.Integer(compute='_compute_student_count', store=False)

    @api.depends('student_ids')
    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)


class VanguardFacility(models.Model):
    _name = 'vanguard.facility'
    _description = 'Sport Facility'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Facility Name', required=True, tracking=True)
    location = fields.Char('Location')
    phone = fields.Char('Phone')
    email = fields.Char('Email')
    owner_email = fields.Char('Owner Login Email', index=True)
    owner_password = fields.Char('Owner Password')  # plain text MVP
    owner_phone = fields.Char('Owner Phone', index=True)
    state = fields.Selection([
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='pending', tracking=True)

    verification_doc = fields.Binary('Verification ID (Aadhar/PAN Card)', attachment=True)
    verification_doc_name = fields.Char('Verification ID Filename')
    turf_img1 = fields.Binary('Turf Image 1', attachment=True)
    turf_img2 = fields.Binary('Turf Image 2', attachment=True)
    turf_img3 = fields.Binary('Turf Image 3', attachment=True)
    turf_img4 = fields.Binary('Turf Image 4', attachment=True)
    turf_location_coords = fields.Char('Turf GPS Coordinates')
    company_registration_no = fields.Char('Business Registration Number (GSTIN/MSME/PAN)')

    sport_asset_ids = fields.One2many('vanguard.sport.asset', 'facility_id', string='Sport Assets')
    booking_ids = fields.One2many('vanguard.booking', 'facility_id', string='Bookings')
    customer_ids = fields.One2many('vanguard.customer', 'facility_id', string='Customers')
    plan_ids = fields.One2many('vanguard.subscription.plan', 'facility_id', string='Subscription Plans')
    tutor_ids = fields.One2many('vanguard.tutor', 'facility_id', string='Tutors')

    total_bookings_today = fields.Integer(compute='_compute_stats', string='Bookings Today', store=False)
    total_customers = fields.Integer(compute='_compute_stats', string='Total Customers', store=False)
    revenue_mtd = fields.Float(compute='_compute_stats', string='Revenue MTD', store=False)
    total_assets = fields.Integer(compute='_compute_total_assets', string='Total Assets', store=False)

    @api.depends('booking_ids', 'booking_ids.booking_date', 'booking_ids.price', 'booking_ids.state', 'customer_ids')
    def _compute_stats(self):
        today = fields.Date.today()
        for rec in self:
            today_bookings = rec.booking_ids.filtered(
                lambda b: b.booking_date == today and b.state != 'cancelled')
            rec.total_bookings_today = len(today_bookings)
            rec.total_customers = len(rec.customer_ids)
            rec.revenue_mtd = sum(rec.booking_ids.filtered(
                lambda b: b.booking_date and b.booking_date.month == today.month
                and b.state == 'confirmed'
            ).mapped('price'))

    @api.model
    def authenticate_owner(self, email, password):
        """Returns facility_id if credentials match and state is approved, 0 otherwise."""
        facility = self.search([
            ('owner_email', '=', email),
            ('owner_password', '=', password),
            ('state', '=', 'approved'),
        ], limit=1)
        return facility.id if facility else 0

    @api.depends('sport_asset_ids.count')
    def _compute_total_assets(self):
        for rec in self:
            rec.total_assets = sum(rec.sport_asset_ids.mapped('count'))

    def action_approve(self):
        for rec in self:
            rec.state = 'approved'

    def action_reject(self):
        for rec in self:
            rec.state = 'rejected'



class VanguardSportAsset(models.Model):
    _name = 'vanguard.sport.asset'
    _description = 'Sport Asset Configuration'

    facility_id = fields.Many2one('vanguard.facility', required=True, ondelete='cascade')
    sport_type = fields.Selection(SPORT_TYPES, string='Sport Type', required=True)
    count = fields.Integer('Number of Courts/Units', default=1)
    open_time = fields.Float('Opens At (24h)', default=6.0)
    close_time = fields.Float('Closes At (24h)', default=22.0)
    price_per_hour = fields.Float('Walk-in Price/Hour (₹)', default=500.0)


class VanguardSubscriptionPlan(models.Model):
    _name = 'vanguard.subscription.plan'
    _description = 'Subscription Plan'
    _order = 'price asc'

    name = fields.Char('Plan Name', required=True)
    facility_id = fields.Many2one('vanguard.facility', required=True)
    plan_type = fields.Selection([('member', 'Member'), ('student', 'Student')], default='member', required=True)
    sport_type = fields.Selection(SPORT_TYPES + [('all', 'All Sports')], default='all')
    duration_days = fields.Integer('Duration (Days)', default=30)
    price = fields.Float('Price (₹)', default=0.0)
    subscription_ids = fields.One2many('vanguard.customer.subscription', 'plan_id', string='Subscriptions')

    user_count = fields.Integer(compute='_compute_plan_stats', store=False)
    gross_yield = fields.Float(compute='_compute_plan_stats', store=False)
    renewals = fields.Integer(compute='_compute_plan_stats', store=False)

    @api.depends('subscription_ids', 'subscription_ids.state', 'subscription_ids.amount_paid', 'subscription_ids.is_renewal')
    def _compute_plan_stats(self):
        for rec in self:
            active = rec.subscription_ids.filtered(lambda s: s.state == 'active')
            rec.user_count = len(active)
            rec.gross_yield = sum(rec.subscription_ids.mapped('amount_paid'))
            rec.renewals = len(rec.subscription_ids.filtered(lambda s: s.is_renewal))


class VanguardCustomer(models.Model):
    _name = 'vanguard.customer'
    _description = 'Facility Customer'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char('Customer Name', required=True)
    phone = fields.Char('Phone', required=True)
    email = fields.Char('Email')
    facility_id = fields.Many2one('vanguard.facility', ondelete='set null')

    customer_type = fields.Selection([
        ('member', 'Member'), ('student', 'Student'), ('walk_in', 'Walk-in'),
    ], required=True, default='member', tracking=True)
    sport_type = fields.Selection(SPORT_TYPES, string='Primary Sport')

    # Student-only
    # coaching_level = fields.Selection([
    #     ('beginner', 'Beginner'), ('intermediate', 'Intermediate'), ('advanced', 'Advanced'),
    # ], string='Coaching Level')
    coach_assigned = fields.Boolean('Coach Assigned', default=False)
    court_assignment = fields.Char('Court Assignment')
    tutor_id = fields.Many2one('vanguard.tutor', string='Assigned Tutor', domain="[('facility_id', '=', facility_id)]")

    subscription_ids = fields.One2many('vanguard.customer.subscription', 'customer_id', string='Subscriptions')
    booking_ids = fields.One2many('vanguard.booking', 'customer_id', string='Bookings')

    active_plan_name = fields.Char(compute='_compute_active_sub', store=False)
    active_plan_amount = fields.Float(compute='_compute_active_sub', store=False)
    is_expired = fields.Boolean(compute='_compute_active_sub', store=False)

    @api.depends('subscription_ids', 'subscription_ids.state', 'subscription_ids.plan_id')
    def _compute_active_sub(self):
        for rec in self:
            active = rec.subscription_ids.filtered(lambda s: s.state == 'active')
            if active:
                sub = active[0]
                rec.active_plan_name = sub.plan_id.name if sub.plan_id else ''
                rec.active_plan_amount = sub.amount_paid
                rec.is_expired = False
            else:
                rec.active_plan_name = 'Expired' if rec.subscription_ids else 'No Plan'
                rec.active_plan_amount = 0.0
                rec.is_expired = bool(rec.subscription_ids)


class VanguardCustomerSubscription(models.Model):
    _name = 'vanguard.customer.subscription'
    _description = 'Customer Subscription'
    _order = 'start_date desc'

    customer_id = fields.Many2one('vanguard.customer', required=True, ondelete='cascade')
    plan_id = fields.Many2one('vanguard.subscription.plan', string='Plan')
    sport_type = fields.Selection(SPORT_TYPES, string='Sport')
    start_date = fields.Date('Start Date', default=fields.Date.today)
    end_date = fields.Date('End Date', compute='_compute_end_date', store=True)
    amount_paid = fields.Float('Amount Paid (₹)')
    payment_mode = fields.Selection(PAYMENT_MODES, default='cash')
    receipt_date = fields.Date('Monthly Receipt Date')
    state = fields.Selection([
        ('active', 'Active'), ('expired', 'Expired'), ('cancelled', 'Cancelled'),
    ], default='active', tracking=True)
    is_renewal = fields.Boolean('Is Renewal', default=False)

    @api.depends('start_date', 'plan_id.duration_days')
    def _compute_end_date(self):
        for rec in self:
            if rec.start_date and rec.plan_id and rec.plan_id.duration_days:
                rec.end_date = rec.start_date + timedelta(days=rec.plan_id.duration_days)
            else:
                rec.end_date = rec.start_date


class VanguardBooking(models.Model):
    _name = 'vanguard.booking'
    _description = 'Sport Facility Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'booking_date desc, start_time desc'

    name = fields.Char(required=True, copy=False, default='New')
    facility_id = fields.Many2one('vanguard.facility', required=True)
    customer_id = fields.Many2one('vanguard.customer', string='Customer')
    sport_asset_id = fields.Many2one('vanguard.sport.asset', string='Sport Asset')
    court_number = fields.Integer('Court Number', default=1)
    sport_type = fields.Selection(SPORT_TYPES, required=True)
    booking_type = fields.Selection([
        ('member', 'Member'), ('student', 'Student'), ('walk_in', 'Walk-in'),
    ], default='walk_in')
    athlete_name = fields.Char(required=True)
    phone = fields.Char()
    booking_date = fields.Date(default=fields.Date.today, required=True)
    start_time = fields.Float('Start Time')
    end_time = fields.Float('End Time')
    price = fields.Float('Price (₹)', default=0.0)
    state = fields.Selection([
        ('draft', 'Pending'), ('confirmed', 'Confirmed'), ('cancelled', 'Cancelled'),
    ], default='confirmed', tracking=True)
    subscription_id = fields.Many2one('vanguard.customer.subscription', string='Subscription')
    notes = fields.Text()

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('vanguard.booking') or 'New'

        # Enforce: N free (member) slots per day where N = number of active subscriptions
        if vals.get('booking_type') == 'member' and vals.get('customer_id'):
            today = fields.Date.today()
            # Count free bookings already used today
            existing = self.search_count([
                ('customer_id', '=', vals['customer_id']),
                ('booking_type', '=', 'member'),
                ('booking_date', '=', vals.get('booking_date', str(today))),
                ('state', '!=', 'cancelled'),
            ])
            # Count how many active subscriptions this customer has
            active_sub_count = self.env['vanguard.customer.subscription'].search_count([
                ('customer_id', '=', vals['customer_id']),
                ('state', '=', 'active'),
                ('end_date', '>=', today),
            ])
            # Downgrade to walk-in only when free quota is exhausted
            if existing >= max(active_sub_count, 1):
                vals['booking_type'] = 'walk_in'
                if not vals.get('price'):
                    asset = self.env['vanguard.sport.asset'].search([
                        ('facility_id', '=', vals.get('facility_id')),
                        ('sport_type', '=', vals.get('sport_type')),
                    ], limit=1)
                    if asset:
                        vals['price'] = asset.price_per_hour

        return super().create(vals)




    def action_confirm(self):
        self.state = 'confirmed'

    def action_cancel(self):
        self.state = 'cancelled'

    @api.model
    def get_slots_for_date(self, facility_id, sport_type, date_str):
        """Return booked slots for a given sport on a date."""
        bookings = self.search([
            ('facility_id', '=', facility_id),
            ('sport_type', '=', sport_type),
            ('booking_date', '=', date_str),
            ('state', '!=', 'cancelled'),
        ])
        return [{
            'court_number': b.court_number,
            'start_time': b.start_time,
            'end_time': b.end_time,
            'athlete_name': b.athlete_name,
            'booking_type': b.booking_type,
            'state': b.state,
        } for b in bookings]
