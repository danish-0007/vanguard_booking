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
    tutor_plan_ids = fields.One2many('vanguard.tutor.plan', 'tutor_id', string='Coaching Plans')

    @api.depends('student_ids')
    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)


class VanguardTutorPlan(models.Model):
    _name = 'vanguard.tutor.plan'
    _description = 'Tutor Coaching Tier Plan'
    _order = 'tier asc'

    tutor_id = fields.Many2one('vanguard.tutor', required=True, ondelete='cascade')
    facility_id = fields.Many2one('vanguard.facility', required=True, ondelete='cascade')
    sport_type = fields.Selection(SPORT_TYPES, required=True)

    tier = fields.Selection([
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
    ], required=True, default='beginner')

    price_per_month = fields.Float('Total Price/Month (₹)', required=True)
    max_batch = fields.Integer('Max Students per Batch', default=1)
    duration_days = fields.Integer('Duration (Days)', default=30)

    court_number = fields.Integer('Court Number', default=1)
    start_hour = fields.Integer('Start Hour (24h)', required=True)
    end_hour = fields.Integer('End Hour (24h)', required=True)
    session_days = fields.Char('Session Days', default='mon,tue,wed,thu,fri,sat')

    is_active = fields.Boolean('Active', default=True)

    # Auto-managed — never set manually from Flutter
    coaching_class_id = fields.Many2one(
        'vanguard.coaching.class', string='Linked Class',
        ondelete='set null', readonly=True)

    subscription_ids = fields.One2many(
        'vanguard.customer.subscription', 'tutor_plan_id', string='Enrolled Students')

    price_per_student = fields.Float(compute='_compute_per_student', store=False)
    enrolled_count = fields.Integer(compute='_compute_enrolled', store=False)
    slots_left = fields.Integer(compute='_compute_enrolled', store=False)

    @api.constrains('start_hour', 'end_hour')
    def _check_hours(self):
        for rec in self:
            if rec.start_hour >= rec.end_hour:
                raise models.ValidationError('Start hour must be earlier than end hour.')
            if not (0 <= rec.start_hour <= 23 and 1 <= rec.end_hour <= 24):
                raise models.ValidationError('Hours must be in range 0-23 (start) and 1-24 (end).')

    @api.model
    def dedupe_tutor_plans(self, facility_id):
        """Remove duplicate (tutor, tier) plans, keeping the newest. Returns count removed."""
        plans = self.search([
            ('facility_id', '=', facility_id), ('is_active', '=', True),
        ], order='id desc')
        seen = set()
        to_remove = self.browse()
        for p in plans:
            key = (p.tutor_id.id, p.tier)
            if key in seen:
                to_remove |= p
            else:
                seen.add(key)
        count = len(to_remove)
        if to_remove:
            to_remove.unlink()
        return count

    @api.depends('price_per_month', 'max_batch')
    def _compute_per_student(self):
        for rec in self:
            rec.price_per_student = (
                rec.price_per_month / rec.max_batch if rec.max_batch else rec.price_per_month)

    @api.depends('subscription_ids', 'subscription_ids.state')
    def _compute_enrolled(self):
        for rec in self:
            active = rec.subscription_ids.filtered(lambda s: s.state == 'active')
            rec.enrolled_count = len(active)
            rec.slots_left = max(0, rec.max_batch - rec.enrolled_count)

    def _coaching_class_vals(self):
        self.ensure_one()
        label = f'{self.tutor_id.name} ({self.tier.capitalize()})'
        return {
            'facility_id': self.facility_id.id,
            'name': label,
            'sport_type': self.sport_type,
            'court_number': self.court_number,
            'start_hour': self.start_hour,
            'end_hour': self.end_hour,
            'tutor_id': self.tutor_id.id,
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        CoachingClass = self.env['vanguard.coaching.class']
        for rec in records:
            cls = CoachingClass.create(rec._coaching_class_vals())
            rec.coaching_class_id = cls.id
        return records

    def write(self, vals):
        result = super().write(vals)
        schedule_fields = {'court_number', 'start_hour', 'end_hour', 'sport_type', 'tutor_id', 'tier'}
        if schedule_fields & set(vals.keys()):
            for rec in self:
                if rec.coaching_class_id:
                    rec.coaching_class_id.write(rec._coaching_class_vals())
                else:
                    cls = self.env['vanguard.coaching.class'].create(rec._coaching_class_vals())
                    rec.coaching_class_id = cls.id
        return result

    def unlink(self):
        classes = self.mapped('coaching_class_id')
        result = super().unlink()
        classes.unlink()
        return result


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
    hourly_price_ids = fields.One2many('vanguard.hourly.price', 'facility_id', string='Hourly Pricing Rules')
    booking_ids = fields.One2many('vanguard.booking', 'facility_id', string='Bookings')
    customer_ids = fields.One2many('vanguard.customer', 'facility_id', string='Customers')
    plan_ids = fields.One2many('vanguard.subscription.plan', 'facility_id', string='Subscription Plans')
    tutor_ids = fields.One2many('vanguard.tutor', 'facility_id', string='Tutors')

    total_bookings_today = fields.Integer(compute='_compute_stats', string='Bookings Today', store=False)
    total_customers = fields.Integer(compute='_compute_stats', string='Total Customers', store=False)
    revenue_mtd = fields.Float(compute='_compute_stats', string='Revenue MTD', store=False)
    total_assets = fields.Integer(compute='_compute_total_assets', string='Total Assets', store=False)

    @api.depends('booking_ids', 'booking_ids.booking_date', 'booking_ids.price', 'booking_ids.state', 
                 'customer_ids', 'customer_ids.subscription_ids.amount_paid', 'customer_ids.subscription_ids.start_date', 'customer_ids.subscription_ids.state')
    def _compute_stats(self):
        today = fields.Date.today()
        for rec in self:
            today_bookings = rec.booking_ids.filtered(
                lambda b: b.booking_date == today and b.state != 'cancelled')
            rec.total_bookings_today = len(today_bookings)
            rec.total_customers = len(rec.customer_ids)
            
            booking_rev = sum(rec.booking_ids.filtered(
                lambda b: b.booking_date and b.booking_date.month == today.month
                and b.state == 'confirmed'
            ).mapped('price'))

            subs = rec.customer_ids.subscription_ids.filtered(
                lambda s: s.start_date and s.start_date.month == today.month
                and s.state in ['active', 'expired']
            )
            sub_rev = sum(subs.mapped('amount_paid'))

            rec.revenue_mtd = booking_rev + sub_rev

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
    price_per_hour         = fields.Float('Walk-in Price/Hour (₹)', default=500.0)
    court_rate_per_month   = fields.Float('Tutor Court Rate/Month (₹)', default=0.0)


class VanguardHourlyPrice(models.Model):
    _name = 'vanguard.hourly.price'
    _description = 'Hourly Pricing Rule'
    _order = 'sport_type, start_hour asc'

    facility_id = fields.Many2one('vanguard.facility', required=True, ondelete='cascade')
    sport_type = fields.Selection(SPORT_TYPES, string='Sport Type', required=True)
    start_hour = fields.Float('Start Hour (24h)', required=True)
    end_hour = fields.Float('End Hour (24h)', required=True)
    price = fields.Float('Price/Hour (₹)', required=True)

    @api.constrains('start_hour', 'end_hour')
    def _check_hours(self):
        for rec in self:
            if rec.start_hour >= rec.end_hour:
                raise models.ValidationError('Start hour must be earlier than end hour.')
            if not (0.0 <= rec.start_hour <= 23.99 and 0.0 <= rec.end_hour <= 24.0):
                raise models.ValidationError('Hours must be in range 0.0 to 24.0.')


class VanguardSubscriptionPlan(models.Model):
    _name = 'vanguard.subscription.plan'
    _description = 'Subscription Plan'
    _order = 'price asc'

    name = fields.Char('Plan Name', required=True)
    facility_id = fields.Many2one('vanguard.facility', required=True)
    plan_type = fields.Selection([('member', 'Member'), ('student', 'Student')], default='member', required=True)
    sport_type = fields.Char('Sport Type(s)', default='all')
    duration_days = fields.Integer('Duration (Days)', default=30)
    price = fields.Float('Price (₹)', default=0.0)
    subscription_ids = fields.One2many('vanguard.customer.subscription', 'plan_id', string='Subscriptions')

    user_count = fields.Integer(compute='_compute_plan_stats', store=False)
    gross_yield = fields.Float(compute='_compute_plan_stats', store=False)
    renewals = fields.Integer(compute='_compute_plan_stats', store=False)

    @api.depends('subscription_ids', 'subscription_ids.state', 'subscription_ids.amount_paid', 'subscription_ids.is_renewal', 'subscription_ids.customer_id')
    def _compute_plan_stats(self):
        for rec in self:
            active = rec.subscription_ids.filtered(lambda s: s.state == 'active')
            rec.user_count = len(active.mapped('customer_id'))
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
        ('member', 'Member'), ('student', 'Student'), ('both', 'Member & Student'), ('walk_in', 'Walk-in'),
    ], required=True, default='member', tracking=True)
    sport_type = fields.Selection(SPORT_TYPES, string='Primary Sport')

    def _update_customer_type(self):
        for rec in self:
            active = rec.subscription_ids.filtered(lambda s: s.state == 'active')
            has_member = any(s.plan_id for s in active)
            has_student = any(s.tutor_plan_id for s in active)
            
            if has_member and has_student:
                new_type = 'both'
            elif has_member:
                new_type = 'member'
            elif has_student:
                new_type = 'student'
            else:
                if rec.subscription_ids:
                    last_sub = rec.subscription_ids[0]
                    if last_sub.plan_id:
                        new_type = 'member'
                    elif last_sub.tutor_plan_id:
                        new_type = 'student'
                    else:
                        new_type = 'walk_in'
                else:
                    new_type = 'walk_in'
            
            if rec.customer_type != new_type:
                rec.write({'customer_type': new_type})

    # Student-only
    coaching_level = fields.Selection([
        ('beginner', 'Beginner'), ('intermediate', 'Intermediate'), ('advanced', 'Advanced'),
    ], string='Coaching Level')
    coach_assigned = fields.Boolean('Coach Assigned', default=False)
    court_assignment = fields.Char('Court Assignment')
    tutor_id = fields.Many2one('vanguard.tutor', string='Assigned Tutor', domain="[('facility_id', '=', facility_id)]")

    subscription_ids = fields.One2many('vanguard.customer.subscription', 'customer_id', string='Subscriptions')
    booking_ids = fields.One2many('vanguard.booking', 'customer_id', string='Bookings')

    active_plan_name = fields.Char(compute='_compute_active_sub', store=False)
    active_plan_amount = fields.Float(compute='_compute_active_sub', store=False)
    is_expired = fields.Boolean(compute='_compute_active_sub', store=False)

    @api.depends('subscription_ids', 'subscription_ids.state', 'subscription_ids.plan_id',
                 'subscription_ids.tutor_plan_id', 'subscription_ids.coaching_level', 'subscription_ids.end_date')
    def _compute_active_sub(self):
        today = fields.Date.today()
        for rec in self:
            active = rec.subscription_ids.filtered(lambda s: s.state == 'active' and (not s.end_date or s.end_date >= today))
            if active:
                sub = active[0]
                rec.active_plan_name = sub.display_label
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
    tutor_plan_id = fields.Many2one('vanguard.tutor.plan', string='Tutor Plan', ondelete='set null')
    coaching_level = fields.Selection([
        ('beginner', 'Beginner'), ('intermediate', 'Intermediate'), ('advanced', 'Advanced'),
    ], string='Coaching Level')
    sport_type = fields.Char('Sport', default='all')
    start_date = fields.Date('Start Date', default=fields.Date.today)
    end_date = fields.Date('End Date', compute='_compute_end_date', store=True)
    amount_paid = fields.Float('Amount Paid (₹)')
    payment_mode = fields.Selection(PAYMENT_MODES, default='cash')
    receipt_date = fields.Date('Monthly Receipt Date')
    state = fields.Selection([
        ('active', 'Active'), ('expired', 'Expired'), ('cancelled', 'Cancelled'),
    ], default='active', tracking=True)
    is_renewal = fields.Boolean('Is Renewal', default=False)

    # Permanent / auto-booking recurrence details
    booking_recurrence = fields.Selection([
        ('daily', 'Book Daily'),
        ('permanent', 'Permanent Slot'),
    ], default='daily', string='Booking Recurrence')
    preferred_sport = fields.Selection(SPORT_TYPES, string='Preferred Sport')
    preferred_court = fields.Integer('Preferred Court')
    preferred_hour = fields.Integer('Preferred Hour (24h)')

    display_label = fields.Char(compute='_compute_display_label', store=False)

    @api.constrains('preferred_court', 'preferred_hour', 'preferred_sport', 'state')
    def _check_preferred_slot(self):
        for rec in self:
            if rec.state != 'active' or rec.booking_recurrence not in ['daily', 'permanent']:
                continue
            if not rec.preferred_court or not rec.preferred_hour:
                continue
            
            # Check overlap with coaching classes
            classes = self.env['vanguard.coaching.class'].search([
                ('facility_id', '=', rec.customer_id.facility_id.id),
                ('sport_type', '=', rec.preferred_sport),
                ('court_number', '=', rec.preferred_court),
                ('start_hour', '<=', rec.preferred_hour),
                ('end_hour', '>', rec.preferred_hour),
            ])
            if classes:
                raise models.ValidationError(
                    f"Preferred court {rec.preferred_court} at {rec.preferred_hour}:00 is reserved for Coaching Class '{classes[0].name}'."
                )
            
            # Check overlap with other active permanent subscriptions
            other_subs = self.search([
                ('id', '!=', rec.id),
                ('customer_id.facility_id', '=', rec.customer_id.facility_id.id),
                ('preferred_sport', '=', rec.preferred_sport),
                ('preferred_court', '=', rec.preferred_court),
                ('preferred_hour', '=', rec.preferred_hour),
                ('state', '=', 'active'),
                ('booking_recurrence', 'in', ['daily', 'permanent']),
            ])
            if other_subs:
                raise models.ValidationError(
                    f"Preferred court {rec.preferred_court} at {rec.preferred_hour}:00 is already reserved by {other_subs[0].customer_id.name}."
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.customer_id:
                rec.customer_id._update_customer_type()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ['state', 'plan_id', 'tutor_plan_id', 'customer_id']):
            for rec in self:
                if rec.customer_id:
                    rec.customer_id._update_customer_type()
        return res

    def unlink(self):
        customers = self.mapped('customer_id')
        res = super().unlink()
        for cust in customers:
            if cust.exists():
                cust._update_customer_type()
        return res

    @api.depends('start_date', 'plan_id.duration_days', 'tutor_plan_id.duration_days')
    def _compute_end_date(self):
        for rec in self:
            days = None
            if rec.plan_id and rec.plan_id.duration_days:
                days = rec.plan_id.duration_days
            elif rec.tutor_plan_id and rec.tutor_plan_id.duration_days:
                days = rec.tutor_plan_id.duration_days
            rec.end_date = (rec.start_date + timedelta(days=days)) if rec.start_date and days else rec.start_date

    @api.depends('plan_id', 'plan_id.name', 'tutor_plan_id', 'coaching_level')
    def _compute_display_label(self):
        tier_map = {'beginner': 'Beginner', 'intermediate': 'Intermediate', 'advanced': 'Advanced'}
        for rec in self:
            if rec.plan_id:
                rec.display_label = rec.plan_id.name
            elif rec.tutor_plan_id:
                tier = tier_map.get(rec.coaching_level, '')
                coach = rec.tutor_plan_id.tutor_id.name
                rec.display_label = f'Coaching · {tier} ({coach})'.strip()
            else:
                rec.display_label = 'Plan'

    @api.model
    def enroll_tutor_plan(self, facility_id, tutor_plan_id, phone, name,
                          amount_paid, payment_mode):
        """Atomic coaching enrollment. Find/create student customer, guard against
        duplicates & full batches, link student to tutor, reserve the slot."""
        plan = self.env['vanguard.tutor.plan'].browse(tutor_plan_id)
        if not plan.exists():
            raise models.ValidationError('Coaching plan not found.')

        # Find or create the customer for this facility
        Customer = self.env['vanguard.customer']
        customer = Customer.search([
            ('phone', '=', phone), ('facility_id', '=', facility_id),
        ], limit=1)
        if not customer:
            customer = Customer.create({
                'name': (name or phone).upper(),
                'phone': phone,
                'facility_id': facility_id,
            })

        # Guard: no duplicate active enrollment in the same plan
        dup = self.search_count([
            ('customer_id', '=', customer.id),
            ('tutor_plan_id', '=', tutor_plan_id),
            ('state', '=', 'active'),
        ])
        if dup:
            raise models.ValidationError('Already enrolled in this coaching plan.')

        # Guard: batch full
        if plan.slots_left <= 0:
            raise models.ValidationError('This batch is full.')

        # Make this customer a student of this tutor (drives student_count + owner list)
        customer.write({
            'customer_type': 'student',
            'facility_id': plan.facility_id.id,
            'tutor_id': plan.tutor_id.id,
            'coaching_level': plan.tier,
            'coach_assigned': True,
            'sport_type': plan.sport_type,
        })

        # Safety: ensure the slot-blocking coaching class exists
        if not plan.coaching_class_id:
            cls = self.env['vanguard.coaching.class'].create(plan._coaching_class_vals())
            plan.coaching_class_id = cls.id

        sub = self.create({
            'customer_id': customer.id,
            'tutor_plan_id': tutor_plan_id,
            'coaching_level': plan.tier,
            'amount_paid': amount_paid,
            'payment_mode': payment_mode,
            'sport_type': plan.sport_type,
            'state': 'active',
            'start_date': fields.Date.today(),
            'booking_recurrence': 'permanent',
            'preferred_sport': plan.sport_type,
            'preferred_court': plan.court_number,
            'preferred_hour': plan.start_hour,
        })
        return sub.id


class VanguardCoachingClass(models.Model):
    _name = 'vanguard.coaching.class'
    _description = 'Student Coaching Class'
    _order = 'start_hour asc'

    facility_id = fields.Many2one('vanguard.facility', required=True, ondelete='cascade')
    name = fields.Char('Class Name', required=True)
    sport_type = fields.Selection(SPORT_TYPES, required=True)
    court_number = fields.Integer('Court Number', default=1)
    start_hour = fields.Integer('Start Hour (24h)', required=True)
    end_hour = fields.Integer('End Hour (24h)', required=True)
    tutor_id = fields.Many2one('vanguard.tutor', string='Coach', ondelete='set null')


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

    @api.constrains('facility_id', 'sport_type', 'court_number', 'booking_date', 'start_time', 'end_time', 'state')
    def _check_booking_overlap(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            # 1. Overlap with other bookings
            overlap_bookings = self.search([
                ('id', '!=', rec.id),
                ('facility_id', '=', rec.facility_id.id),
                ('sport_type', '=', rec.sport_type),
                ('court_number', '=', rec.court_number),
                ('booking_date', '=', rec.booking_date),
                ('state', '!=', 'cancelled'),
                ('start_time', '<', rec.end_time),
                ('end_time', '>', rec.start_time),
            ])
            if overlap_bookings:
                raise models.ValidationError(
                    f"Court {rec.court_number} is already booked for this time block (overlap with {overlap_bookings[0].athlete_name})."
                )
            
            # 2. Overlap with coaching classes (vanguard.coaching.class)
            classes = self.env['vanguard.coaching.class'].search([
                ('facility_id', '=', rec.facility_id.id),
                ('sport_type', '=', rec.sport_type),
                ('court_number', '=', rec.court_number),
                ('start_hour', '<', rec.end_time),
                ('end_hour', '>', rec.start_time),
            ])
            if classes:
                raise models.ValidationError(
                    f"Court {rec.court_number} is reserved for Coaching Class '{classes[0].name}' during this time."
                )

    def _calculate_booking_price(self, facility_id, sport_type, start_time, end_time):
        """
        Calculate total price based on hourly pricing rules.
        If booking spans multiple rules, it calculates proportional cost for each hour/fraction.
        If no rules match a time slot, falls back to the default price_per_hour on sport.asset.
        """
        if not facility_id or not sport_type or start_time is None or end_time is None:
            return 0.0
        
        # Get rules sorted by start_hour
        rules = self.env['vanguard.hourly.price'].search([
            ('facility_id', '=', facility_id),
            ('sport_type', '=', sport_type)
        ], order='start_hour asc')

        # Get fallback price from asset
        asset = self.env['vanguard.sport.asset'].search([
            ('facility_id', '=', facility_id),
            ('sport_type', '=', sport_type),
        ], limit=1)
        fallback_rate = asset.price_per_hour if asset else 0.0

        total_price = 0.0
        current_time = start_time
        
        while current_time < end_time:
            # Find rule covering current_time
            matching_rule = False
            for rule in rules:
                if rule.start_hour <= current_time < rule.end_hour:
                    matching_rule = rule
                    break
            
            if matching_rule:
                # Calculate how much of this rule's block we consume
                segment_end = min(end_time, matching_rule.end_hour)
                duration = segment_end - current_time
                total_price += duration * matching_rule.price
                current_time = segment_end
            else:
                # No rule matches. Use fallback_rate until next rule start or end_time
                next_rule_start = end_time
                for rule in rules:
                    if rule.start_hour > current_time:
                        next_rule_start = min(next_rule_start, rule.start_hour)
                
                duration = next_rule_start - current_time
                total_price += duration * fallback_rate
                current_time = next_rule_start
                
        return total_price

    @api.onchange('facility_id', 'sport_type', 'start_time', 'end_time', 'booking_type')
    def _onchange_booking_details(self):
        for rec in self:
            if rec.booking_type != 'member':
                rec.price = rec._calculate_booking_price(
                    rec.facility_id.id,
                    rec.sport_type,
                    rec.start_time,
                    rec.end_time
                )

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('vanguard.booking') or 'New'

        # Enforce: N free (member) slots per day where N = number of active subscriptions
        if vals.get('booking_type') == 'member' and vals.get('customer_id'):
            today = fields.Date.today()
            # Count any bookings already used today (confirmed or draft)
            existing = self.search_count([
                ('customer_id', '=', vals['customer_id']),
                ('booking_date', '=', vals.get('booking_date', str(today))),
                ('state', '!=', 'cancelled'),
            ])
            # Count how many active free-choice subscriptions this customer has
            active_sub_count = self.env['vanguard.customer.subscription'].search_count([
                ('customer_id', '=', vals['customer_id']),
                ('state', '=', 'active'),
                ('end_date', '>=', today),
                ('booking_recurrence', '!=', 'permanent'),
            ])
            # Downgrade to walk-in only when free quota is exhausted
            if active_sub_count == 0 or existing >= active_sub_count:
                vals['booking_type'] = 'walk_in'

        # Calculate price if not provided, or is 0.0, and not a member booking
        if vals.get('booking_type') != 'member' and not vals.get('price'):
            vals['price'] = self._calculate_booking_price(
                vals.get('facility_id'),
                vals.get('sport_type'),
                vals.get('start_time'),
                vals.get('end_time')
            )

        return super().create(vals)

    def write(self, vals):
        res = super().write(vals)
        # Recalculate price if any relevant fields are changed and price is not explicitly set in vals
        if any(field in vals for field in ['facility_id', 'sport_type', 'start_time', 'end_time', 'booking_type']) and 'price' not in vals:
            for rec in self:
                if rec.booking_type != 'member':
                    rec.write({
                        'price': rec._calculate_booking_price(
                            rec.facility_id.id,
                            rec.sport_type,
                            rec.start_time,
                            rec.end_time
                        )
                    })
        return res




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
