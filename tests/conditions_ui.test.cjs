const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.py'), 'utf8');

function fixture() {
  const nodes = {};
  const $ = id => nodes[id] ||= {hidden: true, children: [], attributes: {},
    classList: {toggle() {}},
    setAttribute(name, value) {this.attributes[name] = value;},
    removeAttribute(name) {delete this.attributes[name];}};
  const context = {$, topology: 'peer', primed: 1, autonomy: 'autonomous', initialRead: 1,
    mutual: 0, freepost: 1, recall: 1, setToggle() {}, syncPromptPanel() {}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function syncConditionConstraints('),
    source.indexOf('function syncPromptPanel(')), context);
  return {context, nodes, $};
}

test('Only board-backed Measure enables Free board actions and Records fade', () => {
  const {context, $} = fixture();
  for (const topology of ['peer', 'fleet']) {
    for (const autonomy of ['autonomous', 'scaffolded']) {
      for (const primed of [1, 'ambient', 0]) {
        Object.assign(context, {topology, autonomy, primed});
        context.syncTopologyConstraints();
        const applies = topology === 'peer' && autonomy === 'autonomous' && !!primed;
        for (const id of ['c_freepost', 'c_recall']) {
          assert.equal($(id).disabled, !applies);
          assert.equal($(id).title, applies ? '' : 'Available in Primed or Ambient Measure runs.');
          assert.equal($(id).attributes['aria-describedby'], applies ? undefined : 'conditions_scope');
        }
        assert.equal($('conditions_scope').hidden, applies);
        assert.notEqual($('c_mutual').disabled, true);
        assert.equal(context.freepost, 1);
        assert.equal(context.recall, 1);
      }
    }
  }
});

test('Returning to Measure restores usable controls without clearing selected settings', () => {
  const {context, $} = fixture();
  context.autonomy = 'scaffolded';
  context.syncTopologyConstraints();
  assert.equal($('c_recall').disabled, true);
  context.autonomy = 'autonomous';
  context.syncTopologyConstraints();
  assert.equal($('c_recall').disabled, false);
  assert.equal(context.recall, 1);
  assert.equal(context.freepost, 1);
});

test('Disabled condition clicks cannot change staged values', () => {
  const {context, $} = fixture();
  let click, changed = 0;
  $('condtoggle').addEventListener = (event, fn) => {click = fn;};
  context.setMulti = () => {};
  context.markCustom = () => {changed++;};
  vm.runInContext(source.slice(source.indexOf('$("condtoggle").addEventListener('),
    source.indexOf('\nsetMulti();', source.indexOf('$("condtoggle").addEventListener('))), context);
  click({target: {closest: () => ({disabled: true, dataset: {v: 'recall'}})}});
  assert.equal(context.recall, 1);
  assert.equal(changed, 0);
  click({target: {closest: () => ({disabled: false, dataset: {v: 'recall'}})}});
  assert.equal(context.recall, 0);
  assert.equal(changed, 1);
});

test('Non-relay wording keeps the correct, abstained and wrong breakdown', () => {
  const {context, $} = fixture();
  vm.runInContext(source.slice(source.indexOf('function updateNonRelayTooltip('),
    source.indexOf('async function tick(')), context);
  context.updateNonRelayTooltip({correct: 7, abstained: 2, wrong: 3});
  assert.equal($('lg_solo_row').title,
    '7 correct · 2 abstains · 3 wrong. Answers without a recorded value relay. Agents may still have read the board.');
  context.updateNonRelayTooltip();
  assert.match($('lg_solo_row').title, /^0 correct · 0 abstains · 0 wrong\./);
  assert.match(source, /Non-relay answers<b id=lg_solo>/);
  assert.doesNotMatch(source, /Answered without board/);
});
