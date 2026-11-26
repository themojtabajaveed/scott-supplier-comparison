"""Supported English questions -> narrow deterministic plan -> offline tool demo.
No live execution is exposed by this entrypoint until safety review.
"""
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scout.engine.planner import plan_question
from scout.engine.tool_loop import execute_plan
from scout.demo_fixtures import DemoBrowser,DemoLLM,sample_plan
p=argparse.ArgumentParser();p.add_argument('--question',required=True);p.add_argument('--demo',action='store_true');p.add_argument('--output-dir');a=p.parse_args()
plan=plan_question(a.question)
if not a.demo:print(json.dumps(plan.to_dict(),indent=2));sys.exit()
plan=sample_plan(plan) if plan.state=='ready' else plan  # reserved .example addresses, never real pages
r=execute_plan(plan,DemoBrowser(plan),DemoLLM(plan),sample=True);r['demo_fixture_only']=True;r['network_used']=False
if a.output_dir:
 # One new sub-folder per run, as the UI does; existing files are never overwritten.
 d=Path(a.output_dir)/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));d.mkdir(parents=True,exist_ok=False)
 (d/'result.json').write_text(json.dumps(r,indent=2));(d/'comparison.md').write_text('DEMO FIXTURES ONLY, not live facts.\n\n'+r.get('readable','Needs clarification: '+str(r.get('gaps'))));(d/'trace.md').write_text('# Offline tool trace\n\n'+'\n'.join(str(x) for x in r['trace']))
print(json.dumps({'state':r['state'],'demo_fixture_only':True,'network_used':False,'gaps':r.get('gaps',[]),'trace':r['trace'],'saved_to':str(d) if a.output_dir else None},indent=2))
