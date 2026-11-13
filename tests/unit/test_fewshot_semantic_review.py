import hashlib
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from legal_issue_pipeline.agents.generator import GeneratorAgent
from legal_issue_pipeline.io.fewshot import FewShotBank, FewShotGroundingError
from legal_issue_pipeline.schemas import FewShotValidation
from conftest import FakeClient, ROOT, fewshot_review


def parsed(value):
    return FewShotValidation.model_validate_json(json.dumps(value, ensure_ascii=False))


def test_semantic_review_preserves_facts_and_has_no_quote_or_span_fields(config):
    before = config.fewshot_path.read_bytes()
    bank = FewShotBank(config.fewshot_path)
    examples = bank.validation_examples()
    assert examples == bank.examples
    report = parsed(fewshot_review(examples))
    for check in report.checks:
        check.explanation = 'Diễn đạt tổng hợp các tình tiết có sẵn và suy luận pháp lý hợp lý từ chúng.'
    bank.validate_report(report)
    assert all(set(example) == {'example_id', 'category', 'facts_clean', 'issues', 'explain'} for example in examples)
    assert all(set(check.model_dump()) == {'example_id', 'issue_index', 'issue_supported', 'explain_supported', 'explanation'} for check in report.checks)
    assert config.fewshot_path.read_bytes() == before


@pytest.mark.parametrize('corruption', ['missing', 'duplicate', 'wrong_index', 'wrong_example'])
def test_review_covers_every_pair_once(config, corruption):
    bank = FewShotBank(config.fewshot_path)
    review = fewshot_review(bank.validation_examples())
    if corruption == 'missing': review['checks'].pop()
    if corruption == 'duplicate': review['checks'].append(deepcopy(review['checks'][0]))
    if corruption == 'wrong_index': review['checks'][0]['issue_index'] = 999
    if corruption == 'wrong_example': review['checks'][0]['example_id'] = 'E5'
    with pytest.raises(ValueError, match='every issue/explain pair'):
        bank.validate_report(parsed(review))


def test_semantic_rejection_reports_all_findings_without_evidence(config):
    bank = FewShotBank(config.fewshot_path)
    value = fewshot_review(bank.validation_examples())
    for check in (value['checks'][0], value['checks'][-1]):
        check.update(issue_supported=False, explanation='Điều kiện công chứng không được tình tiết mô tả hay suy ra hợp lý.')
    with pytest.raises(FewShotGroundingError) as result:
        bank.validate_report(parsed(value))
    assert len(result.value.findings) == 2
    assert '330709' in str(result.value) and '1362988' in str(result.value)
    assert result.value.findings[0]['issue']
    assert not isinstance(result.value, ValueError)


async def test_semantic_false_does_not_retry_or_flip_into_pass(config):
    config.max_json_repair_retries = 2
    bank = FewShotBank(config.fewshot_path)
    rejected = fewshot_review(bank.validation_examples())
    rejected['checks'][0].update(issue_supported=False, explanation='Không thể suy ra việc công chứng từ thông tin đã cung cấp.')

    class Client(FakeClient):
        async def complete(self, messages, schema):
            from legal_issue_pipeline.llm.base_client import Completion
            self.messages.append(deepcopy(messages))
            return Completion(json.dumps(rejected), {}, 0, 'review')

    client = Client([])
    with pytest.raises(FewShotGroundingError):
        await GeneratorAgent(client, config, bank).validate_fewshot()
    assert len(client.messages) == 1


async def test_bad_pair_id_repair_is_bounded_and_only_requests_semantic_schema(config):
    config.max_json_repair_retries = 1
    bank = FewShotBank(config.fewshot_path)
    wrong = fewshot_review(bank.validation_examples())
    wrong['checks'][0]['issue_index'] = 999
    correct = fewshot_review(bank.validation_examples())

    class Client(FakeClient):
        async def complete(self, messages, schema):
            from legal_issue_pipeline.llm.base_client import Completion
            self.messages.append(deepcopy(messages))
            assert schema['title'] == 'FewShotValidation'
            return Completion(json.dumps(wrong if len(self.messages) == 1 else correct), {}, 0, str(len(self.messages)))

    client = Client([])
    report = await GeneratorAgent(client, config, bank).validate_fewshot()
    assert len(client.messages) == 2 and report.checks
    bank.validate_report(report)
    schema = client.messages[0][0]['content'].split('JSON Schema:')[-1]
    assert 'evidence_quotes' not in schema and 'span_id' not in schema


@pytest.mark.parametrize('old_field', ['facts_evidence_quotes', 'facts_span_ids'])
def test_old_evidence_fields_are_not_part_of_semantic_response(config, old_field):
    data = fewshot_review(FewShotBank(config.fewshot_path).validation_examples())
    data['checks'][0][old_field] = ['anything']
    with pytest.raises(ValidationError):
        parsed(data)


def test_reference_correction_changes_only_one_label_and_keeps_original_backup():
    correction = json.loads((ROOT/'docs/fewshot_grounding_correction.json').read_text())
    original = (ROOT/correction['backup']).read_bytes()
    assert hashlib.sha256(original).hexdigest() == correction['original_sha256']
    source = ROOT/'input/fewshot.jsonl'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == correction['corrected_sha256']
    old = [json.loads(line) for line in original.decode().splitlines()]
    new = [json.loads(line) for line in source.read_text().splitlines()]
    assert len(new) == 5 and len(correction['corrections']) == 1
    original_label = old[3]['issues'][2]['issue']
    old[3]['issues'][2]['issue'] = new[3]['issues'][2]['issue']
    assert old == new
    assert 'công chứng' in original_label and 'công chứng' not in new[3]['issues'][2]['issue']
