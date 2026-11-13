"""Reproduce the B200 report through the real HTTP adapter and startup gate."""
import asyncio
import json
import httpx
import pytest

from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.fewshot import FewShotGroundingError
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.llm.openai_client import OpenAICompatibleClient
from legal_issue_pipeline.pipeline.runner import PipelineRunner
from conftest import ROOT, fewshot_review, gen_data, judge_data


@pytest.mark.parametrize('reference',['original','corrected'])
async def test_b200_notarization_error_is_fixed_without_bypassing_grounding(config,record,reference):
    if reference=='original':config.fewshot_path=ROOT/'docs/history/fewshot_before_grounding_fix.jsonl'
    config.token_count_method='vllm'
    config.max_json_repair_retries=2
    JSONLWriter(config.input_path).write([record])
    calls=[]
    def handler(request):
        body=json.loads(request.content)
        if request.url.path=='/tokenize':
            return httpx.Response(200,json={'count':12000})
        assert body['model']=='DeepSeek-V4.1-Flash-1017'
        assert body['chat_template_kwargs']=={'thinking':True,'reasoning_effort':50}
        assert body['max_tokens']==131073
        payload=json.loads(body['messages'][1]['content'])
        if 'examples_to_audit' in payload:
            calls.append('approval')
            examples=payload['examples_to_audit']
            answer=fewshot_review(examples)
            commercial=next(x for x in examples if x['example_id']=='E4')
            check=next(x for x in answer['checks'] if x['example_id']=='E4' and x['issue_index']==2)
            # This is the exact defect reported by the real B200 run, not a
            # general regex claimed to prove semantic grounding.
            if 'công chứng' in commercial['issues'][2] and 'công chứng' not in commercial['facts_clean'].casefold():
                check.update(issue_supported=False,explanation='Issue nêu hợp đồng thế chấp đã được công chứng, nhưng facts_clean chỉ ghi hợp đồng được ký, không xác lập công chứng.')
            assert 'facts_evidence_quotes' not in json.dumps(answer)
        elif 'benchmark_seed' in payload:
            calls.append('generate');answer=gen_data()
            assert len(payload['few_shot_examples'])==5
            assert 'công chứng' not in payload['few_shot_examples'][3]['issues'][2]
        else:
            calls.append('judge');answer=judge_data()
            assert payload['facts_clean']==record['benchmark_seed']['facts_clean']
            assert 'examples_to_audit' not in payload and 'few_shot_examples' not in payload
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(answer,ensure_ascii=False)},'finish_reason':'stop'}],
                                       'usage':{'total_tokens':40}})
    def factory():
        gate=asyncio.Semaphore(config.max_concurrent_requests)
        gen=OpenAICompatibleClient(config.gen,config,gate,'gen',httpx.MockTransport(handler))
        judge=OpenAICompatibleClient(config.judge,config,gate,'judge',httpx.MockTransport(handler))
        return DebateController(GeneratorAgent(gen,config),JudgeAgent(judge,config),config)
    if reference=='original':
        with pytest.raises(FewShotGroundingError,match='1178738'):
            await PipelineRunner(config,factory).run()
        assert calls==['approval']  # No repair that can erase the valid rejection.
        failure=json.loads((config.audit_dir/'fewshot_validation_failed.json').read_text())
        assert failure['error_type']=='FewShotGroundingError'
        assert len(failure['findings'])==1 and failure['findings'][0]['issue_index']==2
        assert failure['findings'][0]['doc_name']=='1178738' and failure['api_calls']
        summary=json.loads((config.audit_dir/'summary.json').read_text())
        assert summary['global_status']=='FAILED' and summary['fewshot_grounding']=='NOT_APPROVED'
        assert summary['pending']==1 and summary['accepted']==0 and summary['rejected']==0
        assert summary['token_usage']['total_tokens']==40
        assert config.output_path.read_text()==''
    else:
        summary=await PipelineRunner(config,factory).run()
        assert calls==['approval','generate','judge'] and summary['accepted']==1
        saved=json.loads((config.audit_dir/'fewshot_validation.json').read_text())
        assert saved['method']=='semantic_grounding_v1' and saved['review']['checks']
        assert saved['report']==saved['review']
        assert all(c['issue_supported'] and c['explain_supported'] for c in saved['report']['checks'])
        def never():raise AssertionError('Cached approval or completed record recomputed')
        resumed=await PipelineRunner(config,never).run()
        assert resumed['accepted']==1 and calls==['approval','generate','judge']


def payload_examples(config):
    from legal_issue_pipeline.io.fewshot import FewShotBank
    return FewShotBank(config.fewshot_path).examples
