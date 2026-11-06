"""Fixture-provider orchestration tests; these never establish live AI quality."""
from functools import partial
import hashlib
import json
from pathlib import Path

import pytest

from backend.analysis import AnalysisBlocked, _strict_object, configuration_status, run_analysis
from backend.contracts import Asset, Brief, CandidateWindow, validate_plan
from backend.jobs import JobCancelled
from backend.planning import CoverageError, build_plan, timeline_slots
from backend.providers import ProviderReply
from backend.store import Store


class FixtureProvider:
    mode = "fixture"
    provider = "fixture"
    model = "fixture-not-a-model"
    calls = []

    def __init__(self, config, directory, cancel):
        pass

    def close(self):
        pass

    def complete(self, prompt, images, cancel):
        request = json.loads(prompt[prompt.index('{'):])
        self.calls.append(request)
        task, samples = request["task"], request["frames_in_image_order"]
        stage = task["stage"]
        if stage == "reference_analysis":
            result = {"role":"full silhouette", "action":"turn", "framing":"full body", "requirements":["garment visible"], "uncertainties":["Fixture response; no visual inference"]}
        elif stage in {"source_scouting", "source_refinement", "source_window_assembly"}:
            first,last=samples[0]["source_s"],samples[-1]["source_s"]
            start,end=max(first,6.),min(last,7.4)
            windows=[]
            if end>start:
                windows=[{"start_s":start,"end_s":end,"role":"full silhouette","action":"turn","framing":"full body","confidence":.8,
                          "evidence_ids":[samples[0]["sample_id"],samples[-1]["sample_id"]],"warnings":["Fixture only"]}]
            result={"windows":windows,"coverage_gaps":[]}
        elif stage == "sequence_planning":
            candidates=task["candidates"]
            selections=[]
            for slot in task["slots"]:
                matches=[c for c in candidates if c["end_s"]-c["start_s"]>=slot["duration_s"]]
                if matches:
                    c=matches[0];selections.append({"slot_index":slot["slot_index"],"candidate_id":c["id"],"source_start_s":c["start_s"],"confidence":.8,"reason":"Explicit fixture choice inside the later take"})
            result={"constraints_satisfied":True,"selections":selections,"coverage_gaps":[] if len(selections)==len(task["slots"]) else ["No adequate fixture interval"]}
        else:
            raise AssertionError(stage)
        return ProviderReply(json.dumps(result),{"fixture":True},actual_call=False,mode="fixture")


@pytest.fixture
def setup_pipeline(tmp_path, monkeypatch):
    from backend import analysis
    source=tmp_path/'source.bin';source.write_bytes(b'source-fixture')
    reference=tmp_path/'reference.bin';reference.write_bytes(b'reference-fixture')
    def asset(path,role,duration):
        return Asset(id=role,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),original_path=str(path),role=role,duration_s=duration,width=160,height=240)
    assets={"source":asset(source,"source",8),"reference":asset(reference,"reference",1)}
    brief=Brief(id="project",name="Fixture recreation",reference_asset_id="reference",source_asset_ids=["source"],duration_s=1)
    store=Store(tmp_path/'runtime')
    monkeypatch.setattr(analysis,"detect_reference_cuts",lambda *a,**k:{"cuts_s":[],"warning":"Fixture cut proposals"})
    def frames(asset,output_dir,timestamps_s=None,**kwargs):
        p=tmp_path/'fixture.jpg';p.write_bytes(b'not-an-actual-image-fixture-provider-only')
        return [{"asset_id":asset.id,"requested_s":t,"source_s":min(t,asset.duration_s-.01),"source_pts_s":t,"path":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for t in timestamps_s]
    monkeypatch.setattr(analysis,"sample_frames",frames)
    FixtureProvider.calls=[]
    return brief,assets,store


def test_unconfigured_offline_model_blocks_without_download(tmp_path,monkeypatch):
    from backend.providers import local
    def forbidden(*args,**kwargs):raise AssertionError('No runtime process may start without a local snapshot')
    monkeypatch.setattr(local.subprocess,'run',forbidden)
    monkeypatch.setattr(local.subprocess,'Popen',forbidden)
    monkeypatch.delenv('SEVENHEAVENS_MODEL_PATH',raising=False)
    monkeypatch.delenv('SEVENHEAVENS_MODEL_PYTHON',raising=False)
    status=configuration_status({"model_path":str(tmp_path/'not-downloaded')})
    assert not status['ready'] and status['stage']=='model_missing'
    brief=Brief(name='Pending media')
    store=Store(tmp_path/'runtime')
    with pytest.raises(AnalysisBlocked,match='snapshot'):
        run_analysis(brief,{},store.root,lambda:False,lambda *a:None,[],store,config={"model_path":str(tmp_path/'not-downloaded')})
    assert not store.list('analysis_runs') and not (tmp_path/'not-downloaded').exists()


def test_later_take_selection_evidence_feedback_and_cache(setup_pipeline):
    brief,assets,store=setup_pipeline
    feedback=[{"id":"approved1","approval_state":"approved","scope":"edit","reason":"Keep the whole silhouette","changes":{"direction_rule":"Prefer the complete turn"}},
              {"id":"rejected1","approval_state":"rejected","reason":"Not approved"}]
    runner=partial(run_analysis,provider_factory=FixtureProvider)
    result=runner(brief,assets,store.root,lambda:False,lambda *a:None,feedback,store)
    plan=store.get('plans',result['plan_id'])
    assert plan['mode']=='fixture' and plan['shots'][0]['source_start_s']>=6
    assert plan['shots'][0]['source_end_s']<=7.4
    assert plan['shots'][0]['candidate_id'] in result['candidate_ids']
    candidate=store.get('candidates',plan['shots'][0]['candidate_id'])
    run=store.get('analysis_runs',candidate['analysis_run_id'])
    document=json.loads(Path(run['artifact_path']).read_text())
    assert not run['actual_call'] and not document['actual_call']
    assert document['raw_response'] and document['samples'] and document['runtime']['fixture']
    assert set(candidate['evidence_ids']).issubset({s['sample_id'] for s in document['samples']})
    assert all([f['id'] for f in c['brief_and_approved_feedback']['approved_feedback']]==['approved1'] for c in FixtureProvider.calls)
    assert plan['provenance']['approved_feedback_ids']==['approved1']
    count=len(FixtureProvider.calls)
    again=runner(brief,assets,store.root,lambda:False,lambda *a:None,feedback,store)
    assert again['cache_hit'] and again['plan_id']==result['plan_id'] and len(FixtureProvider.calls)==count
    assert not any(r['actual_call'] for r in store.list('analysis_runs'))


def test_missing_coverage_never_creates_plan(setup_pipeline):
    brief,assets,store=setup_pipeline
    class NoCoverage(FixtureProvider):
        def complete(self,prompt,images,cancel):
            request=json.loads(prompt[prompt.index('{'):])
            if request['task']['stage'].startswith('source'):
                return ProviderReply('{"windows":[],"coverage_gaps":["No turn"]}',{},False,'fixture')
            return super().complete(prompt,images,cancel)
    with pytest.raises(AnalysisBlocked,match='No useful') as error:
        run_analysis(brief,assets,store.root,lambda:False,lambda *a:None,[],store,provider_factory=NoCoverage)
    assert error.value.artifacts['coverage_gaps']
    assert not store.list('plans') and store.list('recipes')


def test_missing_evidence_replaces_cache_pointer_and_preserves_old_plan(setup_pipeline):
    brief,assets,store=setup_pipeline
    runner=partial(run_analysis,provider_factory=FixtureProvider)
    arguments=(brief,assets,store.root,lambda:False,lambda *a:None,[],store)
    first=runner(*arguments)
    old_plan=store.get('plans',first['plan_id'])
    missing=store.get('analysis_runs',first['analysis_run_ids'][0])
    Path(missing['artifact_path']).unlink()
    second=runner(*arguments)
    assert not second['cache_hit'] and second['plan_id']!=first['plan_id']
    assert store.get('plans',first['plan_id'])==old_plan
    assert store.get('plans',second['plan_id'])['version']==old_plan['version']+1
    assert len(store.list('plans'))==2 and len(store.list('analysis_cache'))==1
    assert store.list('analysis_cache')[0]['plan_id']==second['plan_id']
    count=len(FixtureProvider.calls)
    third=runner(*arguments)
    assert third['cache_hit'] and third['plan_id']==second['plan_id']
    assert len(FixtureProvider.calls)==count


def test_invalid_json_retries_bounded_and_no_live_attribution(setup_pipeline):
    brief,assets,store=setup_pipeline
    class Invalid(FixtureProvider):
        def complete(self,*args):return ProviderReply('not JSON',{},False,'fixture')
    with pytest.raises(AnalysisBlocked,match='twice'):
        run_analysis(brief,assets,store.root,lambda:False,lambda *a:None,[],store,provider_factory=Invalid)
    assert len(store.list('analysis_runs'))==2
    assert all(r['status']=='invalid_response' and not r['actual_call'] for r in store.list('analysis_runs'))
    assert not store.list('plans')


def test_cancellation_and_product_filter(setup_pipeline):
    brief,assets,store=setup_pipeline
    with pytest.raises(JobCancelled):
        run_analysis(brief,assets,store.root,lambda:True,lambda *a:None,[],store,provider_factory=FixtureProvider)
    assert not store.list('plans')
    brief.product_group='confirmed-other-outfit'
    with pytest.raises(AnalysisBlocked,match='No source footage'):
        run_analysis(brief,assets,store.root,lambda:False,lambda *a:None,[],store,provider_factory=FixtureProvider)


def test_strict_json_and_absolute_timeline_alignment():
    for bad in ['{"x":NaN}','{"x":1,"x":2}','prefix {"x":1}','[]']:
        with pytest.raises(ValueError):_strict_object(bad)
    brief=Brief(name='Timing',duration_s=3,fps_num=30,music_asset_id='music')
    slots=timeline_slots([1,2],3,brief,[1.04,2.04])
    assert [s['end_frame'] for s in slots]==[31,61,90]
    assert all(a['end_frame']==b['start_frame'] for a,b in zip(slots,slots[1:]))
    assert slots[-1]['end_frame']==90


def test_unknown_or_outside_candidate_is_rejected(setup_pipeline):
    brief,assets,store=setup_pipeline
    c=CandidateWindow(id='candidate',asset_id='source',start_s=6,end_s=7,selection_mode='fixture')
    slots=timeline_slots([],1,brief)
    choice={'constraints_satisfied':True,'coverage_gaps':[], 'selections':[{'slot_index':0,'candidate_id':'candidate','source_start_s':6.5,'confidence':.8,'reason':'Fixture'}]}
    with pytest.raises(CoverageError,match='cannot cover'):
        build_plan(brief,assets,[c],slots,choice,recipe_id='recipe',planning_run_id='run',analysis_run_ids=[],mode='fixture')
    choice['selections'][0]['candidate_id']='invented'
    with pytest.raises(CoverageError,match='unknown candidate'):
        build_plan(brief,assets,[c],slots,choice,recipe_id='recipe',planning_run_id='run',analysis_run_ids=[],mode='fixture')


def test_repeating_one_source_window_is_not_missing_coverage_fallback(setup_pipeline):
    brief,assets,store=setup_pipeline
    c=CandidateWindow(id='candidate',asset_id='source',start_s=6,end_s=7,selection_mode='fixture')
    slots=timeline_slots([.5],1,brief)
    choices={'constraints_satisfied':True,'coverage_gaps':[], 'selections':[
        {'slot_index':i,'candidate_id':'candidate','source_start_s':6,'confidence':.9,'reason':'Fixture repeated window'} for i in range(2)]}
    with pytest.raises(CoverageError,match='overlapping'):
        build_plan(brief,assets,[c],slots,choices,recipe_id='recipe',planning_run_id='run',analysis_run_ids=[],mode='fixture')
