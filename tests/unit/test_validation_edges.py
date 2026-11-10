import json
import asyncio
import httpx
import pytest
from pydantic import ValidationError
from legal_issue_pipeline.config import AgentConfig,PipelineConfig,load_config
from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.agents.judge import JudgeAgent,FeedbackFirewall
from legal_issue_pipeline.debate.controller import DebateController
from legal_issue_pipeline.llm.base_client import LLMError
from legal_issue_pipeline.llm.openai_client import OpenAICompatibleClient
from legal_issue_pipeline.io.jsonl_reader import JSONLReader
from legal_issue_pipeline.schemas import JudgeOutput
from conftest import FakeClient,gen_data,judge_data,response,critique,SITUATION


def material_finding(quote):
    return dict(fact="Thiếu dữ kiện trọng yếu",markdown_evidence_quotes=[quote],material=True,
        importance_reason="Ảnh hưởng việc nhận diện vấn đề trung tâm",affected_issue="Quyền yêu cầu",
        equivalent_in_situation=False,equivalence_assessment="Không có nội dung tương đương trong situation")


async def test_material_missing_fact_is_audited(config,record):
    data=judge_data();data["situation_audit"]["missing_facts"]=[material_finding("PRIVATE_MARKDOWN_ONLY_FACT")]
    controller=DebateController(GeneratorAgent(FakeClient([gen_data()]),config),JudgeAgent(FakeClient([data]),config),config)
    result=await controller.run(record)
    assert result.situation_error is True
    assert result.audit["selected_situation_audit"]["missing_facts"][0]["affected_issue"]
    assert "PRIVATE_MARKDOWN_ONLY_FACT" not in json.dumps(controller.generator.client.messages)


async def test_fabricated_markdown_quote_is_rejected(config,record,generator_output):
    data=judge_data();data["situation_audit"]["missing_facts"]=[material_finding("fabricated source quote")]
    agent=JudgeAgent(FakeClient([data]),config)
    with pytest.raises(LLMError,match="quote absent"):
        await agent.evaluate(record,generator_output,None,None,[],[])


async def test_judge_cannot_ignore_generator_contest(config,record,generator_output):
    current=type(generator_output).model_validate_json(json.dumps(response()))
    previous=JudgeOutput.model_validate_json(json.dumps(critique()))
    with pytest.raises(LLMError,match="Reconsider each"):
        await JudgeAgent(FakeClient([judge_data()]),config).evaluate(record,current,previous,None,[],[])


async def test_no_valid_candidate_cannot_be_exported(config,record):
    config.max_debate_rounds=1
    data=gen_data();data["issues"][0]["situation_evidence_quotes"]=["absent from situation"]
    second=json.loads(json.dumps(data))
    controller=DebateController(GeneratorAgent(FakeClient([data,second]),config),JudgeAgent(FakeClient([judge_data(),judge_data()]),config),config)
    with pytest.raises(LLMError,match="structured validation exhausted"):
        await controller.run(record)


async def test_request_semaphore_is_shared_between_roles(config):
    active=peak=0
    async def handler(request):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        await asyncio.sleep(0.005)
        active-=1
        return httpx.Response(200,json={"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]})
    sem=asyncio.Semaphore(2)
    clients=[OpenAICompatibleClient(config.gen,config,sem,r,httpx.MockTransport(handler)) for r in ["gen","judge"]]
    await asyncio.gather(*(clients[i%2].complete([{"role":"user","content":"x"}],{}) for i in range(8)))
    assert peak==2
    await asyncio.gather(*(c.close() for c in clients))


@pytest.mark.parametrize("url",["http://user:password@localhost/v1","http://localhost/v1?key=secret","ftp://host","http://host/#secret"])
def test_credentials_cannot_leak_via_endpoint_url(url):
    with pytest.raises(ValidationError):AgentConfig(api_base=url)


def test_secret_file_and_json_env_config(config,tmp_path,monkeypatch):
    secret=tmp_path/"secret.key";secret.write_text("test-secret\n")
    monkeypatch.setenv("GEN_API_KEY_FILE",str(secret));monkeypatch.delenv("GEN_API_KEY",raising=False)
    monkeypatch.setenv("API_EXTRA_BODY",'{"custom": true}')
    loaded=load_config()
    assert loaded.gen.api_key.get_secret_value()=="test-secret"
    assert loaded.api_extra_body=={"custom":True}
    assert "test-secret" not in json.dumps(loaded.public_dict())


@pytest.mark.parametrize("line",['{"situation":"x","situation":"y"}',"null","",'{"doc_name":"a"}'])
def test_malformed_input_rejected(tmp_path,line):
    path=tmp_path/"bad.jsonl";path.write_text(line+"\n")
    with pytest.raises(ValueError):list(JSONLReader(path))


def test_protect_input_path(config):
    values=config.model_dump();values["output_path"]=config.input_path
    with pytest.raises(ValidationError,match="differ"):
        PipelineConfig(**values)


def test_cli_configuration_error_does_not_print_credentials(monkeypatch,capsys):
    from legal_issue_pipeline.cli import main
    monkeypatch.setenv("GEN_API_BASE","http://user:SECRET_BAD_URL@localhost/v1")
    monkeypatch.setattr("sys.argv",["legal-issues","run"])
    assert main()==2
    captured=capsys.readouterr()
    assert "SECRET_BAD_URL" not in captured.err+captured.out
