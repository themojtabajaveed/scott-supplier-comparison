"""No browser, network or key. Shows missing conditions and disagreement output."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout.engine.atomic import validate_atoms,merge_evidence,assess
source='Charge per box: £5.10 ex VAT (£6.12 inc. VAT)'
checked=validate_atoms({'amount':{'value':'£6.12','quote':source},'box_count':{'value':'one 16kg sack','quote':source}},['amount','box_count'],source,'https://fixture.example/shipping')
print('DEMO ONLY: synthetic offline evidence, not live supplier research')
print(json.dumps(checked,indent=2))
evidence={};merge_evidence(evidence,{'amount':{'value':'£21.30','source_url':'https://fixture.example/page'}});merge_evidence(evidence,{'amount':{'value':'£22.10','source_url':'https://fixture.example/data'}})
print(json.dumps(assess(evidence,{'amount':'price'}),indent=2))
