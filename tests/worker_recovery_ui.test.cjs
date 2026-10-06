const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.py'), 'utf8');
const code = source.slice(source.indexOf('function renderProviderError('), source.indexOf('/* ---- goal / drawer state ---- */'));

function render(stats) {
  const nodes = {providererror: {hidden: true, textContent: ''}, stream: {querySelector() {return null;}}};
  const context = {$: id => nodes[id]};
  vm.createContext(context);
  vm.runInContext(code, context);
  context.renderProviderError(stats);
  return nodes.providererror;
}

test('Worker failures are visible without a provider failure', () => {
  const el = render({completion: {failed_agents: 11}});
  assert.equal(el.hidden, false);
  assert.match(el.textContent, /11 agents failed/);
  assert.match(el.textContent, /must not be used as a measurement/);
  assert.match(el.textContent, /not automatically rerun/);
});

test('Successful run has no warning and hosted failures retain their explanation', () => {
  assert.equal(render({completion: {failed_agents: 0}}).hidden, true);
  const el = render({provider_failures: 1, completion: {failed_agents: 1}});
  assert.equal(el.hidden, false);
  assert.match(el.textContent, /Hosted model requests failed/);
});
