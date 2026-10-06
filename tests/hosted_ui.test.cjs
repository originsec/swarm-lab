const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.py'), 'utf8');
const comparison = {};
vm.createContext(comparison);
vm.runInContext(source.slice(source.indexOf('function scenarioSettingsChanged('), source.indexOf('async function loadGoal(')), comparison);
test('Matching settings do not show an edited warning after starting', () => {
  const settings = {generation: 18, reasoning: 'medium', recall: 1, initial_read: 0, overlap: .35};
  assert.equal(comparison.scenarioSettingsChanged(settings, {...settings}), false);
  assert.equal(comparison.scenarioSettingsChanged(settings, {...settings, reasoning: ''}), true);
  assert.equal(comparison.scenarioSettingsChanged(settings, {...settings, recall: 0}), true);
  assert.equal(comparison.scenarioSettingsChanged(settings, {...settings, initial_read: 1}), true);
});
test('Missing fields and startup poll races are not treated as edits', () => {
  const run = {generation: 18, reasoning: 'medium', recall: 1};
  assert.equal(comparison.scenarioSettingsChanged(run, {generation: 18}), false);
  assert.equal(comparison.scenarioSettingsChanged(run, {generation: 19, reasoning: ''}), false);
});
const code = source.slice(source.indexOf('async function controlRequest('), source.indexOf('async function togglePause('))
  + source.slice(source.indexOf('async function applyHosted('), source.indexOf('$("btn_pause").onclick='));

function fixture({savedKey = true, failSave = false, touched = true} = {}) {
  const nodes = {}, calls = [];
  const $ = id => nodes[id] ||= {value: '', textContent: '', hidden: true, addEventListener() {}};
  $('in_apimodel').value = 'google/new-model';
  const context = {$, URLSearchParams, apiTouched: touched, autonomy: 'autonomous',
    metric: 'test', topology: 'peer', mutual: 0, freepost: 1, recall: 0, initialRead: 0,
    primed: 'ambient', publish: 'manual', reasoning: 'medium', scenarioOverrides: {},
    seenCross: new Set(), streamKeys: new Set(), prevRelays: 0,
    setToggle() {}, openD() {}, loadGoal: async () => {}, setDirty() {},
    fetch: async (url, options = {}) => {
      const data = options.body ? JSON.parse(options.body) : {};
      calls.push({url, options, data});
      const q = new URLSearchParams(data);
      if (options.method !== 'POST') return {ok: true, json: async () => ({config: {
        api_key: savedKey ? 'set (masked)' : '', api_model: 'old-model', api_base: 'https://openrouter.ai/api/v1'
      }})};
      if (q.has('api_model')) return {ok: !failSave, json: async () => ({staged: true, api_on: true})};
      return {ok: true, json: async () => ({applied: true})};
    }};
  vm.createContext(context); vm.runInContext(code, context);
  return {context, calls, nodes};
}

test('Start run saves the edited model first and retains the saved key', async () => {
  const {context, calls, nodes} = fixture();
  await context.applyScenario();
  assert.equal(calls.length, 3);
  const staged = new URLSearchParams(calls[1].data);
  assert.equal(staged.get('api_model'), 'google/new-model');
  assert.equal(staged.has('api_key'), false);
  assert.equal(staged.get('api_base'), 'https://openrouter.ai/api/v1');
  assert.equal(new URLSearchParams(calls[2].data).has('metric'), true);
  assert.equal(nodes.btn_go.disabled, false);
});
test('Failed hosted save prevents starting a run', async () => {
  const {context, calls, nodes} = fixture({failSave: true});
  await context.applyScenario();
  assert.equal(calls.length, 2);
  assert.equal(nodes.hostederror.hidden, false);
  assert.equal(nodes.btn_go.disabled, false);
});
test('Missing key blocks an edited hosted model without clearing credentials', async () => {
  const {context, calls, nodes} = fixture({savedKey: false});
  await context.applyScenario();
  assert.equal(calls.length, 1);
  assert.match(nodes.hostederror.textContent, /Enter an API key/);
});
test('Unedited local scenario starts without touching hosted configuration', async () => {
  const {context, calls} = fixture({savedKey: false, touched: false});
  await context.applyScenario();
  assert.equal(calls.length, 1);
  assert.equal(new URLSearchParams(calls[0].data).has('api_key'), false);
});
test('Switching back to local clears pending hosted edits and permits Start run', async () => {
  const {context, calls, nodes} = fixture({savedKey: false});
  await context.clearHosted();
  assert.equal(context.apiTouched, false);
  await context.applyScenario();
  assert.equal(calls.length, 2);
  assert.equal(new URLSearchParams(calls[1].data).has('metric'), true);
  assert.equal(nodes.hostederror.hidden, true);
});
test('Use hosted model also retains the saved key', async () => {
  const {context, calls, nodes} = fixture();
  await context.applyHosted();
  assert.equal(calls.length, 2);
  assert.equal(new URLSearchParams(calls[1].data).has('api_key'), false);
  assert.equal(nodes.btn_api.disabled, false);
});

test('Provider credentials use a JSON POST body, never a URL', async () => {
  const {context, calls, nodes} = fixture({savedKey: false});
  context.$('in_apikey').value = 'synthetic-provider-key';
  await context.applyHosted();
  const saved = calls[1];
  assert.equal(saved.url, '/api/config');
  assert.equal(saved.options.method, 'POST');
  assert.equal(saved.options.headers['X-Swarm-Lab'], '1');
  assert.equal(saved.data.api_key, 'synthetic-provider-key');
  assert.equal(nodes.in_apikey.value, '');
});

test('Published preset overrides reach configuration without replacing the selected model', async () => {
  const {context, calls} = fixture();
  context.scenarioOverrides = {max_tokens: 2000, objective: 'individual', keyname: 'batch tag'};
  await context.applyScenario();
  const q = new URLSearchParams(calls.at(-1).data);
  assert.equal(q.get('max_tokens'), '2000');
  assert.equal(q.get('objective'), 'individual');
  assert.equal(q.get('keyname'), 'batch tag');
  assert.equal(new URLSearchParams(calls[1].data).get('api_model'), 'google/new-model');
});
