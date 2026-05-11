{
    'name': 'Vanguard Booking',
    'version': '1.2',
    'category': 'Services',
    'summary': 'Complete sport facility management — Facilities, Assets, Customers, Subscriptions, Bookings',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/booking_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
