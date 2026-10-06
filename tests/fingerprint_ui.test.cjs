const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.py'), 'utf8');
const keys = ['fanout', 'gap_coverage', 'protocol', 'vocab', 'requests', 'relay', 'repair', 'blocked'];

function element() {
  const classes = new Set(), descendants = {};
  return {children: [], dataset: {}, style: {}, attributes: {},
    classList: {toggle(name, on) {on ? classes.add(name) : classes.delete(name);},
      contains(name) {return classes.has(name);}},
    appendChild(child) {this.children.push(child);},
    setAttribute(name, value) {this.attributes[name] = value;},
    querySelector(selector) {
      if (selector.startsWith('[data-k=')) return this.children.find(child => child.dataset.k === selector.split('"')[1]);
      return descendants[selector] ||= element();
    }};
}

function fixture() {
  const host = element();
  const context = {$: () => host, document: {createElement: element}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('const FPHELP='), source.indexOf('async function copyFP(')), context);
  return {host, render: context.renderFP, row: key => host.querySelector(`[data-k="${key}"]`)};
}

test('All eight measurements start outlined, with no old category distinction', () => {
  const {host, render, row} = fixture();
  render();
  assert.equal(host.children.length, 16);
  for (const key of keys) {
    assert.equal(row(key).className, 'fprow');
    assert.equal(row(key).querySelector('i').classList.contains('observed'), false);
    assert.equal(row(key).querySelector('i').title, 'No measurement yet.');
  }
  assert.equal(row('gap_coverage').querySelector('b').textContent, '–');
});

test('Each nonzero measurement fills independently and resets when zero', () => {
  const {host, render, row} = fixture();
  for (const active of keys) {
    const values = Object.fromEntries(keys.map(key => [key, key === active ? .5 : 0]));
    render(values);
    for (const key of keys) {
      const dot = row(key).querySelector('i');
      assert.equal(dot.classList.contains('observed'), key === active);
      assert.equal(dot.title, key === active ? 'Observed in this run—not proof of coordination.' : 'Not observed in this run.');
      assert.ok(dot.attributes['aria-label'].endsWith(dot.title));
    }
    assert.deepEqual(values, Object.fromEntries(keys.map(key => [key, key === active ? .5 : 0])));
  }
  render(Object.fromEntries(keys.map(key => [key, 0])));
  assert.equal(host.children.length, 16);
  assert.ok(keys.every(key => !row(key).querySelector('i').classList.contains('observed')));
});

test('Values, percentage formatting, meters and expandable explanations are preserved', () => {
  const {host, render, row} = fixture();
  render({fanout: 6, gap_coverage: .25, relay: 25});
  assert.equal(row('fanout').querySelector('b').textContent, 6);
  assert.equal(row('fanout').querySelector('em').style.width, '50%');
  assert.equal(row('gap_coverage').querySelector('b').textContent, '25%');
  assert.equal(row('relay').querySelector('em').style.width, '100%');
  const help = host.children[1];
  assert.equal(help.hidden, true);
  row('fanout').onclick();
  assert.equal(help.hidden, false);
  assert.equal(help.textContent, 'Distinct identities that wrote to the board.');
});

test('Assisted styling cannot fill zero dots; all dots use the same neutral colour', () => {
  assert.doesNotMatch(source, /#fp\.assisted[^\n]*\.lab i/);
  assert.match(source, /\.fprow \.lab i\{[^}]*background:transparent/);
  assert.match(source, /\.fprow \.lab i\.observed\{background:var\(--muted\)\}/);
  assert.doesNotMatch(source, /\.fprow\.nd/);
});
