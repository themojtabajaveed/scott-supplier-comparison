"""SYNTHETIC page bodies for the public test suite (25 November 2026).

Every text here is INVENTED for invented mills on reserved .example addresses. They are synthetic derivatives: they
keep the STRUCTURE the tests need (a standard charge with a starred free-delivery threshold, per-parcel regional
charges listed by zone, a repeated banner, a sentence with "or" and "may", a dispatch-only line), but none of the
wording, amounts or zones is a rewrite of any real supplier's page.
"""
import hashlib

# -- Demo Mill product page (stands in for a product page with delivery terms) --------------------------------------
P1 = 'Standard delivery costs £3.80, and orders above £45* ship free at the standard rate (terms apply)'
P2 = '£6.40 per parcel to:\nNorth Coast Isles\nWestern Highlands Zone\nFar Valley District'
P3 = '£8.20 per parcel to:\nHarbour Island\nOuter Reef Islands'
P4 = ('Regional variations apply to some areas:\n\nOrders above £45 travel free at the base rate but will add a '
      'surcharge as well* (terms apply)')
BANNER = 'Free standard delivery on orders above £45* (terms apply)'
IRRELEVANT = 'A flour our bakers keep coming back for.'
PRODUCT_BODY = '\n'.join([
    BANNER, 'Demo Mill', 'Home', 'Bread flour', 'Demo Strong Flour 16kg', IRRELEVANT, '£12.34',
    'Delivery and returns', P1, '', P2, '', P3, '', P4, '', 'Dispatch usually takes two working days.', BANNER])

# -- Demo Mill delivery page ---------------------------------------------------------------------------------------
D7 = ('An order containing a sack or bulk item or weighing over 20kg may be sent as several parcels on '
      'different days.')
DELIVERY_BODY = '\n'.join(['Demo Mill delivery information', 'We deliver to addresses on the mainland.', D7,
                           'Delivery charges are shown at checkout.'])

# -- Demo Mill Two product page (dispatch-only delivery wording) ---------------------------------------------------
DISPATCH = '- Orders leave the mill within 3-5 working days'
DISPATCH_BODY = '\n'.join(['Demo Mill Two', 'Demo Canadian-style Flour 16kg', '£15.67', 'Delivery', DISPATCH,
                           'Questions? Use the contact form.'])

PRODUCT_URL = 'https://demo-mill.example/product/demo-strong-flour-16kg/'
DELIVERY_URL = 'https://demo-mill.example/delivery/'
DISPATCH_URL = 'https://demo-mill-two.example/products/demo-canadian-flour'
PRODUCT_BODY_SHA = hashlib.sha256(PRODUCT_BODY.encode('utf-8')).hexdigest()
