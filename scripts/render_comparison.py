"""Turn actual atomic result JSON into a cited readable Markdown comparison.
Usage: python3 -S scripts/render_comparison.py result.json > comparison.md
"""
import json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout.engine.comparison import render_comparison,bound_delivery_assessment
obj=json.loads(Path(sys.argv[1]).read_text());rows=obj['rows'] if isinstance(obj,dict) else obj
for row in rows:
 if 'delivery_charge' in row['atomic_fields']:bound_delivery_assessment(row['atomic_fields']['delivery_charge'])
# Only a live run's own start time dates the evidence; other files say the date is not recorded.
started=obj.get('live',{}).get('started') if isinstance(obj,dict) and isinstance(obj.get('live'),dict) else None
as_of=None
if started:
 d=datetime.fromisoformat(started);as_of='%d %s %d'%(d.day,d.strftime('%B'),d.year)
print(render_comparison(rows,'Scott evidence comparison',as_of=as_of,sample=bool(isinstance(obj,dict) and obj.get('demo_fixture_only'))))
