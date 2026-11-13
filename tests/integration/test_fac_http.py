import asyncio
import json
import httpx
import pytest
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.io.jsonl_writer import JSONLWriter
from legal_issue_pipeline.llm.openai_client import OpenAICompatibleClient
from legal_issue_pipeline.llm.base_client import LLMError,ContextLimitError
from legal_issue_pipeline.pipeline.runner import PipelineRunner
from conftest import (FakeClient,FACTS,APPLICATION,gen_data,judge_data,critique,response,assessment,
                     discovery_data,fewshot_review)
from test_fac_agents_and_debate import assert_judge_isolated


async def test_http_pipeline_full_sources_fewshot_only_generator_and_facts_only_judge(config,record):
    config.enable_blind_judge_discovery=True;config.max_debate_rounds=1;config.max_json_repair_retries=1
    JSONLWriter(config.input_path).write([record])
    roles=[];judge_messages=[];gen_payloads=[]
    gstage=jstage=0
    def handler(request):
        nonlocal gstage,jstage
        body=json.loads(request.content);payload=json.loads(body['messages'][1]['content'])
        assert body['model']=='DeepSeek-V4.1-Flash-1017'
        assert body['max_tokens']==131073 and body['chat_template_kwargs']=={'thinking':True,'reasoning_effort':50}
        if request.headers['x-test-role']=='gen':
            roles.append('generator');gen_payloads.append(payload)
            if 'examples_to_audit' in payload:answer=fewshot_review(payload['examples_to_audit'])
            else:
                assert payload['benchmark_seed']==record['benchmark_seed'] and payload['markdown']==record['markdown']
                assert len(payload['few_shot_examples'])==5
                answer=gen_data() if gstage==0 else response();gstage+=1
        else:
            roles.append('judge');judge_messages.append(body['messages'])
            assert payload['facts_clean']==FACTS
            if 'BLIND ISSUE DISCOVERY' in body['messages'][0]['content']:answer=discovery_data()
            elif jstage==0:
                answer=critique();answer['blind_comparison']=judge_data(blind=True)['blind_comparison'];jstage+=1
            else:
                answer=judge_data(blind=True);answer['rebuttal_assessments']=[assessment()]
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(answer,ensure_ascii=False),'reasoning_content':'DO_NOT_SAVE'},'finish_reason':'stop'}],
                                        'usage':{'total_tokens':40}})
    def factory():
        sem=asyncio.Semaphore(40)
        gen=OpenAICompatibleClient(config.gen,config,sem,'gen',httpx.MockTransport(handler))
        judge=OpenAICompatibleClient(config.judge,config,sem,'judge',httpx.MockTransport(handler))
        gen.http.headers['x-test-role']='gen';judge.http.headers['x-test-role']='judge'
        return DebateController(GeneratorAgent(gen,config),JudgeAgent(judge,config),config)
    summary=await PipelineRunner(config,factory).run()
    assert roles==['generator','generator','judge','judge','generator','judge']
    assert summary['accepted']==1 and summary['token_usage']['total_tokens']==240
    assert_judge_isolated(judge_messages,record)
    output=json.loads(config.output_path.read_text())
    assert output['explain']==[gen_data()['issues'][0]['explain']]
    assert set(output)==set(record)|{'issues','explain'}
    assert summary['effective_thinking']['judge']['effective_effort']==50
    assert 'DO_NOT_SAVE' not in ''.join(p.read_text() for p in config.audit_dir.glob('*.json'))


async def test_remote_tokenization_uses_same_actual_template_and_guards_context(config):
    config.token_count_method='vllm';routes=[]
    def handler(request):
        body=json.loads(request.content);routes.append(request.url.path)
        assert body['chat_template_kwargs']=={'thinking':True,'reasoning_effort':50}
        if request.url.path=='/tokenize':
            assert body['messages'][0]['content']=='x'*200000
            return httpx.Response(200,json={'count':1000})
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]})
    client=OpenAICompatibleClient(config.gen,config,asyncio.Semaphore(40),'gen',httpx.MockTransport(handler))
    try:
        await client.complete([{'role':'user','content':'x'*200000}],{})
        assert routes==['/tokenize','/v1/chat/completions']
    finally:await client.close()


@pytest.mark.parametrize('mode',['auto','vllm'])
async def test_tokenization_unavailable_never_silently_bypasses_guard(config,mode):
    config.token_count_method=mode
    client=OpenAICompatibleClient(config.gen,config,asyncio.Semaphore(1),'gen',httpx.MockTransport(lambda request:httpx.Response(404)))
    try:
        with pytest.raises((LLMError,ContextLimitError)):
            await client.complete([{'role':'user','content':'x'*200000}],{})
    finally:await client.close()


async def test_shared_http_limit_40_across_roles(config):
    active=peak=0;full=asyncio.Event()
    async def handler(request):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        if active==40:full.set()
        try:
            await asyncio.wait_for(full.wait(),5)
            await asyncio.sleep(0)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]})
        finally:active-=1
    sem=asyncio.Semaphore(config.max_concurrent_requests)
    clients=[OpenAICompatibleClient(getattr(config,role),config,sem,role,httpx.MockTransport(handler)) for role in ('gen','judge')]
    try:
        await asyncio.gather(*(clients[i%2].complete([{'role':'user','content':'test'}],{}) for i in range(100)))
        assert peak==40
    finally:await asyncio.gather(*(c.close() for c in clients))
