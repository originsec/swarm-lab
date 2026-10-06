const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.py'), 'utf8');

function fixture() {
  const nodes = {};
  const $ = id => nodes[id] ||= {value: '', hidden: true, textContent: '', addEventListener() {}};
  const context = {$, presetGoal: {agents_up: 20, api_on: true}, promptViews: {measureCustom: false},
    scenarioOverrides: {}, reasoning: '', setToggle() {}, forceAutonomous() {}, setMulti() {},
    syncTopologyConstraints() {}, setDirty() {}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('const PRESETS=['), source.indexOf('const psel='))
    + source.slice(source.indexOf('function showPresetDesc('), source.indexOf('psel.addEventListener('))
    + source.slice(source.indexOf('function renderReadCounts('), source.indexOf('async function tick(')), context);
  return {context, $};
}

test('Every published layout sets twenty agents, medium reasoning and two thousand tokens', () => {
  const {context, $} = fixture();
  for (const [id, publish, recall] of [['published', 'auto', 0], ['deliberate', 'manual', 0], ['fade', 'manual', 1]]) {
    $('in_preset').value = id;
    context.applyPreset(id);
    assert.equal($('in_agents').value, 20);
    assert.equal(context.reasoning, 'medium');
    assert.equal($('in_reasoning').value, 'medium');
    assert.equal(context.scenarioOverrides.max_tokens, 2000);
    assert.equal(context.scenarioOverrides.objective, 'individual');
    assert.equal(context.publish, publish);
    assert.equal(context.recall, recall);
    assert.equal(context.primed, 'ambient');
    assert.equal(context.freepost, 1);
    assert.equal($('presetwarning').hidden, true);
  }
});

test('Warnings report missing workers, local mode, custom prompts and cut board', () => {
  const {context, $} = fixture();
  $('in_preset').value = 'published';
  context.presetGoal = {agents_up: 6, api_on: false, cut: true};
  context.promptViews.measureCustom = true;
  context.renderPresetWarning();
  assert.equal($('presetwarning').hidden, false);
  assert.match($('presetwarning').textContent, /Needs 20 workers; 6 are available/);
  assert.match($('presetwarning').textContent, /Select a hosted model/);
  assert.match($('presetwarning').textContent, /custom prompt/);
  assert.match($('presetwarning').textContent, /Restore Reachable/);
  context.presetGoal = {};
  context.renderPresetWarning();
  assert.match($('presetwarning').textContent, /Waiting for the available worker count/);
  $('in_preset').value = 'balanced';
  context.renderPresetWarning();
  assert.equal($('presetwarning').hidden, true);
});

test('Published identification considers reasoning and seeding; other presets preserve reasoning', () => {
  const {context, $} = fixture();
  const published = vm.runInContext('PRESETS[0]', context);
  assert.equal(context.presetFor(key => published[key]).id, 'published');
  assert.equal(context.presetFor(key => key === 'reasoning' ? 'high' : published[key]), null);
  assert.equal(context.presetFor(key => key === 'preseed' ? 2 : published[key]), null);
  context.reasoning = 'high';
  context.applyPreset('balanced');
  assert.equal(context.reasoning, 'high');
  assert.equal(Object.keys(context.scenarioOverrides).length, 0);
  assert.equal($('in_agents').value, 0);
});

test('Read counters distinguish choices, harness reads and unclassified events', () => {
  const {context, $} = fixture();
  context.renderReadCounts({model_chosen: 8, automatic: 20, total: 27, unclassified: 1});
  assert.equal($('lg_read').textContent, 8);
  assert.equal($('lg_auto_read').textContent, 20);
  assert.equal($('lg_auto_read_row').hidden, false);
  assert.equal($('lg_other_read').textContent, 1);
  assert.match($('lg_read_row').title, /including blocked attempts/);
  assert.match($('lg_read_row').title, /27 successful board reads in total/);
  context.renderReadCounts();
  assert.equal($('lg_read').textContent, 0);
  assert.equal($('lg_auto_read_row').hidden, true);
  assert.equal($('lg_other_read_row').hidden, true);
});
