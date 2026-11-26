"""Gemini client with explicit free-project gate and durable per-attempt reservations.
Single-thread-only client. Local limits cannot establish billing status. A verified project/key binding is
required independently before live use; there is no model or paid fallback.
"""
import json, urllib.request, time, hashlib

ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:{op}'
class BudgetExceeded(RuntimeError): pass

class GeminiFree:
    def __init__(self, api_key, model='gemini-3.5-flash-lite', max_calls=15,
                 max_input_tokens=20000, max_output_tokens=8000,
                 max_output_per_call=1024, transport=None, ledger_path=None,
                 free_project_verified=False):
        if not transport and (not free_project_verified or not ledger_path):
            raise RuntimeError('Live use requires verified free-project/key binding and a ledger path')
        self.api_key, self.model = api_key, model
        self.caps={'calls':max_calls,'input':max_input_tokens,'output':max_output_tokens}
        self.spent={'calls':0,'input':0,'output':0}
        self.max_output_per_call=max_output_per_call
        self._transport, self.ledger_path=transport,ledger_path

    def _record(self, **event):
        if self.ledger_path:
            with open(self.ledger_path,'a',encoding='utf-8') as f:
                f.write(json.dumps(dict(ts=time.time(),model=self.model,**event))+'\n')
                f.flush()
                import os
                os.fsync(f.fileno())

    def _post(self, op, body):
        if self._transport: return self._transport(op,body)
        req=urllib.request.Request(ENDPOINT.format(model=self.model,op=op),
            data=json.dumps(body).encode(),headers={'Content-Type':'application/json','x-goog-api-key':self.api_key})
        with urllib.request.urlopen(req,timeout=45) as r: return json.loads(r.read())

    def _charge(self, inputs, outputs):
        after={'calls':self.spent['calls']+1,'input':self.spent['input']+inputs,'output':self.spent['output']+outputs}
        for k,cap in self.caps.items():
            if after[k]>cap: raise BudgetExceeded(f'{k}: {after[k]} > cap {cap}')
        return after

    def generate_json(self,prompt):
        return self._generate(prompt,None)

    def generate_structured(self,prompt,response_schema):
        return self._generate(prompt,response_schema)

    def _generate(self,prompt,response_schema):
        # countTokens is a metadata preflight, never a generation probe.
        self._charge(0,self.max_output_per_call)
        contents=[{'parts':[{'text':prompt}]}]
        generation={'temperature':0,'responseMimeType':'application/json',
                    'maxOutputTokens':self.max_output_per_call}
        if response_schema is not None:
            generation['responseJsonSchema']=response_schema
        request={'model':'models/'+self.model,'contents':contents,'generationConfig':generation}
        canonical=json.dumps(request,sort_keys=True)
        try:
            count=self._post('countTokens',{'generateContentRequest':request}).get('totalTokens')
            if not isinstance(count,int) or count<0: raise RuntimeError('Unverifiable token preflight')
        except Exception as e:
            self._record(kind='preflight_error',error_type=type(e).__name__)
            raise
        if json.dumps(request,sort_keys=True)!=canonical:
            raise RuntimeError('Full request changed during preflight')
        reserved=self._charge(count,self.max_output_per_call)
        self._record(kind='reserved',input_tokens=count,output_tokens=self.max_output_per_call,
                     cumulative=reserved,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
        self.spent=reserved # consume before transmission; failures retain reservation
        try:
            resp=self._post('generateContent',request)
            usage=resp.get('usageMetadata',{})
            actual_in=usage.get('promptTokenCount')
            actual_out=(usage.get('candidatesTokenCount',0)+usage.get('thoughtsTokenCount',0)) if 'candidatesTokenCount' in usage else None
            self._record(kind='response',usage=usage)
            if isinstance(actual_in,int) and isinstance(actual_out,int) and actual_in<=count and actual_out<=self.max_output_per_call:
                self.spent['input']-=count-actual_in
                self.spent['output']-=self.max_output_per_call-actual_out
                self._record(kind='reconciled',released_input=count-actual_in,
                             released_output=self.max_output_per_call-actual_out,cumulative=self.spent)
            elif isinstance(actual_in,int) and isinstance(actual_out,int):
                raise BudgetExceeded('Provider usage exceeded preflight/reservation; stop')
            text=''.join(p.get('text','') for p in resp['candidates'][0]['content']['parts'])
            return json.loads(text)
        except Exception as e:
            self._record(kind='failed',error_type=type(e).__name__,reserved_totals=self.spent)
            raise
