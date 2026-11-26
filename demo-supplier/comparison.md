DEMO FIXTURES ONLY, not live facts.

# Scott planned research

Sample data invented for this demo, not evidence read from any website. Literal evidence is not a semantic proof or exhaustive extraction. No cheapest/model-quality verdict.

## demo_mill_one

Input: Compare strong white bread flour 16kg delivery conditions

| Field | Observed claims | Status / unknowns |
| --- | --- | --- |
| product_price | amount: £12.34 ([source](https://demo-mill-one.sample.example/product))<br>currency: £ ([source](https://demo-mill-one.sample.example/product))<br>variant: 16kg ([source](https://demo-mill-one.sample.example/product)) | literal_components_present |
| delivery_charge | amount: £5.67 ([source](https://demo-mill-one.sample.example/delivery))<br>basis: per order ([source](https://demo-mill-one.sample.example/delivery))<br>zone: UK ([source](https://demo-mill-one.sample.example/delivery)) | incomplete; missing: vat, packing, surcharge, order_condition |
| free_delivery_threshold | amount: £60.00 ([source](https://demo-mill-one.sample.example/delivery))<br>comparison: over ([source](https://demo-mill-one.sample.example/delivery))<br>zone: UK ([source](https://demo-mill-one.sample.example/delivery)) | incomplete; missing: weight_limit, discount_condition, exceptions |
| delivery_time | No accepted claims | incomplete; missing: dispatch, arrival |
| delivery_geography | No accepted claims | incomplete; missing: included, excluded, surcharge |

### Evidence trail

- product_price.amount: "Demo Strong Flour 16kg sack £12.34" ([source](https://demo-mill-one.sample.example/product))
- product_price.currency: "Demo Strong Flour 16kg sack £12.34" ([source](https://demo-mill-one.sample.example/product))
- product_price.variant: "Demo Strong Flour 16kg sack £12.34" ([source](https://demo-mill-one.sample.example/product))
- delivery_charge.amount: "Standard UK delivery is £5.67 per order" ([source](https://demo-mill-one.sample.example/delivery))
- delivery_charge.basis: "Standard UK delivery is £5.67 per order" ([source](https://demo-mill-one.sample.example/delivery))
- delivery_charge.zone: "Standard UK delivery is £5.67 per order" ([source](https://demo-mill-one.sample.example/delivery))
- free_delivery_threshold.amount: "Free standard UK delivery on orders over £60.00" ([source](https://demo-mill-one.sample.example/delivery))
- free_delivery_threshold.comparison: "Free standard UK delivery on orders over £60.00" ([source](https://demo-mill-one.sample.example/delivery))
- free_delivery_threshold.zone: "Free standard UK delivery on orders over £60.00" ([source](https://demo-mill-one.sample.example/delivery))

Human review required. Unknowns are final output for this bounded run, not a promise of further research.

## demo_mill_two

Input: Compare strong white bread flour 16kg delivery conditions

| Field | Observed claims | Status / unknowns |
| --- | --- | --- |
| product_price | amount: £45.67 ([source](https://demo-mill-two.sample.example/product))<br>currency: £ ([source](https://demo-mill-two.sample.example/product))<br>variant: 16kg ([source](https://demo-mill-two.sample.example/product)) | literal_components_present |
| delivery_charge | No accepted claims | incomplete; missing: amount, basis, vat, zone, packing, surcharge, order_condition |
| free_delivery_threshold | No accepted claims | incomplete; missing: amount, comparison, zone, weight_limit, discount_condition, exceptions |
| delivery_time | No accepted claims | incomplete; missing: dispatch, arrival |
| delivery_geography | No accepted claims | incomplete; missing: included, excluded, surcharge |

### Evidence trail

- product_price.amount: "Demo Premium Flour 16kg sack £45.67" ([source](https://demo-mill-two.sample.example/product))
- product_price.currency: "Demo Premium Flour 16kg sack £45.67" ([source](https://demo-mill-two.sample.example/product))
- product_price.variant: "Demo Premium Flour 16kg sack £45.67" ([source](https://demo-mill-two.sample.example/product))

Human review required. Unknowns are final output for this bounded run, not a promise of further research.

## demo_mill_three

Input: Compare strong white bread flour 16kg delivery conditions

| Field | Observed claims | Status / unknowns |
| --- | --- | --- |
| product_price | amount: £23.45 ([source](https://demo-mill-three.sample.example/product))<br>amount: 24.56 ([source](https://demo-mill-three.sample.example/product.js))<br>currency: £ ([source](https://demo-mill-three.sample.example/product))<br>variant: 16kg ([source](https://demo-mill-three.sample.example/product.js)) | possible_numeric_disagreement; conflicting values retained, no winner selected |
| delivery_charge | No accepted claims | incomplete; missing: amount, basis, vat, zone, packing, surcharge, order_condition |
| free_delivery_threshold | No accepted claims | incomplete; missing: amount, comparison, zone, weight_limit, discount_condition, exceptions |
| delivery_time | No accepted claims | incomplete; missing: dispatch, arrival |
| delivery_geography | No accepted claims | incomplete; missing: included, excluded, surcharge |

### Evidence trail

- product_price.amount: "Demo Canadian-style Flour £23.45" ([source](https://demo-mill-three.sample.example/product))
- product_price.amount: "16kg | 24.56 | available=False" ([source](https://demo-mill-three.sample.example/product.js))
- product_price.currency: "Demo Canadian-style Flour £23.45" ([source](https://demo-mill-three.sample.example/product))
- product_price.variant: "16kg | 24.56 | available=False" ([source](https://demo-mill-three.sample.example/product.js))

Human review required. Unknowns are final output for this bounded run, not a promise of further research.
