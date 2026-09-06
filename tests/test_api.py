import pytest

def test_health(client):
    r=client.get('/api/health')
    assert r.status_code==200, f'health endpoint returned {r.status_code}'

def test_create_experiment(client):
    r=client.post('/api/experiments', json={'name':'QA Test Experiment','description':'Automated QA scaffold test','tags':['qa-test']})
    assert r.status_code in (200,201), f'create experiment returned {r.status_code}: {r.text}'
    data=r.json()
    assert 'id' in data or 'name' in data

def test_list_experiments(client):
    r=client.get('/api/experiments')
    assert r.status_code==200, f'list experiments returned {r.status_code}'
    body=r.json()
    assert isinstance(body,(list,dict))

def test_list_runs(client):
    r=client.get('/api/runs')
    assert r.status_code in (200,404), f'list runs returned {r.status_code}'

def test_list_models(client):
    r=client.get('/api/models')
    assert r.status_code in (200,404), f'list models returned {r.status_code}'

def test_analytics(client):
    r=client.get('/api/analytics')
    assert r.status_code in (200,404), f'analytics returned {r.status_code}'

def test_invalid_input(client):
    r=client.post('/api/experiments', json={})
    assert 400<=r.status_code<500, f'empty body should return 4xx, got {r.status_code}'

def test_create_comparison(client):
    r=client.post('/api/comparisons', json={'name':'QA Test Comparison','experiment_ids':[]})
    assert 400<=r.status_code<500, f'empty experiment_ids should return 4xx, got {r.status_code}'
