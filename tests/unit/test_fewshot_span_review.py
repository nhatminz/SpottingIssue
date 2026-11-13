import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.io.fewshot import FewShotBank, FewShotGroundingError
from legal_issue_pipeline.llm.base_client import LLMError
from legal_issue_pipeline.schemas import FewShotReview
from conftest import FakeClient, ROOT, fewshot_review


def parsed(value):
    return FewShotReview.model_validate_json(json.dumps(value,ensure_ascii=False))


def test_all_spans_resolve_to_exact_original_ocr_and_unicode(config):
    bank=FewShotBank(config.fewshot_path)
    examples=bank.validation_examples()
    review=fewshot_review(examples)
    for check in review['checks']:
        check['facts_span_ids']=[span['span_id'] for span in bank.fact_spans[check['example_id']]]
    report=bank.resolve_review(parsed(review))
    originals={example['example_id']:example['facts_clean'] for example in examples}
    for check in report.checks:
        assert all(quote in originals[check.example_id] for quote in check.facts_evidence_quotes)
        assert check.facts_evidence_quotes==[span['text'] for span in bank.fact_spans[check.example_id]]
    # Normal demonstration payload is unchanged; only the audit request has spans.
    assert all('facts_spans' not in example for example in bank.examples)


@pytest.mark.parametrize('ids',[[],['UNKNOWN'],['S1','S1'],['S999999']])
def test_acceptance_requires_known_nonempty_unique_source_ids(config,ids):
    bank=FewShotBank(config.fewshot_path)
    review=fewshot_review(bank.validation_examples())
    review['checks'][0]['facts_span_ids']=ids
    with pytest.raises(ValueError,match='facts_span_ids'):
        bank.resolve_review(parsed(review))


@pytest.mark.parametrize('corruption',['missing','duplicate','wrong_index','wrong_example'])
def test_review_covers_every_pair_once(config,corruption):
    bank=FewShotBank(config.fewshot_path)
    review=fewshot_review(bank.validation_examples())
    if corruption=='missing':review['checks'].pop()
    if corruption=='duplicate':review['checks'].append(deepcopy(review['checks'][0]))
    if corruption=='wrong_index':review['checks'][0]['issue_index']=999
    if corruption=='wrong_example':review['checks'][0]['example_id']='E5'
    with pytest.raises(ValueError,match='every example/issue_index'):
        bank.resolve_review(parsed(review))


def test_semantic_false_survives_bad_evidence_and_reports_all_findings(config):
    bank=FewShotBank(config.fewshot_path)
    value=fewshot_review(bank.validation_examples())
    for check in (value['checks'][0],value['checks'][-1]):
        check['issue_supported']=False
        check['facts_span_ids']=[]
        check['explanation']='Chi tiết công chứng không có trong facts_clean; không thể xác nhận điều kiện này.'
    value['checks'][0]['facts_span_ids']=['UNKNOWN']
    with pytest.raises(FewShotGroundingError) as result:
        bank.resolve_review(parsed(value))
    assert len(result.value.findings)==2
    assert '330709' in str(result.value) and '1362988' in str(result.value)
    assert result.value.findings[0]['issue']
    assert not isinstance(result.value,ValueError)  # Not handled as JSON repair.


async def test_known_unsupported_content_does_not_retry_or_flip_into_pass(config):
    config.max_json_repair_retries=2
    bank=FewShotBank(config.fewshot_path)
    rejected=fewshot_review(bank.validation_examples())
    rejected['checks'][0].update(issue_supported=False,explanation='Không có căn cứ về việc công chứng trong facts_clean.')
    class Client(FakeClient):
        async def complete(self,messages,schema):
            # Force a semantic rejection rather than the usual automatic test approval.
            from legal_issue_pipeline.llm.base_client import Completion
            self.messages.append(deepcopy(messages))
            return Completion(json.dumps(rejected),{},0,'review')
    client=Client([])
    with pytest.raises(FewShotGroundingError):
        await GeneratorAgent(client,config,bank).validate_fewshot()
    assert len(client.messages)==1


async def test_repair_unknown_span_ids_is_bounded_and_does_not_request_quotes(config):
    config.max_json_repair_retries=1
    bank=FewShotBank(config.fewshot_path)
    wrong=fewshot_review(bank.validation_examples());wrong['checks'][0]['facts_span_ids']=['S99999']
    correct=fewshot_review(bank.validation_examples())
    class Client(FakeClient):
        async def complete(self,messages,schema):
            from legal_issue_pipeline.llm.base_client import Completion
            self.messages.append(deepcopy(messages))
            value=wrong if len(self.messages)==1 else correct
            assert schema['title']=='FewShotReview'
            return Completion(json.dumps(value),{},0,str(len(self.messages)))
    client=Client([])
    report=await GeneratorAgent(client,config,bank).validate_fewshot()
    assert len(client.messages)==2 and report.checks
    assert 'facts_evidence_quotes' not in client.messages[0][0]['content'].split('JSON Schema:')[-1]
    bank.validate_report(report)


def test_reference_correction_changes_only_one_label_and_keeps_original_backup():
    correction=json.loads((ROOT/'docs/fewshot_grounding_correction.json').read_text())
    backup=ROOT/correction['backup']
    original=backup.read_bytes()
    assert hashlib.sha256(original).hexdigest()==correction['original_sha256']
    source=ROOT/'input/fewshot.jsonl'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==correction['corrected_sha256']
    old=[json.loads(line) for line in original.decode().splitlines()]
    new=[json.loads(line) for line in source.read_text().splitlines()]
    assert len(new)==5 and len(correction['corrections'])==1
    original_label=old[3]['issues'][2]['issue']
    old[3]['issues'][2]['issue']=new[3]['issues'][2]['issue']
    assert old==new
    assert 'công chứng' in original_label and 'công chứng' not in new[3]['issues'][2]['issue']
    assert 'công chứng' not in new[3]['benchmark_seed']['facts_clean'].casefold()


def test_span_ids_cannot_be_borrowed_from_another_example(config):
    bank=FewShotBank(config.fewshot_path)
    review=fewshot_review(bank.validation_examples())
    review['checks'][0]['facts_span_ids']=[bank.fact_spans['E2'][0]['span_id']]
    with pytest.raises(ValueError,match='facts_span_ids'):
        bank.resolve_review(parsed(review))
    ids=[span['span_id'] for spans in bank.fact_spans.values() for span in spans]
    assert len(ids)==len(set(ids))
