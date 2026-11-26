"""Supplier comparison workflow: config only. Fields + checklist + source list.

Bounded supporting-page navigation and source quotes are shared engine behavior.
"""

WORKFLOW = {
    "name": "supplier",
    "question": "Compare cited product prices and delivery conditions for one 16kg sack of strong white bread flour. Preserve conflicts and unknowns; do not select cheapest or invent a delivered total.",
    "fields": {
        "product_price": "Price of the matched 16kg strong white bread flour sack, with currency.",
        "delivery_charge": "Standard delivery charge for an order of one sack, with currency.",
        "free_delivery_threshold": "Order value above which standard delivery is free, if stated.",
        "delivery_time": "Stated dispatch or delivery time.",
        "delivery_geography": "Where the seller delivers (countries/regions), as stated.",
    },
    "required": ["product_price", "delivery_charge"],
    "research_fields": ["product_price", "delivery_charge", "free_delivery_threshold", "delivery_time", "delivery_geography"],
    "sites": [
        # delivery_page: the same-site page the reference file's delivery facts were read from (27 Oct 2026).
        # Read only when the product page offers no delivery link and delivery details are still missing.
        # offer_binding: the reviewed product path + SKU + pack a structured offer record must match before a
        # price is shown as a headline (scout/engine/offers.py, offer-v1). SKUs and paths were taken from
        # reviewed public-page snapshots of November 2026; a changed SKU or path leaves the price
        # unconfirmed rather than matched by name.
        {"name": "wessex_mill",
         "url": "https://wessexmill.co.uk/product/strong-white-bread-flour-16kg-17/",
         "delivery_page": "https://wessexmill.co.uk/delivery/",
         "offer_binding": {"product_path": "/product/strong-white-bread-flour-16kg-17", "sku": "WXSTWT16",
                           "pack": "16kg", "single_offer": True}},
        {"name": "cotswold",
         # matched product page; handle read from the store's own /products.json on 27 Oct 2026
         "url": "https://cotswoldflour.com/products/matthews-churchill-premium-white-bread-flour-16kg",
         "delivery_page": "https://cotswoldflour.com/policies/shipping-policy",
         "offer_binding": {"product_path": "/products/matthews-churchill-premium-white-bread-flour-16kg",
                           "sku": "CH16", "pack": "16kg"}},
        {"name": "shipton_mill",
         "url": "https://www.shipton-mill.com/products/canadian-strong-white-bread-flour",
         "variant_option": "16kg",  # pack-size dropdown; 16kg price renders after selection
         "delivery_page": "https://www.shipton-mill.com/pages/faq-ordering-delivery",
         "offer_binding": {"product_path": "/products/canadian-strong-white-bread-flour",
                           "sku": "F.12.6%CAN/OP.16", "pack": "16kg",
                           # its page script's productVariants list held a different 16kg price (GBP 19.00)
                           # than its JSON-LD (GBP 22.80) in November 2026; never confirm without reading it
                           "required_channels": ["inline_script"]}},
    ],
}

# Wholemeal is supported on Wessex only; the planner substitutes this site for wholemeal questions.
WHOLEMEAL_SITE = {"name": "wessex_wholemeal",
                  "url": "https://wessexmill.co.uk/product/wholemeal-bread-flour-16kg-17/"}

# Atomic mode is opt-in while regression and live evaluation are in progress.
ATOMIC_FIELDS = {'product_price': {'amount': 'Exact price of matched pack', 'currency': 'Explicit currency identifier', 'variant': 'Exact pack-size label'}, 'delivery_charge': {'amount': 'Exact delivery charge', 'basis': 'Per box/parcel/order basis', 'vat': 'Explicit VAT basis', 'zone': 'Geography/zone condition', 'packing': 'Explicit product quantity per box, absent stays unknown', 'surcharge': 'Explicit surcharge and applicable zone, absent stays unknown', 'order_condition': 'Order value or quantity condition under which this delivery charge applies, quoted in the same sentence as the charge; absent stays unknown'}, 'free_delivery_threshold': {'amount': 'Exact threshold', 'comparison': 'Over or inclusive threshold', 'zone': 'Eligible zones', 'weight_limit': 'Weight limit if any; absent stays unknown', 'discount_condition': 'Threshold before or after discounts, if stated', 'exceptions': 'Exceptions to free shipping'}, 'delivery_time': {'dispatch': 'Dispatch timing', 'arrival': 'Arrival timing'}, 'delivery_geography': {'included': 'Included area', 'excluded': 'Excluded area', 'surcharge': 'Remote-area surcharge conditions'}}