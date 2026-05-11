# -*- coding: utf-8 -*-
# from odoo import http


# class VanguardBooking(http.Controller):
#     @http.route('/vanguard_booking/vanguard_booking', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/vanguard_booking/vanguard_booking/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('vanguard_booking.listing', {
#             'root': '/vanguard_booking/vanguard_booking',
#             'objects': http.request.env['vanguard_booking.vanguard_booking'].search([]),
#         })

#     @http.route('/vanguard_booking/vanguard_booking/objects/<model("vanguard_booking.vanguard_booking"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('vanguard_booking.object', {
#             'object': obj
#         })
