"""Opt-in fresh Gemini evaluation of synthetic inputs, without DB/Sheet writes.

Each document gets an isolated empty ledger. Eligibility is not acceptance.
Model input contains only document text, never manifest expectations/references.
"""
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone
from hashlib import sha256
import argparse,csv,json,sys,time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.extraction import GeminiExtractor,ExtractionError,read_document
from app.procurement import parse_reference
from app.rules import evaluate
from app.decision_view import explain_decision


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-model',action='store_true',help='Send synthetic page text to the configured Gemini provider')
    parser.add_argument('--output',type=Path,default=ROOT/'data/layout-evaluation.json')
    args=parser.parse_args()
    if not args.live_model:parser.error('This evaluator requires the explicit --live-model option; it never supplies canned extraction.')
    settings=Settings();extractor=GeminiExtractor(settings.gemini_api_key.get_secret_value(),settings.gemini_model)
    parsed=parse_reference({p.stem:list(csv.reader(p.open())) for p in (ROOT/'tests/reference_data').glob('*.csv')})
    reference={'id':'isolated-evaluation-reference','fresh':True,**{k:[asdict(x) for x in getattr(parsed,k)] for k in ('vendors','pos','lines','rules')}}
    directory=ROOT/'tests/fixtures/layouts';entries=json.loads((directory/'manifest.json').read_text())['fixtures']
    report={'scope':'FRESH_PROVIDER_EXTRACTION_LOCAL_SYNTHETIC_REFERENCE_NO_DB_OR_SHEET_WRITES','recorded_at_utc':datetime.now(timezone.utc).isoformat(),'model':settings.gemini_model,'results':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for entry in entries:
        start=time.perf_counter();row={'file':entry['file'],'sha256':entry['sha256'],'provider_attempted':False,'financial_commitment':'not_recorded'}
        try:
            raw=(directory/entry['file']).read_bytes();assert sha256(raw).hexdigest()==entry['sha256']
            document=read_document(raw,entry['mime']);row['provider_attempted']=True
            candidate=extractor.extract(document)
            decision=evaluate(candidate,document,reference,{'accepted_amounts':{},'accepted_quantities':{},'duplicate':False})
            view={'submission':{'status':'needs_review'},'validation':{'checks':decision.checks,'verdict':decision.verdict,'acceptance_mode':decision.acceptance_mode,'po_candidates':decision.po_candidates},'revision':decision.revision}
            row.update(outcome=decision.verdict,candidate=candidate.model_dump(mode='json'),checks=decision.checks,explanation=explain_decision(view),source_methods=[p.method for p in document.pages])
        except ExtractionError as e:
            row.update(outcome='processing_failed',error=e.code,next_action='Inspect the bounded source/provider error. Do not infer approval; retry a transient provider failure or provide a clearer source.')
        except Exception as e:
            row.update(outcome='evaluation_failed',error_type=type(e).__name__)
        row['seconds']=round(time.perf_counter()-start,3);report['results'].append(row)
        args.output.write_text(json.dumps(report,indent=2,default=str)+'\n')
        print(json.dumps({k:v for k,v in row.items() if k in ('file','outcome','seconds','error','error_type')}),flush=True)
    return 0 if all(r['outcome'] in ('eligible','needs_review','processing_failed') for r in report['results']) else 1


if __name__=='__main__':raise SystemExit(main())
