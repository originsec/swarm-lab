const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.py'), 'utf8');
function fixture(request) {
  const nodes = {btn_sweep: {disabled: false}, sweep_status: {hidden: true}};
  const calls = [];
  const context = {$: id => nodes[id], controlRequest: async (route, data) => {
    calls.push({route, data}); return request();
  }};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function sweep(){'), source.indexOf('async function applyHosted(){')), context);
  return {nodes, calls, sweep: context.sweep};
}
test('Sweep reports the actual deletion count, with singular and empty states', async () => {
  for (const [deleted, message] of [
    [['A','B','C'], 'Removed 3 pages.'], [['A'], 'Removed 1 page.'],
    [[], 'Board was empty; no pages removed.']]) {
    const {nodes, calls, sweep} = fixture(() => ({deleted}));
    await sweep();
    assert.equal(nodes.sweep_status.textContent, message);
    assert.equal(nodes.sweep_status.hidden, false);
    assert.equal(nodes.btn_sweep.disabled, false);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].route, '/api/sweep');
    assert.equal(Object.keys(calls[0].data).length, 0);
  }
});
test('Sweep blocks duplicate clicks until its request finishes', async () => {
  let finish;
  const {nodes, calls, sweep} = fixture(() => new Promise(resolve => {finish = resolve;}));
  const pending = sweep();
  assert.equal(nodes.btn_sweep.disabled, true);
  assert.equal(nodes.sweep_status.textContent, 'Sweeping…');
  await sweep();
  assert.equal(calls.length, 1);
  finish({deleted: ['A']});
  await pending;
  assert.equal(nodes.btn_sweep.disabled, false);
});
test('Sweep errors are shown beside the button and leave it usable', async () => {
  const {nodes, sweep} = fixture(() => {throw new Error('Board unavailable');});
  await sweep();
  assert.equal(nodes.sweep_status.textContent, 'Board unavailable');
  assert.equal(nodes.sweep_status.hidden, false);
  assert.equal(nodes.btn_sweep.disabled, false);
});
test('Unexpected sweep response does not falsely claim success or an empty board', async () => {
  const {nodes, sweep} = fixture(() => ({}));
  await sweep();
  assert.match(nodes.sweep_status.textContent, /Could not confirm the sweep result/);
  assert.equal(nodes.btn_sweep.disabled, false);
  assert.match(source, /id=sweep_status[^>]*role=status[^>]*aria-live=polite/);
});
